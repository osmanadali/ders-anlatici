"""Mühendis hoca: hesap araçları, araç seçimi akışı, bilgi haritası, ERP rehberleri ve alıştırması."""
import json
import math

import pytest
from fastapi.testclient import TestClient

import fakes
from app import bilgi_haritasi, erp_alistirma, hazir_bilgi, hesap, kutuphane, llm, main, yerel

fakes.install()


def _g(arac, girdi):
    return hesap.calistir(arac, girdi)


# ---------------------------------------------------------------- hesap araçları
def test_eoq_ve_emniyet_stogu():
    s = _g("eoq", {"talep_yillik": 1000, "siparis_maliyeti": 50, "elde_tutma": 2, "tedarik_gun": 10,
                   "gunluk_ss": 5, "servis_duzeyi": 0.95})
    assert s.sayilar["EOQ"] == pytest.approx(math.sqrt(2 * 1000 * 50 / 2), abs=1e-4)
    assert s.sayilar["siparis_maliyeti"] == pytest.approx(s.sayilar["elde_tutma_maliyeti"], abs=1e-4)
    assert s.sayilar["emniyet_stogu"] == pytest.approx(1.6449 * 5 * math.sqrt(10), abs=0.01)
    assert s.sayilar["yeniden_siparis_noktasi"] == pytest.approx(1000 / 365 * 10 + s.sayilar["emniyet_stogu"], abs=1e-3)
    assert any("EOQ" in a for a in s.adimlar)


def test_kuyruk_mm1_ve_erlang_c():
    s = _g("kuyruk", {"lam": 2, "mu": 3})
    assert s.sayilar["Lq"] == pytest.approx(4 / 3, abs=1e-5) and s.sayilar["W"] == pytest.approx(1.0)
    c = _g("kuyruk", {"lam": 8, "mu": 3, "c": 3})  # a=8/3, rho=8/9
    a = 8 / 3
    p0 = 1 / (sum(a ** k / math.factorial(k) for k in range(3)) + a ** 3 / (6 * (1 - 8 / 9)))
    erlang_c = a ** 3 / (6 * (1 - 8 / 9)) * p0
    assert c.sayilar["beklemek_zorunda_olasilik"] == pytest.approx(erlang_c, abs=1e-5)
    assert c.sayilar["Lq"] == pytest.approx(erlang_c * (8 / 9) / (1 / 9), abs=1e-4)
    with pytest.raises(hesap.HesapHatasi):
        _g("kuyruk", {"lam": 5, "mu": 3})  # kararsız


def test_simulasyon_kurama_yakin():
    s = _g("simulasyon", {"lam": 2, "mu": 3, "musteri": 60000, "tohum": 7})
    assert s.sayilar["Wq"] == pytest.approx(s.sayilar["Wq_kuram"], rel=0.15)


def test_cp_cpk():
    s = _g("yeterlilik", {"LSL": 9, "USL": 11, "ortalama": 10.2, "sigma": 0.25})
    assert s.sayilar["Cp"] == pytest.approx(2 / 1.5, abs=1e-5)
    assert s.sayilar["Cpk"] == pytest.approx(0.8 / 0.75, abs=1e-5)


def test_dogrusal_programlama_ve_tamsayi():
    s = _g("dogrusal_programlama", {"c": [3, 5], "A_ub": [[1, 0], [0, 2], [3, 2]], "b_ub": [4, 12, 18]})
    assert s.sayilar["z"] == pytest.approx(36) and s.sayilar["degiskenler"] == {"x1": 2.0, "x2": 6.0}
    assert s.sayilar["golge_fiyat"] == pytest.approx([0, 1.5, 1.0], abs=1e-6)
    t = _g("dogrusal_programlama", {"c": [5, 4], "A_ub": [[6, 4], [1, 2]], "b_ub": [24, 6], "tamsayi": True})
    assert t.sayilar["z"] == pytest.approx(20)  # LP optimumu 21, tam sayılı 20
    with pytest.raises(hesap.HesapHatasi):
        _g("dogrusal_programlama", {"c": [1], "A_ub": [[1]], "b_ub": [-1]})  # uygun çözüm yok


def test_ulastirma_ve_atama():
    u = _g("ulastirma", {"arz": [20, 30], "talep": [10, 25, 15], "maliyet": [[8, 6, 10], [9, 12, 13]]})
    assert u.sayilar["toplam_maliyet"] == pytest.approx(465) and u.sayilar["plan"][0][1] == pytest.approx(20)
    d = _g("ulastirma", {"arz": [30, 30], "talep": [20, 20], "maliyet": [[1, 2], [2, 1]]})  # arz fazla → sanal hedef
    assert d.sayilar["toplam_maliyet"] == pytest.approx(40)
    a = _g("atama", {"maliyet": [[9, 2, 7], [6, 4, 3], [5, 8, 1]]})
    assert a.sayilar["toplam"] == pytest.approx(9) and a.sayilar["atamalar"] == [[1, 2], [2, 1], [3, 3]]


def test_johnson_ve_tek_makine():
    j = _g("johnson", {"isler": [[3, 6], [5, 2], [1, 2], [6, 6], [7, 5]]})
    assert j.sayilar["sira"] == [3, 1, 4, 5, 2] and j.sayilar["cmax"] == 24
    spt = _g("tek_makine", {"kural": "SPT", "sureler": [5, 2, 3]})
    assert spt.sayilar["sira"] == [2, 3, 1] and spt.sayilar["ortalama_akis"] == pytest.approx((2 + 5 + 10) / 3)
    edd = _g("tek_makine", {"kural": "EDD", "sureler": [4, 2, 3], "teslim": [9, 3, 5]})
    assert edd.sayilar["sira"] == [2, 3, 1] and edd.sayilar["maks_gecikme"] == 0


def test_cpm_kritik_yol_ve_pert():
    f = [{"ad": "A", "sure": 3}, {"ad": "B", "sure": 4, "onculler": ["A"]}, {"ad": "C", "sure": 2, "onculler": ["A"]},
         {"ad": "D", "sure": 5, "onculler": ["B", "C"]}]
    s = _g("cpm", {"faaliyetler": f})
    assert s.sayilar["kritik_yol"] == ["A", "B", "D"] and s.sayilar["proje_suresi"] == 12
    assert s.sayilar["bolluk"]["C"] == 2
    p = _g("cpm", {"faaliyetler": [{"ad": "X", "a": 1, "m": 2, "b": 3}, {"ad": "Y", "a": 2, "m": 4, "b": 12, "onculler": ["X"]}],
                   "hedef_sure": 8})
    assert p.sayilar["proje_suresi"] == pytest.approx(2 + 5)  # te: X=2, Y=(2+16+12)/6=5
    assert p.sayilar["kritik_yol_varyansi"] == pytest.approx((2 / 6) ** 2 + (10 / 6) ** 2)
    with pytest.raises(hesap.HesapHatasi):
        _g("cpm", {"faaliyetler": [{"ad": "A", "sure": 1, "onculler": ["B"]}, {"ad": "B", "sure": 1, "onculler": ["A"]}]})


def test_kontrol_kartlari():
    s = _g("kontrol_karti", {"tip": "xbar_r", "alt_gruplar": [[10, 11, 9, 10], [12, 10, 11, 11], [9, 10, 10, 9]]})
    xbb, rb = (10 + 11 + 9.5) / 3, (2 + 2 + 1) / 3
    assert s.sayilar["xbar_cizgi"] == pytest.approx(xbb, abs=1e-4)
    assert s.sayilar["xbar_UCL"] == pytest.approx(xbb + 0.729 * rb, abs=1e-4)
    assert s.sayilar["R_UCL"] == pytest.approx(2.282 * rb, abs=1e-4) and s.sayilar["R_LCL"] == 0
    p = _g("kontrol_karti", {"tip": "p", "hatali": [4, 6, 5, 5], "n": 100})
    assert p.sayilar["p_bar"] == pytest.approx(0.05) and p.sayilar["UCL"] == pytest.approx(0.05 + 3 * math.sqrt(0.05 * 0.95 / 100), abs=1e-5)
    c = _g("kontrol_karti", {"tip": "c", "kusur": [4, 6, 5, 25]})
    assert c.sayilar["c_bar"] == pytest.approx(10) and c.sayilar["sinir_disi"] == [4]


def test_istatistik_ogrenme_basabas_nbd():
    s = _g("istatistik", {"veri": [10, 12, 11, 13, 9], "mu0": 10})
    assert s.sayilar["ortalama"] == pytest.approx(11) and s.sayilar["ss"] == pytest.approx(math.sqrt(2.5), abs=1e-5)
    assert s.sayilar["GA_alt"] < 11 < s.sayilar["GA_ust"] and "p_degeri" in s.sayilar
    o = _g("ogrenme_egrisi", {"t1": 100, "oran": 0.8, "n": 4})
    assert o.sayilar["Tn"] == pytest.approx(64, abs=1e-4)
    b = _g("basabas", {"sabit_maliyet": 10000, "birim_fiyat": 50, "birim_degisken_maliyet": 30})
    assert b.sayilar["basabas_miktar"] == pytest.approx(500)
    n = _g("nbd_igo", {"nakit_akislari": [-1000, 300, 400, 500, 600], "faiz": 0.10})
    kol = -1000 + 300 / 1.1 + 400 / 1.1 ** 2 + 500 / 1.1 ** 3 + 600 / 1.1 ** 4
    assert n.sayilar["NBD"] == pytest.approx(kol, abs=1e-3)
    r = n.sayilar["IGO"]
    assert sum(v / (1 + r) ** t for t, v in enumerate([-1000, 300, 400, 500, 600])) == pytest.approx(0, abs=1e-3)


MRP_GIRDI = {
    "urun": "P", "ana_cizelge": [0, 0, 0, 0, 0, 100],
    "bom": [{"ust": "P", "bilesen": "B", "adet": 2}],
    "malzemeler": [{"ad": "P", "tedarik_suresi": 1}, {"ad": "B", "stok": 50, "tedarik_suresi": 2}],
}


def test_mrp_patlatma_bilinen_tablo():
    s = _g("mrp", MRP_GIRDI)
    p, b = s.sayilar["plan"]["P"], s.sayilar["plan"]["B"]
    assert p["planlanan_siparis_cikisi"] == [0, 0, 0, 0, 100, 0]
    assert b["brut"] == [0, 0, 0, 0, 200, 0] and b["net"] == [0, 0, 0, 0, 150, 0]
    assert b["planlanan_siparis_cikisi"] == [0, 0, 150, 0, 0, 0]
    assert b["eldeki_stok"][:4] == [50, 50, 50, 50] and b["eldeki_stok"][4] == 0
    # parti kuralları: FOQ 100'ün katı, stok fazlası taşınır
    g = json.loads(json.dumps(MRP_GIRDI))
    g["malzemeler"][1].update(parti="FOQ", parti_miktari=100)
    f = _g("mrp", g).sayilar["plan"]["B"]
    assert f["planlanan_siparis_girisi"][4] == 200 and f["eldeki_stok"][4] == 50
    # Wagner-Whitin ve Silver-Meal: ihtiyaçlar tek siparişte birleşebilir
    g2 = {"urun": "P", "ana_cizelge": [10, 10, 10, 10], "bom": [],
          "malzemeler": [{"ad": "P", "parti": "WW", "siparis_maliyeti": 100, "elde_tutma": 1}]}
    ww = _g("mrp", g2).sayilar["plan"]["P"]["planlanan_siparis_girisi"]
    assert sum(ww) == 40 and ww[0] == 40  # 100'lük sipariş maliyeti 4 siparişten ucuz
    g2["malzemeler"][0]["parti"] = "SM"
    sm = _g("mrp", g2).sayilar["plan"]["P"]["planlanan_siparis_girisi"]
    assert sum(sm) == 40
    # tedarik süresi yüzünden geçmişe düşen sipariş uyarılır
    g3 = json.loads(json.dumps(MRP_GIRDI))
    g3["ana_cizelge"] = [100, 0, 0, 0, 0, 0]
    uyari = _g("mrp", g3)
    assert any("UYARI" in a for a in uyari.adimlar)


def test_gecersiz_girdi_hata_verir():
    with pytest.raises(hesap.HesapHatasi):
        _g("eoq", {"talep_yillik": 100})
    with pytest.raises(hesap.HesapHatasi):
        _g("yok_arac", {})
    assert "eoq" in hesap.arac_listesi_metni() and "mrp" in hesap.arac_listesi_metni()


# ---------------------------------------------------------------- araç seçimi akışı
@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def _events(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


SORU = "Yıllık talebi 1000 birim, sipariş maliyeti 50 TL, elde tutma maliyeti 2 TL olan ürün için EOQ kaçtır?"


def test_arac_secimi_sonucu_mesaja_ekler(client, monkeypatch):
    async def sahte_parse(model_cls, content, system=None, effort=None, max_tokens=16000):
        if model_cls is not llm.HesapSecimi:
            raise llm.TutorError("test: başka çağrı")
        assert "eoq" in content  # araç listesi modele gösterildi
        return llm.HesapSecimi(arac="eoq", girdiler_json=json.dumps(
            {"talep_yillik": 1000, "siparis_maliyeti": 50, "elde_tutma": 2}))

    monkeypatch.setattr(llm, "_parse", sahte_parse)
    fakes.CALLS.clear()
    ev = _events(client.post("/api/ask", data={"text": SORU}))
    hes = [e for e in ev if e["type"] == "hesap"]
    assert hes and "EOQ" in hes[0]["message"] and hes[0]["arac"] == "eoq"
    son = fakes.CALLS[-1]["messages"][-1]["content"]
    metin = "\n".join(b.get("text", "") for b in son)
    assert "<hesap_sonucu>" in metin and "223.6" in metin and "kendin hesaplama" in metin
    assert ev[-1]["type"] == "done"


def test_arac_yok_iken_mesaj_degismez(client, monkeypatch):
    async def sahte_parse(model_cls, content, system=None, effort=None, max_tokens=16000):
        if model_cls is not llm.HesapSecimi:
            raise llm.TutorError("test: başka çağrı")
        return llm.HesapSecimi(arac="yok", girdiler_json="{}")

    monkeypatch.setattr(llm, "_parse", sahte_parse)
    fakes.CALLS.clear()
    ev = _events(client.post("/api/ask", data={"text": SORU}))
    assert not [e for e in ev if e["type"] == "hesap"]
    assert "hesap_sonucu" not in json.dumps(fakes.CALLS[-1]["messages"][-1]["content"])


def test_hesap_hatasi_sessizce_atlanir(client, monkeypatch):
    async def bozuk(model_cls, content, system=None, effort=None, max_tokens=16000):
        if model_cls is not llm.HesapSecimi:
            raise llm.TutorError("test: başka çağrı")
        return llm.HesapSecimi(arac="eoq", girdiler_json='{"talep_yillik": 100}')  # eksik girdi

    monkeypatch.setattr(llm, "_parse", bozuk)
    ev = _events(client.post("/api/ask", data={"text": SORU}))
    assert not [e for e in ev if e["type"] in ("hesap", "error")] and ev[-1]["type"] == "done"

    async def patlayan(*a, **k):
        raise llm.TutorError("model yok")

    monkeypatch.setattr(llm, "_parse", patlayan)
    ev = _events(client.post("/api/ask", data={"text": SORU}))
    assert ev[-1]["type"] == "done"


def test_hesap_kurali_ve_ayar():
    st = {"hesap_araclari": True}
    assert main._wants_hesap(st, "chat", SORU)
    assert not main._wants_hesap(st, "chat", "Merhaba hocam nasılsın bugün")  # sayı/anahtar yok
    assert not main._wants_hesap(st, "chat", "EOQ nedir, kısaca anlatır mısın lütfen")  # sayı yok
    assert not main._wants_hesap({"hesap_araclari": False}, "chat", SORU)
    assert not main._wants_hesap(st, "lecture", SORU)


def test_hesap_secimi_yok_ve_bilinmeyen_arac(monkeypatch):
    import asyncio

    async def yok(model_cls, content, **k):
        return llm.HesapSecimi(arac="bilinmeyen", girdiler_json="{}")

    monkeypatch.setattr(llm, "_parse", yok)
    assert asyncio.run(llm.hesap_secimi("soru 12")) is None


# ---------------------------------------------------------------- bilgi haritası
def test_bilgi_haritasi_yapisi_ve_dersler():
    h = bilgi_haritasi.harita()
    ids = [k["id"] for a in h["alanlar"] for k in a["konular"]]
    assert len(ids) == len(set(ids)) and len(h["alanlar"]) >= 15
    adlar = " ".join(a["ad_en"] for a in h["alanlar"])
    for ad in ("Work Design", "Operations Research", "Quality", "Ergonomics", "Supply Chain", "Simulation", "ERP", "Lean", "Six Sigma"):
        assert ad in adlar
    mufredat = json.load(open(main.Path(main.__file__).parent / "mufredat" / "gazi_endustri.json", encoding="utf-8"))
    kodlar = {d["kod"] for d in mufredat["dersler"]}
    for a in h["alanlar"]:
        assert set(a["dersler"]) <= kodlar, a["id"]
        for k in a["konular"]:
            assert k["anahtar"] and k["ad_en"] and set(k.get("dersler", [])) <= kodlar, k["id"]


def test_bilgi_haritasi_kapsam_ve_endpoint(tmp_path, monkeypatch, client):
    kutuphane._kapat()
    monkeypatch.setattr(kutuphane, "KOK", tmp_path / "kut")
    monkeypatch.setattr(yerel, "HOST", "http://127.0.0.1:9")
    try:
        bos = client.get("/api/bilgi-haritasi").json()
        assert bos["zayif_sayisi"] == bos["dugum_sayisi"] and bos["kapsam"] == 0
        metin = ("Ekonomik siparis miktari EOQ modeli: emniyet stoku ve yeniden siparis noktasi stok kontrol sistemlerinde "
                 "kullanilir. Stok kontrol politikalari siparis maliyeti ile elde tutma maliyetini dengeler. ") * 12
        import asyncio
        for i in range(3):
            kutuphane.ekle_dosya(f"stok{i}.txt", (metin + f" Ek bilgi {i}. ").encode(), "kitap")
        asyncio.run(kutuphane.isle_bekleyenler())
        h = client.get("/api/bilgi-haritasi").json()
        stok = next(x for a in h["alanlar"] for x in a["konular"] if x["id"] == "stok_kontrol")
        assert stok["parca"] > 0 and not stok["zayif"] and stok["kapsam"] > 0
        assert h["zayif_sayisi"] < h["dugum_sayisi"]
        q = bilgi_haritasi.zayif_sorgular(2)
        assert len(q) == 2 and all(x.islower() for x in q) and not any("inventory control" in x for x in q)
    finally:
        kutuphane._kapat()


def test_literatur_harita_sorgulari(monkeypatch):
    from app import literatur

    monkeypatch.setattr(bilgi_haritasi, "zayif_sorgular", lambda n=2: ["time study engineering", "ergonomics engineering"][:n])
    assert literatur.harita_sorgulari(1) == ["time study engineering"]
    monkeypatch.setattr(bilgi_haritasi, "zayif_sorgular", lambda n=2: 1 / 0)
    assert literatur.harita_sorgulari() == []


# ---------------------------------------------------------------- ERP rehberleri
def test_erp_rehberleri_bir_kez_eklenir(tmp_path, monkeypatch):
    kutuphane._kapat()
    monkeypatch.setattr(kutuphane, "KOK", tmp_path / "kut")
    monkeypatch.setattr(yerel, "HOST", "http://127.0.0.1:9")
    try:
        dosyalar = sorted(hazir_bilgi.DIR.glob("*.md"))
        assert 6 <= len(dosyalar) <= 10
        for f in dosyalar:
            n = len(f.read_text("utf-8").split())
            assert 600 <= n <= 1200, (f.name, n)
        assert hazir_bilgi.yukle() == len(dosyalar)
        liste = kutuphane.liste()
        assert len(liste) == len(dosyalar) and all(k["tur"] == "kitap" for k in liste)
        assert hazir_bilgi.yukle() == 0 and len(kutuphane.liste()) == len(dosyalar)
        kutuphane.sil(liste[0]["id"])  # kullanıcı sildiyse geri gelmez
        assert hazir_bilgi.yukle() == 0 and len(kutuphane.liste()) == len(dosyalar) - 1
    finally:
        kutuphane._kapat()


# ---------------------------------------------------------------- ERP alıştırması
def test_erp_alistirma_senaryo_ve_kontrol(client):
    s = client.get("/api/erp-alistirma", params={"seed": 11, "seviye": 2}).json()
    assert s["id"] == "s11-2" and len(s["ana_cizelge"]) == s["hafta_sayisi"] and "cozum" not in json.dumps(s).lower().replace("çözüm", "")
    assert {k["ad"] for k in s["kalemler"]} == {"A", "B", "C", "D", "E"}
    assert client.get("/api/erp-alistirma", params={"seed": 11, "seviye": 2}).json() == s  # tohumdan yeniden üretilir
    assert len(client.get("/api/erp-alistirma", params={"seviye": 1}).json()["kalemler"]) == 3
    dogru = erp_alistirma.cozum(s["id"])
    cevap = {ad: p["net"] for ad, p in dogru.items()}
    r = client.post("/api/erp-alistirma/kontrol", json={"id": s["id"], "cevap": cevap}).json()
    assert r["tamam"] and r["puan"] == r["toplam"] == 5 * s["hafta_sayisi"]
    # bir hücreyi boz, bir kalemi boş bırak
    yanlis = json.loads(json.dumps(cevap))
    yanlis["B"][2] = yanlis["B"][2] + 7
    yanlis.pop("E")
    r = client.post("/api/erp-alistirma/kontrol", json={"id": s["id"], "cevap": yanlis}).json()
    assert not r["tamam"] and r["dogru"]["B"][2] is False and r["dogru"]["B"][0] is True
    assert not any(r["dogru"]["E"]) and r["puan"] == r["toplam"] - 1 - s["hafta_sayisi"]
    assert any("Alt montaj B" in a for a in r["aciklama"]) and any("Parça E" in a for a in r["aciklama"])
    assert client.post("/api/erp-alistirma/kontrol", json={"id": "kotu", "cevap": {}}).status_code == 400


def test_ayar_varsayilani_acik(client):
    assert client.get("/api/settings").json()["hesap_araclari"] is True
