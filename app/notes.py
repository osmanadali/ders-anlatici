"""Ders notları: dersler, belgeler (PDF / fotoğraf), sayfa metinleri ve sayfa görüntüleri.

Klasör yapısı:
    veri/dersler/<ders_id>/ders.json
    veri/dersler/<ders_id>/belgeler/<belge_id>/kaynak.pdf | kaynak.png
    veri/dersler/<ders_id>/belgeler/<belge_id>/sayfa_001.png ...
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR, FULL_NOTES_CHAR_LIMIT

COURSES_DIR = DATA_DIR / "dersler"
COURSES_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".webm", ".aac", ".flac", ".mp4", ".mov", ".mkv", ".amr", ".3gp"}
IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _safe_id(x: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", x or ""):
        raise ValueError("geçersiz kimlik")
    return x


# ---------------------------------------------------------------- dersler
def course_dir(course_id: str) -> Path:
    return COURSES_DIR / _safe_id(course_id)


def list_courses() -> list[dict]:
    out = []
    for d in sorted(COURSES_DIR.iterdir()) if COURSES_DIR.exists() else []:
        f = d / "ders.json"
        if f.exists():
            out.append(json.loads(f.read_text("utf-8")))
    out.sort(key=lambda c: c.get("created", 0))
    return out


def get_course(course_id: str) -> dict | None:
    f = course_dir(course_id) / "ders.json"
    return json.loads(f.read_text("utf-8")) if f.exists() else None


def save_course(course: dict) -> None:
    d = course_dir(course["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "ders.json").write_text(json.dumps(course, ensure_ascii=False, indent=2), "utf-8")


def create_course(name: str) -> dict:
    course = {"id": _new_id(), "name": name.strip() or "Yeni ders", "created": time.time(), "docs": []}
    save_course(course)
    return course


def delete_course(course_id: str) -> None:
    shutil.rmtree(course_dir(course_id), ignore_errors=True)


# ---------------------------------------------------------------- belgeler
def doc_dir(course_id: str, doc_id: str) -> Path:
    return course_dir(course_id) / "belgeler" / _safe_id(doc_id)


_RENDER_LOCK = threading.Lock()  # pdfium iş parçacığı güvenli değil


def page_image_path(course_id: str, doc_id: str, page: int) -> Path:
    """Sayfa görüntüsü; PDF sayfaları ilk istendiğinde üretilir (yükleme hızlı olsun diye)."""
    d = doc_dir(course_id, doc_id)
    out = d / f"sayfa_{page:03d}.png"
    src = d / "kaynak.pdf"
    if not out.exists() and src.exists() and page >= 1:
        with _RENDER_LOCK:
            if not out.exists():
                _render_page(src, page, out)
    return out


def _render_page(pdf_path: Path, page: int, out: Path) -> None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:  # hata olsa da dosya kilidi bırakılsın (Windows'ta klasör silinebilsin)
        if page > len(pdf):
            return
        img = pdf[page - 1].render(scale=1.6).to_pil()
        tmp = out.with_name(out.name + ".yeni")
        img.save(tmp, format="PNG")
        os.replace(tmp, out)
    finally:
        pdf.close()


def add_document(course_id: str, filename: str, data: bytes) -> dict:
    """PDF'i sayfalara ayırır (metin + görüntü) ya da fotoğrafı tek sayfalık belge yapar."""
    course = get_course(course_id)
    if course is None:
        raise KeyError("ders bulunamadı")
    ext = Path(filename).suffix.lower()
    doc_id = _new_id()
    d = doc_dir(course_id, doc_id)
    d.mkdir(parents=True, exist_ok=True)

    try:
        return _add_document(course, course_id, filename, data, ext, doc_id, d)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)  # yarım kalan belge klasörünü bırakma
        raise


def _add_document(course: dict, course_id: str, filename: str, data: bytes, ext: str, doc_id: str, d: Path) -> dict:
    pages: list[dict] = []
    if ext == ".pdf":
        (d / "kaynak.pdf").write_bytes(data)
        pages = _split_pdf(d / "kaynak.pdf", d)
        kind = "pdf"
    elif ext in IMAGE_EXTS:
        src = d / f"kaynak{ext}"
        src.write_bytes(data)
        _image_to_png(src, d / "sayfa_001.png")
        pages = [{"n": 1, "text": "", "needs_ocr": True}]
        kind = "image"
    else:
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError("Sadece PDF ve fotoğraf (png/jpg/webp) yüklenebilir.")

    doc = {
        "id": doc_id,
        "name": Path(filename).stem,
        "kind": kind,
        "added": time.time(),
        "pages": pages,
    }
    course["docs"].append(doc)
    save_course(course)
    return doc


def _split_pdf(pdf_path: Path, out_dir: Path) -> list[dict]:
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    texts = []
    for p in reader.pages:
        try:
            texts.append((p.extract_text() or "").strip())
        except Exception:  # bozuk sayfa
            texts.append("")

    pdf = pdfium.PdfDocument(str(pdf_path))  # açılabildiğini denetle; sayfa görüntüleri istendikçe üretilir
    try:
        n = len(pdf)
    finally:
        pdf.close()
    texts += [""] * (n - len(texts))

    pages = []
    for i, t in enumerate(texts):
        # Metin katmanı olmayan (taranmış) sayfalar sonradan Claude ile okunur.
        pages.append({"n": i + 1, "text": t, "needs_ocr": len(t) < 40})
    return pages


def _image_to_png(src: Path, dst: Path) -> None:
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((2000, 2000))
        im.save(dst, optimize=True)


def find_doc(course: dict, doc_id: str) -> dict | None:
    return next((d for d in course["docs"] if d["id"] == doc_id), None)


def set_page_text(course_id: str, doc_id: str, page: int, text: str) -> None:
    course = get_course(course_id)
    doc = find_doc(course, doc_id) if course else None
    if not doc:
        return
    for p in doc["pages"]:
        if p["n"] == page:
            p["text"] = text
            p["needs_ocr"] = False
    save_course(course)


def delete_document(course_id: str, doc_id: str) -> None:
    course = get_course(course_id)
    if not course:
        return
    course["docs"] = [d for d in course["docs"] if d["id"] != doc_id]
    save_course(course)
    shutil.rmtree(doc_dir(course_id, doc_id), ignore_errors=True)


# ---------------------------------------------------------------- modele verilecek bağlam
@dataclass
class NotesContext:
    text: str
    full: bool  # tüm notlar mı, seçilmiş sayfalar mı


def _page_block(doc: dict, p: dict) -> str:
    return f"[Belge: {doc['name']} | belge_id={doc['id']} | Sayfa {p['n']}]\n{p['text'].strip()}\n"


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"\w{3,}", s.lower())}


def notes_context(course: dict | None, query: str = "", focus: tuple[str, int] | None = None) -> NotesContext:
    """Ders notlarını model bağlamı için metne çevirir.

    Notlar küçükse tamamı (önbelleğe alınır), büyükse sorguya en çok benzeyen sayfalar.
    """
    if not course or not course["docs"]:
        return NotesContext("", True)
    blocks = [(doc, p) for doc in course["docs"] for p in doc["pages"] if p.get("text")]
    total = sum(len(p["text"]) for _, p in blocks)
    if total <= FULL_NOTES_CHAR_LIMIT:
        return NotesContext("\n".join(_page_block(d, p) for d, p in blocks), True)

    q = _tokens(query)
    scored = []
    for doc, p in blocks:
        score = len(q & _tokens(p["text"]))
        if focus and doc["id"] == focus[0] and abs(p["n"] - focus[1]) <= 1:
            score += 1000
        scored.append((score, doc, p))
    scored.sort(key=lambda x: -x[0])
    chosen, size = [], 0
    budget = FULL_NOTES_CHAR_LIMIT // 3
    for _, doc, p in scored:
        if chosen and size + len(p["text"]) > budget:
            continue
        chosen.append((doc, p))
        size += len(p["text"])
    chosen.sort(key=lambda dp: (course["docs"].index(dp[0]), dp[1]["n"]))
    return NotesContext("\n".join(_page_block(d, p) for d, p in chosen), False)


PAGE_RE = re.compile(r"(?:sayfa|syf|sf|s\.)\s*(\d{1,4})|(\d{1,4})\s*\.?\s*(?:sayfa|syf)", re.IGNORECASE)


def detect_page(text: str) -> int | None:
    """'12. sayfayı anlat', 'sayfa 12', 's. 12' gibi ifadelerden sayfa numarası çıkarır."""
    m = PAGE_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1) or m.group(2))


# ---------------------------------------------------------------- ders ses kayıtları
def add_audio_document(course_id: str, filename: str, data: bytes) -> dict:
    """Ders ses/video kaydını saklar; metne çevirme ve not çıkarma arka planda yapılır."""
    course = get_course(course_id)
    if course is None:
        raise KeyError("ders bulunamadı")
    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXTS:
        raise ValueError("Ses kaydı biçimi desteklenmiyor (mp3, m4a, wav, ogg, webm, mp4...).")
    doc_id = _new_id()
    d = doc_dir(course_id, doc_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"kaynak{ext}").write_bytes(data)
    doc = {"id": doc_id, "name": Path(filename).stem, "kind": "audio", "added": time.time(), "pages": [],
           "status": "Yazıya dökülüyor…"}
    course["docs"].append(doc)
    save_course(course)
    return doc


def audio_source(course_id: str, doc_id: str) -> Path | None:
    return next(iter(sorted(doc_dir(course_id, doc_id).glob("kaynak.*"))), None)


def update_doc(course_id: str, doc_id: str, **fields) -> None:
    course = get_course(course_id)
    doc = find_doc(course, doc_id) if course else None
    if not doc:
        return
    doc.update(fields)
    save_course(course)


def set_course_field(course_id: str, key: str, value) -> dict | None:
    course = get_course(course_id)
    if not course:
        return None
    course[key] = value
    save_course(course)
    return course
