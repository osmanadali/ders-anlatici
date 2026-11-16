"""Endüstri mühendisliği bilgi haritası: konu ağacı + kütüphane kapsam ölçümü.

Ağaç app/bilgi_haritasi.json içinde: IISE bilgi alanları + sektörün olmazsa olmazları (ERP, yalın, Altı Sigma…).
Kapsam: her düğümün anahtar kelimelerini içeren kütüphane parçalarının sayısı. Az olanlar "zayıf" düğümdür;
literatür taraması bunların İngilizce adlarıyla ek sorgu üretir.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import kutuphane

DOSYA = Path(__file__).with_name("bilgi_haritasi.json")
TAM_KAPSAM = 8  # bu kadar parça = çubuk dolu
ZAYIF_ESIK = 3  # bundan az parça = zayıf düğüm


@lru_cache(maxsize=1)
def harita() -> dict:
    return json.loads(DOSYA.read_text("utf-8"))


def _dugumler():
    for a in harita()["alanlar"]:
        for k in a["konular"]:
            yield a, k


def kapsam_olc() -> dict[str, int]:
    """{düğüm_id: kütüphanedeki ilgili parça sayısı}"""
    sonuc = {}
    for _, k in _dugumler():
        sonuc[k["id"]] = kutuphane.ifade_say(list(k["anahtar"]) + [k["ad"], k["ad_en"]])
    return sonuc


def agac() -> dict:
    """Ağaç + kapsam: alan başına ortalama kapsam, düğüm başına parça sayısı, zayıf işareti."""
    say = kapsam_olc()
    alanlar = []
    for a in harita()["alanlar"]:
        konular = []
        for k in a["konular"]:
            n = say.get(k["id"], 0)
            konular.append({
                "id": k["id"], "ad": k["ad"], "ad_en": k["ad_en"], "anahtar": k["anahtar"],
                "dersler": k.get("dersler") or a["dersler"], "kaynaklar": k.get("kaynaklar") or a["kaynaklar"],
                "parca": n, "kapsam": round(min(1.0, n / TAM_KAPSAM), 2), "zayif": n < ZAYIF_ESIK,
            })
        ort = sum(x["kapsam"] for x in konular) / len(konular)
        alanlar.append({"id": a["id"], "ad": a["ad"], "ad_en": a["ad_en"], "grup": a.get("grup", ""),
                        "dersler": a["dersler"], "kaynaklar": a["kaynaklar"], "kapsam": round(ort, 2),
                        "zayif_sayisi": sum(x["zayif"] for x in konular), "konular": konular})
    tum = [k for a in alanlar for k in a["konular"]]
    return {"alanlar": alanlar, "dugum_sayisi": len(tum), "zayif_sayisi": sum(k["zayif"] for k in tum),
            "kapsam": round(sum(k["kapsam"] for k in tum) / len(tum), 2) if tum else 0.0}


def zayif_sorgular(en_fazla: int = 2) -> list[str]:
    """Kapsamı en düşük düğümlerin İngilizce literatür sorguları (en zayıf önce)."""
    say = kapsam_olc()
    adaylar = sorted(((say[k["id"]], k["id"], k) for _, k in _dugumler()), key=lambda x: (x[0], x[1]))
    out = []
    for n, _, k in adaylar:
        if n >= ZAYIF_ESIK or len(out) >= en_fazla:
            break
        q = re.sub(r"\s+", " ", k["ad_en"]).strip().lower()
        if "engineering" not in q and "management" not in q:
            q += " engineering"
        out.append(q)
    return out
