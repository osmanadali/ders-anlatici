"""Hazır ders paketleri (app/hazir/*.json).

Bir dersin PDF'leri önceden okunup işlenmiştir: taranmış sayfaların metinleri, belge özetleri, kavramlar,
ders planı, kavram kâğıdı ve sınav rehberi. Öğrenci aynı PDF'leri yüklediğinde dosya adından tanınır ve
bu içerik kendiliğinden eklenir (Gemini kotası harcanmaz, ders hemen anlatıma hazır olur).
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import notes

DIR = Path(__file__).resolve().parent / "hazir"


def key(name: str) -> str:
    """Dosya adını eşleştirme anahtarına çevirir: uzantısız, büyük/küçük harf ve Türkçe karakter duyarsız."""
    n = unicodedata.normalize("NFKD", Path(name).stem).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", n)


@lru_cache(maxsize=None)
def packs() -> list[dict]:
    out = []
    for f in sorted(DIR.glob("*.json")):
        try:
            p = json.loads(f.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        p["_id"] = f.stem
        p["_docs"] = {key(n): d for n, d in p.get("docs", {}).items()}
        out.append(p)
    return out


def find_doc(filename: str) -> tuple[dict, dict] | None:
    k = key(filename)
    for p in packs():
        if k in p["_docs"]:
            return p, p["_docs"][k]
    return None


def apply_to_document(course_id: str, doc: dict, filename: str) -> bool:
    """Yeni yüklenen belge bir hazır pakette varsa: taranmış sayfa metinlerini, özeti ve kavramları ekler;
    dersin planını/kavram kâğıdını (yoksa) doldurur. Uygulandıysa True."""
    hit = find_doc(filename)
    if not hit:
        return False
    pack, info = hit
    course = notes.get_course(course_id)
    d = notes.find_doc(course, doc["id"]) if course else None
    if not d:
        return False
    ocr = {int(k): v for k, v in (info.get("ocr") or {}).items()}
    for p in d["pages"]:
        if p["n"] in ocr and (p.get("needs_ocr") or len(p.get("text", "")) < 40):
            p["text"] = ocr[p["n"]]
            p["needs_ocr"] = False
    d["hazir"] = {"paket": pack["_id"], "baslik": info.get("baslik", ""), "ozet": info.get("ozet", ""),
                  "bolumler": info.get("bolumler", []), "kavramlar": info.get("kavramlar", []),
                  "olasi_sorular": info.get("olasi_sorular", [])}
    if pack.get("ders_plani") and not course.get("lecture_plan"):
        course["lecture_plan"] = pack["ders_plani"] | {"hazir": True}
    if pack.get("kavram_kagidi") and not course.get("formula_sheet"):
        course["formula_sheet"] = pack["kavram_kagidi"] | {"created": time.time(), "focus": "", "hazir": True}
    if pack.get("sinav_rehberi") and not course.get("sinav_rehberi"):
        course["sinav_rehberi"] = pack["sinav_rehberi"]
    notes.save_course(course)
    return True


def course_guide(course: dict | None) -> str:
    """Hocanın sistem talimatına eklenecek kısa ders rehberi: belge özetleri + kavramlar (her soruda gönderilir)."""
    if not course:
        return ""
    parts = []
    for d in course.get("docs", []):
        h = d.get("hazir")
        if not h:
            continue
        kav = "; ".join(f"{k['terim']}: {k['tanim']}" for k in h.get("kavramlar", [])[:25])
        parts.append(f"## {d['name']} — {h.get('baslik', '')}\n{h.get('ozet', '')}\nKavramlar: {kav}")
    if not parts:
        return ""
    guide = "# DERS NOTLARININ ÖZETİ (hocanın belgeleri)\n" + "\n\n".join(parts)
    if course.get("sinav_rehberi"):
        guide += "\n\n# SINAV REHBERİ\n" + course["sinav_rehberi"]
    return guide
