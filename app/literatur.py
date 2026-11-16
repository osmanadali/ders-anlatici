"""Literatür taraması: hoca, derslerin konularıyla ilgili yeni makaleleri kendiliğinden bulup kütüphaneye ekler.

Kaynaklar: Crossref (birincil, anahtarsız), arXiv (yardımcı, anahtarsız), OpenAlex (isteğe bağlı; kota dolarsa atlanır).
Kibar kullanım: genel User-Agent (kişisel bilgi/e-posta YOK), seri istek (Crossref >=1,1 sn, arXiv >=3 sn arayla),
429/503'te beklenir, çok büyük bekleme isteyen kaynak o tur bırakılır. İnternet yoksa sessizce {"hatalar": [...]} döner.
Kütüphaneye yalnızca kutuphane.ekle_makale / var_mi_doi ile yazılır. Kitaplar bilgisayardan çıkmaz; yalnızca arama
sorguları (ders adı/konu başlıkları) internete gider.
Durum DATA_DIR/literatur.json'da tutulur (atomik yazılır).
"""
from __future__ import annotations

import asyncio
import html
import importlib
import io
import json
import logging
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import shutil
import httpx

from . import config, notes

log = logging.getLogger("ders.literatur")

UA = "DersAnlatici/1.0 (educational app)"
HAFTA = 7 * 24 * 3600
KONTROL_ARALIGI = 3600  # zamanlayıcı saatte bir bakar
ILK_BEKLEME = 120  # uygulama açıldıktan sonra ilk bakışa kadar (sn)
TUR_DERS_SAYISI = 15  # bir turda taranan en fazla ders
DERS_BASINA_YENI = 8
YIL_PENCERESI = 5  # ilk taramada geriye bakılan yıl
CROSSREF_ARALIK = 1.1
ARXIV_ARALIK = 3.0
OPENALEX_ARALIK = 1.0
BEKLEME_UST = 60  # Retry-After bundan büyükse o kaynak bırakılır
PDF_LIMIT = 15 * 1024 * 1024
PDF_SAYFA = 80
PDF_TUR_LIMIT = 15  # bir turda indirilen en fazla PDF
TARANAN_ONEKLER = {"ENM", "IE", "ISG", "TOS"}  # dil/genel dersler (HAZ, ENG, TÜR, MATH...) taranmaz
ARXIV_KATEGORILER = ("stat.AP", "math.OC", "cs.LG", "eess.SY", "econ.GN")
GURULTU = ("MIDTERM", "FINAL", "EXAM", "REVIEW", "LESSON", "HOLIDAY", "QUIZ", "VİZE", "ARA SINAV")

_transport: httpx.AsyncBaseTransport | None = None  # testlerde MockTransport verilir
_calisiyor = False
_gorev: asyncio.Task | None = None
_son_istek: dict[str, float] = {}


class _KaynakBirak(Exception):
    """Kaynak bu tur kullanılamıyor (kota, bağlantı yok, uzun bekleme)."""


# ---------------------------------------------------------------- yardımcılar
def _simdi() -> float:
    return time.time()


def _durum_dosyasi():
    return config.DATA_DIR / "literatur.json"


def _durum_oku() -> dict:
    try:
        return json.loads(_durum_dosyasi().read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _durum_yaz(d: dict) -> None:
    f = _durum_dosyasi()
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, f)  # atomik


def _kutuphane():
    """Çekirdek modül geç içe aktarılır (paralel geliştirmede ve testlerde sahtelenebilsin)."""
    return importlib.import_module("app.kutuphane")


async def _sira() -> None:
    """Öğrenci hocayla konuşuyorsa arka plan işi bekler."""
    try:
        from . import llm
        await llm.arka_plan_sirasi()
    except ImportError:
        pass


async def _uyu(sn: float) -> None:
    await asyncio.sleep(sn)


def temizle_ozet(s: str | None) -> str:
    """Crossref JATS / HTML etiketlerini ve baştaki 'Abstract' başlığını temizler."""
    if not s:
        return ""
    s = re.sub(r"<jats:title>.*?</jats:title>", lambda m: " " + re.sub(r"<[^>]+>", "", m.group(0)) + ": ", s,
               flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(abstract|summary|özet)\s*[:.\-]?\s+", "", s, flags=re.I)
    return re.sub(r"\s+([:;,.])", r"\1", s).strip()


def doi_duzelt(doi: str | None) -> str:
    d = (doi or "").strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    return d.strip()


def _baslik_anahtar(b: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (b or "").lower()).strip()


def _yil(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- ders ve sorgu seçimi
def _ders_kodu(c: dict) -> str:
    return ((c.get("profile") or {}).get("kod") or "").strip()


def taranacak_mi(c: dict) -> bool:
    p = c.get("profile") or {}
    kod = _ders_kodu(c)
    if not kod or not (p.get("ad_en") or "").strip():
        return False
    return kod.split()[0].upper() in TARANAN_ONEKLER


def _konu_temizle(t: str) -> str:
    t = re.split(r"[:;,]| - |\.\s", t.strip(), maxsplit=1)[0]
    return re.sub(r"\s+", " ", t).strip(" .-()")


def sorgular(profil: dict) -> list[str]:
    """Ders başına 2-4 sorgu: ders adı + en bilgi verici 1-2 haftalık konu (İngilizce)."""
    ad = re.sub(r"\s+", " ", (profil.get("ad_en") or "")).strip().lower()
    if not ad:
        return []
    out = [ad]
    adaylar = []
    for t in profil.get("haftalik_konular_en") or []:
        if any(g in str(t).upper() for g in GURULTU):
            continue
        k = _konu_temizle(str(t))
        if len(k) < 12 or len(k) > 80 or len(k.split()) < 2 or k.lower() == ad:
            continue
        adaylar.append(k.lower())
    if adaylar:
        # konular arasından eşit aralıklı en fazla 2 tane
        adim = max(1, len(adaylar) // 2)
        for k in adaylar[::adim][:2]:
            out.append(k if "engineering" in k else f"{k} engineering")
    gorulen, son = set(), []
    for q in out:
        n = _baslik_anahtar(q)
        if n not in gorulen:
            gorulen.add(n)
            son.append(q)
    return son[:4]


# ---------------------------------------------------------------- HTTP
async def _get(client: httpx.AsyncClient, url: str, kaynak: str, aralik: float, **kw) -> httpx.Response:
    """Kibar GET: aralık bekler, 429/5xx'te yeniden dener, çok uzun bekleme isteyen kaynağı bırakır."""
    bekle_5xx = [5, 15]
    deneme = 0
    while True:
        gecen = _simdi() - _son_istek.get(kaynak, 0)
        if gecen < aralik:
            await _uyu(aralik - gecen)
        await _sira()
        _son_istek[kaynak] = _simdi()
        try:
            r = await client.get(url, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout,
                httpx.NetworkError, httpx.TimeoutException) as e:
            raise _KaynakBirak(f"{kaynak}: bağlantı kurulamadı ({type(e).__name__})") from e
        if r.status_code == 429:
            try:
                ra = float(r.headers.get("retry-after", ""))
            except ValueError:
                ra = [5, 15, 45][min(deneme, 2)]
            if ra > BEKLEME_UST or deneme >= 2:
                raise _KaynakBirak("OpenAlex kotası doldu" if kaynak == "openalex" else f"{kaynak}: kota/hız sınırı doldu (429)")
            await _uyu(ra)
            deneme += 1
            continue
        if r.status_code >= 500:
            if deneme >= len(bekle_5xx):
                raise _KaynakBirak(f"{kaynak}: sunucu hatası ({r.status_code})")
            await _uyu(bekle_5xx[deneme])
            deneme += 1
            continue
        return r


# ---------------------------------------------------------------- kaynaklar
def _crossref_ayristir(veri: dict, bugun_yil: int) -> list[dict]:
    out = []
    for it in (veri.get("message") or {}).get("items") or []:
        doi = doi_duzelt(it.get("DOI"))
        baslik = html.unescape(((it.get("title") or [""])[0] or "")).strip()
        baslik = re.sub(r"<[^>]+>", "", baslik)
        ozet = temizle_ozet(it.get("abstract"))
        if not doi or not baslik or not ozet:
            continue
        dp = ((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None]
        yil = _yil(dp[0])
        if yil is not None and yil > bugun_yil:
            continue  # Crossref'in bozuk "gelecek" tarihli kayıtları
        yazarlar = []
        for a in it.get("author") or []:
            ad = f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name") or ""
            if ad:
                yazarlar.append(ad)
        pdf = None
        acik = any("creativecommons.org" in (l.get("URL") or "").lower() for l in it.get("license") or [])
        if acik:
            for l in it.get("link") or []:
                if l.get("content-type") == "application/pdf" and l.get("URL"):
                    pdf = l["URL"]
                    break
        out.append({"baslik": baslik, "yazarlar": yazarlar, "yil": yil,
                    "dergi": html.unescape(((it.get("container-title") or [""])[0] or "")).strip(),
                    "doi": doi, "url": it.get("URL") or f"https://doi.org/{doi}", "ozet": ozet,
                    "atif": int(it.get("is-referenced-by-count") or 0), "pdf": pdf, "kaynak": "crossref"})
    return out


async def _crossref(client, sorgu: str, baslangic: date, bugun: date) -> list[dict]:
    params = {"query.bibliographic": sorgu,
              "filter": f"type:journal-article,from-pub-date:{baslangic.isoformat()},"
                        f"until-pub-date:{bugun.isoformat()},has-abstract:true",
              "rows": "20",
              "select": "DOI,title,author,issued,container-title,abstract,link,license,URL,is-referenced-by-count"}
    r = await _get(client, "https://api.crossref.org/works", "crossref", CROSSREF_ARALIK, params=params)
    if r.status_code != 200:
        raise _KaynakBirak(f"Crossref: beklenmeyen cevap ({r.status_code})")
    return _crossref_ayristir(r.json(), bugun.year)


_NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}


def _arxiv_ayristir(metin: str, bugun_yil: int) -> list[dict]:
    out = []
    root = ET.fromstring(metin)
    for e in root.findall("a:entry", _NS):
        def t(yol):
            n = e.find(yol, _NS)
            return re.sub(r"\s+", " ", n.text).strip() if n is not None and n.text else ""
        kimlik = re.sub(r"v\d+$", "", t("a:id").rsplit("/", 1)[-1])
        baslik, ozet = t("a:title"), t("a:summary")
        if not kimlik or not baslik or not ozet:
            continue
        yil = _yil(t("a:published")[:4])
        if yil is not None and yil > bugun_yil:
            continue
        doi = doi_duzelt(t("x:doi")) or f"10.48550/arxiv.{kimlik.lower()}"
        pdf, url = None, f"https://arxiv.org/abs/{kimlik}"
        for l in e.findall("a:link", _NS):
            if l.get("title") == "pdf" and l.get("href"):
                pdf = l.get("href")
            elif l.get("rel") == "alternate" and l.get("href"):
                url = l.get("href")
        out.append({"baslik": baslik, "yazarlar": [n.text.strip() for n in e.findall("a:author/a:name", _NS) if n.text],
                    "yil": yil, "dergi": t("x:journal_ref") or "arXiv", "doi": doi, "url": url, "ozet": ozet,
                    "atif": 0, "pdf": pdf, "kaynak": "arxiv"})
    return out


async def _arxiv(client, sorgu: str, baslangic: date, bugun: date) -> list[dict]:
    kat = " OR ".join(f"cat:{k}" for k in ARXIV_KATEGORILER)
    q = (f'abs:"{sorgu}" AND ({kat}) AND submittedDate:[{baslangic:%Y%m%d}0000 TO {bugun:%Y%m%d}2359]')
    params = {"search_query": q, "start": "0", "max_results": "10", "sortBy": "submittedDate",
              "sortOrder": "descending"}
    r = await _get(client, "https://export.arxiv.org/api/query", "arxiv", ARXIV_ARALIK, params=params)
    if r.status_code != 200:
        raise _KaynakBirak(f"arXiv: beklenmeyen cevap ({r.status_code})")
    return _arxiv_ayristir(r.text, bugun.year)


def _openalex_ozet(ters: dict | None) -> str:
    if not ters:
        return ""
    konum = [(p, w) for w, ps in ters.items() for p in ps]
    return " ".join(w for _, w in sorted(konum))


def _openalex_ayristir(veri: dict, bugun_yil: int) -> list[dict]:
    out = []
    for it in veri.get("results") or []:
        doi = doi_duzelt(it.get("doi"))
        baslik = (it.get("title") or "").strip()
        ozet = temizle_ozet(_openalex_ozet(it.get("abstract_inverted_index")))
        yil = _yil(it.get("publication_year"))
        if not doi or not baslik or not ozet or (yil is not None and yil > bugun_yil):
            continue
        kaynak = ((it.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        pdf = (it.get("best_oa_location") or {}).get("pdf_url") or None
        out.append({"baslik": baslik, "yil": yil, "dergi": kaynak, "doi": doi, "url": f"https://doi.org/{doi}",
                    "yazarlar": [((a.get("author") or {}).get("display_name") or "") for a in it.get("authorships") or []
                                 if (a.get("author") or {}).get("display_name")],
                    "ozet": ozet, "atif": int(it.get("cited_by_count") or 0), "pdf": pdf, "kaynak": "openalex"})
    return out


async def _openalex(client, sorgu: str, baslangic: date, bugun: date, anahtar: str) -> list[dict]:
    params = {"search": sorgu,
              "filter": f"from_publication_date:{baslangic.isoformat()},to_publication_date:{bugun.isoformat()},"
                        "type:article,has_abstract:true,open_access.is_oa:true",
              "sort": "publication_date:desc", "per-page": "15",
              "select": "id,doi,title,publication_year,authorships,primary_location,best_oa_location,"
                        "open_access,abstract_inverted_index,cited_by_count"}
    if anahtar:
        params["api_key"] = anahtar
    r = await _get(client, "https://api.openalex.org/works", "openalex", OPENALEX_ARALIK, params=params)
    if r.status_code == 429:
        raise _KaynakBirak("OpenAlex kotası doldu")
    if r.status_code != 200:
        raise _KaynakBirak(f"OpenAlex: beklenmeyen cevap ({r.status_code})")
    return _openalex_ayristir(r.json(), bugun.year)


# ---------------------------------------------------------------- PDF
def _pdf_metni(veri: bytes) -> str | None:
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(veri))
        parcalar = []
        for sayfa in r.pages[:PDF_SAYFA]:
            parcalar.append(sayfa.extract_text() or "")
        m = re.sub(r"[ \t]+", " ", "\n".join(parcalar)).strip()
        return m if len(m) >= 500 else None
    except Exception:  # bozuk/şifreli PDF: özetle yetinilir
        return None


async def _pdf_indir(client, url: str) -> str | None:
    kaynak = "arxiv" if "arxiv.org" in url else "pdf"
    try:
        gecen = _simdi() - _son_istek.get(kaynak, 0)
        aralik = ARXIV_ARALIK if kaynak == "arxiv" else 1.0
        if gecen < aralik:
            await _uyu(aralik - gecen)
        await _sira()
        _son_istek[kaynak] = _simdi()
        veri = bytearray()
        async with client.stream("GET", url, timeout=60) as r:
            if r.status_code != 200:
                return None
            try:
                if int(r.headers.get("content-length", "0")) > PDF_LIMIT:
                    return None
            except ValueError:
                pass
            async for parca in r.aiter_bytes():
                veri += parca
                if len(veri) > PDF_LIMIT:
                    return None
        if not bytes(veri[:5]).startswith(b"%PDF"):
            return None
        return await asyncio.to_thread(_pdf_metni, bytes(veri))
    except (httpx.HTTPError, OSError):
        return None


# ---------------------------------------------------------------- puanlama
def puan(m: dict, bugun_yil: int) -> float:
    s = math.log1p(m.get("atif") or 0)
    yil = m.get("yil")
    if yil is not None:
        s += 3.0 * max(0.0, 1 - (bugun_yil - yil) / (YIL_PENCERESI + 1))
    if len(m.get("ozet") or "") < 200:
        s -= 1.0
    if m.get("kaynak") == "crossref":
        s += 0.3  # yayımlanmış dergi makalesi önprint'ten biraz önde
    return s


# ---------------------------------------------------------------- tarama
def vakti_geldi(simdi: float | None = None) -> bool:
    son = _durum_oku().get("son_tarama")
    return son is None or (simdi or _simdi()) - son >= HAFTA


def durum() -> dict:
    d = _durum_oku()
    otomatik = bool(config.load_settings().get("literatur_otomatik", True))
    son = d.get("son_tarama")
    return {"son_tarama": son, "sonraki": (son + HAFTA) if (son and otomatik) else None,
            "calisiyor": _calisiyor, "son_sonuc": d.get("son_sonuc"), "otomatik": otomatik}


async def _ders_tara(client, c: dict, bugun: date, durum_d: dict, rapor: dict, kapali: set, gorulen: set,
                     pdf_sayac: list, anahtar: str) -> int:
    kut = _kutuphane()
    p = c["profile"]
    kod = _ders_kodu(c)
    ad = p.get("ad") or c.get("name") or kod
    son = (durum_d.get("ders_son") or {}).get(kod)
    try:
        # Crossref kayıtları yayın tarihinden günler sonra indekslenir: 30 gün geriye bak (tekrarı DOI engeller)
        baslangic = date.fromtimestamp(son - 30 * 86400) if son else date(bugun.year - YIL_PENCERESI, bugun.month, 1)
    except (OverflowError, OSError, ValueError):
        baslangic = date(bugun.year - YIL_PENCERESI, 1, 1)
    adaylar: dict[str, dict] = {}
    qs = sorgular(p)
    for i, q in enumerate(qs):
        kaynaklar = [("crossref", lambda q=q: _crossref(client, q, baslangic, bugun))]
        if i == 0:  # arXiv ve OpenAlex yalnızca ders adıyla (yardımcı kaynak, hafif kullanım)
            kaynaklar.append(("arxiv", lambda q=q: _arxiv(client, q, baslangic, bugun)))
            kaynaklar.append(("openalex", lambda q=q: _openalex(client, q, baslangic, bugun, anahtar)))
        for ks, fn in kaynaklar:
            if ks in kapali:
                continue
            try:
                for m in await fn():
                    anahtar_ = m["doi"]
                    if anahtar_ in adaylar or anahtar_ in gorulen:
                        continue
                    adaylar[anahtar_] = m
            except _KaynakBirak as e:
                kapali.add(ks)
                if str(e) not in rapor["hatalar"]:
                    rapor["hatalar"].append(str(e))
            except (httpx.HTTPError, ValueError, ET.ParseError, KeyError) as e:
                if f"{ks}: veri okunamadı" not in rapor["hatalar"]:
                    rapor["hatalar"].append(f"{ks}: veri okunamadı ({type(e).__name__})")
            rapor["istek"] += 1
    # başlık tekrarlarını ayıkla (aynı çalışmanın arXiv + dergi sürümü: dergi sürümü kalır)
    basliklar: dict[str, dict] = {}
    for m in sorted(adaylar.values(), key=lambda m: m["kaynak"] != "crossref"):
        basliklar.setdefault(_baslik_anahtar(m["baslik"]), m)
    sirali = sorted(basliklar.values(), key=lambda m: puan(m, bugun.year), reverse=True)
    eklenen = 0
    acik_pdf = bool(config.load_settings().get("literatur_pdf", True))
    for m in sirali:
        if eklenen >= DERS_BASINA_YENI:
            break
        if len(m["ozet"]) < 100:
            continue
        gorulen.add(m["doi"])
        try:
            if kut.var_mi_doi(m["doi"]):
                continue
            tam = None
            if acik_pdf and m.get("pdf") and pdf_sayac[0] < PDF_TUR_LIMIT:
                pdf_sayac[0] += 1
                tam = await _pdf_indir(client, m["pdf"])
            meta = {k: m[k] for k in ("baslik", "yazarlar", "yil", "dergi", "doi", "url", "ozet")}
            meta["dersler"] = [kod]
            if kut.ekle_makale(meta, tam) is not None:
                eklenen += 1
        except Exception as e:  # kütüphane hatası taramayı bozmasın
            log.warning("makale eklenemedi: %s", e)
            rapor["hatalar"].append(f"Kütüphane: {m['baslik'][:50]} eklenemedi ({e})")
    if eklenen:
        rapor["ders_bazinda"][ad] = rapor["ders_bazinda"].get(ad, 0) + eklenen
    return eklenen


# ---------------------------------------------------------------- açık erişimli ders kitapları (OpenStax, CC lisanslı)
OPENSTAX_API = ("https://openstax.org/apps/cms/api/v2/pages/?type=books.Book"
                "&fields=title,book_state,pdf_url,license_name&limit=200")
# Dersin İngilizce adındaki anahtar kelime → uygun OpenStax kitapları (başlıkları)
KITAP_KURALLARI = [
    (("PROBABILITY", "STATISTIC"), ("Introductory Statistics 2e", "Introductory Business Statistics 2e")),
    (("CALCULUS",), ("Calculus Volume 1", "Calculus Volume 2")),
    (("DIFFERENTIAL EQUATION",), ("Calculus Volume 3",)),
    (("PHYSICS",), ("University Physics Volume 1", "University Physics Volume 2")),
    (("CHEMISTRY",), ("Chemistry 2e",)),
    (("ECONOMICS", "ECONOMY"), ("Principles of Economics 3e",)),
    (("ACCOUNTING", "COST"), ("Principles of Accounting, Volume 2: Managerial Accounting",)),
    (("FINANCE", "FEASIBILITY", "BANKING"), ("Principles of Finance 2e",)),
    (("MANAGEMENT",), ("Principles of Management",)),
    (("ORGANIZATION", "HUMAN RESOURCE", "BEHAVIOR"), ("Organizational Behavior",)),
    (("ENTREPRENEUR",), ("Entrepreneurship",)),
    (("MARKETING",), ("Principles of Marketing",)),
    (("ETHIC",), ("Business Ethics",)),
    (("DATA", "INFORMATION SYSTEM", "BUSINESS INTELLIGENCE"), ("Principles of Data Science", "Foundations of Information Systems")),
    (("PROGRAMMING", "COMPUTER"), ("Introduction to Python Programming",)),
]
KITAP_TUR_LIMIT = 2  # bir taramada indirilen en fazla kitap (büyük dosyalar)


def kitap_onerileri(dersler: list[dict]) -> list[tuple[str, str]]:
    """[(kitap başlığı, ders kodu)]: kullanıcının derslerine uyan kitaplar (sıra: ders sırası)."""
    out, gorulen = [], set()
    for c in dersler:
        ad = ((c.get("profile") or {}).get("ad_en") or "").upper()
        if not ad:
            continue
        for anahtarlar, kitaplar in KITAP_KURALLARI:
            if any(k in ad for k in anahtarlar):
                for b in kitaplar:
                    if b not in gorulen:
                        gorulen.add(b)
                        out.append((b, (c.get("profile") or {}).get("kod") or ""))
    return out


async def _kitaplar(client, d: dict, rapor: dict) -> int:
    """Derslere uyan serbest lisanslı ders kitaplarını indirip kütüphaneye ekler (en fazla KITAP_TUR_LIMIT)."""
    if not config.load_settings().get("kitap_otomatik", True):
        return 0
    oneriler = [(b, k) for b, k in kitap_onerileri(notes.list_courses()) if b not in (d.get("kitaplar") or {})]
    if not oneriler:
        return 0
    try:
        await _sira()
        r = await client.get(OPENSTAX_API)
        r.raise_for_status()
        katalog = {b["title"]: b for b in r.json().get("items", [])
                   if b.get("book_state") == "live" and b.get("pdf_url") and "Creative Commons" in (b.get("license_name") or "")}
    except Exception as e:
        rapor["hatalar"].append(f"OpenStax: {e}")
        return 0
    eklenen = 0
    kutuphane = _kutuphane()
    for baslik, kod in oneriler:
        if eklenen >= KITAP_TUR_LIMIT:
            break
        b = katalog.get(baslik)
        if not b:
            continue
        try:
            await _sira()
            h = await client.head(b["pdf_url"])
            boyut = int(h.headers.get("content-length") or 0)
            bos = shutil.disk_usage(config.DATA_DIR).free
            if not boyut or boyut > kutuphane.MAX_BOYUT or bos < boyut + 3 * 2**30:
                d.setdefault("kitaplar", {})[baslik] = {"atlandi": "boyut/disk", "zaman": _simdi()}
                continue
            r = await client.get(b["pdf_url"], timeout=httpx.Timeout(30, read=300))
            r.raise_for_status()
            k = await asyncio.to_thread(kutuphane.ekle_dosya, re.sub(r"[^\w .,-]+", "", baslik) + ".pdf", r.content, "kitap")
            alanlar = {"baslik": baslik, "yazar": "OpenStax (CC lisanslı)"}
            if kod:
                alanlar["dersler"] = [kod]
            await asyncio.to_thread(kutuphane.guncelle, k["id"], alanlar)
            d.setdefault("kitaplar", {})[baslik] = {"id": k["id"], "zaman": _simdi()}
            eklenen += 1
        except ValueError as e:  # ör. zaten kütüphanede
            d.setdefault("kitaplar", {})[baslik] = {"atlandi": str(e), "zaman": _simdi()}
        except Exception as e:
            rapor["hatalar"].append(f"Kitap indirilemedi ({baslik}): {e}")
    return eklenen


async def guncelle(zorla: bool = False) -> dict:
    """Bir tarama turu. zorla=False iken son taramadan 7 gün geçmediyse hiçbir şey yapmaz."""
    global _calisiyor
    if _calisiyor:
        return {"yeni": 0, "ders_bazinda": {}, "hatalar": ["Tarama zaten çalışıyor"]}
    if not zorla and not vakti_geldi():
        return {"yeni": 0, "ders_bazinda": {}, "hatalar": [], "atlandi": True}
    _calisiyor = True
    rapor = {"yeni": 0, "ders_bazinda": {}, "hatalar": [], "istek": 0}
    try:
        d = _durum_oku()
        bugun = date.fromtimestamp(_simdi())
        dersler = [c for c in notes.list_courses() if taranacak_mi(c)]
        dersler.sort(key=lambda c: (d.get("ders_son") or {}).get(_ders_kodu(c), 0))  # en eski taranan önce
        secilen = dersler[:TUR_DERS_SAYISI]
        anahtar = str(config.load_settings().get("openalex_api_key", "") or "")
        kapali: set[str] = set()
        gorulen: set[str] = set()
        pdf_sayac = [0]
        ders_son = dict(d.get("ders_son") or {})
        async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=35, follow_redirects=True,
                                     transport=_transport) as client:
            for c in secilen:
                if {"crossref", "arxiv"} <= kapali:
                    break  # internet yok/kaynaklar kapalı: boşuna dönme
                try:
                    rapor["yeni"] += await _ders_tara(client, c, bugun, {"ders_son": ders_son}, rapor, kapali,
                                                      gorulen, pdf_sayac, anahtar)
                except Exception as e:
                    log.warning("ders taranamadı %s: %s", _ders_kodu(c), e)
                    rapor["hatalar"].append(f"{_ders_kodu(c)}: {e}")
                    continue
                if "crossref" not in kapali:
                    ders_son[_ders_kodu(c)] = _simdi()
            kitap = await _kitaplar(client, d, rapor)
        basari = not ({"crossref", "arxiv"} <= kapali) and bool(secilen)
        sonuc = {"yeni": rapor["yeni"], "ders_bazinda": rapor["ders_bazinda"], "hatalar": rapor["hatalar"], "kitap": kitap}
        d["ders_son"] = ders_son
        d["son_sonuc"] = dict(sonuc, zaman=_simdi())
        if not secilen:
            d["son_sonuc"]["not"] = "Taranacak ders yok"  # son_tarama ilerlemez: ders eklenince hemen taranır
        elif basari:
            d["son_tarama"] = _simdi()  # tamamen çevrimdışıysa tarih ilerlemez, sonraki saatte tekrar denenir
        _durum_yaz(d)
        if kitap:
            try:
                from . import klasor
                klasor.olay("literatur", f"📘 {kitap} serbest lisanslı ders kitabı kütüphaneye eklendi (OpenStax)")
            except Exception:
                pass
        if sonuc["yeni"]:
            try:
                from . import klasor
                ozet = ", ".join(f"{a}: {n}" for a, n in sorted(sonuc["ders_bazinda"].items(), key=lambda x: -x[1])[:4])
                klasor.olay("literatur", f"🔎 Literatür güncellendi: {sonuc['yeni']} yeni makale ({ozet})")
            except Exception:
                pass
        return sonuc
    except Exception as e:  # hiçbir şey uygulamayı düşürmesin
        log.warning("literatür taraması başarısız: %s", e)
        return {"yeni": 0, "ders_bazinda": {}, "hatalar": [f"Tarama başarısız: {e}"]}
    finally:
        _calisiyor = False


def baslat_arka_planda(zorla: bool = False) -> None:
    """Taramayı arka plan görevi olarak başlatır (zaten çalışıyorsa bir şey yapmaz)."""
    global _gorev
    if _calisiyor or (_gorev is not None and not _gorev.done()):
        return
    _gorev = asyncio.get_running_loop().create_task(guncelle(zorla))


async def zamanlayici() -> None:
    """Uygulama açıkken saatte bir bakar; ayar açıksa ve son taramadan 7 gün geçtiyse tarar."""
    await asyncio.sleep(ILK_BEKLEME)
    while True:
        try:
            if config.load_settings().get("literatur_otomatik", True) and vakti_geldi() and not _calisiyor:
                await guncelle()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("literatür zamanlayıcısı: %s", e)
        await asyncio.sleep(KONTROL_ARALIGI)
