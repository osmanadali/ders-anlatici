"""Kütüphane (yerel bilgi bankası): içe alma, arama, ders etiketleme, cevaplarda kaynak, uç noktalar, Not Kutusu."""
import asyncio
import io
import json
import os
import tempfile
import threading
import time
import zipfile
from http.server import ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("OLLAMA_MODELS", tempfile.mkdtemp(prefix="sahte_ollama_"))
import fake_ollama  # noqa: E402
import fakes  # noqa: E402
from app import klasor, kutuphane, llm, main, notes, prompts, yerel  # noqa: E402
from conftest import make_text_pdf  # noqa: E402

fakes.install()

STOK = ("Ekonomik siparis miktari modeli stok kontrol sisteminde toplam maliyeti en kucukleyen siparis buyuklugunu verir. "
        "Siparis maliyeti ve elde tutma maliyeti dengelenir. ")
KUYRUK = ("Kuyruk teorisinde gelisler Poisson surecine uyar, servis sureleri ustel dagilir ve sistemin kararlilik kosulu "
          "gelis hizinin servis hizindan kucuk olmasidir. ")


@pytest.fixture(autouse=True)
def kutup(tmp_path, monkeypatch):
    kutuphane._kapat()
    monkeypatch.setattr(kutuphane, "KOK", tmp_path / "kutuphane")
    monkeypatch.setattr(yerel, "HOST", "http://127.0.0.1:9")  # Ollama yok: yalnızca kelime araması
    kutuphane._sorgu_hata["zaman"] = 0.0
    kutuphane._gomme.update(hazir=False, son_hata=0.0, mesaj="")
    yield tmp_path
    kutuphane._kapat()


@pytest.fixture()
def ollama(tmp_path, monkeypatch):
    """Süreç içinde çalışan sahte Ollama (gömme modeli kurulu)."""
    d = tmp_path / "ollama"
    d.mkdir()
    monkeypatch.setattr(fake_ollama, "DB", d / "modeller.json")
    monkeypatch.setattr(fake_ollama, "LOG", d / "istekler.jsonl")
    (d / "modeller.json").write_text(json.dumps(["qwen3-embedding:0.6b"]))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), fake_ollama.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(yerel, "HOST", f"http://127.0.0.1:{srv.server_address[1]}")
    yield d
    srv.shutdown()


def _isle():
    asyncio.run(kutuphane.isle_hepsi())


def _epub() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/icerik.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/icerik.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Yöneylem Araştırması</dc:title>'
                   '<dc:creator>Hamdy Taha</dc:creator><dc:date>2017-01-01</dc:date><dc:language>tr</dc:language></metadata>'
                   '<manifest><item id="b2" href="metin/b2.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="b1" href="metin/b1.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="css" href="s.css" media-type="text/css"/></manifest>'
                   '<spine><itemref idref="b1"/><itemref idref="b2"/></spine></package>')
        z.writestr("OEBPS/metin/b1.xhtml", "<html><head><style>p{color:red}</style></head><body><h1>Doğrusal Programlama</h1>"
                   "<p>Simpleks yöntemi köşe noktaları arasında amaç fonksiyonunu iyileştirerek ilerler ve en iyi çözüme ulaşır.</p></body></html>")
        z.writestr("OEBPS/metin/b2.xhtml", "<html><body><h2>Kuyruk Modelleri</h2><p>" + KUYRUK + "</p></body></html>")
    return b.getvalue()


# ---------------------------------------------------------------- içe alma
def test_pdf_ice_alma_sayfa_numarasi_ve_tekrar():
    pdf = make_text_pdf(["Giris bolumu: endustri muhendisligi sistemleri tasarlar ve iyilestirir. " * 16, STOK * 8, KUYRUK * 8])
    k = kutuphane.ekle_dosya("Uretim_Planlama.pdf", pdf)
    assert k["durum"] == "bekliyor" and k["tur"] == "kitap"
    with pytest.raises(ValueError, match="zaten kütüphanede"):
        kutuphane.ekle_dosya("kopya.pdf", pdf)
    _isle()
    k = kutuphane.liste()[0]
    assert k["durum"] == "hazir", k
    assert k["sayfa_sayisi"] == 3 and k["parca_sayisi"] >= 1 and k["baslik"] == "Uretim Planlama"
    s = kutuphane.ara("ekonomik sipariş miktarı")
    assert s and s[0]["kaynak_id"] == k["id"] and 2 in {x["sayfa"] for x in s}
    assert {"metin", "kaynak_id", "baslik", "yazar", "yil", "sayfa", "tur", "skor"} <= set(s[0])
    assert {x["sayfa"] for x in kutuphane.ara("Poisson")} == {3}
    assert k["parca_sayisi"] >= 4
    d = kutuphane.durum()
    assert d["kaynak_sayisi"] == 1 and d["parca_sayisi"] == k["parca_sayisi"] and not d["gomme_hazir"]


def test_epub_okuma_sirasi_ve_bilgileri():
    kutuphane.ekle_dosya("taha.epub", _epub())
    _isle()
    k = kutuphane.liste()[0]
    assert k["durum"] == "hazir", k
    assert (k["baslik"], k["yazar"], k["yil"], k["dil"]) == ("Yöneylem Araştırması", "Hamdy Taha", 2017, "tr")
    s = kutuphane.ara("simpleks köşe noktaları")
    assert s and "bölüm 1" in s[0]["bolum"] and s[0]["sayfa"] is None
    assert "color" not in s[0]["metin"]  # stil içeriği atlanır
    assert "bölüm 2" in kutuphane.ara("Poisson kuyruk")[0]["bolum"]


def test_txt_turkce_harf_katlama():
    kutuphane.ekle_dosya("notlar.txt", "Işık şiddeti ölçümü ergonomide çalışma ortamının aydınlatma koşullarını belirler. "
                                       "İşçi verimliliği bu koşullara bağlıdır.".encode())
    _isle()
    for q in ("ışık", "ISIK", "IŞIK ŞİDDETİ", "isci verimliligi", "çalışma"):
        assert kutuphane.ara(q), q


def test_desteklenmeyen_ve_taranmis_pdf():
    with pytest.raises(ValueError, match="Desteklenmeyen"):
        kutuphane.ekle_dosya("a.exe", b"MZ")
    kutuphane.ekle_dosya("tarama.pdf", make_text_pdf(["", "", ""]))
    _isle()
    k = kutuphane.liste()[0]
    assert k["durum"] == "hata" and "Taranmış PDF" in k["hata"]


def test_fts_sozdizimini_bozan_sorgular():
    kutuphane.ekle_dosya("s.txt", (STOK + KUYRUK).encode())
    _isle()
    for q in ['"', 'stok AND', '-stok', 'stok: maliyet', '(stok', 'NEAR(stok', '*', 'stok OR NOT', "'; DROP TABLE x"]:
        assert isinstance(kutuphane.ara(q), list), q
    assert kutuphane.ara('"stok kontrol" -AND:')
    assert kutuphane.ara("nedir bu ve ile") == []  # yalnızca durak sözcükleri
    assert kutuphane.ara("termodinamik entropi") == []  # alakasız: kaynak uydurma


def test_ekle_makale_doi_tekrari():
    meta = {"baslik": "Yeni bir stok kontrol yaklaşımı", "yazarlar": ["A. Yılmaz", "B. Kaya"], "yil": 2026,
            "dergi": "IJPE", "doi": "https://doi.org/10.1000/ABC.123", "url": "https://ornek.org/m", "ozet": STOK}
    m = kutuphane.ekle_makale(meta)
    assert m and m["doi"] == "10.1000/abc.123" and m["tur"] == "makale" and m["durum"] == "hazir"
    assert kutuphane.var_mi_doi("10.1000/abc.123") and kutuphane.var_mi_doi("doi:10.1000/ABC.123")
    assert kutuphane.ekle_makale(dict(meta, doi="10.1000/abc.123")) is None
    s = kutuphane.ara("stok kontrol", tur="makale")
    assert s and s[0]["yeni"] and s[0]["yazar"].startswith("A. Yılmaz")
    assert kutuphane.ara("stok kontrol", tur="kitap") == []


def test_guncelle_ve_sil():
    k = kutuphane.ekle_makale({"baslik": "X", "ozet": KUYRUK, "doi": "10.1/x"})
    k = kutuphane.guncelle(k["id"], {"baslik": "Kuyruk Kitabı", "yazar": "Gross", "yil": "2008", "dersler": ["ENM 305"]})
    assert (k["baslik"], k["yazar"], k["yil"], k["dersler"]) == ("Kuyruk Kitabı", "Gross", 2008, ["ENM 305"])
    kutuphane.sil(k["id"])
    assert kutuphane.liste() == [] and kutuphane.ara("Poisson") == [] and kutuphane.bos_mu()
    with pytest.raises(KeyError):
        kutuphane.sil(k["id"])


# ---------------------------------------------------------------- ders etiketleme
def test_ders_etiketleme_mufredattan_ve_koddan():
    metin = ("Tesis planlama ve tesis yer seçimi, tesis tasarımı, depo sistemleri düzenlemesi, malzeme yönetim sistemi, "
             "otomatik yönlü araç sistemleri ve bilgisayar destekli tesis düzenlemesi. ") * 5
    assert "ENM 317" in kutuphane.ders_etiketle(metin, "Facilities Planning")
    assert kutuphane.ders_etiketle("rastgele", "ENM 463 Ders Notu")[0] == "ENM 463"
    assert len(kutuphane.ders_etiketle(metin)) <= 3


def test_ders_onceligi():
    a = kutuphane.ekle_makale({"baslik": "A", "ozet": STOK, "doi": "10.1/a", "dersler": ["ENM 312"]})
    b = kutuphane.ekle_makale({"baslik": "B", "ozet": STOK + " ", "doi": "10.1/b", "dersler": ["ENM 305"]})
    assert kutuphane.ara("stok kontrol", "ENM 312")[0]["kaynak_id"] == a["id"]
    assert kutuphane.ara("stok kontrol", "ENM305")[0]["kaynak_id"] == b["id"]


# ---------------------------------------------------------------- gömme + hibrit arama
def test_gomme_ve_hibrit_siralama(ollama, monkeypatch):
    kutuphane.ekle_dosya("stok.txt", (STOK * 3).encode())
    kutuphane.ekle_dosya("kuyruk.txt", (KUYRUK * 3).encode())
    _isle()
    d = kutuphane.durum()
    assert d["gomme_hazir"] and d["gomulu_parca"] == d["parca_sayisi"] > 0, d
    assert all(k["gomulu_orani"] == 1.0 for k in kutuphane.liste())
    istek = [json.loads(x) for x in (ollama / "istekler.jsonl").read_text().splitlines()]
    embed = [r["body"] for r in istek if r["path"] == "/api/embed"]
    assert embed and all(b["model"] == "qwen3-embedding:0.6b" and isinstance(b["input"], list) for b in embed)
    assert not any(x.startswith("Instruct:") for b in embed for x in b["input"])  # belgelere talimat öneki yok

    s = kutuphane.ara("siparis maliyeti stok")
    assert s[0]["baslik"] == "stok"
    sorgu = [r["body"] for r in map(json.loads, (ollama / "istekler.jsonl").read_text().splitlines())
             if r["path"] == "/api/embed"][-1]
    assert sorgu["input"][0].startswith("Instruct:")

    # kelime eşleşmesi olmayan ama anlamca (vektörce) yakın parça yine bulunur
    hedef = kutuphane._vektorler({"embeddings": [fake_ollama.sahte_vektor(KUYRUK * 3)]})[0]
    monkeypatch.setattr(kutuphane, "_sorgu_vektoru", lambda q: hedef)
    s = kutuphane.ara("zzqx wwyy")
    assert s and s[0]["baslik"] == "kuyruk"
    # iki listede de olan parça (kelime + vektör) yalnız birinde olanın önüne geçer
    s = kutuphane.ara("maliyet Poisson")
    assert s[0]["baslik"] == "kuyruk"


def test_gomme_modeli_yoksa_yalniz_kelime_aramasi():
    kutuphane.ekle_dosya("stok.txt", STOK.encode())
    _isle()
    assert not kutuphane.durum()["gomme_hazir"]
    assert kutuphane.ara("stok kontrol")


# ---------------------------------------------------------------- cevaplarda kaynak
@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def _sistem_metni() -> str:
    return "\n".join(b["text"] for b in fakes.CALLS[-1]["system"])


def test_ask_kutuphane_bosken_degismez(client, monkeypatch):
    monkeypatch.setattr(main.kutuphane, "ara", lambda *a, **k: pytest.fail("boş kütüphanede arama yapılmamalı"))
    r = client.post("/api/ask", data={"text": "Stok kontrol nedir?"})
    assert r.status_code == 200
    assert "KAYNAK KİTAP" not in _sistem_metni()
    from app import config, store

    beklenen = llm.build_system(None, "", False, store.memory_summary(None), config.load_settings().get("level", "normal"))
    sistem = fakes.CALLS[-1]["system"]  # (hafıza metni cevap sonrası değişebilir: yalnızca yapı karşılaştırılır)
    assert len(sistem) == len(beklenen) and sistem[:-1] == beklenen[:-1]


def test_ask_kaynak_blogu_ve_butce(client, monkeypatch):
    for i in range(12):
        kutuphane.ekle_makale({"baslik": f"Stok kitabı {i}", "yazarlar": ["Silver"], "yil": 2016,
                               "ozet": (STOK + f" bolum {i} ") * 8, "doi": f"10.1/s{i}"})
    monkeypatch.setattr(llm, "provider", lambda: "yerel")
    limit = llm.notes_limit()
    c = notes.create_course("ENM 312 Üretim Planlaması")
    notes.add_document(c["id"], "hafta1.pdf", make_text_pdf(["Stok kontrol modelleri: ekonomik siparis miktari " * 40] * 30))
    gorulen = {}
    gercek = notes.notes_context

    def izle(*a, **k):
        gorulen["limit"] = k.get("limit")
        return gercek(*a, **k)

    monkeypatch.setattr(main.notes, "notes_context", izle)
    r = client.post("/api/ask", data={"text": "Ekonomik sipariş miktarı nasıl bulunur?", "course_id": c["id"]})
    assert r.status_code == 200
    txt = _sistem_metni()
    assert "KAYNAK KİTAP/MAKALE BÖLÜMLERİ" in txt and "Silver, Stok kitabı" in txt and "arrow_note" in txt
    blok = next(b["text"] for b in fakes.CALLS[-1]["system"] if b["text"].startswith("# KAYNAK"))
    icerik = blok.split("<kaynak_bolumleri>\n", 1)[1].rsplit("\n</kaynak_bolumleri>", 1)[0]
    assert 0 < len(icerik) <= int(limit * 0.3)
    assert gorulen["limit"] == limit - len(icerik)  # not bütçesi kaynak kadar azalır, toplam aşılmaz
    assert blok.count("[") >= 2


def test_kaynak_metni_butceyi_asmaz():
    s = [{"metin": "x" * 5000, "baslik": "K", "yazar": "Y", "yil": 2020, "sayfa": 4, "tur": "kitap"}] * 4
    out = kutuphane.kaynak_metni(s, 3000)
    assert len(out) <= 3000 and out.startswith("[1] Y, K (2020), s.4")
    assert kutuphane.kaynak_metni([], 3000) == "" and prompts.kaynak_block("a").startswith("# KAYNAK")


# ---------------------------------------------------------------- uç noktalar
def test_uc_noktalar(client):
    r = client.post("/api/kutuphane", files=[("files", ("stok.txt", STOK.encode(), "text/plain")),
                                             ("files", ("stok2.txt", STOK.encode(), "text/plain")),
                                             ("files", ("virus.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(j["eklenen"]) == 1 and {a["dosya"] for a in j["atlanan"]} == {"stok2.txt", "virus.exe"}
    assert "zaten" in next(a["neden"] for a in j["atlanan"] if a["dosya"] == "stok2.txt")
    kid = j["eklenen"][0]["id"]
    _isle()
    g = client.get("/api/kutuphane").json()
    assert g["kaynaklar"][0]["durum"] == "hazir" and g["durum"]["kaynak_sayisi"] == 1 and "otomatik" in g["literatur"]
    assert client.get("/api/kutuphane/ara", params={"q": "stok", "ders": ""}).json()["sonuclar"]
    p = client.patch(f"/api/kutuphane/{kid}", json={"baslik": "Stok Yönetimi", "dersler": ["ENM 312"]}).json()
    assert p["baslik"] == "Stok Yönetimi" and p["dersler"] == ["ENM 312"]
    assert client.patch("/api/kutuphane/yok", json={"baslik": "x"}).status_code == 404
    assert client.get("/api/literatur").status_code == 200
    assert client.delete(f"/api/kutuphane/{kid}").json() == {"ok": True}
    assert client.delete(f"/api/kutuphane/{kid}").status_code == 404
    s = client.get("/api/settings").json()
    assert s["literatur_otomatik"] is True and s["kutuphane_ocr"] is False and s["gomme_modeli"] == "qwen3-embedding:0.6b"


# ---------------------------------------------------------------- Not Kutusu / Kitaplar
def test_not_kutusu_kitaplar(kutup, monkeypatch):
    monkeypatch.setenv("DERS_NOT_KUTUSU", str(kutup / "Not Kutusu"))
    k = klasor.kutu_hazirla()
    assert (k / "Kitaplar").is_dir()
    (k / "Kitaplar" / "kuyruk.txt").write_text(KUYRUK, "utf-8")
    (k / "Kitaplar" / "bos.txt").write_text("", "utf-8")
    monkeypatch.setattr(klasor, "_hazir_mi", lambda f: True)
    assert asyncio.run(klasor.kitaplari_tara()) == 1
    assert not (k / "Kitaplar" / "kuyruk.txt").exists() and not (k / "Eklendi" / "Kitaplar" / "kuyruk.txt").exists()  # öğrenilecek; ikinci kopya tutulmaz
    assert (k / "Eklenemedi" / "bos.txt").exists()
    _isle()
    assert kutuphane.ara("Poisson")
    assert any("Kütüphaneye eklendi: kuyruk" in o["mesaj"] for o in klasor.OLAYLAR)


# ---- inceleme düzeltmeleri
def test_guncelle_dersler_ve_yil_temizleme():
    k = kutuphane.ekle_dosya("a.txt", (STOK * 20).encode())
    k = kutuphane.guncelle(k["id"], {"yil": 2020, "dersler": "ENM 463, ENM 317"})
    assert k["dersler"] == ["ENM 463", "ENM 317"] and k["yil"] == 2020
    k = kutuphane.guncelle(k["id"], {"yil": None, "dersler": 5})
    assert k["yil"] is None and k["dersler"] == []


def test_tek_kaynakta_k_kadar_parca():
    kutuphane.ekle_dosya("a.txt", ((STOK + "Ek ornek cumle burada. ") * 80).encode())
    _isle()
    assert len(kutuphane.ara("siparis maliyeti", k=8)) > kutuphane.KAYNAK_BASINA


def test_yeni_isareti_yayin_yilina_bagli():
    kutuphane.ekle_makale({"baslik": "Eski makale siparis", "yazarlar": ["A"], "yil": 2015, "doi": "10.1/e",
                           "ozet": STOK * 3})
    kutuphane.ekle_makale({"baslik": "Yeni makale siparis", "yazarlar": ["B"], "yil": time.localtime().tm_year,
                           "doi": "10.1/y", "ozet": STOK * 3})
    sonuc = {s["baslik"]: s["yeni"] for s in kutuphane.ara("siparis maliyeti")}
    assert sonuc["Eski makale siparis"] is False and sonuc["Yeni makale siparis"] is True


def test_isleyici_sinyali_is_sirasinda_kaybolmaz():
    async def dene():
        kutuphane.ekle_dosya("a.txt", (STOK * 10).encode())
        kutuphane.baslat_isleyici()
        for _ in range(100):
            await asyncio.sleep(0.1)
            if kutuphane.durum()["kaynak_sayisi"] and not kutuphane.liste()[0]["durum"] == "bekliyor":
                break
        kutuphane.ekle_dosya("b.txt", (KUYRUK * 10).encode())
        for _ in range(100):
            await asyncio.sleep(0.1)
            if all(x["durum"] == "hazir" for x in kutuphane.liste()):
                break
        return [x["durum"] for x in kutuphane.liste()]
    assert asyncio.run(dene()) == ["hazir", "hazir"]


def test_gemini_iken_kaynak_bolumu_yok(monkeypatch):
    monkeypatch.setattr(llm, "provider", lambda: "gemini")
    assert llm.kaynak_limit() == 0


def test_ogrenilen_kitabin_kopyasi_silinir(tmp_path):
    import asyncio as _a

    from app import config as _c, kutuphane as _k

    k = _k.ekle_dosya("silinecek_kitap.txt", ("Talep tahmini ve stok yonetimi ekonomik siparis miktari. " * 80).encode(), "kitap")
    kopya = _k.KOK / "dosyalar" / f"{k['id']}.txt"
    assert kopya.exists()
    _a.run(_k.isle_hepsi())
    assert not kopya.exists()  # öğrenildi, kopya silindi
    assert _k.ara("ekonomik siparis miktari")  # ama bilgi duruyor
    _c.save_settings({"kutuphane_dosya_sakla": True})
    try:
        k2 = _k.ekle_dosya("saklanacak.txt", ("Montaj hatti dengeleme cevrim suresi istasyon. " * 80).encode(), "kitap")
        _a.run(_k.isle_hepsi())
        assert (_k.KOK / "dosyalar" / f"{k2['id']}.txt").exists()
    finally:
        _c.save_settings({"kutuphane_dosya_sakla": False})
