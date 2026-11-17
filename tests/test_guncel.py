"""Güncel kal modülü testleri: RSS ayrıştırma, trend, bülten, günün kavramı, Vikipedi, bitirme, uç noktalar.
Ağ çağrıları httpx.MockTransport ile sahtedir; yapay zeka llm._parse monkeypatch ile sahtelenir."""
import asyncio
import time
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app import guncel, kutuphane, llm, main, notes, yerel

SIMDI = 1794787200.0  # 2026-11-16 UTC
GUN = 86400


def _rss(ogeler):
    govde = "".join(f"<item><title>{b}</title><link>{u}</link><description>&lt;p&gt;{o}&lt;/p&gt;</description>"
                    f"<pubDate>{t}</pubDate></item>" for b, u, o, t in ogeler)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{govde}</channel></rss>'


def _tarih(gun_once):
    from email.utils import formatdate
    return formatdate(SIMDI - gun_once * GUN, usegmt=True)


ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom haberi</title>
<link rel="alternate" href="https://ornek.com/atom1"/><summary>Özet &amp; metin</summary>
<updated>2026-11-10T10:00:00Z</updated></entry></feed>"""


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kutuphane._kapat()
    monkeypatch.setattr(kutuphane, "KOK", tmp_path / "kutuphane")
    monkeypatch.setattr(yerel, "HOST", "http://127.0.0.1:9")
    monkeypatch.setattr(guncel, "KOK", tmp_path / "guncel")
    monkeypatch.setattr(guncel, "_simdi", lambda: SIMDI)
    monkeypatch.setattr(llm, "ai_hazir", lambda: False)

    async def yok(*_):
        return None
    monkeypatch.setattr(guncel, "_bekle", yok)
    for c in notes.list_courses():
        notes.delete_course(c["id"])
    yield tmp_path
    kutuphane._kapat()


def _istemci_yap(monkeypatch, handler):
    monkeypatch.setattr(guncel, "_istemci", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"User-Agent": guncel.UA}, follow_redirects=True))


# ---------------------------------------------------------------- RSS
def test_rss_ve_atom_ayristirma():
    r = guncel.akis_ayristir(_rss([("Tedarik zinciri &lt;b&gt;krizi&lt;/b&gt;", "https://a.com/1", "Liman &amp; kargo", _tarih(2)),
                                   ("Linksiz", "", "x", _tarih(1))]), "Dive", SIMDI)
    assert len(r) == 1 and r[0]["baslik"] == "Tedarik zinciri krizi" and r[0]["ozet"] == "Liman & kargo"
    assert abs(r[0]["tarih"] - (SIMDI - 2 * GUN)) < 2 and r[0]["kaynak"] == "Dive"
    a = guncel.akis_ayristir(ATOM, "A", SIMDI)
    assert a[0]["url"] == "https://ornek.com/atom1" and a[0]["ozet"] == "Özet & metin"
    assert guncel.akis_ayristir("<bozuk", "x") == []


def test_arxiv_guncelleme_duyurusu_atlanir():
    x = _rss([("Yeni", "https://arxiv.org/abs/1", "arXiv:1 Announce Type: new Abstract: Optimizasyon", _tarih(1)),
              ("Eski", "https://arxiv.org/abs/2", "arXiv:2 Announce Type: replace Abstract: x", _tarih(1))])
    r = guncel.akis_ayristir(x, "arXiv", SIMDI)
    assert [o["baslik"] for o in r] == ["Yeni"] and r[0]["ozet"] == "Optimizasyon"


def test_haberleri_cek_kutuphaneye_ekler_bozuk_akisi_atlar(monkeypatch):
    def h(req):
        if "iyi" in req.url.host:
            return httpx.Response(200, text=_rss([("Kuyruk teorisi hastanede", "https://iyi.com/1", "Bekleme süresi", _tarih(3))]))
        return httpx.Response(404)
    _istemci_yap(monkeypatch, h)
    akislar = [("İyi", "https://iyi.com/rss"), ("Kötü", "https://kotu.com/rss")]
    r = asyncio.run(guncel.haberleri_cek(akislar))
    assert r["calisan"] == ["İyi"] and len(r["hatalar"]) == 1 and r["kutuphaneye"] == 1
    k = [x for x in kutuphane.liste() if x["tur"] == "haber"]
    assert len(k) == 1 and k[0]["url"] == "https://iyi.com/1"
    r2 = asyncio.run(guncel.haberleri_cek(akislar))  # ikinci tur: aynı haber tekrar eklenmez
    assert r2["kutuphaneye"] == 0 and r2["yeni"] == 0
    assert len(guncel.haberler()) == 1


# ---------------------------------------------------------------- trend
def test_trend_yukselenleri_bulur():
    liste = []
    for i in range(5):  # son 6 ayda 5 simülasyon haberi
        liste.append({"baslik": f"Dijital ikiz ve simülasyon {i}", "ozet": "dijital ikiz kullanımı", "url": f"u{i}",
                      "tarih": SIMDI - (10 + i) * GUN, "kaynak": "x"})
    liste.append({"baslik": "Kanban uygulaması", "ozet": "", "url": "e1", "tarih": SIMDI - 250 * GUN, "kaynak": "x"})
    liste.append({"baslik": "Kanban ve JIT", "ozet": "", "url": "e2", "tarih": SIMDI - 260 * GUN, "kaynak": "x"})
    t0 = guncel.trend_hesapla(liste, SIMDI)  # önceki dönemde 50'den az haber: yükselen listesi boş + neden
    assert t0["yukselenler"] == [] and t0["yeterli_veri"] is False and t0["yukselen_neden"]
    t = guncel.trend_hesapla(liste, SIMDI, en_az_onceki=0)
    ids = [x["id"] for x in t["yukselenler"]]
    assert "dijital_ikiz" in ids
    assert t["son_haber"] == 5 and t["onceki_haber"] == 2
    kanban = next(x for x in t["dusenler"] if x["id"] == "kanban_jit")
    assert kanban["yeni"] == 0 and kanban["eski"] == 2


def test_trend_onbellek_ve_haber_kirpma(monkeypatch):
    guncel._yaz("haberler", [{"baslik": "Dijital ikiz", "ozet": "x", "url": "u1", "tarih": SIMDI - GUN, "kaynak": "x"}])
    t1 = guncel.trend_hesapla()
    assert guncel.trend_hesapla() is t1  # aynı sürüm: önbellekten
    guncel._yaz("haberler", guncel.haberler() + [{"baslik": "Kanban", "ozet": "", "url": "u2", "tarih": SIMDI - 2 * GUN, "kaynak": "x"}])
    assert guncel.trend_hesapla() is not t1
    # 3000'den fazla yakın tarihli haber kırpılmaz; 90 günden eski haberin özeti atılır, 730 günden eskisi silinir
    eski = {"baslik": "Eski", "ozet": "uzun özet", "url": "eski", "tarih": SIMDI - 200 * GUN, "kaynak": "x"}
    cok_eski = {"baslik": "Çok eski", "ozet": "y", "url": "ce", "tarih": SIMDI - 800 * GUN, "kaynak": "x"}
    cok = [{"baslik": f"H{i}", "ozet": "o", "url": f"c{i}", "tarih": SIMDI - 5 * GUN - i, "kaynak": "x"} for i in range(3100)]
    guncel._yaz("haberler", cok + [eski, cok_eski])
    _istemci_yap(monkeypatch, lambda req: httpx.Response(200, text=_rss([])))
    asyncio.run(guncel.haberleri_cek([("Dive", "https://x.com/rss")]))
    k = {h["url"]: h for h in guncel.haberler()}
    assert len(k) == 3101 and "ce" not in k and k["eski"]["ozet"] == "" and k["eski"]["baslik"] == "Eski"


# ---------------------------------------------------------------- bülten
def _haber_yaz(n=5):
    guncel._yaz("haberler", [{"baslik": f"Haber {i} kuyruk teorisi", "ozet": "Bekleme süreleri azaldı. " * 3,
                              "url": f"https://h.com/{i}", "tarih": SIMDI - i * GUN, "kaynak": "Dive"} for i in range(n)])


def test_bulten_yedek_yapay_zeka_yok():
    _haber_yaz()
    b = asyncio.run(guncel.bulten_uret())
    assert b["yapay_zeka"] is False and len(b["maddeler"]) == 5
    assert b["maddeler"][0]["url"].startswith("https://h.com/") and b["maddeler"][0]["ders"]
    assert guncel._oku("bulten", None)["baslik"]


def test_bulten_yapay_zeka(monkeypatch):
    _haber_yaz()
    monkeypatch.setattr(llm, "ai_hazir", lambda: True)

    async def sira():
        return None

    async def sahte(model_cls, content, system=None, effort=None, max_tokens=16000):
        assert "Haber 0" in content
        return model_cls(baslik="Haftanın özeti", maddeler=[
            {"baslik": "Bekleme azaldı", "ozet": "Sade özet", "ders": "Kuyruk teorisi", "kariyer": "Python, Simio", "kaynak_no": 1},
            {"baslik": "Uydurma bağlantı", "ozet": "x", "kaynak_no": 99}])
    monkeypatch.setattr(llm, "arka_plan_sirasi", sira)
    monkeypatch.setattr(llm, "_parse", sahte)
    b = asyncio.run(guncel.bulten_uret())
    assert b["yapay_zeka"] and b["baslik"] == "Haftanın özeti"
    assert b["maddeler"][0]["url"] == "https://h.com/0" and b["maddeler"][1]["url"] == ""  # model url uyduramaz


def test_bulten_yapay_zeka_hata_verirse_yedege_duser(monkeypatch):
    _haber_yaz()
    monkeypatch.setattr(llm, "ai_hazir", lambda: True)

    async def sira():
        return None

    async def bozuk(*a, **k):
        raise RuntimeError("model yok")
    monkeypatch.setattr(llm, "arka_plan_sirasi", sira)
    monkeypatch.setattr(llm, "_parse", bozuk)
    assert asyncio.run(guncel.bulten_uret())["yapay_zeka"] is False


# ---------------------------------------------------------------- günün kavramı
def test_gunun_kavrami_deterministik_ve_tekrarsiz():
    d0 = date(2026, 11, 16)
    k0 = guncel.gunun_kavrami_sec(d0)
    assert guncel.gunun_kavrami_sec(d0)["id"] == k0["id"]  # aynı gün aynı kavram
    gorulen = {k0["id"]}
    for i in range(1, 40):
        k = guncel.gunun_kavrami_sec(date.fromordinal(d0.toordinal() + i))
        assert k["id"] not in gorulen
        gorulen.add(k["id"])
    # aynı tarih, durum silinse bile aynı sonucu verir (tohum tarihe bağlı)
    guncel._yaz("durum", {})
    assert guncel.gunun_kavrami_sec(d0)["id"] == k0["id"]


def test_gunun_kavrami_icerik_yedek():
    k = asyncio.run(guncel.gunun_kavrami())
    assert k["kavram"] and k["aciklama"] and k["soru"] and k["cevap"] and k["yapay_zeka"] is False
    assert asyncio.run(guncel.gunun_kavrami())["id"] == k["id"]


# ---------------------------------------------------------------- Vikipedi
def _viki_handler(sayac, bulunamaz=False):
    def h(req: httpx.Request):
        sayac.append(str(req.url))
        assert req.headers["user-agent"].startswith("DersAnlatici/1.0")
        yol = req.url.path
        if "/api/rest_v1/page/summary/" in yol:
            if bulunamaz:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"type": "standard", "title": "Kuyruk teorisi", "extract": "Kuyruk teorisi bekleme hatlarını inceler.",
                                             "content_urls": {"desktop": {"page": "https://tr.wikipedia.org/wiki/Kuyruk_teorisi"}}})
        if yol == "/w/api.php" and req.url.params.get("prop") == "extracts":
            return httpx.Response(200, json={"query": {"pages": {"1": {"extract": "Kuyruk teorisi, bekleme hatlarının matematiksel incelenmesidir. " * 8}}}})
        if yol == "/w/api.php":
            return httpx.Response(200, json={"query": {"search": []}})
        return httpx.Response(404)
    return h


def test_vikipedi_bir_kez_ekler(monkeypatch):
    sayac = []
    _istemci_yap(monkeypatch, _viki_handler(sayac))
    r = asyncio.run(guncel.vikipedi_ogren("kuyruk teorisi", "tr"))
    assert r == {"durum": "eklendi", "baslik": "Kuyruk teorisi", "dil": "tr"}
    k = [x for x in kutuphane.liste() if x["tur"] == "diger"]
    assert len(k) == 1 and k[0]["baslik"] == "Vikipedi: Kuyruk teorisi"
    n = len(sayac)
    r2 = asyncio.run(guncel.vikipedi_ogren("Kuyruk teorisi", "tr"))  # ikinci istek: ağa bile gitmez
    assert r2["durum"] == "zaten" and len(sayac) == n
    assert len([x for x in kutuphane.liste() if x["tur"] == "diger"]) == 1
    guncel._yaz("durum", {})  # kayıt silinse de kütüphane tekrarı engeller
    assert asyncio.run(guncel.vikipedi_ogren("kuyruk teorisi", "tr"))["durum"] == "zaten"
    assert len([x for x in kutuphane.liste() if x["tur"] == "diger"]) == 1


def test_vikipedi_bulunamadi_ve_hata(monkeypatch):
    _istemci_yap(monkeypatch, _viki_handler([], bulunamaz=True))
    assert asyncio.run(guncel.vikipedi_ogren("zzzqqq yok", "en"))["durum"] == "bulunamadi"
    assert asyncio.run(guncel.vikipedi_ogren("ab"))["durum"] == "atlandi"
    _istemci_yap(monkeypatch, lambda req: httpx.Response(429, text="slow down"))
    assert asyncio.run(guncel.vikipedi_ogren("Little's law", "en"))["durum"] == "hata"


def test_vikipedi_eslesmeyen_baslik_eklenmez(monkeypatch):
    def h(req):
        yol = req.url.path
        if "/api/rest_v1/page/summary/" in yol:
            return httpx.Response(404, json={})
        if yol == "/w/api.php":
            return httpx.Response(200, json={"query": {"search": [{"title": "Alakasız Makale"}]}})
        return httpx.Response(404)
    _istemci_yap(monkeypatch, h)
    r = asyncio.run(guncel.vikipedi_ogren("kuyruk teorisi", "tr"))
    assert r["eklendi"] is False and r["neden"] == "eşleşme yok"
    assert not [x for x in kutuphane.liste() if x["tur"] == "diger"]


def test_vikipedi_429_geri_cekilir(monkeypatch):
    n = []
    _istemci_yap(monkeypatch, lambda req: (n.append(1), httpx.Response(429))[1])
    assert asyncio.run(guncel.vikipedi_ogren("Little's law", "en"))["durum"] == "hata"
    s = len(n)
    assert asyncio.run(guncel.vikipedi_ogren("Pareto analysis", "en"))["durum"] == "hata" and len(n) == s  # ağa gitmez


def test_zayif_dugumler_ayni_puanda_siralanir(monkeypatch):
    monkeypatch.setattr(guncel.bilgi_haritasi, "kapsam_olc", lambda: {})  # hepsi 0 puan
    cagri = []

    async def sahte(terim, dil=None):
        cagri.append(terim)
        return {"durum": "eklendi", "baslik": terim}
    monkeypatch.setattr(guncel, "vikipedi_ogren", sahte)
    r = asyncio.run(guncel.zayif_dugumleri_ogren(2))
    assert len(r) == 2 and len(cagri) == 2


def test_tur_calistir_adimlar_birbirini_durdurmaz(monkeypatch):
    async def patla(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(guncel, "haberleri_cek", patla)
    monkeypatch.setattr(guncel, "zayif_dugumleri_ogren", patla)
    r = asyncio.run(guncel.tur_calistir())
    assert "hata" in r["haber"] and "hata" in r["vikipedi"]
    assert _oku_kavram()["kavram"]  # günün kavramı yine üretildi


def _oku_kavram():
    return guncel._oku("kavram", {})


def test_yedek_kavram_olay_dongusunu_bloklamaz(monkeypatch):
    import threading
    kimlikler = []
    ana = threading.get_ident()
    monkeypatch.setattr(guncel.kutuphane, "ara", lambda *a, **k: kimlikler.append(threading.get_ident()) or [])
    asyncio.run(guncel.gunun_kavrami())
    assert kimlikler and all(i != ana for i in kimlikler)


# ---------------------------------------------------------------- bitirme
def test_bitirme_eszamanli_adimlar_ve_sifirlama(monkeypatch):
    guncel._yaz("bitirme", {"konu": "Depo", "aciklama": "", "adimlar": {}, "literatur": []})
    orijinal = guncel._yz

    async def yavas(*a, **k):
        await asyncio.sleep(0.05)
        return None
    monkeypatch.setattr(guncel, "_yz", yavas)

    async def paralel():
        return await asyncio.gather(guncel.bitirme_adim_uret("daraltma"), guncel.bitirme_adim_uret("zaman"))
    asyncio.run(paralel())
    assert guncel.bitirme_durumu()["adimlar"].keys() == {"daraltma", "zaman"}  # biri ötekini silmedi

    async def sifirlanirken():
        t = asyncio.create_task(guncel.bitirme_adim_uret("rapor"))
        await asyncio.sleep(0.01)
        guncel._yaz("bitirme", {})
        return await t
    taze = asyncio.run(sifirlanirken())
    assert taze["konu"] == "" and guncel.bitirme_durumu()["adimlar"] == {}  # sıfırlama geri alınmadı


def test_literatur_hata_ve_bos_sonucta_listeyi_korur(monkeypatch):
    mevcut = [{"baslik": "Eski makale", "doi": "10.1/e"}]
    guncel._yaz("bitirme", {"konu": "Depo", "aciklama": "", "adimlar": {}, "literatur": mevcut})
    _istemci_yap(monkeypatch, lambda req: httpx.Response(500))

    async def patla(*a, **k):
        raise RuntimeError("ağ yok")
    monkeypatch.setattr(guncel.literatur, "_crossref", patla)
    r = asyncio.run(guncel.bitirme_literatur(guncel.LiteraturGirdi(sorgu="depo")))
    assert r["hata"] and guncel.bitirme_durumu()["literatur"] == mevcut

    async def bos(*a, **k):
        return []
    monkeypatch.setattr(guncel.literatur, "_crossref", bos)
    r = asyncio.run(guncel.bitirme_literatur(guncel.LiteraturGirdi(sorgu="depo")))
    assert r["hata"] and guncel.bitirme_durumu()["literatur"] == mevcut


def test_bitirme_durum_kaydi_ve_adimlar():
    guncel_b = guncel.bitirme_durumu()
    assert guncel_b["konu"] == "" and guncel_b["adimlar"] == {}
    with pytest.raises(ValueError):
        asyncio.run(guncel.bitirme_adim_uret("daraltma"))
    guncel._yaz("bitirme", {"konu": "Hastane acil servis kuyruk simülasyonu", "aciklama": "", "adimlar": {}, "literatur": []})
    b = asyncio.run(guncel.bitirme_adim_uret("daraltma"))
    assert b["adimlar"]["daraltma"]["maddeler"] and b["adimlar"]["daraltma"]["sorgular"]
    b = asyncio.run(guncel.bitirme_adim_uret("yontem"))
    assert set(b["adimlar"]["yontem"]["araclar"]) >= {"kuyruk", "simulasyon"}
    b = asyncio.run(guncel.bitirme_adim_uret("zaman"))
    assert b["adimlar"]["zaman"]["maddeler"][0]["baslik"].startswith("Hafta 1")
    b = asyncio.run(guncel.bitirme_adim_uret("rapor"))
    assert any("Giriş" in m["baslik"] for m in b["adimlar"]["rapor"]["maddeler"])
    assert guncel.bitirme_durumu()["adimlar"].keys() == {"daraltma", "yontem", "zaman", "rapor"}  # diske yazıldı


# ---------------------------------------------------------------- uç noktalar
@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def test_gunluk_gorev_deterministik():
    a, b = guncel.gunluk_gorev(date(2026, 11, 16)), guncel.gunluk_gorev(date(2026, 11, 16))
    assert a == b and a["gorev"] and "ENDÜSTRİ" in a["talimat"]


def test_uc_noktalar(client, monkeypatch):
    assert client.get("/api/guncel/bulten").json() == {"bulten": None}
    _haber_yaz()
    b = client.post("/api/guncel/bulten/uret").json()["bulten"]
    assert len(b["maddeler"]) == 5
    assert client.get("/api/guncel/bulten").json()["bulten"]["baslik"] == b["baslik"]
    assert client.get("/api/guncel/gunun-kavrami").json()["kavram"]
    h = client.get("/api/guncel/haberler").json()
    assert len(h["haberler"]) == 5 and "yukselenler" in h["trend"]
    assert client.get("/api/guncel/gunluk-hayat/gorev").json()["gorev"]
    # bitirme
    assert client.get("/api/guncel/bitirme").json()["konu"] == ""
    r = client.post("/api/guncel/bitirme", json={"konu": "Depo yerleşim optimizasyonu", "adim": "daraltma"}).json()
    assert r["konu"].startswith("Depo") and r["adimlar"]["daraltma"]["maddeler"]
    assert client.post("/api/guncel/bitirme", json={"adim": "zaman", "konu": ""}).status_code == 400
    # literatür: sahte Crossref
    crossref = {"message": {"items": [{"DOI": "10.1/x1", "title": ["Warehouse layout"], "author": [{"given": "A", "family": "B"}],
                                       "issued": {"date-parts": [[2025]]}, "abstract": "<jats:p>" + "Depo yerleşimi. " * 10 + "</jats:p>",
                                       "URL": "https://doi.org/10.1/x1", "is-referenced-by-count": 3}]}}
    _istemci_yap(monkeypatch, lambda req: httpx.Response(200, json=crossref))
    monkeypatch.setattr(guncel.literatur, "_uyu", lambda s: asyncio.sleep(0))
    monkeypatch.setattr(guncel.literatur, "_sira", lambda: asyncio.sleep(0))
    monkeypatch.setattr(guncel.literatur, "_son_istek", {})
    lit = client.post("/api/guncel/bitirme/literatur", json={"sorgu": "warehouse layout"}).json()
    assert lit["sonuclar"][0]["doi"] == "10.1/x1" and lit["sonuclar"][0]["yeni"] is True
    assert client.post("/api/guncel/bitirme/literatur", json={"sorgu": "warehouse layout"}).json()["sonuclar"][0]["yeni"] is False
    # öğren
    _istemci_yap(monkeypatch, _viki_handler([]))
    assert client.post("/api/guncel/ogren", json={"terim": "kuyruk teorisi", "dil": "tr"}).json()["durum"] == "eklendi"
    assert client.post("/api/guncel/ogren", json={"terim": "kuyruk teorisi", "dil": "tr"}).json()["durum"] == "zaten"


def test_prompt_sabitleri():
    from app import prompts
    assert "yoklama" in prompts.ON_BILGI_YOKLAMA.lower() and "KAVRAM" in prompts.HATA_ANALIZI
