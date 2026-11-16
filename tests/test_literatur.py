"""Literatür taraması testleri: sahte Crossref / arXiv / OpenAlex (httpx.MockTransport), sahte kütüphane."""
import asyncio
import json
import sys
import types

import httpx
import pytest

from app import config, literatur as lit, notes

BUGUN = 1794787200  # 2026-11-16


class SahteKutuphane(types.ModuleType):
    def __init__(self):
        super().__init__("app.kutuphane")
        self.kayit: list[tuple[dict, str | None]] = []

    def var_mi_doi(self, doi):
        return any(m["doi"] == doi for m, _ in self.kayit)

    def ekle_makale(self, meta, tam_metin=None):
        if self.var_mi_doi(meta["doi"]):
            return None
        self.kayit.append((meta, tam_metin))
        return {"id": "k" + str(len(self.kayit)), **meta}


OZET = "<jats:p>" + ("Statistical process control in manufacturing lines. " * 6) + "</jats:p>"
CROSSREF = {"message": {"items": [
    {"DOI": "10.1000/ABC1", "title": ["SPC in lean plants"], "author": [{"given": "Ayşe", "family": "Yılmaz"}],
     "issued": {"date-parts": [[2026, 3]]}, "container-title": ["J. Ops &amp; Quality"], "abstract": OZET,
     "URL": "https://doi.org/10.1000/abc1", "is-referenced-by-count": 12, "license": [], "link": []},
    {"DOI": "10.1000/future", "title": ["Gelecek"], "issued": {"date-parts": [[2121, 10]]}, "abstract": OZET},
    {"DOI": "10.1000/noabs", "title": ["Özetsiz"], "issued": {"date-parts": [[2025]]}},
]}}
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/2611.06194v3</id><published>2026-11-10T00:00:00Z</published>
<title>Deep  SPC
 for plants</title><summary>%s</summary><author><name>A. Kaya</name></author>
<link rel="alternate" href="http://arxiv.org/abs/2611.06194v3"/><link title="pdf" href="https://arxiv.org/pdf/2611.06194v3"/>
</entry></feed>""" % ("Control charts with learning. " * 10)


def _handler(istekler, openalex=429):
    def h(req: httpx.Request):
        istekler.append(str(req.url))
        assert req.headers["user-agent"].startswith("DersAnlatici/1.0")
        if req.url.host == "api.crossref.org":
            return httpx.Response(200, json=CROSSREF)
        if req.url.host == "export.arxiv.org":
            return httpx.Response(200, text=ATOM)
        if req.url.host == "arxiv.org":
            return httpx.Response(404)
        if req.url.host == "api.openalex.org":
            return httpx.Response(openalex, json={"error": "Rate limit exceeded"}, headers={"retry-after": "11671"})
        return httpx.Response(404)
    return h


@pytest.fixture
def ortam(monkeypatch):
    kut = SahteKutuphane()
    monkeypatch.setitem(sys.modules, "app.kutuphane", kut)
    monkeypatch.setattr(lit, "_simdi", lambda: BUGUN)

    async def yok(_):
        return None
    monkeypatch.setattr(lit, "_uyu", yok)
    monkeypatch.setattr(lit, "_son_istek", {})
    monkeypatch.setattr(lit, "_calisiyor", False)
    lit._durum_dosyasi().unlink(missing_ok=True)
    for c in notes.list_courses():
        notes.delete_course(c["id"])
    c = notes.create_course("ENM 305 Kalite")
    c["profile"] = {"kod": "ENM 305", "ad": "KALİTE KONTROL", "ad_en": "STATISTICAL QUALITY CONTROL",
                    "haftalik_konular_en": ["Introduction", "Control Charts for Variables: X-bar and R", "MIDTERM",
                                            "Process Capability Analysis, Cp and Cpk", "Acceptance Sampling Plans",
                                            "FINAL"]}
    notes.save_course(c)
    e = notes.create_course("ENG 103 İngilizce")
    e["profile"] = {"kod": "ENG 103", "ad": "İNGİLİZCE", "ad_en": "ENGLISH"}
    notes.save_course(e)
    return kut


def calistir(zorla=True, **kw):
    istekler = []
    lit._transport = httpx.MockTransport(_handler(istekler, **kw))
    try:
        return asyncio.run(lit.guncelle(zorla)), istekler
    finally:
        lit._transport = None


def test_yeni_makaleler_eklenir_ve_ikinci_kez_eklenmez(ortam):
    s, ist = calistir()
    assert s["yeni"] == 2
    assert s["ders_bazinda"] == {"KALİTE KONTROL": 2}
    assert any("OpenAlex kotası" in h for h in s["hatalar"])
    dois = {m["doi"] for m, _ in ortam.kayit}
    assert dois == {"10.1000/abc1", "10.48550/arxiv.2611.06194"}  # DOI küçük harf, arXiv DOI'si türetildi
    m = next(m for m, _ in ortam.kayit if m["doi"] == "10.1000/abc1")
    assert m["dergi"] == "J. Ops & Quality" and m["yazarlar"] == ["Ayşe Yılmaz"] and m["yil"] == 2026
    assert m["dersler"] == ["ENM 305"] and "<" not in m["ozet"]
    assert not any("ENG" in u or "english" in u.lower() for u in ist)  # genel dersler taranmaz
    # ikinci tur: aynı DOI'ler tekrar eklenmez
    s2, _ = calistir()
    assert s2["yeni"] == 0 and len(ortam.kayit) == 2


def test_olay_ve_durum_dosyasi(ortam):
    from app import klasor
    n = len(klasor.OLAYLAR)
    calistir()
    assert any(o["tur"] == "literatur" and "2 yeni makale" in o["mesaj"] for o in klasor.OLAYLAR[n:])
    d = json.loads(lit._durum_dosyasi().read_text("utf-8"))
    assert d["son_tarama"] == BUGUN and d["son_sonuc"]["yeni"] == 2
    assert lit.durum()["sonraki"] == BUGUN + lit.HAFTA and lit.durum()["calisiyor"] is False


def test_internet_yokken_sessiz_devam(ortam):
    def h(req):
        raise httpx.ConnectError("yok")
    lit._transport = httpx.MockTransport(h)
    try:
        s = asyncio.run(lit.guncelle(True))
    finally:
        lit._transport = None
    assert s["yeni"] == 0 and s["hatalar"] and not ortam.kayit
    assert lit.durum()["son_tarama"] is None  # çevrimdışı tarama sayılmaz, tekrar denenir


def test_yedi_gun_kurali(ortam, monkeypatch):
    assert lit.vakti_geldi()
    lit._durum_yaz({"son_tarama": BUGUN - 3 * 86400})
    assert not lit.vakti_geldi()
    s, ist = calistir(zorla=False)
    assert s.get("atlandi") and not ist
    lit._durum_yaz({"son_tarama": BUGUN - 8 * 86400})
    assert lit.vakti_geldi()
    assert calistir(zorla=False)[0]["yeni"] == 2


def test_jats_temizligi():
    s = ("<jats:sec><jats:title>Purpose</jats:title><jats:p>Improve &amp; test.</jats:p></jats:sec>"
         "<jats:p>Results <jats:italic>show</jats:italic> gains.</jats:p>")
    t = lit.temizle_ozet(s)
    assert "<" not in t and "&amp;" not in t and "Improve & test." in t and "Results show gains." in t
    assert lit.temizle_ozet("<jats:title>Abstract</jats:title><jats:p>Metin burada.</jats:p>").endswith("Metin burada.")
    assert lit.doi_duzelt("https://doi.org/10.1/ABC") == "10.1/abc" and lit.doi_duzelt("doi:10.1/X") == "10.1/x"


def test_sorgu_uretimi():
    p = {"ad_en": "QUALITY  MANAGEMENT", "haftalik_konular_en": [
        "MIDTERM", "Strategic Planning and Management: levels", "History and Pioneers of Quality Management",
        "Lesson 4 - grammar", "short"]}
    q = lit.sorgular(p)
    assert q[0] == "quality management" and 2 <= len(q) <= 4
    assert all("midterm" not in x and "lesson" not in x for x in q)
    assert any(x.endswith("engineering") for x in q[1:])


def test_ders_secimi_ve_gelecek_tarih(ortam):
    kod = [lit.taranacak_mi(c) for c in notes.list_courses()]
    assert sorted(kod) == [False, True]
    r = lit._crossref_ayristir(CROSSREF, 2026)
    assert [m["doi"] for m in r] == ["10.1000/abc1"]


def test_pdf_tam_metin(ortam, monkeypatch):
    async def sahte_pdf(client, url):
        return "TAM METIN " * 100
    monkeypatch.setattr(lit, "_pdf_indir", sahte_pdf)
    calistir()
    tam = {m["doi"]: t for m, t in ortam.kayit}
    assert tam["10.48550/arxiv.2611.06194"].startswith("TAM METIN")  # arXiv PDF'i var
    assert tam["10.1000/abc1"] is None  # lisanssız Crossref: yalnızca özet


def test_ders_yokken_son_tarama_ilerlemez(ortam):
    for c in notes.list_courses():
        notes.delete_course(c["id"])
    s, _ = calistir()
    assert s["yeni"] == 0
    assert lit.durum()["son_tarama"] is None  # ders eklenince hemen taranabilsin
