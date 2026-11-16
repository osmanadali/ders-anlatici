import json

from app import notes, store
from app.llm import StepParser, normalize_step

from conftest import make_text_pdf


# ---------------------------------------------------------------- adım ayrıştırıcı
def test_parser_streams_lines_in_chunks():
    p = StepParser()
    text = '{"say": "Merhaba", "board": [{"op": "title", "text": "Limit"}]}\n{"say": "İkinci", "board": []}\n'
    got = []
    for i in range(0, len(text), 7):  # akış gibi parça parça
        got += p.feed(text[i : i + 7])
    got += p.flush()
    assert [g["say"] for g in got] == ["Merhaba", "İkinci"]
    assert got[0]["board"][0]["op"] == "title"


def test_parser_last_line_without_newline_and_code_fence():
    p = StepParser()
    got = p.feed('```json\n{"say": "a", "board": []}\n')
    got += p.feed('{"say": "son", "board": []}')
    got += p.flush()
    assert [g["say"] for g in got] == ["a", "son"]


def test_parser_multiline_json_and_plain_text():
    p = StepParser()
    got = p.feed('{"say": "çok\n')  # kural dışı: JSON iki satıra bölünmüş
    got += p.feed('satır", "board": []}\nDüz metin satırı\n')
    got += p.flush()
    assert got[0]["say"].startswith("çok")
    assert got[1]["say"] == "Düz metin satırı"
    assert got[1]["board"][0]["op"] == "write"


def test_normalize_filters_bad_ops_and_memory():
    assert normalize_step({"memory": {"topic": "Türev"}}) == {"memory": {"topic": "Türev"}}
    s = normalize_step({"say": " x ", "board": [{"op": "write", "text": "a"}, "çöp", {"no": 1}]})
    assert s == {"say": "x", "board": [{"op": "write", "text": "a"}]}
    assert normalize_step({"say": "", "board": []}) is None


# ---------------------------------------------------------------- notlar
def test_pdf_upload_splits_pages_and_context():
    c = notes.create_course("Kalkulus")
    doc = notes.add_document(c["id"], "hafta1.pdf", make_text_pdf(["Limit tanimi ve ornekler sayfasi, sag ve sol limit", "Turev kurallari zincir kurali ve carpim kurali"]))
    assert len(doc["pages"]) == 2
    assert "Limit" in doc["pages"][0]["text"]
    assert not doc["pages"][0]["needs_ocr"]
    assert notes.page_image_path(c["id"], doc["id"], 2).exists()

    ctx = notes.notes_context(notes.get_course(c["id"]))
    assert ctx.full and "Sayfa 2" in ctx.text and "zincir" in ctx.text


def test_image_upload_marks_ocr():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "PNG")
    c = notes.create_course("Fizik")
    doc = notes.add_document(c["id"], "defter.png", buf.getvalue())
    assert doc["kind"] == "image" and doc["pages"][0]["needs_ocr"]
    notes.set_page_text(c["id"], doc["id"], 1, "Newton yasalari")
    assert notes.get_course(c["id"])["docs"][0]["pages"][0]["text"] == "Newton yasalari"


def test_large_notes_select_relevant_pages(monkeypatch):
    monkeypatch.setattr(notes, "FULL_NOTES_CHAR_LIMIT", 300)
    course = {
        "name": "X",
        "docs": [
            {
                "id": "d1",
                "name": "n",
                "pages": [{"n": i, "text": ("integral " if i == 7 else "matris ") * 15} for i in range(1, 12)],
            }
        ],
    }
    ctx = notes.notes_context(course, "integral nasıl alınır")
    assert not ctx.full
    assert "Sayfa 7]" in ctx.text


def test_detect_page():
    assert notes.detect_page("12. sayfayı anlat") == 12
    assert notes.detect_page("sayfa 5 te ne var") == 5
    assert notes.detect_page("s. 30 daki soru") == 30
    assert notes.detect_page("bu soruyu çöz") is None


def test_unsupported_file_rejected():
    c = notes.create_course("Y")
    try:
        notes.add_document(c["id"], "a.docx", b"x")
    except ValueError:
        pass
    else:
        raise AssertionError("docx kabul edilmemeliydi")


# ---------------------------------------------------------------- hafıza
def test_memory_weak_topics():
    store.record_topic("ders1", "Kısmi integrasyon", False)
    store.record_topic("ders1", "Kısmi integrasyon", False)
    store.record_topic("ders1", "Limit", True)
    store.record_topic("ders1", "Seriler", None, "yakınsaklık testlerini karıştırıyor")
    names = [r["konu"] for r in store.weak_topics("ders1")]
    assert names[0] == "Kısmi integrasyon" and "Seriler" in names and "Limit" not in names
    assert "yakınsaklık" in store.memory_summary("ders1")


def test_session_roundtrip():
    s = store.new_session(None, "deneme")
    s["timeline"].append({"type": "step", "idx": 0, "say": "a", "board": []})
    store.save_session(s)
    assert store.load_session(s["id"])["timeline"][0]["say"] == "a"
    assert any(r["id"] == s["id"] and r["steps"] == 1 for r in store.list_sessions())
    json.dumps(store.list_sessions())
