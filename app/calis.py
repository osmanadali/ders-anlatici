"""Çalış sekmesi: hatalarım defteri, kartlar + aralıklı tekrar, süreli sınav simülasyonu, hesap çalışma alanı
(Excel/Python indirme) ve ders sonrası özet kartı.

Veriler DATA_DIR/calis/ altında: hatalar.json, kartlar.json (aralıklı tekrar durumu + özel kartlar), simulasyon.json.
Kartlar kaynaklardan (hazır paket kavramları, formül kâğıdı, soru bankası, hatalar) anında üretilir; yalnızca
tekrar durumu saklanır. Hata analizi ve özet kartı yapay zekayla yapılır, yapay zeka yoksa kural tabanlı yedeğe düşer.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import threading
import time
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from pydantic import BaseModel, Field

from . import calis_dosya, calisma, config, hesap, llm, notes, store

log = logging.getLogger("ders.calis")
router = APIRouter(prefix="/api/calis")
_kilit = threading.RLock()

ARALIKLAR = [1, 3, 7, 14, 30]  # gün
YENI_GUNLUK = 10  # bir günde en fazla bu kadar yeni kart
HATA_TURLERI = {
    "kavram_yanilgisi": "Kavram yanılgısı", "islem_hatasi": "İşlem hatası", "dikkat": "Dikkat", "bilgi_eksikligi": "Bilgi eksikliği",
}


# ---------------------------------------------------------------- depolama
def _yol(ad: str):
    d = config.DATA_DIR / "calis"
    d.mkdir(parents=True, exist_ok=True)
    return d / ad


class DepoHatasi(HTTPException):
    """Veri dosyası okunamadı (geçici G/Ç hatası); yazarak ezmemek için yükseltilir (uç noktada 503)."""

    def __init__(self, ayrinti: str):
        super().__init__(503, "Veri dosyası şu an okunamıyor, biraz sonra tekrar dene.")
        self.log_ayrinti = ayrinti


def _oku(ad: str, varsayilan):
    p = _yol(ad)
    son = None
    for deneme in range(3):
        try:
            return json.loads(p.read_text("utf-8"))
        except FileNotFoundError:
            return varsayilan
        except json.JSONDecodeError as e:
            yedek = p.with_name(f"{p.name}.bozuk-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                p.replace(yedek)
            except OSError:
                pass
            log.error("%s bozuk (%s); %s olarak yedeklendi, boş devam ediliyor", ad, e, yedek.name)
            return varsayilan
        except OSError as e:
            son = e
            if deneme < 2:
                time.sleep(0.1)
    log.error("%s okunamadı: %s", ad, son)
    raise DepoHatasi(f"{ad} okunamadı: {son}")


def _yaz(ad: str, veri) -> None:
    p = _yol(ad)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(veri, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _bugun() -> date:
    return date.today()


def _ders(course_id: str | None) -> dict | None:
    try:
        return notes.get_course(course_id) if course_id else None
    except ValueError:
        return None


def _kimlik(*parcalar: str) -> str:
    s = "|".join(re.sub(r"\s+", " ", (p or "").strip().lower()) for p in parcalar)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


# ================================================================ 1) HATALARIM
class HataGirdi(BaseModel):
    course_id: str = ""
    soru: str
    dogru_cevap: str = ""
    ogrenci_cevabi: str = ""
    konu: str = ""
    kaynak: str = ""


class HataAnalizi(BaseModel):
    tur: Literal["kavram_yanilgisi", "islem_hatasi", "dikkat", "bilgi_eksikligi"] = Field(
        description="hata türü: kavram_yanilgisi, islem_hatasi, dikkat ya da bilgi_eksikligi")
    aciklama: str = Field(description="Hatanın nedeni, 1-2 kısa cümle")
    tekrar_onerisi: str = Field(description="Neyi nasıl tekrar etmeli, 1 kısa cümle")


def hata_ekle(g: HataGirdi, kaynak_ek: str = "") -> tuple[dict, bool]:
    """Hatayı deftere yazar; aynı soru varsa sayacı artırır ve arşivden çıkarır. (kayıt, yeni_mi)"""
    soru = (g.soru or "").strip()
    if not soru:
        raise HTTPException(400, "Soru boş")
    hid = _kimlik(g.course_id, soru)
    simdi = time.time()
    with _kilit:
        liste = _oku("hatalar.json", [])
        for r in liste:
            if r["id"] == hid:
                r["sayac"] = r.get("sayac", 1) + 1
                r["son"] = simdi
                r["arsiv"] = False
                if g.ogrenci_cevabi:
                    r["ogrenci_cevabi"] = g.ogrenci_cevabi[:1500]
                if g.dogru_cevap and not r.get("dogru_cevap"):
                    r["dogru_cevap"] = g.dogru_cevap[:2000]
                _yaz("hatalar.json", liste)
                return r, False
        r = {"id": hid, "course_id": g.course_id or "", "soru": soru[:2000], "dogru_cevap": (g.dogru_cevap or "")[:2000],
             "ogrenci_cevabi": (g.ogrenci_cevabi or "")[:1500], "konu": (g.konu or "")[:120],
             "kaynak": (g.kaynak or kaynak_ek or "")[:200], "tur": "", "aciklama": "", "oneri": "",
             "sayac": 1, "ilk": simdi, "son": simdi, "arsiv": False}
        liste.append(r)
        _yaz("hatalar.json", liste)
    return r, True


async def hata_analiz_et(hid: str) -> None:
    """Arka planda: yapay zekayla hata türü + açıklama + tekrar önerisi. Yapay zeka yoksa sessizce atlar."""
    try:
        if not llm.ai_hazir():
            return
        r = next((x for x in _oku("hatalar.json", []) if x["id"] == hid), None)
        if not r or r.get("tur"):
            return
        await llm.arka_plan_sirasi()
        metin = (f"Öğrenci bir soruyu yanlış yaptı.\nSoru: {r['soru']}\nDoğru cevap: {r.get('dogru_cevap') or '(bilinmiyor)'}\n"
                 f"Öğrencinin cevabı: {r.get('ogrenci_cevabi') or '(boş)'}\nKonu: {r.get('konu') or '-'}\n\n"
                 "Hatanın türünü seç: kavram_yanilgisi (kavramı yanlış anlamış), islem_hatasi (yöntem doğru, hesap/işlem yanlış), "
                 "dikkat (soruyu yanlış okuma, birim, işaret, acelecilik), bilgi_eksikligi (konuyu bilmiyor). "
                 "Kısa bir açıklama ve tek cümlelik tekrar önerisi yaz. Türkçe yaz.")
        a = await llm._parse(HataAnalizi, metin, "Sen öğrencinin hatalarını teşhis eden sabırlı bir öğretim üyesisin. Türkçe yaz.", max_tokens=600)
        with _kilit:
            liste = _oku("hatalar.json", [])
            for x in liste:
                if x["id"] == hid:
                    x["tur"], x["aciklama"], x["oneri"] = a.tur, a.aciklama[:400], a.tekrar_onerisi[:300]
            _yaz("hatalar.json", liste)
    except Exception as e:  # analiz isteğe bağlı: hiçbir şey bozulmasın
        log.info("hata analizi atlandı: %s", e)


@router.post("/hata")
async def post_hata(g: HataGirdi, bg: BackgroundTasks):
    r, yeni = hata_ekle(g)
    if not r.get("tur"):
        bg.add_task(hata_analiz_et, r["id"])
    return {"hata": r, "yeni": yeni}


@router.get("/hatalar")
async def get_hatalar(course_id: str = "", arsiv: int = 0):
    liste = [r for r in _oku("hatalar.json", []) if (not course_id or r.get("course_id") == course_id) and bool(r.get("arsiv")) == bool(arsiv)]
    liste.sort(key=lambda r: -r.get("son", 0))
    gruplar: dict[str, list] = {}
    for r in liste:
        gruplar.setdefault(r.get("konu") or "Genel", []).append(r)
    return {"hatalar": liste, "gruplar": [{"konu": k, "hatalar": v} for k, v in sorted(gruplar.items(), key=lambda kv: -len(kv[1]))],
            "turler": HATA_TURLERI}


@router.post("/hata/{hid}/arsiv")
async def hata_arsiv(hid: str, body: dict | None = None):
    geri = bool((body or {}).get("geri"))
    with _kilit:
        liste = _oku("hatalar.json", [])
        for r in liste:
            if r["id"] == hid:
                r["arsiv"] = not geri
                _yaz("hatalar.json", liste)
                return {"ok": True}
    raise HTTPException(404, "Hata kaydı yok")


@router.delete("/hata/{hid}")
async def hata_sil(hid: str):
    with _kilit:
        liste = _oku("hatalar.json", [])
        _yaz("hatalar.json", [r for r in liste if r["id"] != hid])
    return {"ok": True}


# ================================================================ 2) KARTLAR + ARALIKLI TEKRAR
def _kart(course_id: str, kaynak: str, on: str, arka: str, konu: str = "") -> dict:
    return {"id": _kimlik(course_id, kaynak, on), "course_id": course_id, "kaynak": kaynak, "on": on.strip(), "arka": arka.strip(), "konu": konu}


def kart_havuzu(course_id: str) -> list[dict]:
    """Dersin tüm kartları (kaynaklardan anında üretilir, tekrarsız)."""
    c = _ders(course_id)
    kartlar: list[dict] = []
    # hatalar önce: en çok tekrar gerektirenler
    for r in sorted(_oku("hatalar.json", []), key=lambda r: -r.get("sayac", 1)):
        if r.get("course_id") == course_id and not r.get("arsiv") and r.get("dogru_cevap"):
            arka = r["dogru_cevap"] + (("\n\n" + r["oneri"]) if r.get("oneri") else "")
            kartlar.append(_kart(course_id, "hata", r["soru"], arka, r.get("konu") or "Hatalarım"))
    if c:
        for d in c.get("docs", []):
            h = d.get("hazir") or {}
            for k in h.get("kavramlar", []):
                if k.get("terim") and k.get("tanim"):
                    sayfa = f"\n\n({d.get('name', '')} s.{k['sayfa']})" if k.get("sayfa") else ""
                    kartlar.append(_kart(course_id, "kavram", k["terim"], k["tanim"] + sayfa, h.get("baslik") or d.get("name", "")))
        for s in (c.get("formula_sheet") or {}).get("sections", []):
            for it in s.get("items", []):
                if it.get("name") and (it.get("tex") or it.get("note")):
                    arka = (f"$${it['tex']}$$" if it.get("tex") else "") + (("\n" + it["note"]) if it.get("note") else "")
                    kartlar.append(_kart(course_id, "formul", it["name"], arka, s.get("title", "")))
        for r in calisma.banka():
            if calisma._uygun(r, c, False):
                k = r.get("kaynak") or {}
                arka = r["cevap"]
                if r.get("tur") == "coktan" and r.get("siklar"):
                    arka = "Cevap: " + r["cevap"]
                kartlar.append(_kart(course_id, "banka", r["soru"], arka, k.get("baslik", "") or "Soru bankası"))
    for o in _oku("kartlar.json", {}).get("ozel", []):
        if o.get("course_id") == course_id:
            kartlar.append(o)
    gorulen, tekil = set(), []
    for k in kartlar:
        if k["id"] not in gorulen:
            gorulen.add(k["id"])
            tekil.append(k)
    return tekil


def _bugun_listesi(course_id: str, n: int) -> dict:
    durum = _oku("kartlar.json", {}).get("durum", {})
    bugun = _bugun().isoformat()
    havuz = kart_havuzu(course_id)
    tekrar, yeni = [], []
    for k in havuz:
        d = durum.get(k["id"])
        if d is None:
            yeni.append(k)
        elif d.get("sonraki", "") <= bugun:
            tekrar.append({**k, "durum": d})
    tekrar.sort(key=lambda k: k["durum"].get("sonraki", ""))
    yeni_kalan = max(0, YENI_GUNLUK - sum(1 for d in durum.values() if d.get("ilk") == bugun and d.get("course_id") == course_id))
    yeni = yeni[:yeni_kalan]
    return {"tekrar": tekrar, "yeni": yeni, "toplam": len(havuz), "kalan": len(tekrar) + len(yeni)}


@router.get("/kartlar")
async def get_kartlar(course_id: str = "", n: int = 20):
    b = _bugun_listesi(course_id, n)
    secili = (b["tekrar"] + b["yeni"])[: max(1, min(int(n), 100))]
    return {"kartlar": secili, "bugun_tekrar": b["kalan"], "tekrar": len(b["tekrar"]), "yeni": len(b["yeni"]), "toplam": b["toplam"]}


class KartCevap(BaseModel):
    puan: str | int = Field(description="bilemedim / zor / kolay (ya da 0/1/2)")
    course_id: str = ""


def sm2(durum: dict | None, puan: str | int, bugun: date) -> dict:
    """Aralıklı tekrar: 1/3/7/14/30 gün. Bilemedim → başa (1 gün), Zor → aynı basamak, Kolay → bir üst basamak."""
    p = {"bilemedim": 0, "zor": 1, "kolay": 2}.get(str(puan).lower(), None) if not isinstance(puan, int) else puan
    if p not in (0, 1, 2):
        raise HTTPException(400, "puan: bilemedim, zor ya da kolay olmalı")
    d = dict(durum or {"idx": -1, "tekrar": 0, "basarisiz": 0, "ilk": bugun.isoformat()})
    idx = d.get("idx", -1)
    if p == 0:
        idx = 0
        d["basarisiz"] = d.get("basarisiz", 0) + 1
    elif p == 1:
        idx = max(0, idx)
    else:
        idx = min(len(ARALIKLAR) - 1, idx + 1) if idx >= 0 else 1
    d.update(idx=idx, tekrar=d.get("tekrar", 0) + 1, son=bugun.isoformat(), aralik=ARALIKLAR[idx],
             sonraki=(bugun + timedelta(days=ARALIKLAR[idx])).isoformat(), puan=p)
    return d


@router.post("/kart/{kid}/cevap")
async def kart_cevap(kid: str, g: KartCevap):
    if not re.fullmatch(r"[a-f0-9]{8,40}", kid):
        raise HTTPException(400, "geçersiz kart")
    with _kilit:
        veri = _oku("kartlar.json", {})
        durum = veri.setdefault("durum", {})
        d = sm2(durum.get(kid), g.puan, _bugun())
        d["course_id"] = g.course_id
        durum[kid] = d
        _yaz("kartlar.json", veri)
    return {"sonraki": d["sonraki"], "aralik_gun": d["aralik"]}


class OzelKart(BaseModel):
    course_id: str = ""
    kartlar: list[dict]


@router.post("/kartlar/ekle")
async def kart_ekle(g: OzelKart):
    eklenen = 0
    with _kilit:
        veri = _oku("kartlar.json", {})
        ozel = veri.setdefault("ozel", [])
        var = {o["id"] for o in ozel}
        for k in g.kartlar:
            on, arka = str(k.get("on", "")).strip(), str(k.get("arka", "")).strip()
            if not on or not arka:
                continue
            kart = _kart(g.course_id, "ozet", on, arka, str(k.get("konu", "")))
            if kart["id"] not in var:
                ozel.append(kart)
                var.add(kart["id"])
                eklenen += 1
        _yaz("kartlar.json", veri)
    return {"eklenen": eklenen}


@router.get("/ozet")
async def ozet(course_id: str = ""):
    hat = [r for r in _oku("hatalar.json", []) if (not course_id or r.get("course_id") == course_id) and not r.get("arsiv")]
    turler: dict[str, int] = {}
    konular: dict[str, int] = {}
    for r in hat:
        if r.get("tur"):
            turler[r["tur"]] = turler.get(r["tur"], 0) + 1
        konular[r.get("konu") or "Genel"] = konular.get(r.get("konu") or "Genel", 0) + 1
    b = _bugun_listesi(course_id, 20)
    sim = [s for s in _oku("simulasyon.json", []) if not course_id or s.get("course_id") == course_id]
    return {"hata_sayisi": len(hat), "bugun_tekrar_kart": b["kalan"], "toplam_kart": b["toplam"], "hata_turleri": turler,
            "en_cok_hata_konu": max(konular, key=konular.get) if konular else "", "son_simulasyon": sim[-1] if sim else None}


# ================================================================ 3) SINAV SİMÜLASYONU
def deneme_genel(x: dict) -> dict:
    """Eski paket biçimini (bolum1_dy … bolum5_bonus) genel şemaya çevirir (static/app.js denemeGenel ile aynı)."""
    if isinstance(x.get("bolumler"), list):
        return x
    b, m = [], x.get("bolum3_metin") or {}
    if x.get("bolum1_dy"):
        b.append({"baslik": "Doğru / Yanlış", "tur": "dy", "sorular": [
            {"soru": q.get("ifade"), "cevap": q.get("cevap"), "aciklama": q.get("aciklama"), "kaynak": q.get("kaynak")} for q in x["bolum1_dy"]]})
    if x.get("bolum2_coktan"):
        b.append({"baslik": "Çoktan seçmeli", "tur": "coktan", "sorular": x["bolum2_coktan"]})
    if m.get("metin") or m.get("sorular"):
        b.append({"baslik": "Metin soruları", "tur": "metin", "metin": m.get("metin"),
                  "sorular": [{**q, "kaynak": q.get("kaynak") or m.get("kaynak")} for q in m.get("sorular") or []]})
    if x.get("bolum4_klasik"):
        b.append({"baslik": "Klasik", "tur": "klasik", "sorular": x["bolum4_klasik"]})
    if x.get("bolum5_bonus"):
        b.append({"baslik": "Bonus", "tur": "bonus", "sorular": [{"soru": q.get("soru"), "ornek_cevap": q.get("cozum")} for q in x["bolum5_bonus"]]})
    return {"baslik": x.get("baslik"), "aciklama": x.get("aciklama", ""), "bolumler": b}


def _dy(c: Any) -> str:
    s = str(c or "").strip().upper()[:1]
    return {"T": "D", "F": "Y"}.get(s, s)


def _sik(c: Any) -> str:
    return str(c or "").strip().lstrip("(")[:1].upper()


def _konu_bul(q: dict, bolum: dict, ders_adi: str) -> str:
    if q.get("konu"):
        return str(q["konu"])[:80]
    kay = str(q.get("kaynak") or bolum.get("kaynak") or "")
    kay = re.sub(r"\s*,?\s*(s|sf|sayfa)\.?\s*\d.*$", "", kay, flags=re.I).strip()
    return kay[:80] or bolum.get("baslik") or ders_adi


def deneme_sorulari(x: dict, ders_adi: str = "") -> list[dict]:
    """Bir denemeyi düz soru listesine çevirir: {tur: dy|coktan|acik, soru, siklar, dogru, cevap_metni, aciklama, konu, kaynak, metin}."""
    g = deneme_genel(x)
    out = []
    for b in g.get("bolumler", []):
        tur = b.get("tur") or ""
        for q in b.get("sorular", []):
            soru = str(q.get("soru") or "").strip()
            if not soru:
                continue
            base = {"soru": soru, "bolum": b.get("baslik", ""), "konu": _konu_bul(q, b, ders_adi), "kaynak": str(q.get("kaynak") or b.get("kaynak") or ""),
                    "aciklama": str(q.get("aciklama") or ""), "metin": b.get("metin") if tur == "metin" else "", "siklar": []}
            if tur == "dy":
                out.append({**base, "tur": "dy", "dogru": _dy(q.get("cevap")), "cevap_metni": f"{_dy(q.get('cevap'))} — {base['aciklama']}".strip(" —")})
            elif tur == "coktan" and q.get("siklar"):
                siklar = [re.sub(r"^\(?[A-Ea-e][).]\s*", "", str(s)) for s in q["siklar"]]
                out.append({**base, "tur": "coktan", "siklar": siklar, "dogru": _sik(q.get("cevap")),
                            "cevap_metni": f"{_sik(q.get('cevap'))}) " + (siklar["ABCDE".find(_sik(q.get('cevap')))] if "ABCDE".find(_sik(q.get('cevap'))) in range(len(siklar)) else "")})
            else:
                ornek = q.get("ornek_cevap") or q.get("cevap") or q.get("cozum") or ""
                out.append({**base, "tur": "acik", "dogru": "", "cevap_metni": str(ornek) + (f"\nPuanlama: {q['puanlama']}" if q.get("puanlama") else "")})
    return out


def banka_sorulari(course: dict, n: int) -> list[dict]:
    """Bankadan doğrudan n soru (calisma.quiz_sorulari 20 ile sınırlı olduğu için burada kendimiz örnekleriz)."""
    uygun = [r for r in calisma.banka() if calisma._uygun(r, course, False)]
    random.shuffle(uygun)
    out = []
    for r in uygun[: max(1, min(int(n), 100))]:
        k = r.get("kaynak") or {}
        konu = k.get("baslik", "") or "Soru bankası"
        kaynak = f"{k.get('baslik', '')} s.{k['sayfa']}" if k.get("sayfa") else ""
        siklar = list(r.get("siklar") or []) if r.get("tur") == "coktan" else []
        if siklar and r.get("cevap") in siklar:
            random.shuffle(siklar)
            i = siklar.index(r["cevap"])
            out.append({"tur": "coktan", "soru": r["soru"], "siklar": siklar, "dogru": "ABCDE"[i], "cevap_metni": f"{'ABCDE'[i]}) {r['cevap']}",
                        "konu": konu, "kaynak": kaynak, "aciklama": "", "metin": "", "bolum": "Soru bankası"})
        else:
            out.append({"tur": "acik", "soru": r["soru"], "siklar": [], "dogru": "", "cevap_metni": r.get("cevap", ""), "konu": konu,
                        "kaynak": kaynak, "aciklama": "", "metin": "", "bolum": "Soru bankası"})
    return out


@router.get("/simulasyon/kaynaklar")
async def sim_kaynaklar(course_id: str):
    c = _ders(course_id)
    if not c:
        raise HTTPException(404, "Ders bulunamadı")
    den = []
    for i, x in enumerate(c.get("denemeler") or []):
        qs = deneme_sorulari(x, c.get("name", ""))
        if qs:
            den.append({"index": i, "baslik": x.get("baslik") or f"Deneme {i + 1}", "soru_sayisi": len(qs)})
    banka = len([r for r in calisma.banka() if calisma._uygun(r, c, False)])
    return {"denemeler": den, "banka_soru": banka}


@router.get("/simulasyon/sorular")
async def sim_sorular(course_id: str, kaynak: str = "deneme", index: int = 0, n: int = 20):
    c = _ders(course_id)
    if not c:
        raise HTTPException(404, "Ders bulunamadı")
    if kaynak == "banka":
        qs = banka_sorulari(c, n)
        baslik = "Soru bankasından sınav"
    else:
        den = c.get("denemeler") or []
        if not (0 <= index < len(den)):
            raise HTTPException(404, "Deneme yok")
        qs = deneme_sorulari(den[index], c.get("name", ""))
        baslik = den[index].get("baslik") or f"Deneme {index + 1}"
    if not qs:
        raise HTTPException(404, "Bu kaynakta soru yok")
    return {"baslik": baslik, "sorular": qs}


class SimCevap(BaseModel):
    soru: str
    tur: Literal["dy", "coktan", "acik"] = "acik"
    ogrenci: str = ""
    dogru: str = ""
    cevap_metni: str = ""
    konu: str = ""
    kaynak: str = ""
    puan: float | None = Field(None, description="açık uçlularda 0-1 (öğrencinin/hocanın verdiği puan)")
    agirlik: float = 1.0


class SimGirdi(BaseModel):
    course_id: str = ""
    cevaplar: list[SimCevap]
    sure_sn: int = 0
    baslik: str = ""


def sim_puanla(cevaplar: list[SimCevap]) -> dict:
    """Saf puanlama: toplam (100 üzerinden), doğru/yanlış/boş, konu bazında kayıp puan."""
    toplam_agirlik = sum(max(0.0, c.agirlik) for c in cevaplar) or 1.0
    konular: dict[str, dict] = {}
    dogru = yanlis = bos = 0
    kazanc = 0.0
    sonuclar = []
    for c in cevaplar:
        w = max(0.0, c.agirlik)
        ogr = c.ogrenci.strip()
        if c.tur == "dy":
            s = None if not ogr else (1.0 if _dy(ogr) == _dy(c.dogru) else 0.0)
        elif c.tur == "coktan":
            s = None if not ogr else (1.0 if _sik(ogr) == _sik(c.dogru) else 0.0)
        else:
            s = None if (not ogr and c.puan is None) else max(0.0, min(1.0, c.puan if c.puan is not None else 0.0))
        if s is None:
            bos += 1
            puan = 0.0
        else:
            puan = s
            if puan >= 0.5:
                dogru += 1
            else:
                yanlis += 1
        kazanc += puan * w
        k = konular.setdefault(c.konu or "Genel", {"konu": c.konu or "Genel", "soru": 0, "dogru": 0, "kayip": 0.0})
        k["soru"] += 1
        k["dogru"] += 1 if puan >= 0.5 else 0
        k["kayip"] += (1 - puan) * w * 100 / toplam_agirlik
        sonuclar.append({"puan": puan, "bos": s is None})
    kon = sorted(({**k, "kayip": round(k["kayip"], 1)} for k in konular.values()), key=lambda k: -k["kayip"])
    return {"puan": round(100 * kazanc / toplam_agirlik, 1), "dogru": dogru, "yanlis": yanlis, "bos": bos, "soru_sayisi": len(cevaplar),
            "konular": kon, "sonuclar": sonuclar}


@router.post("/simulasyon/puanla")
async def sim_puanla_ep(g: SimGirdi, bg: BackgroundTasks):
    if not g.cevaplar:
        raise HTTPException(400, "Cevap yok")
    s = sim_puanla(g.cevaplar)
    eklenen = 0
    for c, r in zip(g.cevaplar, s["sonuclar"]):
        if r["puan"] < 0.5:
            h, _ = hata_ekle(HataGirdi(course_id=g.course_id, soru=c.soru, dogru_cevap=c.cevap_metni, ogrenci_cevabi=c.ogrenci or "(boş)",
                                       konu=c.konu, kaynak=c.kaynak or "Sınav simülasyonu"))
            eklenen += 1
            if not h.get("tur"):
                bg.add_task(hata_analiz_et, h["id"])
        if not r["bos"] and c.konu:  # zayıf konu hafızasına da işle
            store.record_topic(g.course_id or None, c.konu, r["puan"] >= 0.5)
    s["hata_eklendi"] = eklenen
    with _kilit:
        sim = _oku("simulasyon.json", [])
        sim.append({"tarih": _bugun().isoformat(), "course_id": g.course_id, "puan": s["puan"], "baslik": g.baslik, "sure_sn": g.sure_sn})
        _yaz("simulasyon.json", sim[-200:])
    return s


# ================================================================ 4) HESAP ÇALIŞMA ALANI
@router.get("/hesap/araclar")
async def hesap_araclar():
    out = []
    for a in hesap.ARACLAR.values():
        out.append({"ad": a.ad, "aciklama": a.aciklama, "sema": a.sema.model_json_schema(), "ornek": calis_dosya.ORNEKLER.get(a.ad),
                    "excel": a.ad in calis_dosya.EXCEL_OZEL, "python": a.ad in calis_dosya.PY_OZEL})
    return {"araclar": out}


class HesapIstek(BaseModel):
    arac: str
    girdi: dict | str = Field(default_factory=dict)


HESAP_SURE_SN = 30


def _coz(g: HesapIstek) -> hesap.Sonuc:
    try:
        return hesap.calistir(g.arac, g.girdi)
    except hesap.HesapHatasi as e:
        raise HTTPException(400, str(e))


async def _coz_async(g: HesapIstek) -> hesap.Sonuc:
    """CPU ağır çözücüyü olay döngüsünü tıkamadan iş parçacığında, süre sınırıyla çalıştırır."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_coz, g), HESAP_SURE_SN)
    except asyncio.TimeoutError:
        raise HTTPException(504, f"Hesap {HESAP_SURE_SN} saniyede bitmedi; girdiyi küçültüp tekrar dene.")


@router.post("/hesap")
async def hesap_coz(g: HesapIstek):
    s = await _coz_async(g)
    return {**s.model_dump(), "metin": hesap.sonuc_metni(s)}


_MIME = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "py": "text/x-python; charset=utf-8"}


def _dosya_uret(bicim: str, g: HesapIstek) -> bytes:
    s = _coz(g)
    try:
        girdi = g.girdi if isinstance(g.girdi, dict) else json.loads(g.girdi)
    except json.JSONDecodeError:
        raise HTTPException(400, "girdi geçerli JSON değil")
    return calis_dosya.excel_uret(g.arac, girdi, s) if bicim == "xlsx" else calis_dosya.python_uret(g.arac, girdi, s).encode("utf-8")


async def _dosya_yanit(bicim: str, g: HesapIstek) -> Response:
    if bicim not in _MIME:
        raise HTTPException(404, "Biçim: xlsx ya da py")
    try:
        veri = await asyncio.wait_for(asyncio.to_thread(_dosya_uret, bicim, g), HESAP_SURE_SN)
    except asyncio.TimeoutError:
        raise HTTPException(504, f"Hesap {HESAP_SURE_SN} saniyede bitmedi; girdiyi küçültüp tekrar dene.")
    return Response(veri, media_type=_MIME[bicim], headers={"Content-Disposition": f'attachment; filename="{g.arac}.{bicim}"'})


@router.post("/indir/{bicim}")
async def indir_post(bicim: str, g: HesapIstek):
    return await _dosya_yanit(bicim, g)


@router.get("/indir/{bicim}")
async def indir_get(bicim: str, arac: str, girdi: str = "{}"):
    try:
        gj = json.loads(girdi)
    except json.JSONDecodeError:
        raise HTTPException(400, "girdi geçerli JSON değil")
    return await _dosya_yanit(bicim, HesapIstek(arac=arac, girdi=gj))


# ================================================================ 5) DERS SONRASI ÖZET KARTI
class OzetKarti(BaseModel):
    baslik: str = Field(description="Dersin konusu, kısa başlık")
    anahtar_kavramlar: list[str] = Field(description="3-6 anahtar kavram")
    formuller: list[str] = Field(default_factory=list, description="Önemli formüller, LaTeX, dolar işaretsiz")
    ozet_maddeleri: list[str] = Field(description="4-6 kısa özet maddesi")
    kontrol_sorusu: str = Field(description="Öğrenme kontrolü için tek soru")
    cevap: str = Field(description="Kontrol sorusunun kısa cevabı")


class OzetIstek(BaseModel):
    session_id: str


def _oturum_ozeti(s: dict) -> dict:
    basliklar, yazilar, matlar, soylenen = [], [], [], []
    for t in s.get("timeline", []):
        if t.get("type") != "step":
            continue
        if t.get("say"):
            soylenen.append(str(t["say"]))
        for op in t.get("board") or []:
            o = op.get("op")
            if o == "title" and op.get("text"):
                basliklar.append(str(op["text"]))
            elif o == "write" and op.get("text"):
                yazilar.append(str(op["text"]))
            elif o == "math" and op.get("tex"):
                matlar.append(str(op["tex"]))
    return {"basliklar": basliklar, "yazilar": yazilar, "matlar": matlar, "soylenen": soylenen}


def _tekil(liste: list[str], n: int) -> list[str]:
    out, g = [], set()
    for x in liste:
        k = x.strip().lower()
        if k and k not in g:
            g.add(k)
            out.append(x.strip())
    return out[:n]


def kural_ozet(s: dict, o: dict | None = None) -> dict:
    """Yapay zeka yokken tahtadaki title/write/math öğelerinden özet."""
    o = o or _oturum_ozeti(s)
    baslik = (o["basliklar"][0] if o["basliklar"] else "") or s.get("title") or "Ders özeti"
    kav = _tekil(o["basliklar"][1:] or o["basliklar"], 6)
    formul = _tekil(o["matlar"] + [m for y in o["yazilar"] for m in re.findall(r"\$([^$]{3,80})\$", y) if "=" in m], 6)
    madde = _tekil([re.sub(r"\s+", " ", y.replace("$", "")).strip() for y in o["yazilar"]] or [x for x in o["soylenen"]], 6)
    madde = [m[:220] for m in madde]
    soru = f"“{baslik}” konusunu kendi cümlelerinle özetle." if not formul else f"“{baslik}” konusunda gördüğün formülü yaz ve ne işe yaradığını açıkla."
    cevap = madde[0] if madde else ""
    return {"baslik": baslik, "anahtar_kavramlar": kav, "formuller": formul, "ozet_maddeleri": madde, "kontrol_sorusu": soru, "cevap": cevap}


_OZET_ONBELLEK: dict[tuple[str, int], dict] = {}
_OZET_KILITLERI: dict[str, asyncio.Lock] = {}
OZET_SIRA_SN = 12


@router.post("/ozet-karti")
async def ozet_karti(g: OzetIstek):
    # aynı oturum için istekler sırayla çalışır; ikincisi ilkinin önbelleğe yazdığı sonucu alır
    kilit = _OZET_KILITLERI.setdefault(g.session_id, asyncio.Lock())
    async with kilit:
        return await _ozet_karti(g)


async def _ozet_karti(g: OzetIstek):
    try:
        s = store.load_session(g.session_id)
    except ValueError:
        s = None
    if not s:
        raise HTTPException(404, "Oturum bulunamadı")
    anahtar = (g.session_id, len(s.get("timeline", [])))
    if anahtar in _OZET_ONBELLEK:
        return _OZET_ONBELLEK[anahtar]
    o = _oturum_ozeti(s)
    if not (o["basliklar"] or o["yazilar"] or o["matlar"] or o["soylenen"]):
        raise HTTPException(400, "Bu oturumda henüz anlatım yok")
    kart, kaynak = None, "kural"
    if llm.ai_hazir():
        metin = ("Aşağıda bir ders anlatımının tahta ve konuşma özeti var. Bundan öğrencinin sınav öncesi tek bakışta tekrar edeceği "
                 "TEK SAYFALIK özet kartı çıkar. Yalnızca anlatılanlara dayan.\n\nTahta başlıkları: " + "; ".join(o["basliklar"][:15]) +
                 "\nTahtadaki yazılar: " + " | ".join(o["yazilar"][:25]) + "\nFormüller: " + " ; ".join(o["matlar"][:15]) +
                 "\nHocanın anlattıkları: " + " ".join(o["soylenen"])[:3500])
        try:
            try:
                await asyncio.wait_for(llm.arka_plan_sirasi(), OZET_SIRA_SN)
            except asyncio.TimeoutError:
                raise RuntimeError("yapay zeka sırası dolu (zaman aşımı)")
            k = await llm._parse(OzetKarti, metin[:7000], "Sen öğrencinin ders notlarını toparlayan titiz bir asistansın. Türkçe yaz.", max_tokens=1500)
            kart, kaynak = k.model_dump(), "yapay_zeka"
        except Exception as e:
            log.info("özet kartı yapay zekayla üretilemedi, kural tabanlı: %s", e)
    if kart is None:
        kart = kural_ozet(s, o)
    sonuc = {**kart, "kaynak": kaynak, "course_id": s.get("course_id") or "", "session_id": g.session_id}
    for k in [k for k in _OZET_ONBELLEK if k[0] == g.session_id]:
        del _OZET_ONBELLEK[k]
    _OZET_ONBELLEK[anahtar] = sonuc
    if len(_OZET_ONBELLEK) > 50:
        _OZET_ONBELLEK.pop(next(iter(_OZET_ONBELLEK)))
    return sonuc
