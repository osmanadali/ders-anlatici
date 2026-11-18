"""Hocanın kendini geliştirmesi: geri bildirim, kendi kendine çalışma, öğrenci profili, sokratik mod."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import fakes
from app import calisma, llm, main, ogrenme, prompts
from conftest import make_text_pdf

fakes.install()


@pytest.fixture(autouse=True)
def temiz(monkeypatch):
    for f in ogrenme.klasor().iterdir():
        f.unlink()
    monkeypatch.setattr(llm, "_son_etkinlik", 0.0)
    yield


@pytest.fixture()
def client():
    with TestClient(main.app) as c:
        yield c


def _events(resp):
    return [json.loads(line[6:]) for line in resp.text.split("\n\n") if line.startswith("data: ")]


def _sistem_metni(call) -> str:
    return "\n".join(b["text"] for b in call["system"])


def _oturum(client, text="Türev nedir?", course_id=""):
    r = client.post("/api/ask", data={"text": text, "course_id": course_id})
    ev = _events(r)
    return ev[0]["id"], ev[0]["sira"]


# ---------------------------------------------------------------- geri bildirim
def test_geri_bildirim_kaydi_ve_uc_nokta(client):
    sid, sira = _oturum(client)
    r = client.post("/api/geri-bildirim", json={"session_id": sid, "sira": sira, "puan": 1})
    assert r.status_code == 200
    rows = ogrenme.geri_bildirim_listesi()
    assert len(rows) == 1 and rows[0]["puan"] == 1
    assert rows[0]["soru"] == "Türev nedir?" and "parabol" in rows[0]["cevap"].lower()
    assert "Tahta" in rows[0]["cevap"]
    # aynı cevaba sonradan 👎 + not: öncekinin yerini alır
    client.post("/api/geri-bildirim", json={"session_id": sid, "sira": sira, "puan": -1, "not": "çok hızlı"})
    rows = ogrenme.geri_bildirim_listesi()
    assert len(rows) == 1 and rows[0]["puan"] == -1 and rows[0]["not"] == "çok hızlı"
    assert client.post("/api/geri-bildirim", json={"session_id": sid, "sira": sira, "puan": 5}).status_code == 400
    assert client.post("/api/geri-bildirim", json={"session_id": "abcdef012345", "sira": 0, "puan": 1}).status_code == 404
    assert client.post("/api/geri-bildirim", json={"session_id": sid, "sira": 999, "puan": 1}).status_code == 400


def test_ornek_ve_kacin_sistem_talimatinda(client):
    sid, sira = _oturum(client, "Parabol nasıl çizilir?")
    client.post("/api/geri-bildirim", json={"session_id": sid, "sira": sira, "puan": 1})
    sid2, sira2 = _oturum(client, "Integral nedir?")
    client.post("/api/geri-bildirim", json={"session_id": sid2, "sira": sira2, "puan": -1, "not": "çok uzun"})
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "Parabol grafiği nasıl çizilir?"})
    s = _sistem_metni(fakes.CALLS[-1])
    assert "İYİ ANLATIM ÖRNEKLERİ" in s and "Parabol nasıl çizilir?" in s
    assert "KAÇIN" in s and "çok uzun" in s
    assert len(ogrenme.geri_bildirim_blogu(None, "Parabol çizimi")) <= ogrenme.BLOK_SINIRI


def test_bos_iken_sistem_talimati_ayni():
    a = llm.build_system(None, "", False, "", "normal")
    b = llm.build_system(None, "", False, "", "normal", ogrenme="", tarz="anlat")
    assert a == b
    assert "SOKRATİK" not in _sistem_metni({"system": a})
    assert ogrenme.ogrenme_blogu(None, "herhangi bir soru") == ""
    assert calisma.dogrulanmis_blok(None, "herhangi bir soru") == ""


def test_geri_bildirim_yokken_talimata_blok_eklenmez(client):
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "Türev nedir?"})
    s = _sistem_metni(fakes.CALLS[-1])
    for ifade in ("İYİ ANLATIM", "KAÇIN", "ÖĞRENCİNİN TERCİHLERİ", "DOĞRULANMIŞ BİLGİ", "SOKRATİK"):
        assert ifade not in s


# ---------------------------------------------------------------- kendi kendine çalışma
PARCA = {"metin": "Türev, bir fonksiyonun değişim hızıdır. " * 20, "baslik": "Analiz Kitabı", "sayfa": 12,
         "ders_kodu": "MAT101", "ders_id": ""}


def _hazirla(monkeypatch, dogru=True, uretilen=None):
    monkeypatch.setattr(llm, "ai_hazir", lambda: True)
    monkeypatch.setattr(llm, "provider", lambda: "yerel")
    monkeypatch.setattr(calisma, "parca_sec", lambda: PARCA)
    cagrilar = []

    async def sahte_parse(model_cls, content, system=None, effort=None, max_tokens=16000):
        cagrilar.append(model_cls.__name__)
        if model_cls is calisma.SoruUret:
            return calisma.SoruUret(sorular=uretilen or [
                calisma.UretilenSoru(soru="Türev neyi ölçer?", cevap="Değişim hızını"),
                calisma.UretilenSoru(soru="Türevin tanımı hangisidir?", cevap="Değişim hızı", tur="coktan",
                                     siklar=["Alan", "Değişim hızı", "Hacim", "Uzunluk"]),
            ])
        return calisma.Dogrulama(dogru=dogru, duzeltilmis_cevap="" if dogru else "başka")

    monkeypatch.setattr(llm, "_parse", sahte_parse)
    return cagrilar


def test_kendi_calisma_uretir_ve_dogrular(monkeypatch):
    cagrilar = _hazirla(monkeypatch)
    sonuc = asyncio.run(calisma.bir_tur())
    assert sonuc == {"uretilen": 2, "eklenen": 2}
    assert cagrilar == ["SoruUret", "Dogrulama", "Dogrulama"]
    b = calisma.banka()
    assert len(b) == 2 and all(r["dogrulandi"] and r["kaynak"] == {"baslik": "Analiz Kitabı", "sayfa": 12} for r in b)
    assert {r["tur"] for r in b} == {"acik", "coktan"}
    assert calisma.durum()["soru_sayisi"] == 2


def test_dogrulanmayan_bankaya_girmez(monkeypatch):
    _hazirla(monkeypatch, dogru=False)
    sonuc = asyncio.run(calisma.bir_tur())
    assert sonuc["eklenen"] == 0 and calisma.banka() == []


def test_saatlik_sinir(monkeypatch):
    _hazirla(monkeypatch)
    monkeypatch.setattr(calisma, "SAATLIK_SINIR", 2)
    assert asyncio.run(calisma.bir_tur())["eklenen"] == 2
    assert asyncio.run(calisma.bir_tur()) == {"atlandi": "saatlik sınır"}


def test_bosta_degilken_calismaz(monkeypatch):
    cagrilar = _hazirla(monkeypatch)
    monkeypatch.setattr(llm, "_son_etkinlik", time.time())
    assert asyncio.run(calisma.bir_tur()) == {"atlandi": "öğrenci etkinliği"}
    assert cagrilar == []


def test_ayar_kapaliysa_calismaz(monkeypatch):
    cagrilar = _hazirla(monkeypatch)
    monkeypatch.setattr(calisma.config, "load_settings", lambda: {"kendi_calisma": False})
    assert asyncio.run(calisma.bir_tur()) == {"atlandi": "kapalı"}
    assert cagrilar == []


def test_dogrulanmis_bilgi_soruda_kullanilir_ve_banka_uc_noktasi(monkeypatch, client):
    _hazirla(monkeypatch)
    asyncio.run(calisma.bir_tur())
    c = client.post("/api/courses", json={"name": "Matematik MAT101"}).json()
    client.post(f"/api/courses/{c['id']}/docs", files={"file": ("n.pdf", make_text_pdf(["Turev"]), "application/pdf")})
    monkeypatch.setattr(calisma.siniflandir, "ders_kodu", lambda course: "MAT101")
    # ask: benzer soru → DOĞRULANMIŞ BİLGİ
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "Türev neyi ölçer?", "course_id": c["id"]})
    s = _sistem_metni(fakes.CALLS[-1])
    assert "DOĞRULANMIŞ BİLGİ" in s and "Değişim hızını" in s
    # soru bankası quiz biçiminde
    r = client.get(f"/api/soru-bankasi?ders={c['id']}&n=5")
    assert r.status_code == 200
    qs = r.json()["questions"]
    assert len(qs) == 2
    for q in qs:
        assert set(q) == {"question", "kind", "choices", "answer", "topic", "page"}
        assert q["kind"] in ("coktan_secmeli", "acik_uclu") and q["page"] == "Analiz Kitabı s.12"
    coktan = next(q for q in qs if q["kind"] == "coktan_secmeli")
    assert coktan["answer"] in coktan["choices"] and len(coktan["choices"]) == 4
    assert client.get("/api/soru-bankasi?ders=yok123").status_code == 404
    d = client.get("/api/calisma").json()
    assert d["soru_sayisi"] == 2 and "ders_bazinda" in d and "calisiyor" in d and "son_calisma" in d


def test_banka_bos_ders_404(client):
    c = client.post("/api/courses", json={"name": "Fizik"}).json()
    assert client.get(f"/api/soru-bankasi?ders={c['id']}").status_code == 404


# ---------------------------------------------------------------- profil
def test_profil_esik_ve_sifirlama(client):
    assert ogrenme.profil_blogu() == ""
    for _ in range(ogrenme.ESIK - 1):
        ogrenme.profil_say("bir örnek verir misin", not_mu=False)
    assert ogrenme.profil_blogu() == ""  # eşik aşılmadı
    ogrenme.profil_say("bir örnek daha ver", not_mu=False)
    blok = ogrenme.profil_blogu()
    assert blok.startswith("ÖĞRENCİNİN TERCİHLERİ") and "Örnekle" in blok
    assert ogrenme.profil_oku()["sayac"]["ornek"] == ogrenme.ESIK
    assert client.delete("/api/profil").json()["ok"]
    assert ogrenme.profil_blogu() == "" and ogrenme.profil_oku() == {}


def test_profil_geri_bildirim_notundan_ve_mesajdan_sayilir(client):
    sid, sira = _oturum(client)
    for _ in range(ogrenme.ESIK):
        client.post("/api/geri-bildirim", json={"session_id": sid, "sira": sira, "puan": -1, "not": "çok hızlı"})
    assert "yavaş" in ogrenme.profil_blogu()
    ogrenme.profil_sifirla()
    for _ in range(ogrenme.ESIK):
        client.post("/api/ask", data={"text": "formülle göster lütfen"})
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "formülle göster"})
    assert "ÖĞRENCİNİN TERCİHLERİ" in _sistem_metni(fakes.CALLS[-1])
    assert len([s for s in ogrenme.profil_blogu().splitlines() if s.startswith("- ")]) <= 2


# ---------------------------------------------------------------- sokratik mod
def test_sokratik_ayari_talimata_yansir(client):
    fakes.CALLS.clear()
    client.post("/api/ask", data={"text": "Türev nedir?"})
    assert "SOKRATİK" not in _sistem_metni(fakes.CALLS[-1])
    assert client.post("/api/settings", json={"ogretme_tarzi": "sokratik"}).json()["ogretme_tarzi"] == "sokratik"
    try:
        fakes.CALLS.clear()
        client.post("/api/ask", data={"text": "Türev nedir?"})
        assert prompts.SOKRATIK in _sistem_metni(fakes.CALLS[-1])
    finally:
        client.post("/api/settings", json={"ogretme_tarzi": "anlat"})


def test_kontrol_sorusu_talimati_ve_varsayilanlar():
    assert "KESİNTİSİZ" in prompts.TUTOR_SYSTEM and "cevabını bekle" not in prompts.CONVERSATION_STYLE
    from app.config import DEFAULTS
    assert DEFAULTS["ogretme_tarzi"] == "anlat" and DEFAULTS["kendi_calisma"] is True
