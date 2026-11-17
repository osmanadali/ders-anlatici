"""Çalış sekmesi: hatalar, kartlar + aralıklı tekrar, simülasyon, hesap + Excel/Python, özet kartı."""
import asyncio
import io
import json
import subprocess
import sys
from datetime import date, timedelta

import openpyxl
import pytest
from fastapi.testclient import TestClient

import fakes
from app import calis, calis_dosya, hesap, llm, main, notes, store

fakes.install()


@pytest.fixture()
def client(monkeypatch):
    # her test temiz veriyle başlasın
    for ad in ("hatalar.json", "kartlar.json", "simulasyon.json"):
        calis._yol(ad).unlink(missing_ok=True)
    monkeypatch.setattr(llm, "ai_hazir", lambda: False)
    calis._OZET_ONBELLEK.clear()
    calis._OZET_KILITLERI.clear()
    with TestClient(main.app) as c:
        yield c


def _ders():
    return notes.create_course("Kalite")["id"]


# ---------------------------------------------------------------- hatalar
def test_hata_kaydi_tekrarlari_sayar_ve_analiz_eder(client, monkeypatch):
    cid = _ders()

    async def sahte(model, content, system=None, effort=None, max_tokens=0):
        assert "Doğru cevap: 12" in content
        return calis.HataAnalizi(tur="islem_hatasi", aciklama="Toplamada hata", tekrar_onerisi="İşlemleri yeniden yap")

    monkeypatch.setattr(llm, "ai_hazir", lambda: True)
    monkeypatch.setattr(llm, "_parse", sahte)
    g = {"course_id": cid, "soru": "5+7 kaçtır?", "dogru_cevap": "12", "ogrenci_cevabi": "13", "konu": "Toplama", "kaynak": "s.1"}
    r = client.post("/api/calis/hata", json=g).json()
    assert r["yeni"] is True
    liste = client.get(f"/api/calis/hatalar?course_id={cid}").json()
    h = liste["hatalar"][0]
    assert h["tur"] == "islem_hatasi" and h["oneri"] == "İşlemleri yeniden yap"  # arka plan görevi bitti
    assert liste["gruplar"][0]["konu"] == "Toplama"
    r2 = client.post("/api/calis/hata", json=g).json()
    assert r2["yeni"] is False and r2["hata"]["sayac"] == 2
    # arşivle -> listeden çıkar, arşiv listesinde görünür
    client.post(f"/api/calis/hata/{h['id']}/arsiv")
    assert client.get(f"/api/calis/hatalar?course_id={cid}").json()["hatalar"] == []
    assert len(client.get(f"/api/calis/hatalar?course_id={cid}&arsiv=1").json()["hatalar"]) == 1
    assert client.post("/api/calis/hata", json={"soru": "  "}).status_code == 400


def test_analiz_hatasi_kaydi_bozmaz(client, monkeypatch):
    async def patla(*a, **k):
        raise llm.TutorError("model yok")

    monkeypatch.setattr(llm, "ai_hazir", lambda: True)
    monkeypatch.setattr(llm, "_parse", patla)
    client.post("/api/calis/hata", json={"soru": "Soru?", "dogru_cevap": "A"})
    h = client.get("/api/calis/hatalar").json()["hatalar"][0]
    assert h["tur"] == ""


# ---------------------------------------------------------------- kartlar
def test_aralikli_tekrar_zamanlamasi():
    d0 = date(2026, 1, 1)
    d = calis.sm2(None, "kolay", d0)
    assert d["aralik"] == 3 and d["sonraki"] == "2026-01-04"
    d = calis.sm2(d, "kolay", d0)
    assert d["aralik"] == 7
    d = calis.sm2(d, "zor", d0)
    assert d["aralik"] == 7  # zor: aynı basamak
    d = calis.sm2(d, "bilemedim", d0)
    assert d["aralik"] == 1 and d["basarisiz"] == 1
    d = {"idx": 4}
    assert calis.sm2(d, 2, d0)["aralik"] == 30  # üst sınır
    assert calis.sm2(None, "zor", d0)["aralik"] == 1


def test_kartlar_kaynaklardan_gelir_ve_tekrar_gunune_gore_listelenir(client, monkeypatch):
    cid = _ders()
    c = notes.get_course(cid)
    c["docs"] = [{"id": "d1", "name": "1.DERS", "pages": [], "hazir": {"baslik": "Kalite", "kavramlar": [{"terim": "PUKÖ", "tanim": "Planla-Uygula-Kontrol-Önlem", "sayfa": 2}]}}]
    c["formula_sheet"] = {"title": "F", "sections": [{"title": "EOQ", "items": [{"name": "EOQ", "tex": "\\sqrt{2DS/H}", "note": "Optimum parti"}]}]}
    notes.save_course(c)
    client.post("/api/calis/hata", json={"course_id": cid, "soru": "PUKÖ nedir?", "dogru_cevap": "Deming döngüsü", "konu": "Kalite"})
    r = client.get(f"/api/calis/kartlar?course_id={cid}").json()
    kaynaklar = {k["kaynak"] for k in r["kartlar"]}
    assert kaynaklar == {"hata", "kavram", "formul"} and r["bugun_tekrar"] == 3
    assert r["kartlar"][0]["kaynak"] == "hata"  # hatalar önce
    kid = next(k["id"] for k in r["kartlar"] if k["kaynak"] == "kavram")
    assert client.post(f"/api/calis/kart/{kid}/cevap", json={"puan": "kolay", "course_id": cid}).json()["aralik_gun"] == 3
    assert client.get(f"/api/calis/kartlar?course_id={cid}").json()["bugun_tekrar"] == 2
    # 3 gün sonra yeniden çıkar
    monkeypatch.setattr(calis, "_bugun", lambda: date.today() + timedelta(days=3))
    r = client.get(f"/api/calis/kartlar?course_id={cid}").json()
    assert any(k["id"] == kid for k in r["kartlar"]) and r["tekrar"] == 1
    assert client.post(f"/api/calis/kart/{kid}/cevap", json={"puan": "x"}).status_code == 400
    o = client.get(f"/api/calis/ozet?course_id={cid}").json()
    assert o["hata_sayisi"] == 1 and "bugun_tekrar_kart" in o


def test_ozel_kart_eklenir_tekrarsiz(client):
    cid = _ders()
    k = {"kartlar": [{"on": "Soru", "arka": "Cevap"}, {"on": "", "arka": "x"}], "course_id": cid}
    assert client.post("/api/calis/kartlar/ekle", json=k).json()["eklenen"] == 1
    assert client.post("/api/calis/kartlar/ekle", json=k).json()["eklenen"] == 0
    assert [x["kaynak"] for x in client.get(f"/api/calis/kartlar?course_id={cid}").json()["kartlar"]] == ["ozet"]


# ---------------------------------------------------------------- simülasyon
ESKI = {"baslik": "Deneme 1", "bolum1_dy": [{"ifade": "Kalite ölçülemez.", "cevap": "Y", "aciklama": "Ölçülebilir", "kaynak": "1.DERS s.3"}],
        "bolum2_coktan": [{"soru": "PUKÖ'nün P'si?", "siklar": ["A) Planla", "B) Pişir"], "cevap": "A", "kaynak": "1.DERS s.4"}],
        "bolum4_klasik": [{"soru": "Kaliteyi tanımla.", "ornek_cevap": "Amaca uygunluk"}]}
YENI = {"baslik": "Deneme 2", "bolumler": [{"baslik": "Test", "tur": "coktan", "sorular": [{"soru": "2+2?", "siklar": ["3", "4"], "cevap": "B"}]}]}


def test_deneme_sorulari_eski_ve_yeni_sema():
    q = calis.deneme_sorulari(ESKI, "Kalite")
    assert [x["tur"] for x in q] == ["dy", "coktan", "acik"]
    assert q[0]["dogru"] == "Y" and q[1]["dogru"] == "A" and q[1]["siklar"] == ["Planla", "Pişir"] and q[0]["konu"] == "1.DERS"
    assert calis.deneme_sorulari(YENI, "Kalite")[0]["cevap_metni"] == "B) 4"


def test_simulasyon_puanlama_ve_hatalara_ekleme(client):
    cid = _ders()
    c = notes.get_course(cid)
    c["denemeler"] = [ESKI, YENI]
    notes.save_course(c)
    k = client.get(f"/api/calis/simulasyon/kaynaklar?course_id={cid}").json()
    assert [d["soru_sayisi"] for d in k["denemeler"]] == [3, 1]
    s = client.get(f"/api/calis/simulasyon/sorular?course_id={cid}&index=0").json()
    assert len(s["sorular"]) == 3
    cev = [
        {"soru": "q1", "tur": "dy", "ogrenci": "D", "dogru": "Y", "cevap_metni": "Y", "konu": "A"},  # yanlış
        {"soru": "q2", "tur": "coktan", "ogrenci": "a", "dogru": "A", "cevap_metni": "A) x", "konu": "B"},  # doğru
        {"soru": "q3", "tur": "acik", "ogrenci": "yazdım", "puan": 0.5, "cevap_metni": "örnek", "konu": "A"},  # yarım
        {"soru": "q4", "tur": "coktan", "ogrenci": "", "dogru": "B", "cevap_metni": "B) y", "konu": "C"},  # boş
    ]
    r = client.post("/api/calis/simulasyon/puanla", json={"course_id": cid, "cevaplar": cev, "sure_sn": 100}).json()
    assert r["puan"] == 37.5 and (r["dogru"], r["yanlis"], r["bos"]) == (2, 1, 1)
    assert (r["konular"][0]["konu"], r["konular"][0]["kayip"]) == ("A", 37.5) and r["konular"][1]["kayip"] == 25.0
    assert r["hata_eklendi"] == 2  # yanlış (q1) + boş (q4); q3 yarım puanla geçer
    assert len(client.get(f"/api/calis/hatalar?course_id={cid}").json()["hatalar"]) == 2
    assert client.get(f"/api/calis/ozet?course_id={cid}").json()["son_simulasyon"]["puan"] == r["puan"]


def test_puanlama_saf():
    c = [calis.SimCevap(soru="a", tur="dy", ogrenci="T", dogru="D", konu="x"), calis.SimCevap(soru="b", tur="dy", ogrenci="Y", dogru="D", konu="y")]
    r = calis.sim_puanla(c)  # T = Doğru (D) kabul edilir
    assert r["puan"] == 50.0 and r["konular"][0]["konu"] == "y"


# ---------------------------------------------------------------- hesap + dosyalar
def test_hesap_arac_listesi_ve_cozum(client):
    a = client.get("/api/calis/hesap/araclar").json()["araclar"]
    assert {x["ad"] for x in a} == set(hesap.ARACLAR) and all("properties" in x["sema"] for x in a)
    r = client.post("/api/calis/hesap", json={"arac": "eoq", "girdi": calis_dosya.ORNEKLER["eoq"]}).json()
    assert round(r["sayilar"]["EOQ"], 2) == 632.46 and r["adimlar"]
    assert client.post("/api/calis/hesap", json={"arac": "eoq", "girdi": {}}).status_code == 400
    assert client.post("/api/calis/hesap", json={"arac": "yok", "girdi": {}}).status_code == 400


def test_her_ornek_calisir_ve_dosya_uretir():
    assert set(calis_dosya.ORNEKLER) == set(hesap.ARACLAR)
    for ad, g in calis_dosya.ORNEKLER.items():
        s = hesap.calistir(ad, g)
        wb = openpyxl.load_workbook(io.BytesIO(calis_dosya.excel_uret(ad, g, s)))
        assert "Girdiler" in wb.sheetnames and "Sonuç" in wb.sheetnames
        compile(calis_dosya.python_uret(ad, g, s), f"{ad}.py", "exec")


def test_excel_lp_solver_yerlesimi_ve_formuller(client):
    g = calis_dosya.ORNEKLER["dogrusal_programlama"]
    r = client.post("/api/calis/indir/xlsx", json={"arac": "dogrusal_programlama", "girdi": g})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and "attachment" in r.headers["content-disposition"]
    ws = openpyxl.load_workbook(io.BytesIO(r.content))["Model"]
    assert ws["B6"].value == "=SUMPRODUCT(B4:C4,B5:C5)"
    assert (ws["B4"].value, ws["C4"].value) == (2, 6)  # bulunan optimum, değiştirilecek hücreler
    assert ws["D9"].value == "=SUMPRODUCT($B$4:$C$4,B9:C9)" and ws["E9"].value == "<=" and ws["F9"].value == 4
    metin = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "SOLVER" in metin and "$B$6" in metin


def test_excel_kapali_formuller():
    for ad, beklenen in (("eoq", "=SQRT(2*B4*B5/B6)"), ("kuyruk", "=B6/B5"), ("cpm", "=MAX(E4)")):
        g = calis_dosya.ORNEKLER[ad]
        ws = openpyxl.load_workbook(io.BytesIO(calis_dosya.excel_uret(ad, g, hesap.calistir(ad, g))))["Model"]
        assert any(c.value == beklenen for row in ws.iter_rows() for c in row), ad
    g = calis_dosya.ORNEKLER["kontrol_karti"]
    ws = openpyxl.load_workbook(io.BytesIO(calis_dosya.excel_uret("kontrol_karti", g, hesap.calistir("kontrol_karti", g))))["Model"]
    assert any(isinstance(c.value, str) and c.value.startswith("=AVERAGE(") for row in ws.iter_rows() for c in row)


def _calistir(kod: str) -> str:
    r = subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_python_dosyalari_calisir_ve_sonuc_ayni(client):
    for ad in ("dogrusal_programlama", "ulastirma", "atama", "eoq", "kuyruk", "cpm", "johnson"):
        g = calis_dosya.ORNEKLER[ad]
        r = client.post("/api/calis/indir/py", json={"arac": ad, "girdi": g})
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        cikti = _calistir(r.content.decode("utf-8"))
        s = hesap.calistir(ad, g)
        if ad == "dogrusal_programlama":
            assert f"z* = {s.sayilar['z']:.4f}" in cikti
        elif ad == "ulastirma":
            assert f"Toplam maliyet = {s.sayilar['toplam_maliyet']:.4f}" in cikti
        elif ad == "atama":
            assert f"Toplam = {s.sayilar['toplam']:.4f}" in cikti
        elif ad == "eoq":
            assert f"EOQ = {s.sayilar['EOQ']:.4f}" in cikti
        elif ad == "kuyruk":
            assert f"L = {s.sayilar['L']:.4f}" in cikti
        elif ad == "cpm":
            assert f"Proje süresi = {s.sayilar['proje_suresi']:.2f}" in cikti
    # GET ile de indirilebilir; bilinmeyen biçim 404
    assert client.get("/api/calis/indir/py", params={"arac": "eoq", "girdi": '{"talep_yillik":100,"siparis_maliyeti":10,"elde_tutma":2}'}).status_code == 200
    assert client.get("/api/calis/indir/pdf", params={"arac": "eoq"}).status_code == 404


# ---------------------------------------------------------------- özet kartı
def _oturum(cid):
    s = store.new_session(cid, "Kuyruk teorisi")
    s["timeline"] = [
        {"type": "user", "text": "kuyruğu anlat"},
        {"type": "step", "idx": 0, "say": "Önce kuyruk modelini tanıyalım.", "board": [{"op": "title", "text": "M/M/1 kuyruk"}]},
        {"type": "step", "idx": 1, "say": "Kullanım oranı önemli.", "board": [{"op": "write", "text": "Kullanım $\\rho=\\lambda/\\mu$ olmalı < 1"}, {"op": "math", "tex": "L=\\frac{\\rho}{1-\\rho}"}]},
        {"type": "step", "idx": 2, "say": "Bekleme süresi.", "board": [{"op": "title", "text": "Bekleme süresi"}, {"op": "write", "text": "$W_q=\\rho/(\\mu-\\lambda)$ hesaplanır"}]},
    ]
    store.save_session(s)
    return s["id"]


def test_ozet_karti_kural_tabanli_yedek(client):
    sid = _oturum(_ders())
    r = client.post("/api/calis/ozet-karti", json={"session_id": sid}).json()
    assert r["kaynak"] == "kural" and r["baslik"] == "M/M/1 kuyruk"
    assert "L=\\frac{\\rho}{1-\\rho}" in r["formuller"] and "Bekleme süresi" in r["anahtar_kavramlar"]
    assert r["ozet_maddeleri"] and r["kontrol_sorusu"]
    assert client.post("/api/calis/ozet-karti", json={"session_id": "0" * 12}).status_code == 404


def test_ozet_karti_yapay_zekali(client, monkeypatch):
    sid = _oturum(_ders())
    gelen = {}

    async def sahte(model, content, system=None, effort=None, max_tokens=0):
        gelen["c"] = content
        return calis.OzetKarti(baslik="Kuyruk", anahtar_kavramlar=["ρ"], formuller=["L=\\rho"], ozet_maddeleri=["m1"], kontrol_sorusu="ρ nedir?", cevap="kullanım")

    monkeypatch.setattr(llm, "ai_hazir", lambda: True)
    monkeypatch.setattr(llm, "_parse", sahte)
    r = client.post("/api/calis/ozet-karti", json={"session_id": sid}).json()
    assert r["kaynak"] == "yapay_zeka" and r["baslik"] == "Kuyruk" and "M/M/1 kuyruk" in gelen["c"]

    async def patla(*a, **k):
        raise llm.TutorError("yok")

    monkeypatch.setattr(llm, "_parse", patla)  # yapay zeka hata verirse yedeğe düşer
    calis._OZET_ONBELLEK.clear()
    assert client.post("/api/calis/ozet-karti", json={"session_id": sid}).json()["kaynak"] == "kural"


def test_ozet_karti_sira_zaman_asimi_kurala_duser_ve_onbellekler(client, monkeypatch):
    sid = _oturum(_ders())
    monkeypatch.setattr(llm, "ai_hazir", lambda: True)
    monkeypatch.setattr(calis, "OZET_SIRA_SN", 0.05)
    cagri = {"sira": 0, "parse": 0}

    async def takili():
        cagri["sira"] += 1
        await asyncio.sleep(30)

    async def parse(*a, **k):
        cagri["parse"] += 1
        raise AssertionError("sıra dolmadan yapay zeka çağrılmamalı")

    monkeypatch.setattr(llm, "arka_plan_sirasi", takili)
    monkeypatch.setattr(llm, "_parse", parse)
    r = client.post("/api/calis/ozet-karti", json={"session_id": sid}).json()
    assert r["kaynak"] == "kural" and cagri["parse"] == 0
    # aynı (oturum, timeline uzunluğu) için ikinci istek önbellekten gelir
    assert client.post("/api/calis/ozet-karti", json={"session_id": sid}).json() == r
    assert cagri["sira"] == 1


def test_ozet_karti_es_zamanli_istekler_tek_uretim(client, monkeypatch):
    sid = _oturum(_ders())
    monkeypatch.setattr(llm, "ai_hazir", lambda: True)
    n = {"c": 0}

    async def sira():
        return None

    async def parse(model, content, system=None, effort=None, max_tokens=0):
        n["c"] += 1
        await asyncio.sleep(0.2)
        return calis.OzetKarti(baslik="K", anahtar_kavramlar=[], formuller=[], ozet_maddeleri=["m"], kontrol_sorusu="q", cevap="a")

    monkeypatch.setattr(llm, "arka_plan_sirasi", sira)
    monkeypatch.setattr(llm, "_parse", parse)

    async def calistir():
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            return await asyncio.gather(*[c.post("/api/calis/ozet-karti", json={"session_id": sid}) for _ in range(3)])

    sonuc = asyncio.run(calistir())
    assert all(r.status_code == 200 and r.json()["baslik"] == "K" for r in sonuc)
    assert n["c"] == 1


# ---------------------------------------------------------------- CPM geri geçiş sırası
def test_cpm_python_sifir_sureli_tas_ve_esit_ef():
    g = {"faaliyetler": [
        {"ad": "A", "sure": 3, "onculler": []},
        {"ad": "KT", "sure": 0, "onculler": ["A"]},       # 0 süreli kilometre taşı: EF eşitliği
        {"ad": "B", "sure": 4, "onculler": ["KT"]},
        {"ad": "C", "sure": 2, "onculler": ["KT"]},
        {"ad": "D", "sure": 1, "onculler": ["B", "C"]},
    ]}
    s = hesap.calistir("cpm", g)
    cikti = _calistir(calis_dosya.python_uret("cpm", g, s))
    assert f"Proje süresi = {s.sayilar['proje_suresi']:.2f}" in cikti
    satirlar = {l.split(":")[0]: l for l in cikti.splitlines() if "bolluk" in l}
    assert "LS 3.00 LF 3.00 bolluk 0.00" in satirlar["KT"]
    assert "LS 5.00 LF 7.00 bolluk 2.00" in satirlar["C"]


# ---------------------------------------------------------------- hesap uçları (iş parçacığı + süre sınırı)
def test_hesap_ucu_zaman_asimi_504(client, monkeypatch):
    import time as _t
    monkeypatch.setattr(calis, "HESAP_SURE_SN", 0.1)
    monkeypatch.setattr(hesap, "calistir", lambda ad, g: (_t.sleep(0.5), None)[1])
    r = client.post("/api/calis/hesap", json={"arac": "eoq", "girdi": {}})
    assert r.status_code == 504 and "saniyede bitmedi" in r.json()["detail"]
    r = client.post("/api/calis/indir/xlsx", json={"arac": "eoq", "girdi": {}})
    assert r.status_code == 504


# ---------------------------------------------------------------- simülasyon: bankadan 30 soru
def test_banka_sorulari_20den_fazla(monkeypatch):
    c = {"id": "d1", "name": "Kalite"}
    kayitlar = [{"dogrulandi": True, "ders_id": "d1", "tur": "coktan", "soru": f"s{i}", "siklar": ["a", "b", "c"], "cevap": "b",
                 "kaynak": {"baslik": "Kitap", "sayfa": i}} for i in range(35)]
    monkeypatch.setattr(calisma_mod(), "banka", lambda: kayitlar)
    assert len(calis.banka_sorulari(c, 30)) == 30
    q = calis.banka_sorulari(c, 5)[0]
    assert q["tur"] == "coktan" and q["siklar"][ord(q["dogru"]) - 65] == "b"


def calisma_mod():
    from app import calisma
    return calisma


# ---------------------------------------------------------------- depolama: bozuk / okunamayan dosya
def test_oku_bozuk_dosya_yedeklenir_ve_bos_doner(client):
    p = calis._yol("hatalar.json")
    p.write_text("{bozuk", "utf-8")
    assert calis._oku("hatalar.json", []) == []
    assert not p.exists()
    yedekler = list(p.parent.glob("hatalar.json.bozuk-*"))
    assert len(yedekler) == 1 and yedekler[0].read_text("utf-8") == "{bozuk"
    assert calis._oku("yok.json", {"x": 1}) == {"x": 1}  # dosya yoksa varsayılan


def test_oku_gecici_oserror_yeniden_dener_sonra_503(client, monkeypatch):
    from pathlib import Path
    p = calis._yol("hatalar.json")
    p.write_text("[1]", "utf-8")
    gercek = Path.read_text
    n = {"c": 0}

    def sahte(self, *a, **k):
        if self.name == "hatalar.json":
            n["c"] += 1
            if n["c"] < 3:
                raise PermissionError("geçici")
        return gercek(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", sahte)
    assert calis._oku("hatalar.json", []) == [1] and n["c"] == 3

    def hep(self, *a, **k):
        if self.name == "hatalar.json":
            raise PermissionError("kalıcı")
        return gercek(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", hep)
    r = client.get("/api/calis/hatalar?course_id=")
    assert r.status_code == 503 and "okunam" in r.json()["detail"]
    monkeypatch.setattr(Path, "read_text", gercek)
    assert json.loads(p.read_text("utf-8")) == [1]  # dosya ezilmedi
