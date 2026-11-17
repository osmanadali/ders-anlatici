"""Yerel yapay zeka: donanıma göre model, uçtan uca kurulum (sahte Ollama ile) ve sohbet/JSON çıktıları."""
import asyncio
import functools
import http.server
import io
import json
import os
import socket
import sys
import tarfile
import threading
from pathlib import Path

import pytest
from pydantic import BaseModel

import fakes
from app import config, llm, llm_yerel, yerel

fakes.install()
FAKE = Path(__file__).with_name("fake_ollama.py")


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_donanima_gore_model():
    assert yerel.model_sec({"vram_gb": 24, "ram_gb": 32, "disk_gb": 100}) == "gemma4:26b"
    assert yerel.model_sec({"vram_gb": 12, "ram_gb": 16, "disk_gb": 100}) == "gemma4:12b"
    assert yerel.model_sec({"vram_gb": 0, "ram_gb": 16, "disk_gb": 100}) == "gemma4:e4b"
    assert yerel.model_sec({"vram_gb": 0, "ram_gb": 64, "disk_gb": 100}) == "gemma4:26b"  # MoE: işlemcide de akıcı
    assert yerel.model_sec({"vram_gb": 0, "ram_gb": 8, "disk_gb": 100}) == "gemma4:e2b"
    assert yerel.model_sec({"vram_gb": 24, "ram_gb": 32, "disk_gb": 12}) == "gemma4:12b"  # disk yetmiyor: küçült


def test_baglama_sigdirma_sistem_ve_son_soruyu_korur():
    hist = []
    for i in range(40):
        hist += [{"role": "user", "content": f"soru {i} " + "x" * 3000},
                 {"role": "assistant", "content": [{"type": "text", "text": "cevap " + "y" * 3000}]}]
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
    hist.append({"role": "user", "content": [img, {"type": "text", "text": "son soru"}]})
    out = llm_yerel.to_messages([{"type": "text", "text": "SİSTEM"}], hist, 16384)
    assert out[0] == {"role": "system", "content": "SİSTEM"}
    assert out[1]["role"] == "user" and out[-1]["content"] == "son soru" and out[-1]["images"] == ["QUJD"]
    total = sum(len(m["content"]) for m in out)
    assert total < (16384 - llm_yerel.OUTPUT_RESERVE) * llm_yerel.CHARS_PER_TOKEN
    assert len(out) < len(hist)


@pytest.fixture()
def kurulum(tmp_path, monkeypatch):
    """İndirilecek 'program' arşivi: bin/ollama = sahte Ollama sunucusu. Yerel bir HTTP sunucusundan verilir."""
    pub = tmp_path / "yayin"
    pub.mkdir()
    script = f"#!{sys.executable}\n" + FAKE.read_text("utf-8")
    with tarfile.open(pub / "ollama-linux-amd64.tgz", "w:gz") as t:
        data = script.encode()
        info = tarfile.TarInfo("bin/ollama")
        info.size, info.mode = len(data), 0o755
        t.addfile(info, io.BytesIO(data))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler,
                                                                             directory=str(pub)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = _port()
    monkeypatch.setenv("DERS_YEREL_INDIRME", "1")
    monkeypatch.setattr(yerel, "HOST", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(yerel, "RUNTIME_DIR", tmp_path / "yerel-yz")
    monkeypatch.setattr(yerel, "MODELS_DIR", tmp_path / "yerel-yz" / "modeller")
    monkeypatch.setattr(yerel, "_runtime_binary", lambda: tmp_path / "yerel-yz" / "bin" / "ollama")
    monkeypatch.setattr(yerel, "_download_url", lambda: f"http://127.0.0.1:{srv.server_address[1]}/ollama-linux-amd64.tgz")
    monkeypatch.setattr(yerel.shutil, "which", lambda name: None)
    monkeypatch.setattr(yerel, "STATE", {"state": "bilinmiyor", "detail": "", "progress": None, "model": "", "hw": None})
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    config.save_settings({"yerel_model": "gemma4:e2b", "llm_provider": ""})
    yield tmp_path
    yerel.stop_server()
    srv.shutdown()
    config.save_settings({"yerel_model": "", "llm_provider": ""})


def _log(tmp: Path) -> list[dict]:
    f = tmp / "yerel-yz" / "modeller" / "istekler.jsonl"
    return [json.loads(l) for l in f.read_text("utf-8").splitlines()] if f.exists() else []


def test_sifirdan_kurulum_ve_sohbet(kurulum):
    st = asyncio.run(yerel.hazirla())
    assert st["state"] == "hazir", st
    assert st["model"] == "gemma4:e2b"
    assert (kurulum / "yerel-yz" / "bin" / "ollama").exists()
    assert not list((kurulum / "yerel-yz").glob("*.tgz*"))  # arşiv silindi
    reqs = _log(kurulum)
    assert [r["path"] for r in reqs][:2] == ["/api/pull", "/api/generate"]
    assert llm.provider() == "yerel"

    async def steps():
        return [x async for x in llm.real_stream_steps([{"type": "text", "text": "Sen hocasın."}],
                                                       [{"role": "user", "content": "Kalite nedir?"}])]

    out = asyncio.run(steps())
    assert [s["say"] for s in out if "say" in s] == ["Merhaba, önce tanımla başlayalım.", "Bitti."]
    chat = [r for r in _log(kurulum) if r["path"] == "/api/chat"][-1]["body"]
    assert chat["model"] == "gemma4:e2b" and chat["think"] is False
    assert chat["messages"][0] == {"role": "system", "content": "Sen hocasın."}
    assert chat["options"]["num_ctx"] == yerel.baglam()

    class Plan(BaseModel):
        baslik: str
        maddeler: list[str]

    p = asyncio.run(llm._parse(Plan, "Planı çıkar"))
    assert p.baslik == "örnek" and p.maddeler == ["örnek"]
    fmt = [r for r in _log(kurulum) if r["path"] == "/api/chat"][-1]["body"]["format"]
    assert fmt["properties"]["maddeler"]["type"] == "array"

    # ikinci açılış: program ve model zaten var, hiçbir şey indirilmez
    yerel.stop_server()
    yerel.STATE["state"] = "bilinmiyor"
    st = asyncio.run(yerel.hazirla())
    assert st["state"] == "hazir"
    assert [r["path"] for r in _log(kurulum)].count("/api/pull") == 1


def test_indirme_kapaliysa_anlasilir_hata(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(yerel, "HOST", f"http://127.0.0.1:{_port()}")
    monkeypatch.setattr(yerel, "find_binary", lambda: None)
    monkeypatch.setattr(yerel, "STATE", {"state": "bilinmiyor", "detail": "", "progress": None, "model": "", "hw": None})
    st = asyncio.run(yerel.hazirla())
    assert st["state"] == "hata" and "kurulu değil" in st["detail"]
    with pytest.raises(llm.TutorError) as e:
        asyncio.run(llm._parse(llm.PageText, "x"))
    assert "Yerel yapay zeka" in str(e.value)


def test_edge_ulasilamazsa_internetsiz_ses(monkeypatch):
    from app import voice

    async def edge_yok(text, v, *a):
        raise voice.VoiceError("ağ yok")

    monkeypatch.setattr(voice, "_edge_tts", edge_yok)
    monkeypatch.setattr(voice, "piper_available", lambda: True)
    monkeypatch.setattr(voice, "_piper", lambda text: b"RIFF-piper")
    config.save_settings({"tts_provider": "edge"})
    assert asyncio.run(voice.real_speak("Merhaba")) == b"RIFF-piper"


def test_paket_uretimi_yalnizca_yerel_yapay_zekayla(kurulum, monkeypatch):
    """Ders paketi üretimi Gemini'ye bağlı değildir: anahtar yokken her adım yerel modele (sahte Ollama) gider."""
    from app import notes, paket
    from conftest import make_text_pdf

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # başka testler anahtar bırakmış olabilir
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert not config.gemini_key()
    assert asyncio.run(yerel.hazirla())["state"] == "hazir"
    c = notes.create_course("Kalite")
    notes.add_document(c["id"], "hafta1.pdf", make_text_pdf(["Kalite kavrami musteri beklentilerini karsilama derecesidir."]))

    async def run():
        paket.baslat(c["id"], deneme_sayisi=1)
        await paket.bekle(c["id"])

    asyncio.run(run())
    course = notes.get_course(c["id"])
    assert course["paket_is"]["durum"] == "bitti", course["paket_is"]
    assert "yerel yapay zeka" in course["paket_is"]["adim"]
    assert course["docs"][0]["hazir"]["paket"] == "uretilen" and course["konu_anlatimi"] and len(course["denemeler"]) == 1
    chats = [r["body"] for r in _log(kurulum) if r["path"] == "/api/chat"]
    assert len(chats) == 7 and all(b.get("format") for b in chats)  # özet, plan, rehber, konu, kısa özet, deneme, denetim
