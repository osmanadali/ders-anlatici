"""Notun dersini bulma, Not Kutusu ve İndirilenler'den kendiliğinden içe aktarma."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import fakes
from app import hazir, klasor, main, notes, siniflandir
from conftest import make_text_pdf

fakes.install()

KALITE = ("Toplam kalite yonetimi ilkeleri: surekli iyilestirme kaizen, musteri odaklilik, Deming PUKO dongusu, "
          "kalite cemberleri, liderlik, Ishikawa kilcik diyagrami, standardizasyon ve kalibrasyon.")
OLASILIK = ("Olasilik dagilimlari: binom dagilimi, Poisson dagilimi, normal dagilim, beklenen deger, varyans, "
            "rastgele degisken, kosullu olasilik ve Bayes teoremi ornekleri.")


@pytest.fixture()
def dersler():
    for c in notes.list_courses():
        notes.delete_course(c["id"])
    hazir.packs.cache_clear()
    k = notes.create_course("Kalite Yönetimi")
    notes.add_document(k["id"], "hafta1.pdf", make_text_pdf([KALITE, KALITE]))
    o = notes.create_course("Olasılık")
    notes.add_document(o["id"], "olasilik1.pdf", make_text_pdf([OLASILIK]))
    yield k["id"], o["id"]


def test_ders_kodlari():
    assert siniflandir.kodlar("ENM 463 Kalite / enm-311 ve MAT101") == {"ENM463", "ENM311", "MAT101"}
    assert siniflandir.ders_kodu({"name": "ENM 463 KALİTE YÖNETİMİ"}) == "ENM463"


def test_konu_benzerligi_ve_ipucu(dersler):
    k, o = dersler
    assert siniflandir.bul("hafta5.pdf", KALITE).course_id == k
    assert siniflandir.bul("x.pdf", OLASILIK).course_id == o
    # kararsız metin: birlikte yüklenen önceki notun dersi seçilir
    karisik = "Kalite ve olasilik konulari: ornekleme"
    assert siniflandir.bul("x.pdf", karisik, ipucu=o).course_id == o


def test_kod_muhfredattaki_dersi_olusturur(dersler):
    s = siniflandir.bul("ENM 305 Yöneylem Araştırması - Ders 2.pdf", "")
    assert s.course_id and s.course_id.startswith("mufredat:") and "ENM 305" in s.yeni_ders
    cid, yeni = siniflandir.ders_hazirla(s)
    assert yeni and notes.get_course(cid)["profile"]["kod"] == "ENM 305"
    # ikinci kez: artık var olan ders bulunur
    s2 = siniflandir.bul("ENM305 vize notları.pdf", "")
    assert s2.course_id == cid


def test_otomatik_ekleme_ucu_ve_tasima(dersler):
    k, o = dersler
    c = TestClient(main.app)
    r = c.post("/api/notes/auto", files={"file": ("yeni not.pdf", make_text_pdf([OLASILIK, OLASILIK]), "application/pdf")}).json()
    assert r["ders_id"] == o and not r["yeni_ders"]
    assert any(d["name"] == "yeni not" for d in notes.get_course(o)["docs"])
    doc = r["doc"]
    assert c.post(f"/api/courses/{o}/docs/{doc['id']}/move", json={"hedef": k}).json() == {"ok": True}
    assert any(d["id"] == doc["id"] for d in notes.get_course(k)["docs"])
    assert not any(d["id"] == doc["id"] for d in notes.get_course(o)["docs"])
    assert notes.page_image_path(k, doc["id"], 1).exists()  # dosyaları da taşındı


def test_yapay_zekasiz_belirsiz_not_en_yakin_derse(dersler):
    k, o = dersler
    s = siniflandir.bul("not.pdf", "kalite olasilik")
    s = siniflandir.en_yakin(s)
    assert s.course_id in (k, o)


def _paket():
    return {"kurs_kodu": "ENM 463", "ders": "ENM 463 KALİTE YÖNETİMİ", "kisa_ozet": "# Özet",
            "denemeler": [{"baslik": "Deneme 1"}], "ders_plani": {"title": "Plan", "sections": []},
            "docs": {"4.DERS (TKY).pdf": {"baslik": "TKY", "ozet": "ilkeler", "kavramlar": [{"terim": "Kaizen", "tanim": "s.i."}]}}}


def test_paket_dersi_yoksa_muhfredattan_olusur_ve_pdfsiz_calisir(dersler, tmp_path, monkeypatch):
    monkeypatch.setattr(hazir, "USER_DIR", tmp_path / "hazir")
    hazir.packs.cache_clear()
    r = hazir.install_pack(json.dumps(_paket()).encode())
    course = notes.get_course(r["ders_id"])
    assert course["profile"]["kod"] == "ENM 463" and course["kisa_ozet"] == "# Özet"
    assert course["lecture_plan"]["title"] == "Plan"
    assert "Kaizen" in hazir.course_guide(course)  # PDF yüklenmeden de hocanın bilgisinde
    assert len(hazir.course_guide(course, limit=500)) <= 500
    hazir.packs.cache_clear()


def test_not_kutusu_ve_indirilenler(dersler, tmp_path, monkeypatch):
    k, o = dersler
    kutu = tmp_path / "Not Kutusu"
    monkeypatch.setenv("DERS_NOT_KUTUSU", str(kutu))
    monkeypatch.setattr(hazir, "USER_DIR", tmp_path / "hazir")
    hazir.packs.cache_clear()
    klasor.kutu_hazirla()
    (kutu / "olasilik vize.pdf").write_bytes(make_text_pdf([OLASILIK]))
    (kutu / "bozuk.pdf").write_bytes(b"%PDF bozuk")
    (kutu / "yariminiyor.pdf.crdownload").write_bytes(b"x")
    now = [1000.0]
    monkeypatch.setattr(klasor.time, "time", lambda: now[0])

    async def tara():
        return await klasor.kutuyu_tara(main.otomatik_ekle)

    assert asyncio.run(tara()) == 0  # ilk görüşte bekler (dosya hâlâ yazılıyor olabilir)
    now[0] += 5
    asyncio.run(tara())
    assert (kutu / "Eklendi" / "Olasılık" / "olasilik vize.pdf").exists()
    assert (kutu / "Eklenemedi" / "bozuk.pdf").exists() and (kutu / "Eklenemedi" / "bozuk.pdf.neden.txt").exists()
    assert (kutu / "yariminiyor.pdf.crdownload").exists()  # yarım indirme dokunulmadı
    assert any(d["name"] == "olasilik vize" for d in notes.get_course(o)["docs"])
    turler = [x["tur"] for x in klasor.OLAYLAR[-2:]]
    assert set(turler) == {"eklendi", "hata"}

    indir = tmp_path / "Downloads"
    indir.mkdir()
    (indir / "ENM463_Kalite_ders_paketi.json").write_text(json.dumps(_paket()), "utf-8")
    (indir / "baska.json").write_text('{"a": 1}', "utf-8")
    monkeypatch.setattr(klasor, "indirilenler", lambda: indir)
    monkeypatch.setattr(klasor.time, "time", time.time)
    assert klasor.indirilenleri_tara() == 1
    assert klasor.indirilenleri_tara() == 0  # aynı paket ikinci kez kurulmaz
    c = TestClient(main.app)
    assert any("ders paketi kuruldu" in o_["mesaj"] for o_ in c.get("/api/kutu").json()["olaylar"])
    hazir.packs.cache_clear()
