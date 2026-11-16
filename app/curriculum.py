"""Hazır müfredatlar (app/mufredat/*.json): dersleri profil bilgisiyle tek tıkla oluşturur."""
from __future__ import annotations

import json
from pathlib import Path

from . import notes

DIR = Path(__file__).resolve().parent / "mufredat"


def programs() -> list[dict]:
    out = []
    for f in sorted(DIR.glob("*.json")):
        data = json.loads(f.read_text("utf-8"))
        out.append(
            {
                "id": f.stem,
                "program": data.get("program", f.stem),
                "not": data.get("not", ""),
                "kaynaklar": data.get("kaynaklar", []),
                "dersler": [
                    {k: d.get(k) for k in ("kod", "ad", "ad_en", "yariyil", "tur", "dil", "akts")}
                    | {"detayli": bool(d.get("haftalik_konular"))}
                    for d in data.get("dersler", [])
                ],
            }
        )
    return out


def _load(program_id: str) -> dict:
    f = DIR / f"{Path(program_id).name}.json"
    if not f.exists():
        raise KeyError("program bulunamadı")
    return json.loads(f.read_text("utf-8"))


def import_courses(program_id: str, codes: list[str]) -> list[dict]:
    """Seçilen dersleri oluşturur; aynı kodlu ders zaten varsa profilini günceller."""
    data = _load(program_id)
    wanted = set(codes)
    existing = {c.get("profile", {}).get("kod"): c for c in notes.list_courses() if c.get("profile")}
    created = []
    for d in data.get("dersler", []):
        if d.get("kod") not in wanted:
            continue
        profile = {k: d.get(k) for k in ("kod", "ad", "ad_en", "yariyil", "tur", "dil", "akts", "icerik",
                                         "haftalik_konular", "kaynak_kitaplar", "on_kosul")}
        profile["program"] = data.get("program", "")
        name = f"{d.get('kod', '')} {d.get('ad', '')}".strip()
        course = existing.get(d.get("kod"))
        if course is None:
            course = notes.create_course(name)
        course["profile"] = profile
        course["name"] = name
        notes.save_course(course)
        created.append(course)
    return created
