import json

import pytest
from fastapi.testclient import TestClient

import fakes
from app import hazir, llm, main
from conftest import make_text_pdf

fakes.install()


@pytest.fixture()
def paket(tmp_path, monkeypatch):
    p = {
        "kurs_kodu": "ENM 463",
        "docs": {
            "1.DERS (BİLDİKLERİNİZİN TEKRARI).pdf": {
                "baslik": "Kalitenin temel kavramları", "ozet": "Kalite tanımları ve PUKÖ döngüsü.",
                "bolumler": [{"baslik": "Kalite nedir", "sayfalar": "1-2", "ozet": "tanımlar"}],
                "kavramlar": [{"terim": "PUKÖ", "tanim": "Planla-Uygula-Kontrol et-Önlem al", "sayfa": 2}],
                "olasi_sorular": ["PUKÖ döngüsünü açıklayınız."],
                "ocr": {"2": "Deming döngüsü: Planla, Uygula, Kontrol et, Önlem al"},
            }
        },
        "ders_plani": {"title": "Kalite Yönetimi", "sections": [{"title": "Giriş", "summary": "kalite", "pages": ["1.DERS s.1-2"]}]},
        "kavram_kagidi": {"title": "Kavram kâğıdı", "sections": [{"title": "Temel", "items": [{"name": "PUKÖ", "tex": "", "note": "Deming"}]}]},
        "sinav_rehberi": "- PUKÖ döngüsünü ezberle",
    }
    (tmp_path / "enm463.json").write_text(json.dumps(p, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(hazir, "DIR", tmp_path)
    hazir.packs.cache_clear()
    yield
    hazir.packs.cache_clear()


def test_anahtar_turkce_ve_buyuk_kucuk_harf_duyarsiz():
    assert hazir.key("1.DERS (BİLDİKLERİNİZİN TEKRARI).pdf") == hazir.key("1.ders (bildiklerinizin tekrari).PDF")
    assert hazir.key("8..DERS (MOTIVASYON).pdf") != hazir.key("8.DERS (KURUMSAL LIDERLIK).pdf")
    assert hazir.key("4.DERS (TKY'NİN TEMEL ILKELERI)") == hazir.key("4.DERS (TKY'NİN TEMEL ILKELERI).pdf")  # uzantısız ad


def test_pdf_yuklenince_hazir_icerik_eklenir(paket):
    c = TestClient(main.app)
    cid = c.post("/api/courses", json={"name": "ENM 463 KALİTE YÖNETİMİ"}).json()["id"]
    pdf = make_text_pdf(["Kalite kavrami, musteri beklentilerini karsilama derecesidir ve surekli iyilestirme gerektirir.", "x"])
    doc = c.post(f"/api/courses/{cid}/docs", files={"file": ("1.DERS (BİLDİKLERİNİZİN TEKRARI).pdf", pdf, "application/pdf")}).json()
    assert doc["pages"][1]["needs_ocr"] is False and "Deming döngüsü" in doc["pages"][1]["text"]
    course = c.get(f"/api/courses/{cid}").json()
    assert course["lecture_plan"]["sections"][0]["title"] == "Giriş" and course["lecture_plan"]["hazir"]
    assert course["formula_sheet"]["sections"][0]["items"][0]["name"] == "PUKÖ"
    assert c.get(f"/api/courses/{cid}/formula-sheet").json()["sheet"]["title"] == "Kavram kâğıdı"
    # hoca, belge özetini ve kavramları sistem talimatında görür
    fakes.CALLS.clear()
    c.post("/api/ask", data={"text": "PUKÖ nedir", "course_id": cid})
    knowledge = fakes.CALLS[-1]["system"][1]["text"]
    assert "Planla-Uygula-Kontrol et-Önlem al" in knowledge and "SINAV REHBERİ" in knowledge


def test_pakette_olmayan_pdf_etkilenmez(paket):
    c = TestClient(main.app)
    cid = c.post("/api/courses", json={"name": "Başka"}).json()["id"]
    pdf = make_text_pdf(["Tamamen baska bir dersin notlari, uzun bir metin sayfasi burada yer aliyor."])
    c.post(f"/api/courses/{cid}/docs", files={"file": ("rastgele.pdf", pdf, "application/pdf")})
    assert "lecture_plan" not in c.get(f"/api/courses/{cid}").json()


def test_paket_sonradan_yuklenince_var_olan_notlara_uygulanir(tmp_path, monkeypatch):
    monkeypatch.setattr(hazir, "DIR", tmp_path / "bos")
    monkeypatch.setattr(hazir, "USER_DIR", tmp_path / "kullanici")
    hazir.packs.cache_clear()
    c = TestClient(main.app)
    cid = c.post("/api/courses", json={"name": "Kalite"}).json()["id"]
    pdf = make_text_pdf(["Kalite kavrami, musteri beklentilerini karsilama derecesidir ve surekli iyilestirme ister.", "x"])
    c.post(f"/api/courses/{cid}/docs", files={"file": ("4.DERS (TKY'NİN TEMEL ILKELERI).pdf", pdf, "application/pdf")})
    assert c.post("/api/hazir", files={"file": ("x.json", b"{bozuk", "application/json")}).status_code == 400
    deneme = {"baslik": "Deneme 1", "bolum1_dy": [{"ifade": "5M'de Machine vardır.", "cevap": "D", "aciklama": "", "kaynak": ""}]}
    pack = {"kurs_kodu": "ENM 463", "ders": "Kalite", "konu_anlatimi": "## TKY\n- **Müşteri odaklılık**",
            "denemeler": [deneme], "docs": {"4.DERS (TKY'NIN TEMEL ILKELERI).pdf": {"ocr": {"2": "TKY ilkeleri: Kaizen"}}}}
    r = c.post("/api/hazir", files={"file": ("enm463.json", json.dumps(pack).encode(), "application/json")}).json()
    assert r["uygulanan"] == 1 and r["dersler"] == [cid]
    assert (tmp_path / "kullanici" / "enm463.json").exists()
    course = c.get(f"/api/courses/{cid}").json()
    assert course["denemeler"][0]["baslik"] == "Deneme 1" and "TKY" in course["konu_anlatimi"]
    assert "Kaizen" in course["docs"][0]["pages"][1]["text"]
    assert c.get("/api/hazir").json()[-1]["deneme"] == 1
    hazir.packs.cache_clear()
