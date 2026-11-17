"""Ses katmanı: metin ön işleme, sağlayıcı geçişi, Chatterbox yokken Edge'e düşme."""
import asyncio
import json

import pytest

from app import config, voice


def test_kisaltma_ve_sayilar():
    t = voice.hazirla_metin("Örn. s. 12 ve vb. konular, %3,5 artış ve %50 oran.")
    assert "örneğin" in t.lower() and "sayfa 12" in t and "ve benzeri" in t
    assert "üç virgül beş" in t and "yüzde elli" in t


def test_guvenli_olmayan_sayilar_degismez():
    assert "1,2,3" in voice.hazirla_metin("Liste 1,2,3 böyle.")
    assert "12,345" in voice.hazirla_metin("Toplam 12,345 adet.")


def test_isaret_temizligi_ve_uzun_cumle():
    assert voice.hazirla_metin("**Önemli** `kod` # başlık") == "Önemli kod başlık"
    uzun = "Bu çok uzun bir cümle, " * 20 + "bitti."
    out = voice.hazirla_metin(uzun)
    assert out.count(".") > 1 and out.endswith("bitti.")


def test_sayi_oku():
    assert voice.sayi_oku(0) == "sıfır" and voice.sayi_oku(25) == "yirmi beş" and voice.sayi_oku(90) == "doksan"


def test_xtts_ornek_yok_edge_gecis(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_SETTINGS_FILE", tmp_path / "ayarlar.json")
    (tmp_path / "ayarlar.json").write_text(json.dumps({"tts_provider": "xtts", "_ses_v2": True}), "utf-8")
    s = config.load_settings()
    assert s["tts_provider"] == "edge" and s["edge_voice"] == "tr-TR-AhmetNeural" and s["_ses_v3"]
    # örnek varsa kullanıcının seçimi korunur
    (tmp_path / "ayarlar.json").write_text(json.dumps({"tts_provider": "xtts", "_ses_v2": True}), "utf-8")
    (tmp_path / "ses_ornegi.wav").write_bytes(b"x")
    assert config.load_settings()["tts_provider"] == "xtts"


def test_xtts_ornek_yoksa_speak_edge(tmp_path, monkeypatch):
    cagri = []

    async def sahte_edge(text, voice_name, rate="", pitch=""):
        cagri.append(voice_name)
        return b"mp3"

    monkeypatch.setattr(voice, "VOICE_SAMPLE", tmp_path / "yok.wav")
    monkeypatch.setattr(voice, "_edge_tts", sahte_edge)
    monkeypatch.setattr(voice, "load_settings", lambda: {"tts_provider": "xtts", "edge_voice": "tr-TR-AhmetNeural"})
    real = getattr(voice, "real_speak", voice.speak)
    assert asyncio.run(real("merhaba")) == b"mp3" and cagri == ["tr-TR-AhmetNeural"]


def test_chatterbox_yoksa_edge(monkeypatch):
    async def sahte_edge(text, voice_name, rate="", pitch=""):
        return b"edge"

    def bozuk(text):
        raise voice.VoiceError("paket yok")

    monkeypatch.setattr(voice, "_edge_tts", sahte_edge)
    monkeypatch.setattr(voice, "_chatterbox", bozuk)
    monkeypatch.setattr(voice, "load_settings", lambda: {"tts_provider": "chatterbox", "edge_voice": "tr-TR-AhmetNeural"})
    real = getattr(voice, "real_speak", voice.speak)
    assert asyncio.run(real("merhaba")) == b"edge"
