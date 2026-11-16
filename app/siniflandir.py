"""Yüklenen notun hangi derse ait olduğunu bulur (internetsiz, önce hızlı kurallar, gerekirse yerel yapay zeka).

Sıra:
1. Hazır ders paketinde bu dosya adı varsa → paketin dersi.
2. Dosya adında/metinde ders kodu (ör. "ENM 463") geçiyorsa → o koddaki ders (yoksa müfredattan oluşturulur).
3. Metin benzerliği (TF-IDF): notun metni her dersin adı, müfredat içeriği, haftalık konuları, mevcut notları ve
   kavramlarıyla karşılaştırılır; açık bir kazanan varsa o ders.
4. Kararsız kalınırsa yapay zekaya ders listesiyle birlikte sorulur.
"""
from __future__ import annotations

import io
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from . import curriculum, hazir, notes

KOD_RE = re.compile(r"\b([a-z]{2,4})\s?-?\s?(\d{3})\b")
STOP = set("""bir ve ile icin olan olarak gibi daha cok bu su o da de ne ise her sonra kadar ancak veya hem
gore olan olur olarak olmasi oldugu ayni diger bunlar bunu buna sayfa ders dersi hafta konu konusu nedir
the and of to in for is are on with by as an be or at from this that which""".split())


def _ascii(s: str) -> str:
    s = (s or "").replace("ı", "i").replace("İ", "i")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{3,}", _ascii(s)) if w not in STOP]


def kodlar(s: str) -> set[str]:
    """Metindeki ders kodları, normalleştirilmiş: 'ENM 463' → 'ENM463'."""
    return {(a + b).upper() for a, b in KOD_RE.findall(_ascii(s))}


def ders_kodu(course: dict) -> str:
    k = (course.get("profile") or {}).get("kod") or ""
    found = kodlar(k) or kodlar(course.get("name", ""))
    return next(iter(found), "")


def _course_text(course: dict) -> str:
    p = course.get("profile") or {}
    parts = [course.get("name", "")] * 3
    for k in ("ad", "ad_en", "amac", "icerik", "icerik_en"):
        if p.get(k):
            parts.append(str(p[k]))
    for k in ("haftalik_konular", "haftalik_konular_en", "ogrenme_ciktilari"):
        if isinstance(p.get(k), list):
            parts.extend(str(x) for x in p[k])
    budget = 60000
    for d in course.get("docs", []):
        parts.append(d.get("name", ""))
        h = d.get("hazir") or {}
        parts.append(h.get("baslik", "") + " " + h.get("ozet", ""))
        parts.extend(k.get("terim", "") for k in h.get("kavramlar", []))
        for pg in d.get("pages", [])[:6]:
            t = pg.get("text", "")[:1500]
            if budget > 0:
                parts.append(t)
                budget -= len(t)
    return "\n".join(parts)


def _curriculum_courses(existing_codes: set[str]) -> list[dict]:
    """Müfredatta olup henüz oluşturulmamış dersler (aday olarak; seçilirse oluşturulur)."""
    out = []
    for prog in curriculum.programs():
        data = curriculum._load(prog["id"])
        for d in data.get("dersler", []):
            kod = next(iter(kodlar(d.get("kod", ""))), "")
            if not kod or kod in existing_codes:
                continue
            out.append({"id": f"mufredat:{prog['id']}:{d['kod']}", "name": f"{d['kod']} {d.get('ad', '')}".strip(),
                        "profile": d, "docs": [], "_program": prog["id"], "_kod": d["kod"]})
    return out


@dataclass
class Sonuc:
    course_id: str | None
    guven: float
    neden: str
    adaylar: list[dict] = field(default_factory=list)  # [{id, name, skor}]
    yeni_ders: str = ""  # oluşturulması önerilen ders adı (müfredattan ya da yapay zekadan)


def _tfidf_scores(text: str, courses: list[dict]) -> list[tuple[float, dict]]:
    docs = [Counter(_tokens(_course_text(c))) for c in courses]
    q = Counter(_tokens(text))
    if not q:
        return []
    n = len(docs) + 1
    df = Counter()
    for d in docs + [q]:
        df.update(d.keys())
    idf = {w: math.log((n + 1) / (df[w] + 0.5)) for w in df}

    def vec(c: Counter) -> dict:
        v = {w: (1 + math.log(f)) * idf[w] for w, f in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {w: x / norm for w, x in v.items()}

    qv = vec(q)
    out = []
    for c, d in zip(courses, docs):
        dv = vec(d)
        out.append((sum(x * dv.get(w, 0) for w, x in qv.items()), c))
    out.sort(key=lambda t: -t[0])
    return out


def bul(filename: str, text: str, ipucu: str = "") -> Sonuc:
    """Kurallar + metin benzerliği (yapay zekasız, anında).

    ipucu: aynı anda yüklenen bir önceki notun dersi (birlikte yüklenen notlar çoğunlukla aynı derse aittir)."""
    courses = notes.list_courses()
    # 1) hazır paket
    hit = hazir.find_doc(filename)
    if hit:
        pack = hit[0]
        cid = hazir.course_for_pack(pack, create=False)
        if cid:
            return Sonuc(cid, 1.0, "hazır ders paketindeki bir dosya")
    # 2) ders kodu (önce dosya adı, sonra metnin başı)
    by_code = {ders_kodu(c): c for c in courses if ders_kodu(c)}
    for src, label in ((filename, "dosya adındaki"), (text[:6000], "nottaki")):
        for k in kodlar(src):
            if k in by_code:
                return Sonuc(by_code[k]["id"], 0.95, f"{label} ders kodu ({k})")
            for cc in _curriculum_courses(set(by_code)):
                if next(iter(kodlar(cc["_kod"])), "") == k:
                    return Sonuc(cc["id"], 0.9, f"{label} ders kodu ({k}), müfredattan yeni ders", yeni_ders=cc["name"])
    # 3) metin benzerliği: mevcut dersler + müfredattaki dersler
    pool = courses + _curriculum_courses(set(by_code))
    scored = _tfidf_scores(filename + "\n" + text, pool)
    adaylar = [{"id": c["id"], "name": c["name"], "skor": round(s, 3)} for s, c in scored[:5]]
    if not scored:
        return Sonuc(None, 0.0, "notta okunabilir metin yok", adaylar)
    (s1, c1) = scored[0]
    s2 = scored[1][0] if len(scored) > 1 else 0.0
    if ipucu:
        hint = next(((s, c) for s, c in scored if c["id"] == ipucu), None)
        if hint and hint[0] >= 0.04 and hint[0] >= 0.75 * s1:
            return Sonuc(ipucu, 0.7, "birlikte yüklenen notlarla aynı ders", adaylar)
    # Mevcut derse hafif öncelik: kullanıcının dersleri müfredattaki yüzlerce dersten daha olası
    if c1["id"].startswith("mufredat:"):
        own = next(((s, c) for s, c in scored if not c["id"].startswith("mufredat:")), None)
        if own and own[0] >= s1 * 0.85:
            (s1, c1), s2 = own, s1
    if s1 >= 0.08 and (s1 - s2 >= 0.03 or s1 >= 1.4 * s2):
        guven = min(0.89, 0.5 + s1)
        return Sonuc(c1["id"], guven, f"konu benzerliği ({c1['name']})", adaylar,
                     yeni_ders=c1["name"] if c1["id"].startswith("mufredat:") else "")
    return Sonuc(None, s1, "emin olunamadı", adaylar)


def en_yakin(s: Sonuc) -> Sonuc:
    """Yapay zeka yokken kararsız kalındıysa: en yakın MEVCUT derse koy (müfredattan ders uydurmak yerine).

    Yanlışsa kullanıcı tek tıkla taşır; 'Gelen notlar'a atmaktan iyidir çünkü sonraki notlar bunu ipucu alır."""
    if s.course_id or s.yeni_ders:
        return s
    own = [a for a in s.adaylar if not a["id"].startswith("mufredat:")]
    if own and own[0]["skor"] >= 0.04:
        return Sonuc(own[0]["id"], 0.4, f"en yakın ders (emin değil: {own[0]['name']})", s.adaylar)
    top = s.adaylar[0] if s.adaylar else None
    if top and top["id"].startswith("mufredat:") and top["skor"] >= 0.08:
        return Sonuc(top["id"], 0.4, "en yakın müfredat dersi (emin değil)", s.adaylar, yeni_ders=top["name"])
    return s


class DersSecimi(BaseModel):
    ders_id: str = Field(description="Listedeki dersin kimliği; hiçbiri uymuyorsa 'yeni'")
    yeni_ders_adi: str = Field(description="ders_id 'yeni' ise önerilen ders adı (ör. 'Yöneylem Araştırması'), değilse boş")
    guven: float = Field(description="0-1 arası")
    neden: str = Field(description="Kısa gerekçe")


async def bul_yapay_zeka(filename: str, text: str, onceki: Sonuc) -> Sonuc:
    """Kurallar kararsız kaldığında yapay zekaya sorar (yerel model; Gemini anahtarı varsa o da olabilir)."""
    from . import llm

    courses = notes.list_courses()
    ids = {c["id"] for c in courses} | {a["id"] for a in onceki.adaylar}
    lines = []
    for c in courses:
        p = c.get("profile") or {}
        desc = (p.get("icerik") or "")[:250] or ", ".join(d["name"] for d in c.get("docs", [])[:6])
        lines.append(f"- {c['id']}: {c['name']} — {desc}")
    for a in onceki.adaylar:
        if a["id"].startswith("mufredat:"):
            lines.append(f"- {a['id']}: {a['name']} (henüz eklenmemiş müfredat dersi)")
    prompt = (f"Öğrencinin yüklediği not hangi derse ait? Dosya adı: {filename}\n\nNotun başı:\n{text[:3500]}\n\n"
              "Dersler:\n" + "\n".join(lines) + "\n\nEn uygun dersin kimliğini ver. Hiçbiri uymuyorsa ders_id='yeni' ve "
              "yeni_ders_adi'na notun dersinin adını yaz.")
    try:
        r = await llm._parse(DersSecimi, prompt, max_tokens=400)
    except llm.TutorError:
        return onceki
    if r.ders_id in ids:
        name = next((a["name"] for a in onceki.adaylar if a["id"] == r.ders_id), "")
        return Sonuc(r.ders_id, max(0.6, min(r.guven, 0.9)), f"yapay zeka: {r.neden}", onceki.adaylar,
                     yeni_ders=name if r.ders_id.startswith("mufredat:") else "")
    if r.ders_id == "yeni" and r.yeni_ders_adi.strip():
        return Sonuc(None, r.guven, f"yapay zeka: {r.neden}", onceki.adaylar, yeni_ders=r.yeni_ders_adi.strip()[:80])
    return onceki


def metin_cikar(filename: str, data: bytes, pages: int = 12) -> str:
    """Sınıflandırma için notun ilk sayfalarının metni (kaydetmeden)."""
    if Path(filename).suffix.lower() != ".pdf":
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:pages])
    except Exception:
        return ""


def ders_hazirla(sonuc: Sonuc, varsayilan_ad: str = "Gelen notlar") -> tuple[str, bool]:
    """Kararı gerçek bir derse çevirir: müfredat dersi ya da yeni ders gerekiyorsa oluşturur. (ders_id, yeni_mi)"""
    cid = sonuc.course_id
    if cid and not cid.startswith("mufredat:"):
        return cid, False
    if cid and cid.startswith("mufredat:"):
        _, prog, kod = cid.split(":", 2)
        created = curriculum.import_courses(prog, [kod])
        if created:
            return created[0]["id"], True
    name = sonuc.yeni_ders or varsayilan_ad
    same = next((c for c in notes.list_courses() if _ascii(c["name"]) == _ascii(name)), None)
    if same:
        return same["id"], False
    return notes.create_course(name)["id"], True
