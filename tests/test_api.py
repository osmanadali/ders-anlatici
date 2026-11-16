import json
import time

import pytest
from fastapi.testclient import TestClient

import fakes
from app import main
from conftest import make_text_pdf

fakes.install()


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def _events(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def _course_with_pdf(client):
    c = client.post("/api/courses", json={"name": "Matematik"}).json()
    r = client.post(
        f"/api/courses/{c['id']}/docs",
        files={"file": ("hafta1.pdf", make_text_pdf(["Parabol ve kokler: ikinci derece fonksiyonlarin grafigi", "Turev kurallari: carpim, bolum ve zincir kurali"]), "application/pdf")},
    )
    assert r.status_code == 200, r.text
    return c["id"], r.json()["id"]


def test_index_and_static(client):
    assert "Ders Anlatıcı" in client.get("/").text
    assert client.get("/static/board.js").status_code == 200


def test_ask_streams_steps_audio_and_memory(client):
    cid, did = _course_with_pdf(client)
    fakes.CALLS.clear()
    r = client.post("/api/ask", data={"text": "Bu parabolü çiz", "course_id": cid})
    ev = _events(r)
    assert ev[0]["type"] == "session"
    steps = [e for e in ev if e["type"] == "step"]
    assert len(steps) == len(fakes.DEMO_STEPS)
    assert any(e["type"] == "memory" for e in ev) and ev[-1]["type"] == "done"

    # Notlar sistem talimatına eklendi mi?
    sys_text = "".join(b["text"] for b in fakes.CALLS[-1]["system"])
    assert "Parabol ve kokler" in sys_text and "Sayfa 2" in sys_text

    # Ses dosyası üretilip sunuluyor mu?
    a = client.get(steps[0]["audio"])
    assert a.status_code == 200 and len(a.content) > 1000

    # Oturum kaydedildi mi, ikinci soru aynı geçmişe ekleniyor mu?
    sid = ev[0]["id"]
    r2 = client.post("/api/ask", data={"text": "anlamadım", "course_id": cid, "session_id": sid, "interrupted": "Tepe noktası"})
    assert _events(r2)[0]["id"] == sid
    msgs = fakes.CALLS[-1]["messages"]
    assert len(msgs) == 3 and msgs[1]["role"] == "assistant"
    assert "sözünü kestim" in msgs[2]["content"][-1]["text"]
    rec = client.get(f"/api/sessions/{sid}").json()
    assert sum(1 for t in rec["timeline"] if t["type"] == "step") == 2 * len(fakes.DEMO_STEPS)
    assert client.get(f"/api/memory/{cid}").json()[0]["konu"] == "Parabol çizimi"


def test_page_mode_attaches_page_image(client):
    cid, did = _course_with_pdf(client)
    fakes.CALLS.clear()
    client.post("/api/ask", data={"mode": "page", "course_id": cid, "doc_id": did, "page": "2"})
    content = fakes.CALLS[-1]["messages"][-1]["content"]
    assert content[0]["type"] == "image"
    assert "Turev" in content[1]["text"] and "2. sayfasını" in content[-1]["text"]


def test_page_number_detected_from_text(client):
    cid, did = _course_with_pdf(client)
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "1. sayfayı anlat", "course_id": cid})
    content = fakes.CALLS[-1]["messages"][-1]["content"]
    assert content[0]["type"] == "image" and "sayfa 1" in content[1]["text"]


def test_screenshot_attachment(client):
    fakes.CALLS.clear()
    png = fakes._beep(0.01)  # içerik önemli değil, görsel blok olarak eklenmeli
    client.post("/api/ask", data={"text": "bunu çöz"}, files=[("files", ("ss.png", png, "image/png"))])
    content = fakes.CALLS[-1]["messages"][-1]["content"]
    assert content[0]["type"] == "image" and content[-1]["text"] == "bunu çöz"


def test_lecture_quiz_stt_tts_settings(client):
    cid, _ = _course_with_pdf(client)
    plan = client.post("/api/lecture/plan", json={"course_id": cid}).json()
    assert len(plan["sections"]) == 2
    sec = {"i": 1, "n": 2, "title": "Parabol", "summary": "x", "pages": ["s.1"]}
    fakes.CALLS.clear()
    client.post("/api/ask", data={"mode": "lecture", "course_id": cid, "section": json.dumps(sec)})
    assert "1/2. bölüm" in fakes.CALLS[-1]["messages"][-1]["content"][-1]["text"]

    quiz = client.post("/api/quiz/generate", json={"course_id": cid, "count": 2}).json()
    q = quiz["questions"][0]
    g = client.post("/api/quiz/grade", data={"question": json.dumps(q), "answer": "3", "course_id": cid}).json()
    assert g["correct"] is False
    assert any(r["konu"] == "Kökler" for r in client.get(f"/api/memory/{cid}").json())

    assert client.post("/api/stt", files={"file": ("a.webm", b"x" * 3000, "audio/webm")}).json()["text"]
    assert client.post("/api/tts", json={"text": "Merhaba"}).status_code == 200
    s = client.post("/api/settings", json={"level": "basit", "bogus": 1}).json()
    assert s["level"] == "basit" and "bogus" not in s
    assert client.get("/api/voices").json()[0]["category"] == "cloned"


def test_image_note_gets_ocr(client):
    from io import BytesIO

    from PIL import Image

    c = client.post("/api/courses", json={"name": "Fizik"}).json()
    buf = BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "PNG")
    client.post(f"/api/courses/{c['id']}/docs", files={"file": ("defter.png", buf.getvalue(), "image/png")})
    for _ in range(50):
        page = client.get(f"/api/courses/{c['id']}").json()["docs"][0]["pages"][0]
        if not page["needs_ocr"]:
            break
        time.sleep(0.05)
    assert page["text"] == "Fotoğraftan okunan not metni"


def test_rejects_bad_ids(client):
    assert client.get("/api/sessions/../../etc").status_code == 404
    assert client.get("/api/courses/..%2f..").status_code in (400, 404)
