"""Sağlamlık: siteler arası istek koruması, güncelleme durumu, sesli okuma ön işlemesi, Chatterbox hata hafızası."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main, voice


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_baska_siteden_post_reddedilir(client):
    r = client.post("/api/settings", json={"level": "normal"}, headers={"Origin": "https://kotu.example"})
    assert r.status_code == 403
    r = client.post("/api/settings", json={"level": "normal"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.post("/api/settings", json={"level": "normal"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/api/settings", json={"level": "normal"}).status_code == 200


def test_guncelleme_durumu_alanlari(client, monkeypatch):
    monkeypatch.setattr(main, "_surum_denetle", lambda: {"yeni": True, "mesaj": "x", "simdiki": "a", "son": "bbb"})
    monkeypatch.setattr(main, "_DENENEN", main.DATA_DIR / ".denenen_test")
    main._DENENEN.unlink(missing_ok=True)
    d = client.get("/api/guncelle/durum").json()
    assert d["yeni"] and not d["denendi"] and "pencere_acik" in d and "mesgul" in d
    main._guncel_onbellek.update(sonuc={"son": "bbb"})
    monkeypatch.setenv("DERS_BASLATICI", "1")
    assert client.post("/api/guncelle/yeniden-baslat").json()["ok"]
    main.YENIDEN_BASLAT[0] = False
    assert client.get("/api/guncelle/durum").json()["denendi"]  # aynı sürüm için yeniden denenmez
    main._DENENEN.unlink(missing_ok=True)


def test_okuma_anlami_korur():
    h = voice.hazirla_metin
    assert h("x > 5 ise kabul et.") == "x büyüktür 5 ise kabul et."
    assert "küçüktür" in h("p < 0,05") and "çarpı" in h("2*3 = 6")
    assert h("Olasılık 50% olur.") == "Olasılık yüzde elli olur."
    assert h("a -> b") == "a ise b"


def test_chatterbox_hatasi_hatirlanir(monkeypatch):
    cagri = []

    def bozuk(text):
        cagri.append(text)
        voice._cb_hata = (__import__("time").time(), "yüklenemedi")
        raise voice.VoiceError("yüklenemedi")

    async def edge(text, v, *a):
        return b"edge"

    monkeypatch.setattr(voice, "_cb_hata", None)
    monkeypatch.setattr(voice, "_chatterbox", bozuk)
    monkeypatch.setattr(voice, "_edge_tts", edge)
    asil = voice.load_settings
    monkeypatch.setattr(voice, "load_settings", lambda: {**asil(), "tts_provider": "chatterbox"})
    gercek = getattr(voice, "real_speak", voice.speak)  # testlerde speak sahteyle değiştirilmiş olabilir
    for _ in range(3):
        assert asyncio.run(gercek("merhaba")) == b"edge"
    assert len(cagri) == 1  # ilk hatadan sonra her adımda modeli yeniden yüklemeye çalışmaz


def test_degisken_baglam_son_soruya_gider():
    """Hız: sistem talimatı sorudan soruya aynı kalır (Ollama önbelleği), değişen bağlam son soruya eklenir."""
    from app import llm, llm_yerel

    def kur(kaynak, soru):
        system = llm.build_system(None, "NOTLAR", True, "hafıza-" + kaynak, "normal", kaynaklar="kaynak-" + kaynak,
                                  ogrenme="ogren-" + kaynak, sohbet=True)
        return llm_yerel.to_messages(system, [{"role": "user", "content": [{"type": "text", "text": soru}]}], 16384)

    a, b = kur("A", "ilk soru"), kur("B", "ikinci soru")
    assert a[0]["role"] == "system" and a[0]["content"] == b[0]["content"]  # önbellek bozulmaz
    assert "kaynak-A" not in a[0]["content"] and "hafıza-A" not in a[0]["content"]
    assert a[-1]["content"].startswith("<baglam>") and "kaynak-A" in a[-1]["content"] and a[-1]["content"].endswith("ilk soru")
