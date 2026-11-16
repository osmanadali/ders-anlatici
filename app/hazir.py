"""Hazır ders paketleri (app/hazir/*.json ve kullanıcının yüklediği veri/hazir/*.json).

Bir dersin PDF'leri önceden okunup işlenmiştir: taranmış sayfaların metinleri, belge özetleri, kavramlar,
ders planı, kavram kâğıdı ve sınav rehberi. Öğrenci aynı PDF'leri yüklediğinde dosya adından tanınır ve
bu içerik kendiliğinden eklenir (Gemini kotası harcanmaz, ders hemen anlatıma hazır olur).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import notes
from .config import DATA_DIR

DIR = Path(__file__).resolve().parent / "hazir"  # depoyla gelen paketler
USER_DIR = DATA_DIR / "hazir"  # "Ders paketi yükle" ile eklenenler (hocanın notları depoya konmaz)
MAX_BYTES = 30 * 1024 * 1024


def key(name: str) -> str:
    """Dosya adını eşleştirme anahtarına çevirir: uzantısız, büyük/küçük harf ve Türkçe karakter duyarsız."""
    name = re.sub(r"\.(pdf|png|jpe?g|webp|heic|gif|bmp|tiff?)$", "", name.strip(), flags=re.I)  # yalnızca gerçek uzantı
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", n)


@lru_cache(maxsize=None)
def packs() -> list[dict]:
    out = []
    for f in sorted(DIR.glob("*.json")) + sorted(USER_DIR.glob("*.json")):
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
    for k in ("denemeler", "konu_anlatimi", "kisa_ozet"):
        if pack.get(k):
            course[k] = pack[k]
    course["hazir_paket"] = pack["_id"]
    notes.save_course(course)
    return True


def _kod(s: str) -> str:
    from .siniflandir import kodlar

    return next(iter(kodlar(s or "")), "")


def course_for_pack(pack: dict, create: bool = True) -> str | None:
    """Paketin dersi: paket kodu aynı olan ya da paketi önceden almış ders; yoksa (create) oluşturur.

    Ders müfredatta varsa profil bilgisiyle oluşturulur."""
    from . import curriculum
    from .siniflandir import ders_kodu

    kod = _kod(pack.get("kurs_kodu", "")) or _kod(pack.get("ders", ""))
    courses = notes.list_courses()
    for c in courses:  # önce: paketi önceden almış ders
        if c.get("hazir_paket") == pack["_id"]:
            return c["id"]
    hits = [(sum(key(d.get("name", "")) in pack["_docs"] for d in c.get("docs", [])), c) for c in courses]
    best = max(hits, key=lambda t: t[0], default=(0, None))
    if best[0]:  # paketteki belgelerin en çoğunun yüklendiği ders
        return best[1]["id"]
    for c in courses:
        if kod and ders_kodu(c) == kod:
            return c["id"]
    if not create:
        return None
    if kod:
        for prog in curriculum.programs():
            for d in prog["dersler"]:
                if _kod(d.get("kod", "")) == kod:
                    made = curriculum.import_courses(prog["id"], [d["kod"]])
                    if made:
                        return made[0]["id"]
    return notes.create_course(pack.get("ders") or pack.get("kurs_kodu") or "Yeni ders")["id"]


def _apply_course_level(course_id: str, pack: dict) -> None:
    """PDF'ler henüz yüklenmemiş olsa da dersin plan, kavram kâğıdı, rehber, konu anlatımı, özet ve denemeleri gelir."""
    course = notes.get_course(course_id)
    if not course:
        return
    if pack.get("ders_plani") and not course.get("lecture_plan"):
        course["lecture_plan"] = pack["ders_plani"] | {"hazir": True}
    if pack.get("kavram_kagidi") and not course.get("formula_sheet"):
        course["formula_sheet"] = pack["kavram_kagidi"] | {"created": time.time(), "focus": "", "hazir": True}
    if pack.get("sinav_rehberi") and not course.get("sinav_rehberi"):
        course["sinav_rehberi"] = pack["sinav_rehberi"]
    for k in ("denemeler", "konu_anlatimi", "kisa_ozet"):
        if pack.get(k):
            course[k] = pack[k]
    course["hazir_paket"] = pack["_id"]
    notes.save_course(course)


def _installed_index() -> dict:
    f = USER_DIR / "kurulanlar.json"
    try:
        return json.loads(f.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def already_installed(data: bytes) -> bool:
    return hashlib.sha256(data).hexdigest() in _installed_index()


def looks_like_pack(data: bytes) -> bool:
    head = data[:4096].decode("utf-8", "ignore")
    return '"docs"' in data[: 2 * 1024 * 1024].decode("utf-8", "ignore") and ('"kurs_kodu"' in head or '"ders"' in head)


def install_pack(data: bytes) -> dict:
    """Yüklenen paketi doğrular, veri/hazir/ altına kaydeder, dersini bulur (yoksa oluşturur) ve uygular."""
    if len(data) > MAX_BYTES:
        raise ValueError("Paket çok büyük.")
    try:
        p = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Bu bir ders paketi değil (JSON okunamadı).")
    if not isinstance(p, dict) or not isinstance(p.get("docs"), dict) or not p["docs"]:
        raise ValueError("Bu bir ders paketi değil (belge listesi yok).")
    pid = key(p.get("kurs_kodu") or p.get("ders") or "paket") or "paket"
    USER_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USER_DIR / f"{pid}.json.yeni"
    tmp.write_text(json.dumps(p, ensure_ascii=False), "utf-8")
    tmp.replace(USER_DIR / f"{pid}.json")
    packs.cache_clear()
    pack = next(x for x in packs() if x["_id"] == pid)
    target = course_for_pack(pack)
    _apply_course_level(target, pack)
    applied, courses = 0, {target}
    for c in notes.list_courses():
        course = notes.get_course(c["id"])
        for d in (course or {}).get("docs", []):
            if find_doc(d["name"]) and apply_to_document(c["id"], d, d["name"]):
                applied += 1
                courses.add(c["id"])
    idx = _installed_index()
    idx[hashlib.sha256(data).hexdigest()] = {"id": pid, "zaman": time.time()}
    (USER_DIR / "kurulanlar.json").write_text(json.dumps(idx, ensure_ascii=False), "utf-8")
    name = (notes.get_course(target) or {}).get("name", "")
    return {"id": pid, "ders": p.get("ders", ""), "belge": len(p["docs"]), "uygulanan": applied,
            "dersler": sorted(courses), "ders_id": target, "ders_adi": name}


def list_packs() -> list[dict]:
    return [{"id": p["_id"], "ders": p.get("ders", ""), "kurs_kodu": p.get("kurs_kodu", ""), "belge": len(p["_docs"]),
             "deneme": len(p.get("denemeler") or [])} for p in packs()]


def course_guide(course: dict | None, limit: int = 0) -> str:
    """Hocanın sistem talimatına eklenecek kısa ders rehberi: belge özetleri + kavramlar (her soruda gönderilir).

    limit (karakter) verilirse sığacak kadarı alınır: önce kısa özetler ve sınav rehberinin başı, sonra kavramlar.
    Belgeler henüz yüklenmemiş ama dersin hazır paketi varsa paketteki özetler kullanılır."""
    if not course:
        return ""
    items = [(d["name"], d["hazir"]) for d in course.get("docs", []) if d.get("hazir")]
    if not items and course.get("hazir_paket"):
        pack = next((p for p in packs() if p["_id"] == course["hazir_paket"]), None)
        if pack:
            items = [(n.rsplit(".", 1)[0], d) for n, d in pack.get("docs", {}).items()]
    if not items:
        return ""
    rehber = course.get("sinav_rehberi") or ""
    if not limit:
        parts = []
        for name, h in items:
            kav = "; ".join(f"{k['terim']}: {k['tanim']}" for k in h.get("kavramlar", [])[:25])
            parts.append(f"## {name} — {h.get('baslik', '')}\n{h.get('ozet', '')}\nKavramlar: {kav}")
        guide = "# DERS NOTLARININ ÖZETİ (hocanın belgeleri)\n" + "\n\n".join(parts)
        return guide + ("\n\n# SINAV REHBERİ\n" + rehber if rehber else "")
    # Sınırlı bağlam (yerel model): her belgeye eşit pay
    head = "# DERS NOTLARININ ÖZETİ (hocanın belgeleri)\n"
    tail = ("\n\n# SINAV REHBERİ (kısaltılmış)\n" + rehber[: max(0, limit // 5)]) if rehber else ""
    share = max(150, (limit - len(head) - len(tail)) // len(items))
    parts = []
    for name, h in items:
        txt = f"## {name}: {h.get('baslik', '')}\n{h.get('ozet', '')}"
        if len(txt) < share:
            terms = ", ".join(k.get("terim", "") for k in h.get("kavramlar", []))
            txt += ("\nKavramlar: " + terms)[: share - len(txt)]
        parts.append(txt[:share])
    return (head + "\n\n".join(parts))[: limit - len(tail)] + tail
