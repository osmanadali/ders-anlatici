"""Hazır bilgi: depoyla gelen kısa ERP/MRP rehberleri (app/hazir_bilgi/*.md), açılışta kütüphaneye bir kez eklenir.

Kullanıcı bir rehberi kütüphaneden silerse yeniden eklenmez (eklenenlerin imzası kayıt altında tutulur).
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from . import kutuphane

log = logging.getLogger("ders.hazir_bilgi")
DIR = Path(__file__).with_name("hazir_bilgi")


def _imza_dosyasi() -> Path:
    return kutuphane.KOK / "hazir_bilgi_imza.json"


def _oku() -> set[str]:
    try:
        return set(json.loads(_imza_dosyasi().read_text("utf-8")))
    except (OSError, ValueError):
        return set()


def yukle() -> int:
    """Henüz eklenmemiş rehberleri tur='kitap' olarak ekler; eklenen sayısını döndürür."""
    gorulen = _oku()
    eklenen = 0
    for f in sorted(DIR.glob("*.md")):
        veri = f.read_bytes()
        imza = hashlib.sha256(veri).hexdigest()
        if imza in gorulen:
            continue
        try:
            k = kutuphane.ekle_dosya(f.name, veri, "kitap")
            kutuphane.guncelle(k["id"], {"baslik": f.stem, "yazar": "Ders Anlatıcı (hazır rehber)"})
            eklenen += 1
        except ValueError as e:  # zaten kütüphanede (kullanıcı kendisi eklemiş)
            log.info("hazır bilgi atlandı (%s): %s", f.name, e)
        except Exception:
            log.exception("hazır bilgi eklenemedi: %s", f.name)
            continue
        gorulen.add(imza)
    try:
        kutuphane.KOK.mkdir(parents=True, exist_ok=True)
        _imza_dosyasi().write_text(json.dumps(sorted(gorulen)), "utf-8")
    except OSError:
        log.exception("hazır bilgi imzası yazılamadı")
    return eklenen
