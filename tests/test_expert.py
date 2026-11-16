import json

import pytest
from fastapi.testclient import TestClient

import fakes
from app import curriculum, llm, main, prompts

fakes.install()

SAMPLE = {
    "program": "Örnek Üniversite Endüstri Mühendisliği",
    "kaynaklar": ["https://ornek.edu.tr"],
    "dersler": [
        {"kod": "END 211", "ad": "Yöneylem Araştırması I", "ad_en": "Operations Research I", "yariyil": 3,
         "tur": "zorunlu", "dil": "İngilizce", "akts": 6, "icerik": "Doğrusal programlama, simpleks",
         "haftalik_konular": ["Modelleme", "Grafik çözüm", "Simpleks"], "kaynak_kitaplar": ["Taha"], "on_kosul": ""},
        {"kod": "MAT 101", "ad": "Matematik I", "yariyil": 1, "icerik": "Limit, türev", "haftalik_konular": []},
    ],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "ornek.json").write_text(json.dumps(SAMPLE, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(curriculum, "DIR", tmp_path)
    with TestClient(main.app) as c:
        yield c


def test_import_creates_courses_with_profile(client):
    progs = client.get("/api/curriculum").json()
    assert progs[0]["id"] == "ornek" and progs[0]["dersler"][0]["detayli"] is True
    made = client.post("/api/curriculum/import", json={"program": "ornek", "codes": ["END 211"]}).json()
    assert len(made) == 1 and made[0]["profile"]["ad_en"] == "Operations Research I"
    # tekrar içe aktarınca yeni ders açılmaz
    again = client.post("/api/curriculum/import", json={"program": "ornek", "codes": ["END 211"]}).json()
    assert again[0]["id"] == made[0]["id"]


def test_profile_reaches_tutor_without_notes(client):
    cid = client.post("/api/curriculum/import", json={"program": "ornek", "codes": ["END 211"]}).json()[0]["id"]
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "simpleks nedir", "course_id": cid, "style": "konusma"})
    system = fakes.CALLS[-1]["system"]
    knowledge = system[1]["text"]
    assert "Operations Research I" in knowledge and "3. hafta: Simpleks" in knowledge
    assert "cache_control" in system[1]
    assert "KARŞILIKLI KONUŞUYORSUNUZ" in system[-1]["text"]
    # notsuz derste plan ve sınav da çalışır
    assert client.post("/api/lecture/plan", json={"course_id": cid}).status_code == 200
    assert client.post("/api/quiz/generate", json={"course_id": cid}).status_code == 200


def test_course_without_material_rejected(client):
    c = client.post("/api/courses", json={"name": "Boş"}).json()
    assert client.post("/api/lecture/plan", json={"course_id": c["id"]}).status_code == 400


def test_prompt_allows_knowledge_beyond_notes():
    assert "SINIRLI DEĞİL" in prompts.TUTOR_SYSTEM
    sys = llm.build_system({"name": "X", "docs": []}, "", True, "", "normal")
    assert "kendi uzmanlığınla" in sys[1]["text"]


def test_get_tts_and_pwa(client):
    assert client.get("/api/tts", params={"text": "Merhaba"}).status_code == 200
    assert client.get("/sw.js").headers["content-type"].startswith("application/javascript")
    assert client.get("/manifest.webmanifest").json()["display"] == "standalone"
