"""Güncel kal: sektör haberleri + trend, haftalık bülten, günün kavramı, Vikipedi'den öğrenme,
bitirme projesi danışmanı, günlük hayattan endüstri mühendisliği.

Veri: DATA_DIR/guncel/{haberler,durum,bulten,bitirme}.json. Haberler ücretsiz RSS/Atom akışlarından gelir;
kütüphaneye tur='haber' olarak (başlık + özet + bağlantı) eklenir. Yapay zeka yoksa her özellik basit bir yedekle çalışır.
Ağ çağrıları `_istemci()` üzerinden yapılır (testlerde sahtelenir); kişisel bilgi hiçbir isteğe girmez.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import html
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import bilgi_haritasi, config, hesap, klasor, kutuphane, literatur, llm, notes

log = logging.getLogger("ders.guncel")
router = APIRouter(prefix="/api/guncel")

UA = "DersAnlatici/1.0 (educational app)"
KOK = config.DATA_DIR / "guncel"
GUN = 86400
HABER_SAKLA_GUN = 730  # haber kaydı bu kadar gün tutulur (trend için)
HABER_OZET_GUN = 90  # bundan eski haberlerin özeti saklanmaz
TREND_EN_AZ_ONCEKI = 50  # 'yükselen' listesi için önceki dönemde en az bu kadar haber
HABER_KUTUPHANE_GUN = 60  # kütüphaneye yalnızca bu kadar yeni haberler eklenir
AKIS_BASINA = 12  # bir turda bir akıştan kütüphaneye eklenen en fazla haber
KONTROL_ARALIGI = 3600
ILK_BEKLEME = 150
VIKI_GUNLUK = 3  # zamanlayıcının günde ekleyeceği en fazla Vikipedi makalesi
VIKI_KULLANICI_GUNLUK = 25

# Erişilebilirliği curl ile doğrulanmış akışlar (404/403 verenler alınmadı: INFORMS, IISE, IndustryWeek, Manufacturing.net)
AKISLAR = [
    ("arXiv Optimizasyon (math.OC)", "https://rss.arxiv.org/rss/math.OC"),
    ("arXiv Genel Ekonomi (econ.GN)", "https://rss.arxiv.org/rss/econ.GN"),
    ("Supply Chain Dive", "https://www.supplychaindive.com/feeds/news/"),
    ("Supply Chain 24/7", "https://www.supplychain247.com/rss"),
    ("MIT News: Tedarik zincirleri", "https://news.mit.edu/rss/topic/supply-chains"),
    ("MIT News: İmalat", "https://news.mit.edu/rss/topic/manufacturing"),
    ("MIT News: Endüstri", "https://news.mit.edu/rss/topic/industry"),
]

# Alan -> iş ilanlarında sık geçen beceriler (kariyer bağlantısı için sabit eşleme)
BECERI = {
    "is_tasarimi": "Excel, zaman etüdü, süreç iyileştirme", "yoneylem": "Python, Gurobi/CPLEX, optimizasyon modelleme",
    "muh_ekonomisi": "Excel, finansal modelleme, maliyet analizi", "tesis": "AutoCAD, tesis yerleşimi, simülasyon",
    "kalite": "Minitab, SPC, ISO 9001, Altı Sigma", "ergonomi": "İSG, ergonomi değerlendirmesi, RULA/REBA",
    "uretim_planlama": "SAP PP, MRP, planlama ve çizelgeleme", "tedarik_zinciri": "SAP MM/SD, talep planlama, lojistik analitiği",
    "muh_yonetimi": "MS Project, proje yönetimi, PMP/Agile", "bilgi_muh": "SQL, veritabanı, Power BI",
    "imalat_tasarim": "CAD/CAM, CNC, imalat süreçleri", "urun_tasarim": "ürün geliştirme, FMEA, DFM",
    "sistem_tasarim": "sistem analizi, sistem dinamiği", "benzetim": "Arena/Simio/AnyLogic, Python simülasyon",
    "istatistik": "Python/R, istatistik, Minitab", "erp": "SAP, Odoo, ERP uyarlama, MES/WMS",
    "yalin": "yalın üretim, VSM, Kanban, 5S, SMED", "alti_sigma": "DMAIC, Minitab, Yeşil/Siyah Kuşak",
    "endustri40": "IoT, dijital ikiz, veri entegrasyonu", "veri_analitigi": "Python, SQL, Power BI/Tableau",
    "proje_isg": "MS Project, İSG uzmanlığı, proje yönetimi",
}
# Konu anahtar sözcüğü -> hesap aracı (bitirme danışmanı için)
ARAC_IPUCU = [
    (("kuyruk", "bekleme", "queue"), "kuyruk"), (("stok", "envanter", "inventory", "eoq"), "eoq"),
    (("çizelge", "cizelge", "scheduling", "makine"), "johnson"), (("proje", "cpm", "pert"), "cpm"),
    (("kalite", "kontrol kart", "spc"), "kontrol_karti"), (("yeterlilik", "cpk"), "yeterlilik"),
    (("simülasyon", "simulasyon", "benzetim", "simulation"), "simulasyon"), (("atama", "assignment"), "atama"),
    (("ulaştırma", "ulastirma", "transportation", "dağıtım", "dagitim"), "ulastirma"),
    (("optimiz", "doğrusal prog", "dogrusal prog", "linear prog", "karışım", "karisim"), "dogrusal_programlama"),
    (("mrp", "malzeme ihtiyaç"), "mrp"), (("yatırım", "yatirim", "nbd", "maliyet-fayda"), "nbd_igo"),
    (("istatistik", "regresyon", "hipotez"), "istatistik"), (("öğrenme eğrisi", "ogrenme egrisi"), "ogrenme_egrisi"),
    (("başabaş", "basabas"), "basabas"),
]


# ---------------------------------------------------------------- yardımcılar
_kilit = threading.RLock()


def _yol(ad: str):
    return KOK / f"{ad}.json"


def _oku(ad: str, varsayilan):
    try:
        return json.loads(_yol(ad).read_text("utf-8"))
    except (OSError, ValueError):
        return varsayilan


def _yaz(ad: str, veri) -> None:
    with _kilit:
        KOK.mkdir(parents=True, exist_ok=True)
        gecici = _yol(ad).with_suffix(".tmp")
        gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), "utf-8")
        gecici.replace(_yol(ad))


def _durum() -> dict:
    d = _oku("durum", {})
    return d if isinstance(d, dict) else {}


def _durum_guncelle(**kw) -> dict:
    with _kilit:
        d = _durum()
        d.update(kw)
        _yaz("durum", d)
        return d


def _simdi() -> float:
    return time.time()


def _bugun() -> date:
    return date.fromtimestamp(_simdi())


def _istemci() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers={"User-Agent": UA}, timeout=httpx.Timeout(20.0), follow_redirects=True)


async def _bekle(sn: float) -> None:
    await asyncio.sleep(sn)


def _duz(s: str | None, en_cok: int = 1500) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:en_cok]


def _kat(s: str) -> str:
    return kutuphane.katla(s or "")


def _tohum(*parcalar) -> int:
    return int(hashlib.sha256("|".join(map(str, parcalar)).encode()).hexdigest()[:12], 16)


async def _yz(model_cls, istem: str, sistem: str, max_tokens: int = 2000, bekle: bool = True):
    """Yapay zekadan yapılandırılmış cevap; yapay zeka yoksa ya da hata verirse None (çağıran yedeğe düşer)."""
    try:
        if not llm.ai_hazir():
            return None
        if bekle:
            await llm.arka_plan_sirasi()
        return await llm._parse(model_cls, istem, sistem, max_tokens=max_tokens)
    except Exception as e:
        log.warning("yapay zeka çağrısı başarısız: %s", e)
        return None


def _konu_listesi() -> list[dict]:
    out = []
    for a in bilgi_haritasi.harita()["alanlar"]:
        for k in a["konular"]:
            out.append({"id": k["id"], "ad": k["ad"], "ad_en": k["ad_en"], "anahtar": k["anahtar"], "alan": a["id"],
                        "alan_ad": a["ad"], "dersler": k.get("dersler") or a["dersler"]})
    return out


@functools.lru_cache(maxsize=512)
def _desen_derle(anahtar: tuple, ad: str, ad_en: str):
    kel = sorted({_kat(x).strip() for x in list(anahtar) + [ad, ad_en] if len(_kat(x).strip()) >= 3}, key=len,
                 reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(x) for x in kel) + ")") if kel else None


def _desen(k: dict):
    return _desen_derle(tuple(k["anahtar"]), k["ad"], k["ad_en"])


def konu_bul(metin: str, en_fazla: int = 1) -> list[dict]:
    """Metne en çok uyan bilgi haritası konuları (anahtar kelime sayımı)."""
    m = _kat(metin)
    puan = []
    for k in _konu_listesi():
        d = _desen(k)
        n = len(d.findall(m)) if d else 0
        if n:
            puan.append((n, k))
    puan.sort(key=lambda x: -x[0])
    return [k for _, k in puan[:en_fazla]]


def _ders_adlari() -> list[str]:
    try:
        return [c["name"] for c in notes.list_courses()][:20]
    except Exception:
        return []


# ---------------------------------------------------------------- 1) RSS / Atom + trend
def _yerel(etiket: str) -> str:
    return etiket.rsplit("}", 1)[-1].lower() if isinstance(etiket, str) else ""


def _tarih(s: str | None) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def akis_ayristir(metin: str | bytes, kaynak: str = "", simdi: float | None = None) -> list[dict]:
    """RSS 2.0 ve Atom akışını [{baslik, ozet, url, tarih, kaynak}] listesine çevirir (bozuk akış -> [])."""
    simdi = simdi or _simdi()
    try:
        kok = ET.fromstring(metin if isinstance(metin, bytes) else metin.encode("utf-8"))
    except ET.ParseError:
        return []
    out = []
    for e in kok.iter():
        if _yerel(e.tag) not in ("item", "entry"):
            continue
        alan: dict[str, str] = {}
        for c in e:
            ad = _yerel(c.tag)
            if ad == "link" and c.get("href"):
                if c.get("rel", "alternate") == "alternate" or "link" not in alan:
                    alan["link"] = c.get("href")
            elif ad in ("title", "link", "description", "summary", "content", "encoded", "pubdate", "published",
                        "updated", "date", "guid") and ad not in alan:
                alan[ad] = (c.text or "").strip()
        baslik = _duz(alan.get("title"), 300)
        ozet = _duz(alan.get("description") or alan.get("summary") or alan.get("encoded") or alan.get("content"))
        ozet = re.sub(r"^arXiv:\S+\s+Announce Type:\s*\w+\s+Abstract:\s*", "", ozet)
        if "Announce Type: replace" in (alan.get("description") or ""):
            continue  # arXiv'in güncelleme duyuruları yeni çalışma değildir
        url = (alan.get("link") or alan.get("guid") or "").strip()
        if not baslik or not url.startswith("http"):
            continue
        t = _tarih(alan.get("pubdate") or alan.get("published") or alan.get("date") or alan.get("updated")) or simdi
        out.append({"baslik": baslik, "ozet": ozet, "url": url, "tarih": min(t, simdi), "kaynak": kaynak})
    return out


def haberler() -> list[dict]:
    d = _oku("haberler", [])
    return d if isinstance(d, list) else []


async def haberleri_cek(akislar=None) -> dict:
    """Akışları çeker, haber kaydını günceller, yeni haberleri kütüphaneye ekler. Çalışmayan akış atlanır."""
    akislar = akislar if akislar is not None else AKISLAR
    simdi = _simdi()
    kayit = {h["url"]: h for h in haberler()}
    rapor = {"yeni": 0, "kutuphaneye": 0, "calisan": [], "hatalar": []}
    async with _istemci() as c:
        for i, (ad, url) in enumerate(akislar):
            if i:
                await _bekle(0.5)
            try:
                r = await c.get(url)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                ogeler = akis_ayristir(r.content, ad, simdi)
            except Exception as e:
                rapor["hatalar"].append(f"{ad}: {type(e).__name__} {e}"[:160])
                continue
            rapor["calisan"].append(ad)
            eklenen = 0
            for o in sorted(ogeler, key=lambda x: -x["tarih"]):
                yeni = o["url"] not in kayit
                if yeni:
                    kayit[o["url"]] = o
                    rapor["yeni"] += 1
                if simdi - o["tarih"] > HABER_KUTUPHANE_GUN * GUN or eklenen >= AKIS_BASINA:
                    continue
                meta = {"baslik": o["baslik"], "ozet": o["ozet"], "url": o["url"], "kimlik": o["url"], "tur": "haber",
                        "yil": datetime.fromtimestamp(o["tarih"], timezone.utc).year, "dergi": ad,
                        "dil": "en"}
                try:
                    if await asyncio.to_thread(kutuphane.ekle_makale, meta):
                        eklenen += 1
                except Exception as e:
                    log.warning("haber kütüphaneye eklenemedi: %s", e)
            rapor["kutuphaneye"] += eklenen
    esik = simdi - HABER_SAKLA_GUN * GUN
    ozet_esik = simdi - HABER_OZET_GUN * GUN
    liste = sorted((h for h in kayit.values() if h["tarih"] >= esik), key=lambda h: -h["tarih"])
    for h in liste:  # boyutu sınırlamak için eski haberlerin özeti atılır (başlık+tarih+url kalır)
        if h["tarih"] < ozet_esik and h.get("ozet"):
            h["ozet"] = ""
    _yaz("haberler", liste)
    _durum_guncelle(haber_zamani=simdi, haber_rapor=rapor)
    if rapor["kutuphaneye"]:
        klasor.olay("bilgi", f"{rapor['kutuphaneye']} yeni sektör haberi kütüphaneye eklendi")
    return rapor


_trend_onbellek: dict = {}


def trend_hesapla(liste: list[dict] | None = None, simdi: float | None = None, ay: int = 6,
                  en_az_onceki: int = TREND_EN_AZ_ONCEKI) -> dict:
    """Haber kaydı verilmediyse (liste=None) sonuç, kaydın sürümüne (uzunluk + son zaman) göre önbelleğe alınır."""
    if liste is not None:
        return _trend_hesapla(liste, simdi, ay, en_az_onceki)
    kayit = haberler()
    anahtar = (len(kayit), max((h.get("tarih", 0) for h in kayit), default=0), ay, en_az_onceki,
               int((simdi or _simdi()) // GUN))
    sonuc = _trend_onbellek.get(anahtar)
    if sonuc is None:
        sonuc = _trend_hesapla(kayit, simdi, ay, en_az_onceki)
        _trend_onbellek.clear()
        _trend_onbellek[anahtar] = sonuc
    return sonuc


def _trend_hesapla(liste: list[dict], simdi: float | None, ay: int, en_az_onceki: int) -> dict:
    """Son `ay` ay ile ondan önceki aynı uzunluktaki dönemde bilgi haritası anahtar kelimelerinin geçiş sayısı.
    Bir haber bir konu için en çok bir kez sayılır. 'yukselenler': artış > 0 ve son dönemde en az 2 haber."""
    simdi = simdi or _simdi()
    s = ay * 30 * GUN
    son = [h for h in liste if simdi - s <= h["tarih"] <= simdi]
    onceki = [h for h in liste if simdi - 2 * s <= h["tarih"] < simdi - s]
    metin = lambda h: _kat(h["baslik"] + " " + h.get("ozet", ""))
    sm, om = [metin(h) for h in son], [metin(h) for h in onceki]
    sonuc = []
    for k in _konu_listesi():
        d = _desen(k)
        if not d:
            continue
        y, e = sum(bool(d.search(t)) for t in sm), sum(bool(d.search(t)) for t in om)
        if y or e:
            sonuc.append({"id": k["id"], "ad": k["ad"], "alan": k["alan_ad"], "yeni": y, "eski": e, "degisim": y - e,
                          "oran": round((y - e) / (e + 2), 2)})
    yuk = sorted((x for x in sonuc if x["degisim"] > 0 and x["yeni"] >= 2), key=lambda x: (-x["oran"], -x["degisim"]))
    dus = sorted((x for x in sonuc if x["degisim"] < 0), key=lambda x: (x["oran"], x["degisim"]))
    neden = ""
    if len(onceki) < en_az_onceki:  # karşılaştırma dönemi boşsa "yükselen" yanıltıcı olur
        yuk, neden = [], f"Karşılaştırma için önceki dönemde en az {en_az_onceki} haber gerekir (şu an {len(onceki)})"
    return {"ay": ay, "son_haber": len(son), "onceki_haber": len(onceki), "yukselenler": yuk[:8], "dusenler": dus[:5],
            "yeterli_veri": not neden, "yukselen_neden": neden}


@router.get("/haberler")
async def haber_listesi(n: int = 30):
    n = max(1, min(n, 100))
    return {"haberler": haberler()[:n], "durum": {k: v for k, v in _durum().items() if k.startswith("haber")},
            "trend": await asyncio.to_thread(trend_hesapla)}


@router.get("/trend")
async def trend():
    return await asyncio.to_thread(trend_hesapla)


@router.post("/haberler/cek")
async def haber_cek_ucu():
    return await haberleri_cek()


# ---------------------------------------------------------------- 2) haftalık bülten
class BultenMadde(BaseModel):
    baslik: str = Field(description="Maddenin kısa başlığı (Türkçe)")
    ozet: str = Field(description="Sade Türkçe, 2-3 cümle: ne oldu, neden önemli")
    ders: str = Field(default="", description="Bağlı olduğu ders ya da konu")
    kariyer: str = Field(default="", description="İş ilanlarında hangi beceriyle ilişkili")
    kaynak_no: int = Field(default=0, description="Kaynak listesindeki numara (yoksa 0)")


class BultenCikti(BaseModel):
    baslik: str = Field(description="Bültenin başlığı")
    maddeler: list[BultenMadde]


def bulten_kaynaklari(gun: int = 7, en_fazla: int = 24) -> list[dict]:
    """Son `gun` günün haber ve makaleleri (haber kaydı + kütüphaneye yeni eklenen makaleler). Az çıkarsa 30 güne uzar."""
    for g in (gun, 30):
        simdi = _simdi()
        ogeler, gorulen = [], set()
        for h in haberler():
            if simdi - h["tarih"] <= g * GUN and h["url"] not in gorulen:
                gorulen.add(h["url"])
                ogeler.append({"baslik": h["baslik"], "ozet": h.get("ozet", ""), "url": h["url"], "tur": "haber",
                               "kaynak": h.get("kaynak", ""), "tarih": h["tarih"]})
        try:
            yeni = kutuphane.son_eklenenler(g, ("makale",), 30)
        except Exception:
            yeni = []
        for m in yeni:
            u = m.get("url") or ""
            if u in gorulen:
                continue
            gorulen.add(u)
            ogeler.append({"baslik": m["baslik"], "ozet": m.get("ozet") or "", "url": u, "tur": "makale",
                           "kaynak": m.get("yazar", "")[:60], "tarih": m.get("eklenme") or simdi})
        if len(ogeler) >= 4 or g == 30:
            ogeler.sort(key=lambda o: -o["tarih"])
            return ogeler[:en_fazla]
    return []


def _yedek_bulten(ogeler: list[dict]) -> dict:
    maddeler = []
    for i, o in enumerate(ogeler[:7], 1):
        konu = (konu_bul(o["baslik"] + " " + o["ozet"]) or [None])[0]
        maddeler.append({"baslik": o["baslik"], "ozet": (o["ozet"][:220] + "…") if len(o["ozet"]) > 220 else o["ozet"],
                         "ders": f"{konu['alan_ad']} / {konu['ad']}" if konu else "",
                         "kariyer": BECERI.get(konu["alan"], "") if konu else "", "kaynak_no": i,
                         "url": o["url"], "kaynak": o["kaynak"]})
    return {"baslik": "Bu hafta endüstri mühendisliğinde", "maddeler": maddeler, "yapay_zeka": False}


def _bulten_istemi(ogeler: list[dict]) -> tuple[str, str]:
    kaynak = "\n".join(f"[{i}] {o['baslik']} — {o['ozet'][:350]}" for i, o in enumerate(ogeler[:14], 1))
    konular = ", ".join(k["ad"] for k in _konu_listesi())
    dersler = ", ".join(_ders_adlari()) or "(ders eklenmemiş)"
    beceriler = "; ".join(f"{k}: {v}" for k, v in list(BECERI.items())[:12])
    istem = (f"Aşağıdaki son haftanın haber ve makalelerinden 5-7 maddelik, sade Türkçe bir bülten hazırla.\n"
             f"Her madde için: kısa başlık, 2-3 cümlelik özet (gerekirse İngilizce kaynağı Türkçeleştir), "
             f"öğrencinin hangi dersine/konusuna bağlandığı, kariyer bağlantısı (iş ilanlarında hangi beceriyle ilişkili) "
             f"ve kaynak_no (köşeli parantezdeki numara).\nÖğrencinin dersleri: {dersler}\nBilgi haritası konuları: {konular}\n"
             f"İlan becerileri örnekleri: {beceriler}\n\nKaynaklar:\n{kaynak}")
    sistem = ("Sen bir endüstri mühendisliği öğrencisine haftalık bülten hazırlayan sade ve doğru bir Türkçe editörsün. "
              "Yalnızca verilen kaynaklardaki bilgiyi kullan, uydurma. Abartma, jargonu açıkla.")
    return istem, sistem


async def bulten_uret(bekle: bool = True) -> dict:
    ogeler = bulten_kaynaklari()
    if not ogeler:
        b = {"baslik": "Bu hafta endüstri mühendisliğinde", "maddeler": [], "yapay_zeka": False, "bos": True}
    else:
        istem, sistem = _bulten_istemi(ogeler)
        cikti = await _yz(BultenCikti, istem, sistem, 2500, bekle)
        if cikti and cikti.maddeler:
            maddeler = []
            for m in cikti.maddeler[:7]:
                o = ogeler[m.kaynak_no - 1] if 1 <= m.kaynak_no <= len(ogeler) else None
                d = m.model_dump()
                d["url"], d["kaynak"] = (o["url"], o["kaynak"]) if o else ("", "")
                maddeler.append(d)
            b = {"baslik": cikti.baslik or "Bu hafta endüstri mühendisliğinde", "maddeler": maddeler, "yapay_zeka": True}
        else:
            b = _yedek_bulten(ogeler)
    b["tarih"] = _bugun().isoformat()
    b["uretildi"] = _simdi()
    _yaz("bulten", b)
    return b


@router.get("/bulten")
async def bulten_getir():
    b = _oku("bulten", None)
    return {"bulten": b if isinstance(b, dict) else None}


@router.post("/bulten/uret")
async def bulten_uret_ucu():
    return {"bulten": await bulten_uret(bekle=False)}


# ---------------------------------------------------------------- 3) günün kavramı
class KavramCikti(BaseModel):
    aciklama: str = Field(description="2-4 cümle sade Türkçe açıklama")
    ornek: str = Field(description="Gerçek hayattan kısa bir örnek")
    soru: str = Field(description="Öğrencinin düşünmesi için tek bir soru")
    cevap: str = Field(description="Sorunun kısa cevabı")


def kavram_havuzu() -> list[dict]:
    """Bilgi haritası konuları + yükselen konular + öğrencinin derslerindeki kavram başlıkları."""
    havuz = [{"id": "k:" + k["id"], "ad": k["ad"], "ad_en": k["ad_en"], "ders": k["alan_ad"], "kaynak": "harita"}
             for k in _konu_listesi()]
    for c in notes.list_courses():
        icerik = (c.get("profile") or {}).get("icerik")
        if isinstance(icerik, str):
            icerik = re.split(r"[,;\n•]+", icerik)
        for t in (icerik or []) if isinstance(icerik, list) else []:
            t = _duz(str(t), 70)
            if 4 <= len(t) <= 60:
                havuz.append({"id": "d:" + _kat(t).replace(" ", "_")[:50], "ad": t, "ad_en": "", "ders": c["name"],
                              "kaynak": "ders"})
    gorulen, out = set(), []
    for h in havuz:
        if h["id"] not in gorulen:
            gorulen.add(h["id"])
            out.append(h)
    return sorted(out, key=lambda h: h["id"])


def gunun_kavrami_sec(bugun: date | None = None) -> dict:
    """Deterministik günlük seçim: aynı gün aynı kavram; havuz bitmeden tekrar yok. Yükselen konulara hafif ağırlık verir."""
    bugun = bugun or _bugun()
    iso = bugun.isoformat()
    d = _durum()
    gecmis = d.get("kavram_gecmis") or []
    for g in gecmis:
        if g["tarih"] == iso:
            return next((h for h in kavram_havuzu() if h["id"] == g["id"]), {"id": g["id"], "ad": g["ad"], "ad_en": "", "ders": g.get("ders", "")})
    havuz = kavram_havuzu()
    kullanilan = {g["id"] for g in gecmis}
    kalan = [h for h in havuz if h["id"] not in kullanilan]
    if not kalan:  # tur bitti: yeni tura başla (yalnızca en son kavramı hariç tut)
        son = gecmis[-1]["id"] if gecmis else ""
        gecmis, kalan = [], [h for h in havuz if h["id"] != son] or havuz
    yuk = {"k:" + x["id"] for x in trend_hesapla()["yukselenler"][:3]}  # çağıran gunun_kavrami to_thread ile çalıştırır
    oncelikli = [h for h in kalan if h["id"] in yuk]
    adaylar = oncelikli if oncelikli and _tohum(iso, "yuk") % 3 == 0 else kalan
    sec = adaylar[_tohum(iso, len(havuz)) % len(adaylar)]
    gecmis.append({"tarih": iso, "id": sec["id"], "ad": sec["ad"], "ders": sec["ders"]})
    _durum_guncelle(kavram_gecmis=gecmis[-400:])
    return sec


async def _yedek_kavram(k: dict) -> dict:
    parca = None
    try:
        sonuc = await asyncio.to_thread(kutuphane.ara, k["ad_en"] or k["ad"], None, 3)
        if sonuc:
            parca = _duz(sonuc[0]["metin"], 380)
    except Exception:
        pass
    return {"aciklama": parca or f"{k['ad']}, {k['ders']} alanının temel kavramlarından biridir. Hocaya sorup ayrıntısını öğrenebilirsin.",
            "ornek": "Bu kavramı çevrendeki bir sistemde (market kasası, yemekhane, kargo dağıtımı) nasıl görebileceğini düşün.",
            "soru": f"{k['ad']} nedir ve hangi problemi çözmeye yarar? Kendi cümlelerinle anlat.",
            "cevap": parca or "Hocaya sorarak cevabı birlikte oluşturabilirsiniz."}


async def _kavram_yz_uret(k: dict, iso: str) -> None:
    ctx = ""
    try:
        sonuc = await asyncio.to_thread(kutuphane.ara, k["ad_en"] or k["ad"], None, 3)
        ctx = "\n\n".join(_duz(s["metin"], 500) for s in sonuc[:2])
    except Exception:
        pass
    istem = (f"Kavram: {k['ad']} ({k['ad_en']}), alan: {k['ders']}.\nKütüphane alıntısı (varsa):\n{ctx or '-'}\n\n"
             "Bu kavramı bir endüstri mühendisliği öğrencisine anlat: sade açıklama, gerçek hayat örneği, "
             "düşündürücü tek bir soru ve o sorunun kısa cevabı.")
    c = await _yz(KavramCikti, istem, "Sade, doğru ve samimi bir Türkçe ders hocasısın. Uydurma bilgi verme.", 900)
    ic = _oku("kavram", {})
    if c and ic.get("tarih") == iso:
        ic.update({"aciklama": c.aciklama, "ornek": c.ornek, "soru": c.soru, "cevap": c.cevap, "yapay_zeka": True})
        _yaz("kavram", ic)


_kavram_gorevi: asyncio.Task | None = None


async def gunun_kavrami(bekle_yz: bool = False) -> dict:
    global _kavram_gorevi
    iso = _bugun().isoformat()
    ic = _oku("kavram", {})
    if not (isinstance(ic, dict) and ic.get("tarih") == iso):
        k = await asyncio.to_thread(gunun_kavrami_sec)
        ic = {"tarih": iso, "kavram": k["ad"], "kavram_en": k["ad_en"], "ders": k["ders"], "id": k["id"],
              **(await _yedek_kavram(k)), "yapay_zeka": False}
        _yaz("kavram", ic)
        try:
            if llm.ai_hazir():
                if bekle_yz:
                    await _kavram_yz_uret(k, iso)
                    ic = _oku("kavram", ic)
                else:
                    _kavram_gorevi = asyncio.get_running_loop().create_task(_kavram_yz_uret(k, iso))
        except Exception as e:
            log.warning("kavram üretimi başlatılamadı: %s", e)
    ic["bekliyor"] = bool(not ic.get("yapay_zeka") and _kavram_gorevi and not _kavram_gorevi.done())
    return ic


@router.get("/gunun-kavrami")
async def gunun_kavrami_ucu():
    return await gunun_kavrami()


# ---------------------------------------------------------------- 4) Vikipedi'den öğrenme
class _VikiHiz(RuntimeError):
    """Vikipedi 429/5xx: bir süre yeniden denenmez."""


VIKI_GERI_CEKIL = 3600


def _viki_eslesir(terim: str, baslik: str) -> bool:
    t, b = _viki_anahtar(terim), _viki_anahtar(baslik)
    if not t or not b:
        return False
    ilk = t.split(" ")[0]
    return t in b or b in t or (len(ilk) >= 3 and ilk in b)


def _viki_anahtar(terim: str) -> str:
    return re.sub(r"\s+", " ", _kat(terim)).strip()


def _terim_temiz(terim: str) -> str:
    t = re.sub(r"[^\w\s\-\.'()/]", " ", terim or "", flags=re.U)
    return re.sub(r"\s+", " ", t).strip()[:80]


async def _viki_baslik(c: httpx.AsyncClient, dil: str, terim: str) -> dict | None:
    """Özet uç noktası (yönlendirmeler izlenir); bulunamazsa/anlam ayrımı sayfasıysa arama ile en iyi başlık."""
    taban = f"https://{dil}.wikipedia.org"
    for aday in (terim, terim.title()) if terim != terim.title() else (terim,):
        r = await c.get(f"{taban}/api/rest_v1/page/summary/{quote(aday.replace(' ', '_'), safe='')}")
        if r.status_code == 200:
            j = r.json()
            if j.get("type") != "disambiguation" and j.get("title"):
                return j
        elif r.status_code == 429 or r.status_code >= 500:
            raise _VikiHiz(f"Vikipedi geçici hata ({r.status_code})")
    r = await c.get(f"{taban}/w/api.php", params={"action": "query", "list": "search", "srsearch": terim,
                                                      "srlimit": "1", "format": "json"})
    if r.status_code == 429 or r.status_code >= 500:
        raise _VikiHiz(f"Vikipedi geçici hata ({r.status_code})")
    ara = ((r.json().get("query") or {}).get("search") or []) if r.status_code == 200 else []
    if not ara:
        return None
    if not _viki_eslesir(terim, ara[0]["title"]):
        return {"_eslesmedi": True}
    r = await c.get(f"{taban}/api/rest_v1/page/summary/{quote(ara[0]['title'].replace(' ', '_'), safe='')}")
    return r.json() if r.status_code == 200 and r.json().get("type") != "disambiguation" else None


async def vikipedi_ogren(terim: str, dil: str | None = None) -> dict:
    """Terimi Vikipedi'de bulur, makale metnini kütüphaneye tur='diger' ("Vikipedi: <başlık>") olarak bir kez ekler.
    Dönüş: {durum: eklendi|zaten|bulunamadi|hata|atlandi, baslik?, dil?}"""
    terim = _terim_temiz(terim)
    anahtar = _viki_anahtar(terim)
    if len(anahtar) < 3:
        return {"durum": "atlandi", "neden": "terim çok kısa"}
    d = _durum()
    viki = d.get("vikipedi") or {}
    onceki = viki.get(anahtar)
    if onceki and (onceki["durum"] in ("eklendi", "zaten") or _simdi() - onceki["zaman"] < 7 * GUN):
        return {"durum": "zaten" if onceki["durum"] != "bulunamadi" else "bulunamadi", "baslik": onceki.get("baslik", ""),
                "dil": onceki.get("dil", "")}
    if float(d.get("viki_geri_cekil") or 0) > _simdi():
        return {"durum": "hata", "neden": "Vikipedi geçici olarak sınırlı; daha sonra denenecek"}
    diller = [dil] if dil in ("tr", "en") else ["tr", "en"]
    hata = ""
    eslesmedi = False
    try:
        async with _istemci() as c:
            for dl in diller:
                j = await _viki_baslik(c, dl, terim)
                if not j:
                    continue
                if j.get("_eslesmedi"):
                    eslesmedi = True
                    continue
                baslik = j["title"]
                taban = f"https://{dl}.wikipedia.org"
                r = await c.get(f"{taban}/w/api.php", params={"action": "query", "prop": "extracts", "explaintext": "1",
                                                                  "exsectionformat": "plain", "redirects": "1",
                                                                  "titles": baslik, "format": "json"})
                metin = ""
                if r.status_code == 200:
                    for p in ((r.json().get("query") or {}).get("pages") or {}).values():
                        metin = (p.get("extract") or "").strip()
                metin = metin[:60000] or j.get("extract") or ""
                if len(metin) < 80:
                    continue
                url = ((j.get("content_urls") or {}).get("desktop") or {}).get("page") or f"{taban}/wiki/{quote(baslik.replace(' ', '_'))}"
                meta = {"baslik": f"Vikipedi: {baslik}", "ozet": j.get("extract") or metin[:400], "url": url,
                        "kimlik": f"wikipedia:{dl}:{baslik}", "tur": "diger", "dil": dl, "dergi": "Vikipedi"}
                eklendi = await asyncio.to_thread(kutuphane.ekle_makale, meta, metin)
                durum = "eklendi" if eklendi else "zaten"
                with _kilit:
                    d = _durum()
                    v = d.get("vikipedi") or {}
                    v[anahtar] = {"durum": durum, "baslik": baslik, "dil": dl, "zaman": _simdi()}
                    d["vikipedi"] = v
                    _yaz("durum", d)
                if eklendi:
                    klasor.olay("bilgi", f"Vikipedi'den öğrenildi: {baslik}")
                return {"durum": durum, "baslik": baslik, "dil": dl}
    except Exception as e:
        hata = f"{type(e).__name__}: {e}"[:160]
        log.warning("Vikipedi: %s", hata)
        if isinstance(e, _VikiHiz):
            _durum_guncelle(viki_geri_cekil=_simdi() + VIKI_GERI_CEKIL)
    if hata:
        return {"durum": "hata", "neden": hata}
    with _kilit:
        d = _durum()
        v = d.get("vikipedi") or {}
        v[anahtar] = {"durum": "bulunamadi", "zaman": _simdi()}
        d["vikipedi"] = v
        _yaz("durum", d)
    if eslesmedi:
        return {"durum": "atlandi", "eklendi": False, "neden": "eşleşme yok"}
    return {"durum": "bulunamadi"}


class OgrenGirdi(BaseModel):
    terim: str = Field(max_length=200)
    dil: str = ""


@router.post("/ogren")
async def ogren_ucu(g: OgrenGirdi):
    gun = _bugun().isoformat()
    d = _durum()
    sayac = d.get("ogren_sayac") or {}
    if sayac.get("gun") != gun:
        sayac = {"gun": gun, "n": 0}
    if sayac["n"] >= VIKI_KULLANICI_GUNLUK:
        return {"durum": "atlandi", "neden": "günlük sınır"}
    sayac["n"] += 1
    _durum_guncelle(ogren_sayac=sayac)
    return await vikipedi_ogren(g.terim, g.dil or None)


async def zayif_dugumleri_ogren(en_fazla: int = VIKI_GUNLUK) -> list[dict]:
    """Kütüphane kapsamı zayıf bilgi haritası düğümleri için Vikipedi makalesi ekler (günde birkaç)."""
    sonuc = []
    say = await asyncio.to_thread(bilgi_haritasi.kapsam_olc)
    zayiflar = sorted(((n, k) for k in _konu_listesi() for n in [say.get(k["id"], 0)] if n < bilgi_haritasi.ZAYIF_ESIK),
                      key=lambda x: (x[0], x[1]["id"]))
    for _, k in zayiflar:
        if len(sonuc) >= en_fazla:
            break
        for terim, dil in ((k["ad_en"], "en"), (k["ad"], "tr")):
            if len(sonuc) >= en_fazla:
                break
            r = await vikipedi_ogren(terim, dil)
            if r["durum"] == "hata":  # hız sınırı/ağ hatası: bu turu bırak
                return sonuc
            if r["durum"] == "eklendi":
                sonuc.append({"konu": k["ad"], **r})
            await _bekle(1.0)
    return sonuc


# ---------------------------------------------------------------- 5) bitirme projesi danışmanı
ADIMLAR = ("daraltma", "yontem", "veri", "zaman", "rapor")
ADIM_AD = {"daraltma": "Konu daraltma", "yontem": "Yöntem seçimi", "veri": "Veri planı", "zaman": "Zaman çizelgesi",
           "rapor": "Rapor iskeleti"}


class AdimMadde(BaseModel):
    baslik: str
    aciklama: str


class AdimCikti(BaseModel):
    maddeler: list[AdimMadde]
    sorgular: list[str] = Field(default_factory=list, description="Yalnızca konu daraltmada: İngilizce literatür arama sorguları")
    not_: str = Field(default="", description="Kısa genel not")


def bitirme_durumu() -> dict:
    b = _oku("bitirme", {})
    if not isinstance(b, dict) or not b:
        b = {"konu": "", "aciklama": "", "adimlar": {}, "literatur": [], "guncellendi": 0}
    b.setdefault("adimlar", {})
    b.setdefault("literatur", [])
    return b


def _arac_onerileri(konu: str) -> list[str]:
    m = _kat(konu)
    out = []
    for anahtarlar, arac in ARAC_IPUCU:
        if arac in hesap.ARACLAR and arac not in out and any(_kat(a) in m for a in anahtarlar):
            out.append(arac)
    return out[:4] or ["istatistik"]


def _yedek_adim(adim: str, b: dict) -> dict:
    konu = b["konu"]
    bul = konu_bul(konu, 3)
    araclar = _arac_onerileri(konu)
    if adim == "daraltma":
        m = [("Sistemi sınırla", f"“{konu}” için tek bir tesis, bölüm ya da süreç seç; kapsamı 1-2 cümleyle yaz."),
             ("Ölçülebilir hedef belirle", "İyileştirmeyi ölçeceğin bir ölçüt seç (bekleme süresi, maliyet, verim, hata oranı)."),
             ("Araştırma sorusu yaz", "“X sisteminde Y yöntemi uygulanırsa Z ölçütü ne kadar iyileşir?” biçiminde tek bir soru kur."),
             ("Veriye erişimi doğrula", "Konu, 3-4 ayda toplanabilecek veriyle çalışılabilir olmalı; erişemeyeceğin veri gerektiriyorsa daralt.")]
        q = [re.sub(r"\s+", " ", (x["ad_en"] or "")).lower() for x in bul] or [konu]
        return {"maddeler": [{"baslik": a, "aciklama": c} for a, c in m], "sorgular": q, "not_": ""}
    if adim == "yontem":
        m = [{"baslik": f"Hesap aracı: {a}", "aciklama": f"“{hesap.ARACLAR[a].aciklama}” — Hesap araçları bölümünde dene."} for a in araclar]
        m += [{"baslik": x["ad"], "aciklama": f"Bilgi haritası konusu ({x['alan_ad']}); ilgili ders: {', '.join(x['dersler'][:2])}."} for x in bul]
        return {"maddeler": m or [{"baslik": "Yöntem", "aciklama": "Konuyu hocayla konuşup uygun yöntemi birlikte seçin."}], "sorgular": [], "not_": ""}
    if adim == "veri":
        m = [("Mevcut kayıtlar", "Firmanın üretim/satış/duruş kayıtları, ERP çıktıları."),
             ("Doğrudan gözlem", "Zaman etüdü, iş örneklemesi, sayım formu ile saha ölçümü."),
             ("Anket / görüşme", "Çalışan ve yöneticilerle kısa yapılandırılmış görüşme."),
             ("Veri temizleme planı", "Eksik/aykırı değer kuralları, birimler, örneklem büyüklüğü; kaynakları ve izinleri not et.")]
        return {"maddeler": [{"baslik": a, "aciklama": c} for a, c in m], "sorgular": [], "not_": ""}
    if adim == "zaman":
        hafta = max(8, min(20, int(b.get("hafta") or 14)))
        parca = [("Konu ve literatür", 0.2), ("Veri toplama", 0.25), ("Model / analiz", 0.3), ("Sonuçlar ve öneriler", 0.15),
                 ("Yazım ve sunum hazırlığı", 0.1)]
        m, bas = [], 1
        for ad, oran in parca:
            n = max(1, round(hafta * oran))
            son = min(hafta, bas + n - 1)
            m.append({"baslik": f"Hafta {bas}-{son}" if son > bas else f"Hafta {bas}", "aciklama": ad})
            bas = son + 1
        if bas <= hafta:
            m[-1]["baslik"] = f"Hafta {bas - 1}-{hafta}"
        return {"maddeler": m, "sorgular": [], "not_": f"Toplam {hafta} hafta varsayıldı."}
    bol = ["Özet", "1. Giriş (problem, amaç, kapsam)", "2. Literatür taraması", "3. Mevcut sistemin tanıtımı",
           "4. Yöntem ve veri", "5. Analiz ve bulgular", "6. Öneriler ve uygulama planı", "7. Sonuç", "Kaynakça", "Ekler"]
    return {"maddeler": [{"baslik": x, "aciklama": ""} for x in bol], "sorgular": [], "not_": ""}


def _adim_istemi(adim: str, b: dict) -> str:
    onceki = "\n".join(f"- {ADIM_AD[a]}: " + "; ".join(m["baslik"] for m in v["maddeler"][:6])
                       for a, v in b["adimlar"].items() if a != adim and v.get("maddeler"))
    ek = {"daraltma": "Konuyu daralt: 4-5 madde (kapsam, ölçüt, araştırma sorusu...). 'sorgular' alanına 2-3 İngilizce literatür arama sorgusu yaz.",
          "yontem": "Uygun 3-5 yöntem öner; her biri için neden uygun olduğunu yaz. Uygunsa şu hesap araçlarından birini adıyla an: "
                    + ", ".join(hesap.ARACLAR) + ".",
          "veri": "Gereken verileri, nereden/nasıl toplanacağını ve temizleme notlarını 4-6 madde yaz.",
          "zaman": f"{b.get('hafta') or 14} haftalık plan: her madde bir hafta aralığı (başlık 'Hafta 1-2') ve o haftaların çıktısı (açıklama).",
          "rapor": "Bitirme raporu için bölüm başlıkları iskeleti: her madde bir bölüm, açıklamada bölümde ne yazılacağı (1 cümle)."}[adim]
    return (f"Bitirme projesi konusu: {b['konu']}\n{b.get('aciklama') or ''}\nÖnceki adımlar:\n{onceki or '-'}\n\n"
            f"Görev ({ADIM_AD[adim]}): {ek}")


async def bitirme_adim_uret(adim: str, bekle: bool = False) -> dict:
    if adim not in ADIMLAR:
        raise ValueError("Bilinmeyen adım")
    b = bitirme_durumu()
    if not b["konu"].strip():
        raise ValueError("Önce proje konusunu yaz")
    c = await _yz(AdimCikti, _adim_istemi(adim, b),
                  "Sen endüstri mühendisliği bitirme projesi danışmanısın. Somut, uygulanabilir ve Türkçe yaz; uydurma kaynak/veri verme.",
                  1800, bekle)
    if c and c.maddeler:
        s = {"maddeler": [m.model_dump() for m in c.maddeler[:10]], "sorgular": [q for q in c.sorgular if q.strip()][:3],
             "not": c.not_, "yapay_zeka": True}
    else:
        y = _yedek_adim(adim, b)
        s = {"maddeler": y["maddeler"], "sorgular": y["sorgular"], "not": y["not_"], "yapay_zeka": False}
    if adim == "yontem":
        s["araclar"] = _arac_onerileri(b["konu"] + " " + " ".join(m["baslik"] + " " + m["aciklama"] for m in s["maddeler"]))
    s["uretildi"] = _simdi()
    with _kilit:  # uzun await sırasında başka istek yazmış olabilir: taze oku, yalnızca bu adımı birleştir
        taze = bitirme_durumu()
        if taze["konu"] != b["konu"]:
            return taze  # konu değişti ya da sıfırlandı: eski sonucu yazma
        taze["adimlar"][adim] = s
        taze["guncellendi"] = _simdi()
        _yaz("bitirme", taze)
        return taze


class BitirmeGirdi(BaseModel):
    konu: str | None = Field(default=None, max_length=300)
    aciklama: str | None = Field(default=None, max_length=2000)
    hafta: int | None = None
    adim: str | None = None
    sifirla: bool = False


@router.get("/bitirme")
async def bitirme_getir():
    return bitirme_durumu()


@router.post("/bitirme")
async def bitirme_kaydet(g: BitirmeGirdi):
    if g.sifirla:
        with _kilit:
            _yaz("bitirme", {})
            return bitirme_durumu()
    with _kilit:
        b = bitirme_durumu()
        if g.konu is not None:
            if g.konu.strip() != b["konu"]:
                b["adimlar"], b["literatur"] = {}, []
            b["konu"] = g.konu.strip()
        if g.aciklama is not None:
            b["aciklama"] = g.aciklama.strip()
        if g.hafta:
            b["hafta"] = max(8, min(20, g.hafta))
        b["guncellendi"] = _simdi()
        _yaz("bitirme", b)
    if g.adim:
        try:
            return await bitirme_adim_uret(g.adim)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return b


class LiteraturGirdi(BaseModel):
    sorgu: str = Field(default="", max_length=200)


@router.post("/bitirme/literatur")
async def bitirme_literatur(g: LiteraturGirdi):
    b = bitirme_durumu()
    konu0 = b["konu"]
    sorgu = g.sorgu.strip() or " ".join(((b["adimlar"].get("daraltma") or {}).get("sorgular") or [b["konu"]])[:1]).strip()
    if not sorgu:
        raise HTTPException(400, "Önce proje konusunu yaz")
    bugun = _bugun()
    bulunan, hata = [], ""
    try:
        async with _istemci() as c:
            bulunan = await literatur._crossref(c, sorgu, date(bugun.year - 6, 1, 1), bugun)
    except Exception as e:
        hata = f"Literatür kaynağına ulaşılamadı: {type(e).__name__}"
    sonuc = []
    for m in sorted(bulunan, key=lambda x: -x.get("atif", 0))[:10]:
        meta = {k: m.get(k) for k in ("baslik", "yazarlar", "yil", "dergi", "doi", "url", "ozet")}
        try:
            eklendi = bool(await asyncio.to_thread(kutuphane.ekle_makale, meta))
        except Exception:
            eklendi = False
        sonuc.append({"baslik": m["baslik"], "yazar": ", ".join(m.get("yazarlar") or [])[:80], "yil": m.get("yil"),
                      "dergi": m.get("dergi"), "doi": m.get("doi"), "url": m.get("url"), "yeni": eklendi})
    if not sonuc and not hata:
        hata = "Bu sorgu için sonuç bulunamadı"
    with _kilit:  # uzun await sonrası taze oku; yalnızca literatür alanlarını birleştir
        taze = bitirme_durumu()
        if taze["konu"] != konu0:
            return {"sorgu": sorgu, "sonuclar": taze["literatur"], "hata": "Proje konusu değişti; sonuçlar kaydedilmedi"}
        if hata:  # hata ya da boş sonuç: mevcut listeyi ezme
            return {"sorgu": sorgu, "sonuclar": taze["literatur"], "hata": hata}
        taze["literatur"] = sonuc
        taze["literatur_sorgu"] = sorgu
        taze["guncellendi"] = _simdi()
        _yaz("bitirme", taze)
    return {"sorgu": sorgu, "sonuclar": sonuc, "hata": ""}


# ---------------------------------------------------------------- 6) günlük hayattan endüstri mühendisliği
GUNLUK_TALIMAT = (
    "GÜNLÜK HAYATTAN ENDÜSTRİ MÜHENDİSLİĞİ: Öğrenci çevresindeki bir sistemi anlattı ya da fotoğrafını gönderdi. "
    "Sırayla şunları anlat: (1) Sistemi tanımla: girdiler, süreç adımları, çıktılar, kaynaklar (insan/makine/alan), darboğaz nerede. "
    "(2) Hangi endüstri mühendisliği modeliyle modellenir (kuyruk teorisi, tesis yerleşimi, çizelgeleme, envanter, hat dengeleme, simülasyon...) ve neden. "
    "(3) Gereken verileri say (varış hızı, hizmet süresi, talep, süreler...) ve öğrenci bunları nasıl ölçebilir. "
    "(4) Basit bir sayısal örnek kur, sayıları hesap araçlarıyla hesapla (uydurma sayı kullanma, varsayımları belirt) ve sonucu yorumla. "
    "(5) 2-3 somut iyileştirme önerisi ver. Fotoğraf varsa yalnızca görünenlere dayan, göremediğin şeyi varsay diye belirt.")

GOREVLER = [
    "Bir markette ya da kantinde kasa kuyruğuna bak: 10 kişinin varış aralığını ve hizmet süresini say. Hangi model uyar?",
    "Yemekhanede tepsi alma, yemek alma, ödeme sırasını izle: darboğaz hangi istasyon?",
    "Bir kargo şubesine ya da kuryeye bak: paket kabulden teslimata hangi adımlardan geçiyor?",
    "Bir otopark girişinde araç giriş-çıkışını 10 dakika say: doluluk ne zaman en yüksek?",
    "Otobüs/metro durağında bekleme sürelerini not et: sefer aralığı ile bekleme arasındaki ilişki nedir?",
    "Evde mutfağı bir üretim hattı gibi düşün: yemek hazırlığında hangi adım bekletiyor, yerleşimi nasıl değiştirirsin?",
    "Bir kafede sipariş-hazırlama-teslim akışına bak: kaç çalışan, kaç istasyon, kim bekliyor?",
    "Bir kütüphane ya da ofis yazıcısı önünde oluşan bekleme: kaç kişi, ne kadar süre? Ek yazıcı gerekir mi?",
    "Dolabındaki/depodaki malzemeleri düzenle: en sık kullanılan şey nerede duruyor? ABC analizi yap.",
    "Okul girişinde turnike ya da kart okutma noktasını gözle: yoğun saatte kaç kişi/dakika geçiyor?",
]


def gunluk_gorev(bugun: date | None = None) -> dict:
    iso = (bugun or _bugun()).isoformat()
    g = GOREVLER[_tohum(iso, "gorev") % len(GOREVLER)]
    return {"tarih": iso, "gorev": g, "talimat": GUNLUK_TALIMAT}


@router.get("/gunluk-hayat/gorev")
async def gunluk_gorev_ucu():
    return gunluk_gorev()


# ---------------------------------------------------------------- zamanlayıcı
def _gun_gecti(anahtar: str, saat: float = 20) -> bool:
    return _simdi() - float(_durum().get(anahtar) or 0) > saat * 3600


async def tur_calistir() -> dict:
    """Zamanlayıcının bir turu: haber (günde bir), bülten (haftada bir), günün kavramı, Vikipedi (günde bir).
    Her adım ayrı korunur: biri hata verirse diğerleri çalışmaya devam eder."""
    rapor: dict = {}

    async def adim(ad, is_):
        try:
            rapor[ad] = await is_()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("güncel adım %s başarısız: %s", ad, e)
            rapor[ad] = {"hata": f"{type(e).__name__}: {e}"[:160]}

    if _gun_gecti("haber_zamani"):
        await adim("haber", haberleri_cek)
    try:
        b = _oku("bulten", {})
        bulten_gerek = _simdi() - float((b or {}).get("uretildi") or 0) > 7 * GUN and (
            haberler() or kutuphane.son_eklenenler(7, ("makale",), 1))
    except Exception as e:
        log.warning("güncel bülten kontrolü: %s", e)
        bulten_gerek = False
    if bulten_gerek:
        async def bulten():
            return bool(await bulten_uret(bekle=True))
        await adim("bulten", bulten)
    if _gun_gecti("viki_zamani"):
        _durum_guncelle(viki_zamani=_simdi())
        await adim("vikipedi", zayif_dugumleri_ogren)

    async def kavram():
        await gunun_kavrami(bekle_yz=False)
    await adim("kavram", kavram)
    if rapor.get("kavram") is None:
        rapor.pop("kavram", None)
    return rapor


async def zamanlayici() -> None:
    """Uygulama açıkken saatte bir bakar. Ayarlardan `guncel_otomatik` = false ile kapatılabilir."""
    await asyncio.sleep(ILK_BEKLEME)
    while True:
        try:
            if config.load_settings().get("guncel_otomatik", True):
                await tur_calistir()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("güncel zamanlayıcı: %s", e)
        await asyncio.sleep(KONTROL_ARALIGI)


_gorev: asyncio.Task | None = None


def zamanlayici_baslat() -> None:
    global _gorev
    if _gorev is None or _gorev.done():
        _gorev = asyncio.get_running_loop().create_task(zamanlayici())
