"""Kendi kendine çalışma: bilgisayar boşken kütüphane parçalarından ve ders notlarından soru-cevap üretir,
ikinci bir çağrıyla kaynakla doğrular ve yalnızca doğrulananları soru bankasına yazar.

Banka: DATA_DIR/ogrenme/soru_bankasi.jsonl (satır başına bir soru). Durum: calisma_durum.json.
Hocanın cevaplarında "DOĞRULANMIŞ BİLGİ" olarak ve Sınav sekmesinde "Soru bankasından sor" ile kullanılır.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from typing import Literal

from pydantic import BaseModel, Field

from . import config, kutuphane, llm, notes, ogrenme, siniflandir

log = logging.getLogger("ders.calisma")

BOSTA_SN = 300  # son öğrenci etkinliğinden en az 5 dk sonra çalış
SAATLIK_SINIR = 20  # saatte en fazla bu kadar soru üret
ILK_BEKLEME = 120
KONTROL_ARALIGI = 90
KISA_PARCA = 300  # bundan kısa metinlerden soru üretme
_kilit = threading.RLock()
_calisiyor = False
_son_hata = ""


class UretilenSoru(BaseModel):
    soru: str
    cevap: str
    tur: Literal["acik", "coktan"] = "acik"
    siklar: list[str] = Field(default_factory=list, description="Çoktan seçmelide 4 şık (cevap bunlardan biri), açık uçluda boş")


class SoruUret(BaseModel):
    sorular: list[UretilenSoru]


class Dogrulama(BaseModel):
    dogru: bool = Field(description="Cevap, verilen kaynak metne göre tamamen doğru mu")
    duzeltilmis_cevap: str = Field(default="", description="Doğru değilse kaynağa göre doğru cevap, doğruysa boş")


# ---------------------------------------------------------------- depolama
def _banka_yolu():
    return ogrenme.klasor() / "soru_bankasi.jsonl"


def _durum_yolu():
    return ogrenme.klasor() / "calisma_durum.json"


def _durum() -> dict:
    try:
        return json.loads(_durum_yolu().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _durum_yaz(d: dict) -> None:
    _durum_yolu().write_text(json.dumps(d, ensure_ascii=False), "utf-8")


def banka() -> list[dict]:
    p = _banka_yolu()
    if not p.exists():
        return []
    out = []
    for ln in p.read_text("utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _bankaya_yaz(kayit: dict) -> None:
    with _kilit, _banka_yolu().open("a", encoding="utf-8") as f:
        f.write(json.dumps(kayit, ensure_ascii=False) + "\n")


def _kaynak_anahtari(baslik: str, sayfa) -> str:
    return f"{baslik}|{sayfa}"


def durum() -> dict:
    b = [r for r in banka() if r.get("dogrulandi")]
    ders: dict[str, int] = {}
    for r in b:
        k = r.get("ders_id") or r.get("ders_kodu") or "genel"
        ders[k] = ders.get(k, 0) + 1
    d = _durum()
    return {"soru_sayisi": len(b), "ders_bazinda": ders, "son_calisma": d.get("son_calisma"),
            "calisiyor": _calisiyor, "acik": bool(config.load_settings().get("kendi_calisma", True))}


# ---------------------------------------------------------------- aday parçalar
def _adaylar() -> list[dict]:
    """Kütüphane parçaları + ders notu sayfaları; her biri {metin, baslik, sayfa, ders_kodu, ders_id}."""
    out = []
    try:
        for p in kutuphane.rastgele_parcalar(30, KISA_PARCA):
            out.append({"metin": p["metin"], "baslik": p["baslik"], "sayfa": p["sayfa"],
                        "ders_kodu": (p["dersler"] or [""])[0], "ders_id": ""})
    except Exception:
        log.exception("kütüphane parçaları okunamadı")
    try:
        sayfalar = []
        for c in notes.list_courses():
            course = notes.get_course(c["id"]) or {}
            kod = siniflandir.ders_kodu(course)
            for doc in course.get("docs", []):
                for i, pg in enumerate(doc.get("pages", []), 1):
                    if len(pg.get("text") or "") >= KISA_PARCA:
                        sayfalar.append({"metin": pg["text"], "baslik": doc.get("name", ""), "sayfa": i,
                                         "ders_kodu": kod, "ders_id": course["id"]})
        random.shuffle(sayfalar)
        out += sayfalar[:30]
    except Exception:
        log.exception("ders notları okunamadı")
    return out


def parca_sec() -> dict | None:
    """En az kullanılmış (bankada ve denemelerde az geçen) parçayı seçer."""
    adaylar = _adaylar()
    if not adaylar:
        return None
    kullanim: dict[str, int] = {}
    for r in banka():
        k = _kaynak_anahtari((r.get("kaynak") or {}).get("baslik", ""), (r.get("kaynak") or {}).get("sayfa"))
        kullanim[k] = kullanim.get(k, 0) + 1
    for k, n in _durum().get("denenen", {}).items():
        kullanim[k] = kullanim.get(k, 0) + n
    random.shuffle(adaylar)
    return min(adaylar, key=lambda a: kullanim.get(_kaynak_anahtari(a["baslik"], a["sayfa"]), 0))


# ---------------------------------------------------------------- üretim
URET_SISTEM = (
    "Sen titiz bir üniversite hocasısın. Verilen metne dayanarak Türkçe sınav soruları yazarsın. "
    "Yalnızca metinde açıkça yazan bilgiyi sor; metinde olmayan şeyi uydurma. Soru metne bakmadan anlaşılır olsun."
)
DOGRULA_SISTEM = (
    "Sen titiz bir denetçisin. Bir soruyu ve verilen cevabı kaynak metinle karşılaştır. "
    "Cevap kaynakla tamamen uyumluysa dogru=true; eksik, yanlış ya da kaynakta olmayan bilgi içeriyorsa dogru=false "
    "ve duzeltilmis_cevap alanına kaynağa göre doğru cevabı yaz."
)


def _saatlik_kalan() -> int:
    simdi = time.time()
    gecmis = [t for t in _durum().get("gecmis", []) if simdi - t < 3600]
    return max(0, SAATLIK_SINIR - len(gecmis))


async def bir_tur() -> dict:
    """Tek parçadan 1-2 soru üretip doğrular. {'atlandi': neden} ya da {'uretilen': n, 'eklenen': m}."""
    global _calisiyor, _son_hata
    if not config.load_settings().get("kendi_calisma", True):
        return {"atlandi": "kapalı"}
    if _calisiyor:
        return {"atlandi": "zaten çalışıyor"}
    if not llm.ogrenci_bosta(BOSTA_SN):
        return {"atlandi": "öğrenci etkinliği"}
    if _saatlik_kalan() <= 0:
        return {"atlandi": "saatlik sınır"}
    if llm.provider() == "gemini" or not llm.ai_hazir():
        return {"atlandi": "yerel yapay zeka hazır değil"}
    parca = await asyncio.to_thread(parca_sec)
    if not parca:
        return {"atlandi": "parça yok"}
    _calisiyor = True
    uretilen = eklenen = 0
    anahtar = _kaynak_anahtari(parca["baslik"], parca["sayfa"])
    try:
        metin = parca["metin"][:2500]
        await llm.arka_plan_sirasi()
        uretim = await llm._parse(
            SoruUret, f"<kaynak>\n{metin}\n</kaynak>\nBu metinden 1-2 soru ve cevap üret (en fazla 2).",
            URET_SISTEM, max_tokens=1200)
        mevcut = {ogrenme.kirp(r.get("soru", ""), 200).lower() for r in banka()}
        for s in uretim.sorular[:2]:
            if _saatlik_kalan() <= 0:
                break
            if not s.soru.strip() or not s.cevap.strip():
                continue
            uretilen += 1
            _sayac_ekle()
            if ogrenme.kirp(s.soru, 200).lower() in mevcut:
                continue
            await llm.arka_plan_sirasi()
            if not llm.ogrenci_bosta(0):  # öğrenci araya girdi: kalanını sonraya bırak
                break
            kontrol = await llm._parse(
                Dogrulama,
                f"<kaynak>\n{metin}\n</kaynak>\nSoru: {s.soru}\nVerilen cevap: {s.cevap}",
                DOGRULA_SISTEM, max_tokens=500)
            if not kontrol.dogru:
                continue
            siklar = [x.strip() for x in s.siklar if x.strip()]
            tur = "coktan" if s.tur == "coktan" and len(siklar) >= 2 and s.cevap.strip() in siklar else "acik"
            _bankaya_yaz({
                "soru": s.soru.strip(), "cevap": s.cevap.strip(), "ders_kodu": parca["ders_kodu"],
                "ders_id": parca["ders_id"], "kaynak": {"baslik": parca["baslik"], "sayfa": parca["sayfa"]},
                "tur": tur, "siklar": siklar if tur == "coktan" else [], "olusturma": time.time(), "dogrulandi": True,
            })
            eklenen += 1
        _son_hata = ""
    except asyncio.CancelledError:
        raise
    except Exception as e:  # model hatası çalışmayı durdurmasın
        _son_hata = str(e)
        log.warning("kendi kendine çalışma: %s", e)
    finally:
        _calisiyor = False
        with _kilit:
            d = _durum()
            den = d.setdefault("denenen", {})
            den[anahtar] = den.get(anahtar, 0) + 1
            d["son_calisma"] = time.time()
            _durum_yaz(d)
    return {"uretilen": uretilen, "eklenen": eklenen}


def _sayac_ekle() -> None:
    with _kilit:
        d = _durum()
        simdi = time.time()
        d["gecmis"] = [t for t in d.get("gecmis", []) if simdi - t < 3600] + [simdi]
        _durum_yaz(d)


async def zamanlayici() -> None:
    """Uygulama açıkken arka planda: öğrenci boştayken sırayla soru üretir."""
    await asyncio.sleep(ILK_BEKLEME)
    while True:
        try:
            await bir_tur()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("çalışma zamanlayıcısı: %s", e)
        await asyncio.sleep(KONTROL_ARALIGI)


# ---------------------------------------------------------------- kullanım
def _uygun(r: dict, course: dict | None, genel: bool) -> bool:
    if not r.get("dogrulandi"):
        return False
    if course is None:
        return genel
    kod = siniflandir.ders_kodu(course)
    if r.get("ders_id") == course.get("id") or (kod and r.get("ders_kodu") == kod):
        return True
    return genel and not r.get("ders_id") and not r.get("ders_kodu")


def dogrulanmis_blok(course: dict | None, soru: str, en_fazla: int = 2, sinir: int = 500) -> str:
    """Soruya benzeyen doğrulanmış soru-cevaplar (kısa blok). Yoksa ''."""
    if not soru:
        return ""
    puan = [(ogrenme.benzerlik(soru, r["soru"] + " " + r["cevap"]), r) for r in banka() if _uygun(r, course, True)]
    puan = [x for x in sorted(puan, key=lambda x: -x[0]) if x[0] >= 0.15][:en_fazla]
    if not puan:
        return ""
    satirlar = []
    for _, r in puan:
        k = r.get("kaynak") or {}
        satirlar.append(f"- {ogrenme.kirp(r['soru'], 140)} → {ogrenme.kirp(r['cevap'], 220)} ({k.get('baslik', '')} s.{k.get('sayfa', '?')})")
    return ogrenme.kirp_blok("DOĞRULANMIŞ BİLGİ (kaynakla doğrulanmış soru-cevaplar; ilgiliyse güvenle kullan):\n" + "\n".join(satirlar), sinir)


def quiz_sorulari(course: dict, n: int = 5) -> dict:
    """Dersin bankasından rastgele n soru; mevcut sınav görüntüleyicisinin biçiminde."""
    uygun = [r for r in banka() if _uygun(r, course, False)]
    random.shuffle(uygun)
    sorular = []
    for r in uygun[: max(1, min(int(n), 20))]:
        k = r.get("kaynak") or {}
        coktan = r.get("tur") == "coktan" and r.get("siklar")
        siklar = list(r["siklar"]) if coktan else []
        random.shuffle(siklar)
        sorular.append({
            "question": r["soru"], "kind": "coktan_secmeli" if coktan else "acik_uclu", "choices": siklar,
            "answer": r["cevap"], "topic": k.get("baslik", "") or "Soru bankası",
            "page": f"{k.get('baslik', '')} s.{k['sayfa']}" if k.get("sayfa") else "",
        })
    return {"questions": sorular}
