"""Uygulamanın kendi ders paketini üretmesi (app/paket.py): yapay zeka sahte cevaplarla değiştirilir."""
import asyncio
import io
import json
import re
import time
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import fakes
from app import llm, main, notes, paket
from conftest import make_text_pdf

fakes.install()

UZUN = "Kalite yonetimi surekli iyilestirme ister ve musteri odaklidir. " * 60  # ~3800 karakter


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


class Sahte:
    """llm._parse yerine geçer: şema sınıfına ve talimata göre küçük, geçerli cevaplar döndürür."""

    def __init__(self, hata_deneme_cagrisi: int | None = None):
        self.calls: list[tuple[str, str]] = []
        self.hata = hata_deneme_cagrisi
        self.deneme = 0

    def say(self, ad: str) -> int:
        return sum(1 for c, _ in self.calls if c == ad)

    async def __call__(self, cls, content, system=None, effort=None, max_tokens=16000):
        text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content)
        ad = cls.__name__
        self.calls.append((ad, text))
        if ad == "ParcaOzet":
            belge = re.search(r"'(.+?)' belgesinin", text).group(1)
            i = re.search(r"(\d+)/\d+\. parçası", text).group(1)
            return paket.ParcaOzet(baslik=f"{belge} konusu", ozet=f"{belge} parça {i} özeti",
                                   bolumler=[paket.PBolum(baslik=f"Bölüm {i}", sayfalar=i, ozet="kısa")],
                                   kavramlar=[paket.PKavram(terim=f"{belge} terimi", tanim="tanımı", sayfa=1),
                                              paket.PKavram(terim=f"Parça {i} terimi", tanim="tanım", sayfa=int(i))],
                                   olasi_sorular=[f"{belge} nedir?"])
        if ad == "BelgeOzet":
            belge = re.search(r"'(.+?)' belgesinin", text).group(1)
            return paket.BelgeOzet(baslik=f"{belge} (birleşik)", ozet="birleşik özet",
                                   bolumler=[paket.PBolum(baslik="Hepsi", sayfalar="1-2", ozet="tümü")],
                                   olasi_sorular=["Genel soru?"])
        if ad == "LecturePlan":
            return llm.LecturePlan(title="Üretilen plan", sections=[
                llm.LectureSection(title="Giriş", summary="kalite", pages=["hafta1 s.1"])])
        if ad == "Metin":
            if "SINAV REHBERİ" in text:
                return paket.Metin(metin="- PUKÖ döngüsünü ezberle")
            if "KONU ANLATIMI" in text:
                belge = re.search(r"'(.+?)' belgesi için", text).group(1)
                m = re.search(r"belgenin (\d+)/\d+\. parçası", text)
                ek = f" (parça {m.group(1)})" if m else ""
                return paket.Metin(metin=f"### {belge} ana konu{ek}\n**Tanım**: ...\n**Sınavda nasıl sorulabilir:** ...")
            if "KISA SINAV ÖZETİ" in text:
                sablon = "\n## Klasik soru şablonu\n tanım → maddeler" if "Klasik soru şablonu" in text else ""
                return paket.Metin(metin="## Özet\n- kısa" + sablon)
        if ad == "Deneme":
            self.deneme += 1
            if self.hata == self.deneme:
                raise llm.TutorError("Yerel yapay zeka şu an çalışmıyor")
            if "DENETLE" in text:
                x = json.loads(re.search(r"<deneme>\n(.*)\n</deneme>", text, re.S).group(1))
                for b in x["bolumler"]:
                    for q in b["sorular"]:
                        q["aciklama"] += " (denetlendi)"
                return paket.Deneme.model_validate(x)
            return _ham_deneme(int(re.search(r"(\d+)\. DENEME SINAVINI", text).group(1)))
        raise AssertionError(f"beklenmeyen şema {ad}")


def _soru(**kw):
    base = dict(soru="", siklar=[], cevap="", aciklama="", ornek_cevap="", puanlama="", kaynak="hafta1 s.1")
    return paket.DSoru(**(base | kw))


def _ham_deneme(i: int) -> paket.Deneme:
    mc = [_soru(soru=f"Test sorusu {k}", siklar=[f"doğru {k}", "yanlış 1", "yanlış 2", "yanlış 3"], cevap="A",
                aciklama="Doğru cevap A; B şıkkı çeldiricidir.") for k in range(4)]
    return paket.Deneme(baslik=f"Deneme {i}", aciklama="", bolumler=[
        paket.DBolum(baslik="Doğru / Yanlış", tur="dy", yonerge="", metin="yok sayılmalı",
                     sorular=[_soru(soru="PUKÖ dört adımdır.", cevap="Doğru"), _soru(soru="Kalite ölçülemez.", cevap="yanlış")]),
        paket.DBolum(baslik="Test", tur="coktan", yonerge="", metin="", sorular=mc),
        paket.DBolum(baslik="Klasik", tur="klasik", yonerge="", metin="",
                     sorular=[_soru(soru="PUKÖ'yü açıklayınız.", ornek_cevap="Planla...", puanlama="4x5")]),
    ])


@pytest.fixture()
def sahte(monkeypatch):
    s = Sahte()
    ocr = []

    async def fake_ocr(png):
        ocr.append(len(png))
        return "Fotograftan okunan not: PUKO dongusu planla uygula kontrol et onlem al."

    monkeypatch.setattr(llm, "_parse", s)
    monkeypatch.setattr(llm, "ocr_page", fake_ocr)
    monkeypatch.setattr(llm, "notes_limit", lambda: 8000)
    s.ocr = ocr
    return s


def _ders() -> str:
    c = notes.create_course("Kalite Yönetimi")
    notes.add_document(c["id"], "defter.png", _png())  # taranmış sayfa → OCR
    notes.add_document(c["id"], "hafta1.pdf", make_text_pdf([UZUN, UZUN]))  # iki parçaya bölünür
    return c["id"]


def _calistir(cid: str, **kw) -> dict:
    async def run():
        paket.baslat(cid, **kw)
        await paket.bekle(cid)

    asyncio.run(run())
    return notes.get_course(cid)


def test_tam_uretim(sahte):
    cid = _ders()
    c = _calistir(cid, deneme_sayisi=2)
    assert c["paket_is"]["durum"] == "bitti", c["paket_is"]
    assert c["paket_is"]["ilerleme"] == 1.0
    assert len(sahte.ocr) == 1 and not c["docs"][0]["pages"][0]["needs_ocr"]
    assert "PUKO" in c["docs"][0]["pages"][0]["text"]
    # belge özetleri: tek parçalı belge doğrudan, iki parçalı belge birleştirilerek
    assert sahte.say("ParcaOzet") == 3 and sahte.say("BelgeOzet") == 1
    h0, h1 = c["docs"][0]["hazir"], c["docs"][1]["hazir"]
    assert h0["paket"] == "uretilen" and h0["imza"] == paket.belge_imzasi(c["docs"][0])
    assert h1["baslik"] == "hafta1 (birleşik)"
    assert {k["terim"] for k in h1["kavramlar"]} == {"hafta1 terimi", "Parça 1 terimi", "Parça 2 terimi"}  # tekrarsız
    # ders düzeyi çıktılar
    assert c["lecture_plan"]["title"] == "Üretilen plan" and c["lecture_plan"]["uretilen"]
    assert "PUKÖ" in c["sinav_rehberi"]
    assert "## defter" in c["konu_anlatimi"] and "## hafta1" in c["konu_anlatimi"] and "Sınavda nasıl sorulabilir" in c["konu_anlatimi"]
    assert "Klasik soru şablonu" in c["kisa_ozet"]  # varsayılan formatta klasik soru var
    # denemeler: 2 üretim + 2 denetim, biçim düzeltilmiş ve şıklar dengelenmiş
    assert sahte.say("Deneme") == 4
    assert [x["baslik"] for x in c["denemeler"]] == ["Deneme 1", "Deneme 2"]
    x = c["denemeler"][0]
    assert x["uretilen"] and "_denetlendi" not in x
    dy, mc, kl = x["bolumler"]
    assert [q["cevap"] for q in dy["sorular"]] == ["D", "Y"] and dy["metin"] == ""
    assert sorted(q["cevap"] for q in mc["sorular"]) == ["A", "B", "C", "D"]
    for q in mc["sorular"]:
        i = "ABCD".index(q["cevap"])
        assert q["siklar"][i].startswith(f"{q['cevap']}) doğru")
        assert q["aciklama"].startswith(f"Doğru cevap {q['cevap']};") and q["aciklama"].endswith("(denetlendi)")
    # hoca, üretilen özetleri sistem talimatında görür
    from app import hazir
    assert "hafta1 (birleşik)" in hazir.course_guide(c) and "SINAV REHBERİ" in hazir.course_guide(c)
    # ikinci deneme, ilk denemenin sorularını tekrarlamaması için uyarılır
    uretim = [t for a, t in sahte.calls if a == "Deneme" and "DENETLE" not in t]
    assert "Test sorusu 0" in uretim[1] and "TEKRARLAMA" in uretim[1]


def test_artimli_ikinci_calisma(sahte):
    cid = _ders()
    _calistir(cid)
    sahte.calls.clear()
    # değişiklik yok: hiçbir şey yeniden üretilmez
    c = _calistir(cid)
    assert sahte.calls == [] and c["paket_is"]["durum"] == "bitti"
    # yeni belge: yalnızca o belge özetlenir, ders düzeyi çıktılar yeniden üretilir
    notes.add_document(cid, "hafta2.pdf", make_text_pdf(["Toplam kalite yonetimi ilkeleri: musteri odaklilik, surekli iyilestirme."]))
    c = _calistir(cid)
    assert sahte.say("ParcaOzet") == 1 and sahte.say("BelgeOzet") == 0 and not sahte.ocr[1:]
    assert sahte.say("LecturePlan") == 1 and sahte.say("Deneme") == 4
    assert "## hafta2" in c["konu_anlatimi"] and c["docs"][2]["hazir"]["paket"] == "uretilen"
    # baştan üret: değişmemiş belgeler de yeniden özetlenir
    sahte.calls.clear()
    _calistir(cid, yeniden=True)
    assert sahte.say("ParcaOzet") == 4


def test_yarida_hata_ve_devam(sahte):
    cid = _ders()
    sahte.hata = 4  # 2. denemenin denetimi sırasında yapay zeka düşer
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "hata" and "Yerel yapay zeka" in c["paket_is"]["hata"]
    assert "kaldığı yerden" in c["paket_is"]["hata"]
    assert c["lecture_plan"]["title"] == "Üretilen plan" and c["konu_anlatimi"] and c["kisa_ozet"]  # kısmi sonuçlar korunur
    assert all(d["hazir"]["paket"] == "uretilen" for d in c["docs"])
    assert "denemeler" not in c and len(c["paket_ara"]["denemeler"]) == 2
    # tekrar: yalnızca eksik kalan denetim yapılır
    sahte.hata, sahte.deneme = None, 0
    sahte.calls.clear()
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "bitti"
    assert [a for a, _ in sahte.calls] == ["Deneme"] and "DENETLE" in sahte.calls[0][1]
    assert len(c["denemeler"]) == 2


def test_parca_ozetinde_hata_sonra_devam(sahte, monkeypatch):
    cid = _ders()
    asil = sahte.__call__

    async def bozuk(cls, *a, **kw):
        if cls is paket.ParcaOzet and sahte.say("ParcaOzet") == 2:  # hafta1'in ikinci parçası
            sahte.calls.append(("ParcaOzet", ""))
            raise llm.TutorError("bağlantı koptu")
        return await asil(cls, *a, **kw)

    monkeypatch.setattr(llm, "_parse", bozuk)
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "hata"
    assert c["docs"][0]["hazir"]["paket"] == "uretilen" and "hazir" not in c["docs"][1]
    assert len(c["paket_ara"]["parcalar"][c["docs"][1]["id"]]["ozetler"]) == 1  # ilk parça diskte
    monkeypatch.setattr(llm, "_parse", sahte)
    sahte.calls.clear()
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "bitti"
    assert sahte.say("ParcaOzet") == 1 and sahte.say("BelgeOzet") == 1  # yalnızca kalan parça + birleştirme


def test_hazir_paketten_gelenlere_dokunulmaz(sahte):
    c = notes.create_course("Kalite")
    cid = c["id"]
    notes.add_document(cid, "hafta1.pdf", make_text_pdf(["Kalite kavrami musteri beklentilerini karsilama derecesidir."]))
    notes.add_document(cid, "paketli.pdf", make_text_pdf(["Deming dongusu: planla, uygula, kontrol et, onlem al ve tekrarla."]))
    c = notes.get_course(cid)
    c["docs"][1]["hazir"] = {"paket": "enm463", "baslik": "Paket", "ozet": "hazır özet", "bolumler": [], "kavramlar": [],
                             "olasi_sorular": []}
    c["lecture_plan"] = {"title": "Hazır plan", "sections": [], "hazir": True}
    c["sinav_rehberi"] = "- paketin rehberi"
    c["denemeler"] = [{"baslik": "Paket denemesi", "bolum1_dy": []}]
    notes.save_course(c)
    c = _calistir(cid, deneme_sayisi=1)
    assert sahte.say("ParcaOzet") == 1 and sahte.say("LecturePlan") == 0
    assert c["docs"][1]["hazir"]["paket"] == "enm463"
    assert c["lecture_plan"]["title"] == "Hazır plan" and c["sinav_rehberi"] == "- paketin rehberi"
    assert [x["baslik"] for x in c["denemeler"]] == ["Paket denemesi", "Deneme 1"]
    # baştan üretince plan ve rehber de yenilenir; paketin denemesi yine kalır
    c = _calistir(cid, deneme_sayisi=1, yeniden=True)
    assert c["lecture_plan"]["title"] == "Üretilen plan" and "PUKÖ" in c["sinav_rehberi"]
    assert [x["baslik"] for x in c["denemeler"]] == ["Paket denemesi", "Deneme 1"]


def test_sik_dengeleme_cevap_ve_aciklama_birlikte_degisir():
    sorular = [{"soru": f"S{k}", "siklar": [f"A) dogru{k}", "B) y1", "C) y2", "D) y3", "E) y4"], "cevap": "A",
                "aciklama": "Doğru cevap A şıkkıdır; B ve C çeldiricidir. A kümesi tanımı."} for k in range(10)]
    x = paket.sik_dengele({"bolumler": [{"tur": "coktan", "sorular": sorular}]}, seed=3)
    say = Counter(q["cevap"] for q in x["bolumler"][0]["sorular"])
    assert set(say) == set("ABCDE") and set(say.values()) == {2}
    for k, q in enumerate(x["bolumler"][0]["sorular"]):
        h = q["cevap"]
        i = "ABCDE".index(h)
        assert q["siklar"][i] == f"{h}) dogru{k}"
        assert [s[0] for s in q["siklar"]] == list("ABCDE")
        assert q["aciklama"].startswith(f"Doğru cevap {h} şıkkıdır;")
        assert q["aciklama"].endswith("A kümesi tanımı.")  # şık atfı olmayan harf değişmez
        eski = {"B": "B", "C": "C"} | ({"B": "A"} if h == "B" else {}) | ({"C": "A"} if h == "C" else {})
        assert f"{eski['B']} ve {eski['C']} çeldiricidir" in q["aciklama"]


def test_deneme_duzelt():
    x = paket.deneme_duzelt({"bolumler": [
        {"tur": "dy", "metin": "x", "sorular": [{"soru": "a", "cevap": "Yanlış"}, {"soru": "b", "cevap": "True"}, {"soru": " ", "cevap": "D"}]},
        {"tur": "coktan", "metin": "", "sorular": [{"soru": "c", "siklar": ["a) bir", "(b) iki", "üç"], "cevap": "iki"}]},
    ]})
    dy, mc = x["bolumler"]
    assert [q["cevap"] for q in dy["sorular"]] == ["Y", "D"] and dy["metin"] == ""
    assert mc["sorular"][0]["siklar"] == ["A) bir", "B) iki", "C) üç"] and mc["sorular"][0]["cevap"] == "B"


def test_otomatik_baslatma(sahte, monkeypatch):
    cid = _ders()
    paket.yeni_belge(cid)  # testlerde (DERS_ON_YUKLEME=0) kendiliğinden başlamaz
    assert not paket._zamanlayicilar and "paket_is" not in notes.get_course(cid)
    monkeypatch.setenv("DERS_ON_YUKLEME", "1")
    monkeypatch.setattr(paket, "BEKLEME", 0.05)

    async def run():
        paket.yeni_belge(cid)
        ilk = paket._zamanlayicilar[cid]
        await asyncio.sleep(0)
        paket.yeni_belge(cid)  # süre yenilenir, tek iş başlar
        ikinci = paket._zamanlayicilar[cid]
        await asyncio.sleep(0)
        assert ilk is not ikinci and ilk.cancelled() and not paket._isler  # ilk bekleme iptal edildi
        await ikinci  # sabit süre beklemek yerine zamanlayıcının kendisini bekle (yavaş makinede de güvenilir)
        assert cid in paket._isler
        await paket.bekle(cid)

    asyncio.run(run())
    assert notes.get_course(cid)["paket_is"]["durum"] == "bitti" and sahte.say("LecturePlan") == 1


def test_acilista_yarida_kalan_is():
    c = notes.create_course("Yarım")
    c["paket_is"] = {"durum": "calisiyor", "adim": "Deneme sınavı 1/2 hazırlanıyor", "ilerleme": 0.5}
    notes.save_course(c)
    assert paket.durum(c["id"])["durum"] == "yarida"
    paket.acilista_duzelt()
    assert notes.get_course(c["id"])["paket_is"]["durum"] == "yarida"


def test_uc_noktalar(sahte):
    with TestClient(main.app) as client:
        cid = client.post("/api/courses", json={"name": "Kalite"}).json()["id"]
        assert client.get(f"/api/courses/{cid}/paket").json()["durum"] == "yok"
        assert client.post(f"/api/courses/{cid}/paket", json={}).status_code == 400  # not yok
        pdf = make_text_pdf(["Kalite kavrami musteri beklentilerini karsilama derecesidir.", "PUKO dongusu dort adimdir."])
        assert client.post(f"/api/courses/{cid}/docs", files={"file": ("hafta1.pdf", pdf, "application/pdf")}).status_code == 200
        r = client.post(f"/api/courses/{cid}/sinav-formati", json={"metin": " 10 D/Y, 5 test, 1 klasik "}).json()
        assert r["metin"] == "10 D/Y, 5 test, 1 klasik"
        st = client.post(f"/api/courses/{cid}/paket", json={"deneme_sayisi": 1}).json()
        assert st["durum"] in ("calisiyor", "bitti")
        for _ in range(100):
            st = client.get(f"/api/courses/{cid}/paket").json()
            if st["durum"] != "calisiyor":
                break
            time.sleep(0.05)
        assert st["durum"] == "bitti", st
        course = client.get(f"/api/courses/{cid}").json()
        assert len(course["denemeler"]) == 1 and course["sinav_formati"] == "10 D/Y, 5 test, 1 klasik"
        assert any("10 D/Y, 5 test, 1 klasik" in t for a, t in sahte.calls if a == "Deneme")
        assert client.get("/api/courses/yok123/paket").status_code == 404
        assert client.post("/api/courses/yok123/sinav-formati", json={"metin": "x"}).status_code == 404


# ---------------------------------------------------------------- inceleme bulguları
def test_butce_her_zaman_yerel_modele_sigar(sahte, monkeypatch):
    """Gemini birincilken de (200 bin karakter) iş yerel modelin bütçesiyle çalışır: yerel modele düşülse de istek sığar."""
    monkeypatch.setattr(llm, "notes_limit", lambda: 200000)
    monkeypatch.setattr(llm, "yerel_notes_limit", lambda: 8000)
    assert paket.butce() == 8000
    cid = _ders()
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "bitti"
    assert sahte.say("ParcaOzet") == 3  # 8000'lik bütçeyle hafta1 yine iki parçaya bölünür
    assert all(len(t) < 8000 for a, t in sahte.calls)


def test_butce_degisince_ara_parca_ozetleri_kullanilmaz(sahte, monkeypatch):
    cid = _ders()
    asil = sahte.__call__

    async def bozuk(cls, *a, **kw):
        if cls is paket.ParcaOzet and sahte.say("ParcaOzet") == 2:
            sahte.calls.append(("ParcaOzet", ""))
            raise llm.TutorError("bağlantı koptu")
        return await asil(cls, *a, **kw)

    monkeypatch.setattr(llm, "_parse", bozuk)
    c = _calistir(cid)
    hid = c["docs"][1]["id"]
    assert c["paket_is"]["durum"] == "hata" and c["paket_ara"]["parcalar"][hid]["limit"] == int(8000 * 0.85)
    # daha büyük model: bütçe büyür, hafta1 artık tek parça; eski (yarım) parça özeti yeni parçalara eşlenmemeli
    monkeypatch.setattr(llm, "_parse", sahte)
    monkeypatch.setattr(llm, "notes_limit", lambda: 30000)
    monkeypatch.setattr(llm, "yerel_notes_limit", lambda: 30000)
    sahte.calls.clear()
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "bitti"
    assert sahte.say("ParcaOzet") == 1 and sahte.say("BelgeOzet") == 0
    assert c["docs"][1]["hazir"]["ozet"] == "hafta1 parça 1 özeti"


def test_ozetler_butceyi_asmaz():
    docs = [{"id": f"d{k}", "name": f"foto{k}", "hazir": {"baslik": "b" * 50, "ozet": "o" * 900}} for k in range(60)]
    for lim in (5000, 22000):
        assert len(paket._ozetler({"docs": docs}, lim)) <= lim


def test_uzun_sayfa_kirpilmaz_bolunur():
    doc = {"pages": [{"n": 1, "text": "x" * 25000}]}
    parcalar = paket._sayfa_parcalari(doc, 6000)
    assert len(parcalar) >= 5 and all(len(p) <= 6000 for p in parcalar)
    assert sum(p.count("x") for p in parcalar) == 25000


def test_konu_anlatimi_parca_parca_ve_kaldigi_yerden(sahte, monkeypatch):
    cid = _ders()
    asil = sahte.__call__
    konu = []

    async def bozuk(cls, content, *a, **kw):
        if cls is paket.Metin and "KONU ANLATIMI" in content and "hafta1" in content:
            konu.append(content)
            if len(konu) == 2:  # hafta1'in ikinci parçasında düşer
                raise llm.TutorError("bağlantı koptu")
        return await asil(cls, content, *a, **kw)

    monkeypatch.setattr(llm, "_parse", bozuk)
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "hata"
    kayit = c["paket_ara"]["konu"][c["docs"][1]["id"]]
    assert len(kayit["parcalar"]) == 1 and not kayit["tamam"]
    assert "1/2. parçası" in konu[0] and "YALNIZCA bu parçadaki" in konu[0]
    sahte.calls.clear()
    c = _calistir(cid)
    assert c["paket_is"]["durum"] == "bitti"
    kn = [t for a, t in sahte.calls if a == "Metin" and "KONU ANLATIMI" in t]
    assert len(kn) == 1 and "2/2. parçası" in kn[0]  # yalnızca kalan parça
    assert "hafta1 ana konu (parça 1)" in c["konu_anlatimi"] and "hafta1 ana konu (parça 2)" in c["konu_anlatimi"]
    # uzun belgenin her iki sayfası da konu anlatımına girdi (tek çağrıda sayfalar seçilip atılmıyor)
    assert "[Sayfa 1]" in konu[0] and "[Sayfa 2]" in kn[0]


class SahteBuyuk(Sahte):
    """Büyük format: tüm deneme tek çağrıda 'sığmaz', bölüm bölüm üretilir."""

    def __init__(self):
        super().__init__()
        self.hata_parca: int | None = None

    async def __call__(self, cls, content, system=None, effort=None, max_tokens=16000):
        text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content)
        if cls is paket.DYapi:
            self.calls.append(("DYapi", text))
            return paket.DYapi(bolumler=[
                paket.DYapiBolum(baslik="Doğru/Yanlış", tur="dy", soru_sayisi=3, yonerge="D ya da Y"),
                paket.DYapiBolum(baslik="Test", tur="coktan", soru_sayisi=10, yonerge="tek doğru")])
        if cls is paket.Deneme and "DENETLE" not in text:
            self.calls.append(("Deneme", text))
            m = re.search(r'YALNIZCA ŞU BÖLÜMÜ YAZ.*?"(.+?)" \(tur: "(\w+)"\), bu bölümün (?:(\d+)-(\d+)\. sorularını|(\d+) sorusunu)', text)
            if not m:
                raise llm.TutorError("Yerel yapay zeka: Cevap modelin sınırına sığmadı; kapsamı daraltıp tekrar dene.")
            if self.hata_parca is not None:
                self.hata_parca -= 1
                if self.hata_parca == 0:
                    raise llm.TutorError("bağlantı koptu")
            bas, tur = m.group(1), m.group(2)
            ilk, son = (int(m.group(3)), int(m.group(4))) if m.group(3) else (1, int(m.group(5)))
            sorular = [_soru(soru=f"{bas} sorusu {k}", cevap="D" if tur == "dy" else "A",
                             siklar=[] if tur == "dy" else ["doğru", "y1", "y2", "y3"], aciklama="gerekçe")
                       for k in range(ilk, son + 1)]
            return paket.Deneme(baslik="x", aciklama="", bolumler=[
                paket.DBolum(baslik=bas, tur=tur, yonerge="", metin="", sorular=sorular)])
        return await super().__call__(cls, content, system, effort, max_tokens)


def test_buyuk_deneme_bolum_bolum_uretilir_ve_denetlenir(sahte, monkeypatch):
    s = SahteBuyuk()
    monkeypatch.setattr(llm, "_parse", s)
    monkeypatch.setattr(paket, "_sigar", lambda *a: False)  # bütün deneme denetime sığmıyor → bölüm bölüm
    cid = _ders()
    s.hata_parca = 5  # 2. denemenin 2. parçasında bağlantı kopar (1. deneme: 3 parça)
    c = _calistir(cid, deneme_sayisi=2)
    assert c["paket_is"]["durum"] == "hata"
    assert c["paket_ara"]["bolumlu"] and len(c["paket_ara"]["deneme_parca"]["1"]) == 1  # yarım deneme diskte
    tek = [t for a, t in s.calls if a == "Deneme" and "YALNIZCA ŞU BÖLÜMÜ" not in t and "DENETLE" not in t]
    assert len(tek) == 1  # tek çağrı yalnızca bir kez denendi; sonraki deneme doğrudan bölüm bölüm
    assert s.say("DYapi") == 1
    s.hata_parca, s.calls = None, []
    c = _calistir(cid, deneme_sayisi=2)
    assert c["paket_is"]["durum"] == "bitti", c["paket_is"]
    uretim = [t for a, t in s.calls if a == "Deneme" and "DENETLE" not in t]
    assert len(uretim) == 2 and s.say("DYapi") == 0  # yalnızca kalan iki parça (D/Y bölümü zaten diskteydi)
    assert all("Doğru/Yanlış sorusu 1" in t for t in uretim)  # aynı denemenin önceki bölümleri tekrarlanmasın diye verilir
    for x in c["denemeler"]:
        dy, mc = x["bolumler"]
        assert [q["soru"] for q in dy["sorular"]] == [f"Doğru/Yanlış sorusu {k}" for k in (1, 2, 3)]
        assert [q["soru"] for q in mc["sorular"]] == [f"Test sorusu {k}" for k in range(1, 11)]
        assert all(q["aciklama"].endswith("(denetlendi)") for b in x["bolumler"] for q in b["sorular"])
    denetim = [t for a, t in s.calls if a == "Deneme" and "DENETLE" in t]
    assert len(denetim) == 2  # 2. denemenin 2 bölümü ayrı ayrı (1. deneme ilk çalıştırmada denetlenmişti)
    assert "deneme_parca" not in c["paket_ara"] or not c["paket_ara"]["deneme_parca"]


def test_denetim_bolumu_sigmazsa_bolum_oldugu_gibi_kalir(sahte, monkeypatch):
    asil = sahte.__call__

    async def f(cls, content, *a, **kw):
        if cls is paket.Deneme and "DENETLE" in content and '"tur": "coktan"' in content:
            raise llm.TutorError("Cevap modelin sınırına sığmadı")
        return await asil(cls, content, *a, **kw)

    monkeypatch.setattr(llm, "_parse", f)
    monkeypatch.setattr(paket, "_sigar", lambda *a: False)
    cid = _ders()
    c = _calistir(cid, deneme_sayisi=1)
    assert c["paket_is"]["durum"] == "bitti"  # iş ilerleyebildi, aynı adımda takılı kalmadı
    dy, mc, kl = c["denemeler"][0]["bolumler"]
    assert dy["sorular"][0]["aciklama"].endswith("(denetlendi)") and kl["sorular"][0]["aciklama"].endswith("(denetlendi)")
    assert not any(q["aciklama"].endswith("(denetlendi)") for q in mc["sorular"]) and len(mc["sorular"]) == 4


def test_cikti_tokeni_baglamdan_hesaplanir(monkeypatch):
    from app import yerel
    monkeypatch.setattr(yerel, "baglam", lambda: 16384)
    assert paket._cikti(30000, 12000) == 16384 - 10000 - 256
    assert paket._cikti(3000, 4000) == 4000
    assert paket._cikti(60000, 8000) == 1500  # en az
    assert not paket._sigar(30000, 8000) and paket._sigar(9000, 8000)


def test_sik_dengeleme_sik_olmayan_harflere_dokunmaz():
    perm = {"A": "C", "C": "A"}
    t = paket._harf_degistir("P(A)=0,3 ve P(B)=0,5; cevap A. A'nın tümleyeni; ABC analizinde A ve B sınıfı; (A) doğru, C) yanlış; "
                             "A ve C şıkları; B ve C çeldiricidir; doğru şık: A", perm)
    assert t == ("P(A)=0,3 ve P(B)=0,5; cevap C. A'nın tümleyeni; ABC analizinde A ve B sınıfı; (C) doğru, A) yanlış; "
                 "C ve A şıkları; B ve A çeldiricidir; doğru şık: C")


def test_konuma_bagli_sikli_soru_dengelenmez():
    sorular = [{"soru": f"S{k}", "siklar": ["A) bir", "B) iki", "C) üç", "D) Yukarıdakilerin hepsi"], "cevap": "D",
                "aciklama": "D şıkkı doğru"} for k in range(4)]
    sorular += [{"soru": "T", "siklar": ["A) x", "B) y", "C) A ve B", "D) z"], "cevap": "C", "aciklama": ""}]
    x = paket.sik_dengele({"bolumler": [{"tur": "coktan", "sorular": [dict(q) for q in sorular]}]}, seed=1)
    for q, eski in zip(x["bolumler"][0]["sorular"], sorular):
        assert q["siklar"] == eski["siklar"] and q["cevap"] == eski["cevap"]


def test_kisa_ozet_kirpilirken_klasik_sablon_korunur():
    govde = "\n".join(f"- madde {k} " + "kelime " * 20 for k in range(100))  # ~2200 kelime
    md = f"## Belge\n{govde}\n\n## Klasik soru şablonu\ntanım → maddeler → örnek → sonuç\n### Örnek\nPUKÖ'yü açıklayınız."
    out = paket.ozet_kirp(md, 1600)
    assert len(out.split()) <= 1600
    assert out.rstrip().endswith("PUKÖ'yü açıklayınız.") and "## Klasik soru şablonu" in out
    assert out.startswith("## Belge\n- madde 0")
    assert paket.ozet_kirp("## A\nkısa", 1600) == "## A\nkısa"


def test_bastan_uretim_yarida_kalinca_devaminda_da_gecerli(sahte, monkeypatch):
    c = notes.create_course("Kalite")
    cid = c["id"]
    notes.add_document(cid, "hafta1.pdf", make_text_pdf(["Kalite kavrami musteri beklentilerini karsilama derecesidir."]))
    c = notes.get_course(cid)
    c["lecture_plan"] = {"title": "Hazır plan", "sections": [], "hazir": True}
    c["sinav_rehberi"] = "- paketin rehberi"
    notes.save_course(c)
    asil = sahte.__call__

    async def bozuk(cls, *a, **kw):
        if cls is llm.LecturePlan:
            raise llm.TutorError("bağlantı koptu")
        return await asil(cls, *a, **kw)

    monkeypatch.setattr(llm, "_parse", bozuk)
    c = _calistir(cid, deneme_sayisi=1, yeniden=True)
    assert c["paket_is"]["durum"] == "hata" and c["paket_is"]["yeniden"]
    monkeypatch.setattr(llm, "_parse", sahte)
    sahte.calls.clear()
    c = _calistir(cid, deneme_sayisi=1)  # kutu işaretsiz: yine de 'baştan' kurallarıyla, kaldığı yerden sürer
    assert c["paket_is"]["durum"] == "bitti" and not c["paket_is"]["yeniden"]
    assert sahte.say("ParcaOzet") == 0  # özetler ilk çalıştırmada bitmişti, yeniden silinmedi
    assert c["lecture_plan"]["title"] == "Üretilen plan" and "PUKÖ" in c["sinav_rehberi"]
    # bittikten sonra normal başlatma artık 'baştan' değildir
    c = notes.get_course(cid)
    c["lecture_plan"] = {"title": "Hazır plan 2", "sections": [], "hazir": True}
    c["paket_ara"]["imza"] = "eski"
    notes.save_course(c)
    c = _calistir(cid, deneme_sayisi=1)
    assert c["lecture_plan"]["title"] == "Hazır plan 2"


def test_arka_plan_ocr_bitmesi_beklenir(sahte):
    c = notes.create_course("Foto")
    cid = c["id"]
    doc = notes.add_document(cid, "defter.png", _png())

    async def run():
        async def arka():
            await asyncio.sleep(0.05)
            notes.set_page_text(cid, doc["id"], 1, "Arka planda okunan not: PUKO dongusu planla uygula kontrol et.")

        paket.arka_ocr_ekle(cid, asyncio.create_task(arka()))
        paket.baslat(cid, deneme_sayisi=1)
        await paket.bekle(cid)

    asyncio.run(run())
    c = notes.get_course(cid)
    assert c["paket_is"]["durum"] == "bitti"
    assert sahte.ocr == [] and "Arka planda" in c["docs"][0]["pages"][0]["text"]  # sayfa iki kez okunmadı
    assert not paket._arka_ocr.get(cid)


def test_belge_yukleme_paket_isinin_kaydini_ezmez(monkeypatch):
    """add_document PDF'i bölerken (iş parçacığında) paket işi dersi kaydederse o kayıt kaybolmamalı."""
    import threading
    c = notes.create_course("Yarış")
    cid = c["id"]
    basladi, devam = threading.Event(), threading.Event()
    asil = notes._split_pdf

    def yavas(*a):
        basladi.set()
        devam.wait(5)
        return asil(*a)

    monkeypatch.setattr(notes, "_split_pdf", yavas)
    sonuc = {}
    t = threading.Thread(target=lambda: sonuc.setdefault("doc", notes.add_document(cid, "b.pdf", make_text_pdf(["Kalite kavrami ve PUKO dongusu."]))))
    t.start()
    assert basladi.wait(5)
    paket._guncelle(cid, lambda x: x.setdefault("paket_ara", {}).__setitem__("tamam", ["plan"]))  # bölme sürerken
    devam.set()
    t.join(5)
    c = notes.get_course(cid)
    assert c["paket_ara"]["tamam"] == ["plan"] and [d["id"] for d in c["docs"]] == [sonuc["doc"]["id"]]
