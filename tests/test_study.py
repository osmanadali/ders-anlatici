import time
from datetime import date, timedelta

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


def _course(client):
    c = client.post("/api/courses", json={"name": "Yöneylem"}).json()
    client.post(f"/api/courses/{c['id']}/docs",
                files={"file": ("h1.pdf", make_text_pdf(["Dogrusal programlama modelleme ve grafik cozum yontemi"]), "application/pdf")})
    return c["id"]


def test_recording_becomes_notes(client):
    cid = _course(client)
    doc = client.post(f"/api/courses/{cid}/recordings", files={"file": ("ders3.m4a", b"\x00" * 5000, "audio/mp4")}).json()
    assert doc["kind"] == "audio" and doc["status"]
    for _ in range(60):
        d = next(x for x in client.get(f"/api/courses/{cid}").json()["docs"] if x["id"] == doc["id"])
        if not d.get("status"):
            break
        time.sleep(0.05)
    assert d["name"] == "Simpleks yöntemi (ders kaydı)" and len(d["pages"]) == 2
    assert "Pivot" in d["pages"][1]["text"]
    assert "simpleks" in client.get(f"/api/courses/{cid}/docs/{doc['id']}/transcript").text
    # yeni not sayfaları hocanın bağlamına girer
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "pivot nasıl seçilir", "course_id": cid})
    assert "En negatif indirgenmiş maliyet" in fakes.CALLS[-1]["system"][1]["text"]


def test_recording_rejects_bad_type(client):
    cid = _course(client)
    assert client.post(f"/api/courses/{cid}/recordings", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400


def test_formula_sheet_saved(client):
    cid = _course(client)
    assert client.get(f"/api/courses/{cid}/formula-sheet").json()["sheet"] is None
    r = client.post(f"/api/courses/{cid}/formula-sheet", json={}).json()
    assert r["sheet"]["sections"][0]["items"][1]["name"] == "Zincir kuralı"
    assert client.get(f"/api/courses/{cid}/formula-sheet").json()["sheet"]["title"]


def test_schedule_and_today(client):
    cid = _course(client)
    today = date.today()
    exam = (today + timedelta(days=10)).isoformat()
    s = client.post(f"/api/courses/{cid}/schedule", json={"exam_date": exam, "minutes": 60, "today": today.isoformat()}).json()
    assert s["days"][0]["date"] == today.isoformat() and s["days"][0]["tasks"][0]["id"] == f"{today.isoformat()}-0"
    tid = s["days"][0]["tasks"][0]["id"]
    s = client.post(f"/api/courses/{cid}/schedule/done", json={"task_id": tid}).json()
    assert s["done"][tid]
    t = client.get("/api/today", params={"day": today.isoformat()}).json()
    mine = [x for x in t["tasks"] if x["course_id"] == cid]
    assert mine[0]["done"] and mine[1]["kind"] == "sinav"
    assert any(e["course_id"] == cid and e["exam_date"] == exam for e in t["exams"])
    bad = client.post(f"/api/courses/{cid}/schedule", json={"exam_date": "2000-01-01"})
    assert bad.status_code == 400
