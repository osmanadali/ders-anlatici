"""Ses katmanı: metinden sese (TTS) ve sesten metne (STT).

Sağlayıcılar (Ayarlar'dan seçilir):
  TTS  elevenlabs : klon ses, en doğal (ücretli kredi)
       edge       : Microsoft Edge nöral sesleri (Emel, Ahmet) — ÜCRETSİZ, internet gerekir
       chatterbox : Chatterbox Multilingual (Resemble AI, MIT) — yerelde, Türkçe, XTTS'ten daha doğal;
                    pip install -r requirements-ses.txt (ekran kartı önerilir; ilk kullanımda model iner)
       xtts       : XTTS-v2 ile kendi bilgisayarında SES KLONU — ÜCRETSİZ, 10-30 sn ses örneği ister
                    (pip install -r requirements-klon.txt; ekran kartı önerilir)
       piper      : Piper (tr_TR-dfki), tamamen bilgisayarda — ÜCRETSİZ, İNTERNETSİZ; Edge'e erişilemezse
                    kendiliğinden devreye girer (ilk kullanımda ses modeli ~63 MB bir kez indirilir)
       browser    : tarayıcının kendi sesi (sunucu ses üretmez)
  STT  elevenlabs : Scribe (ücretli)
       whisper    : faster-whisper, kendi bilgisayarında — ÜCRETSİZ
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

from .config import elevenlabs_key

log = logging.getLogger("ders.ses")
API = "https://api.elevenlabs.io/v1"
# Aynı anda en fazla bu kadar ses üretimi (ElevenLabs eşzamanlılık sınırı için).
_tts_sem = asyncio.Semaphore(3)
_client: httpx.AsyncClient | None = None


class VoiceError(RuntimeError):
    pass


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))
    return _client


def _headers() -> dict:
    if not elevenlabs_key():
        raise VoiceError("ElevenLabs seçili ama anahtarı yok. Ayarlar'dan ücretsiz bir ses kaynağı seç ya da Ayarlar → API anahtarları'na ElevenLabs anahtarını gir.")
    return {"xi-api-key": elevenlabs_key()}


async def synthesize(
    text: str,
    voice_id: str,
    model_id: str,
    previous_text: str = "",
    next_text: str = "",
) -> bytes:
    """Bir anlatım adımını mp3'e çevirir. previous_text, cümleler arası tonlamayı korur."""
    body: dict = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.85,
            "style": 0.15,
            "use_speaker_boost": True,
        },
    }
    if previous_text:
        body["previous_text"] = previous_text[-600:]
    if next_text:
        body["next_text"] = next_text[:300]
    if "flash" in model_id or "turbo" in model_id:
        body["language_code"] = "tr"
    async with _tts_sem:
        for attempt in range(3):
            r = await _http().post(
                f"{API}/text-to-speech/{voice_id}",
                params={"output_format": "mp3_44100_128"},
                headers=_headers(),
                json=body,
            )
            if r.status_code == 429 or r.status_code >= 500:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise VoiceError(f"ElevenLabs ses hatası {r.status_code}: {r.text[:200]}")
            return r.content
    raise VoiceError("ElevenLabs şu an yoğun, ses üretilemedi.")


async def transcribe(audio: bytes, filename: str = "soru.webm", content_type: str = "audio/webm") -> str:
    """Mikrofondan gelen sesli soruyu Türkçe metne çevirir (ElevenLabs Scribe)."""
    r = await _http().post(
        f"{API}/speech-to-text",
        headers=_headers(),
        data={"model_id": "scribe_v1", "language_code": "tur", "tag_audio_events": "false"},
        files={"file": (filename, audio, content_type)},
    )
    if r.status_code != 200:
        raise VoiceError(f"ElevenLabs metne çevirme hatası {r.status_code}: {r.text[:200]}")
    return (r.json().get("text") or "").strip()


async def list_voices() -> list[dict]:
    r = await _http().get(f"{API}/voices", headers=_headers())
    if r.status_code != 200:
        raise VoiceError(f"Ses listesi alınamadı ({r.status_code}).")
    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        out.append(
            {
                "voice_id": v["voice_id"],
                "name": v.get("name", ""),
                "category": v.get("category", ""),
                "language": labels.get("language", ""),
                "gender": labels.get("gender", ""),
                "preview_url": v.get("preview_url"),
            }
        )
    # Önce klonlar, sonra Türkçe sesler.
    out.sort(key=lambda v: (v["category"] != "cloned", v["language"] != "tr", v["name"]))
    return out


# ================================================================ sağlayıcı seçimi
from pathlib import Path  # noqa: E402
import os  # noqa: E402
import ssl  # noqa: E402
import threading  # noqa: E402

from .config import DATA_DIR, load_settings  # noqa: E402

EDGE_VOICES = {
    "tr-TR-EmelNeural": "Emel (kadın, Türkçe)",
    "tr-TR-AhmetNeural": "Ahmet (erkek, Türkçe)",
}
VOICE_SAMPLE = DATA_DIR / "ses_ornegi.wav"
# Edge'in en doğal duyulan ayarı: hafif hızlı (ders temposu), biraz kalın ton (Ahmet'in tok sesi daha "hoca" gibi)
EDGE_RATE = "+4%"
EDGE_PITCH = "-2Hz"


# ---------------------------------------------------------------- metin ön işleme (TTS'ten önce)
_ONES = ["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_KISALTMA = [
    (r"\bvb\.", "ve benzeri"), (r"\bvs\.", "ve saire"), (r"\börn\.", "örneğin"), (r"\bÖrn\.", "Örneğin"),
    (r"\bbkz\.", "bakınız"), (r"\bBkz\.", "Bakınız"), (r"\bDr\.", "Doktor"), (r"\bProf\.", "Profesör"),
    (r"\bDoç\.", "Doçent"), (r"\byy\.", "yüzyıl"),
    (r"\bs\.\s?(?=\d)", "sayfa "), (r"\bss\.\s?(?=\d)", "sayfa "),
]


def sayi_oku(n: int) -> str:
    """0-99 arası sayıyı Türkçe okunuşa çevirir (1 → 'bir'); dışındakini olduğu gibi bırakır."""
    if 0 <= n < 10:
        return _ONES[n]
    if 10 <= n < 100:
        return _TENS[n // 10] + ((" " + _ONES[n % 10]) if n % 10 else "")
    return str(n)


def _ondalik(m) -> str:
    tam, kesir = m.group(1), m.group(2)
    kes = sayi_oku(int(kesir)) if len(kesir) == 1 else (
        ("sıfır " if kesir[0] == "0" else "") + sayi_oku(int(kesir)))
    return f"{sayi_oku(int(tam))} virgül {kes}"


def hazirla_metin(text: str) -> str:
    """Sesli okuma için metni hazırlar: işaretleri temizler, kısaltmaları açar, güvenli sayıları
    yazıya çevirir, çok uzun cümlelere nefes payı koyar. Anlamı değiştirmez."""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"[*_`#>~|]+", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", t)  # emojiler
    for pat, yeni in _KISALTMA:
        t = re.sub(pat, yeni, t)
    # ondalık: yalnızca tek başına duran "3,5" (liste "1,2,3" ya da "12,345" değil)
    t = re.sub(r"(?<![\d,.])(\d{1,2}),(\d{1,2})(?![\d,]|\.\d)", _ondalik, t)
    t = re.sub(r"%\s?(?=\d)", "yüzde ", t)
    t = re.sub(r"%\s?(?=[^\W\d])", "yüzde ", t)
    t = re.sub(r"yüzde (\d{1,2})(?![\d,.])", lambda m: "yüzde " + sayi_oku(int(m.group(1))), t)
    t = re.sub(r"\s*[—–]\s*", ", ", t)   # uzun tire: doğal duraklama
    t = re.sub(r"\s*\.{3,}\s*", "… ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([.,;:!?…])", r"\1", t)
    t = re.sub(r"\s*\n\s*", ". ", t) if "\n" in t.strip() else t
    t = re.sub(r"([.!?…])\s*\.\s*", r"\1 ", t)
    # çok uzun cümle (>170 karakter): ilk uygun virgül/noktalı virgülde cümleyi böl → Edge nefes alır
    parcalar = []
    for cumle in re.split(r"(?<=[.!?…])\s+", t.strip()):
        while len(cumle) > 170:
            kes = max(cumle.rfind(", ", 60, 150), cumle.rfind("; ", 60, 150))
            if kes < 0:
                break
            parcalar.append(cumle[:kes].rstrip() + ".")
            cumle = cumle[kes + 2:].lstrip()
            cumle = cumle[:1].upper() + cumle[1:]
        parcalar.append(cumle)
    return " ".join(p for p in parcalar if p).strip()


def sniff_mime(data: bytes) -> str:
    if data[:4] == b"RIFF":
        return "audio/wav"
    if data[:4] == b"OggS":
        return "audio/ogg"
    return "audio/mpeg"


async def speak(text: str, previous_text: str = "", next_text: str = "") -> bytes:
    """Seçili sağlayıcıyla metni sese çevirir (mp3 ya da wav baytları)."""
    s = load_settings()
    provider = s.get("tts_provider", "elevenlabs")
    if provider == "edge":
        try:
            return await _edge_tts(text, s.get("edge_voice", "tr-TR-AhmetNeural"),
                                   s.get("edge_rate", EDGE_RATE), s.get("edge_pitch", EDGE_PITCH))
        except VoiceError as e:
            if not piper_available():
                raise
            log.warning("Edge sesine ulaşılamadı (%s); internetsiz ses (Piper) kullanılıyor", e)
            return await asyncio.to_thread(_piper, text)
    if provider == "piper":
        return await asyncio.to_thread(_piper, text)
    if provider == "xtts":
        if not VOICE_SAMPLE.exists():  # ses örneği hiç yüklenmemiş: sessiz kalma, doğal hazır sese geç
            return await _edge_tts(text, s.get("edge_voice") or "tr-TR-AhmetNeural")
        return await asyncio.to_thread(_xtts, text)
    if provider == "chatterbox":
        try:
            return await asyncio.to_thread(_chatterbox, text)
        except Exception as e:  # paket yok, model inmedi, bellek yetmedi...: sessiz kalma, Edge'e düş
            log.warning("Chatterbox kullanılamadı (%s); Edge sesi kullanılıyor", e)
            return await _edge_tts(text, s.get("edge_voice") or "tr-TR-AhmetNeural",
                                   s.get("edge_rate", EDGE_RATE), s.get("edge_pitch", EDGE_PITCH))
    if provider == "browser":
        raise VoiceError("Tarayıcı sesi seçili; sunucu ses üretmiyor.")
    return await synthesize(text, s["voice_id"], s["tts_model"], previous_text, next_text)


async def listen(audio: bytes, filename: str = "soru.webm", content_type: str = "audio/webm") -> str:
    """Seçili sağlayıcıyla sesi metne çevirir."""
    if load_settings().get("stt_provider", "elevenlabs") == "whisper":
        return await asyncio.to_thread(_whisper, audio, filename)
    return await transcribe(audio, filename, content_type)


# ---------------------------------------------------------------- Edge TTS (ücretsiz)
async def _edge_tts(text: str, voice_name: str, rate: str = "", pitch: str = "") -> bytes:
    try:
        import aiohttp
        import edge_tts
    except ImportError as e:
        raise VoiceError("Ücretsiz ses paketi eksik: pip install -r requirements.txt") from e
    # Kurumsal ağ/vekil sunucu arkasında da çalışsın diye sistemin CA dosyasını kullan.
    ca = os.getenv("SSL_CERT_FILE")
    connector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=ca)) if ca else None
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or None
    text = hazirla_metin(text)
    if not text:
        raise VoiceError("Okunacak metin boş.")
    comm = edge_tts.Communicate(text, voice_name, rate=rate or EDGE_RATE, pitch=pitch or EDGE_PITCH,
                                connector=connector, proxy=proxy)
    out = bytearray()
    try:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                out += chunk["data"]
    except Exception as e:  # ağ hataları
        raise VoiceError(f"Edge ses hatası: {e}") from e
    if not out:
        raise VoiceError("Edge sesi boş döndü.")
    return bytes(out)


# ---------------------------------------------------------------- Piper (internetsiz, bilgisayarda)
PIPER_VOICE = "tr_TR-dfki-medium"
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/"
_piper_voice = None
_piper_lock = threading.Lock()


def _piper_dir() -> Path:
    return DATA_DIR / "piper"


def piper_available() -> bool:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return True


def _piper_download() -> Path:
    d = _piper_dir()
    d.mkdir(parents=True, exist_ok=True)
    model = d / f"{PIPER_VOICE}.onnx"
    for name in (f"{PIPER_VOICE}.onnx.json", f"{PIPER_VOICE}.onnx"):
        dst = d / name
        if dst.exists() and dst.stat().st_size > 0:
            continue
        tmp = dst.with_name(dst.name + ".part")
        with httpx.stream("GET", PIPER_URL + name, follow_redirects=True, timeout=httpx.Timeout(30, read=300)) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        os.replace(tmp, dst)
    return model


def _piper(text: str) -> bytes:
    global _piper_voice
    import io
    import wave

    try:
        from piper import PiperVoice
    except ImportError as e:
        raise VoiceError("İnternetsiz ses paketi eksik: pip install -r requirements.txt") from e
    with _piper_lock:
        if _piper_voice is None:
            try:
                _piper_voice = PiperVoice.load(str(_piper_download()))
            except Exception as e:
                raise VoiceError(f"İnternetsiz ses modeli yüklenemedi: {e}") from e
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            _piper_voice.synthesize_wav(text, w)
    return buf.getvalue()


def warm_piper() -> None:
    """Açılışta ses modelini indirir (internet varken), böylece internet kesilince hazır olur."""
    if not piper_available():
        return
    try:
        _piper_download()
    except Exception as e:
        log.warning("Piper ses modeli indirilemedi: %s", e)


# ---------------------------------------------------------------- XTTS-v2 (ücretsiz yerel klon)
_xtts_model = None
_xtts_lock = threading.Lock()


def _xtts(text: str) -> bytes:
    global _xtts_model
    if not VOICE_SAMPLE.exists():
        raise VoiceError("Yerel klon için önce Ayarlar'dan 10-30 saniyelik ses örneğini yükle.")
    try:
        import io
        import wave

        import numpy as np
        from TTS.api import TTS
    except ImportError as e:
        raise VoiceError("Yerel klon için: pip install -r requirements-klon.txt") from e
    with _xtts_lock:  # model aynı anda tek iş yapar
        if _xtts_model is None:
            os.environ.setdefault("COQUI_TOS_AGREED", "1")  # kişisel/ticari olmayan kullanım lisansı
            _patch_xtts_loader()
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
            _xtts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        wav = _xtts_model.tts(text=text, speaker_wav=str(VOICE_SAMPLE), language="tr", speed=1.0,
                                temperature=0.6, top_p=0.8, repetition_penalty=5.0)
    wav = shorten_pauses(np.asarray(wav, dtype=np.float32), 24000)
    pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------- Chatterbox Multilingual (yerel, doğal)
_cb_model = None
_cb_lock = threading.Lock()


def chatterbox_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("chatterbox") is not None
    except Exception:
        return False


def _cb_parcala(text: str, limit: int = 220) -> list[str]:
    """Cümleleri toplayıp ~limit karakterlik parçalara böler (model kısa girdide daha kararlı)."""
    out, cur = [], ""
    for c in re.split(r"(?<=[.!?…])\s+", text):
        if cur and len(cur) + len(c) + 1 > limit:
            out.append(cur)
            cur = c
        else:
            cur = (cur + " " + c).strip()
    if cur:
        out.append(cur)
    return out


def _chatterbox(text: str) -> bytes:
    global _cb_model
    import io
    import wave

    try:
        import numpy as np
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except ImportError as e:
        raise VoiceError("Chatterbox için: pip install -r requirements-ses.txt") from e
    text = hazirla_metin(text)
    if not text:
        raise VoiceError("Okunacak metin boş.")
    with _cb_lock:  # model aynı anda tek iş yapar
        if _cb_model is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                _cb_model = ChatterboxMultilingualTTS.from_pretrained(device=device)
            except Exception as e:
                raise VoiceError(f"Chatterbox modeli yüklenemedi: {e}") from e
        kw = {"language_id": "tr", "exaggeration": 0.5, "cfg_weight": 0.5}
        if VOICE_SAMPLE.exists():  # kullanıcının ses örneği varsa onun sesiyle; yoksa paketin varsayılan sesi
            kw["audio_prompt_path"] = str(VOICE_SAMPLE)
        sr = int(getattr(_cb_model, "sr", 24000))
        parts = []
        for parca in _cb_parcala(text):
            with torch.inference_mode():
                w = _cb_model.generate(parca, **kw)
            parts.append(np.asarray(w.detach().cpu().numpy(), dtype=np.float32).reshape(-1))
            parts.append(np.zeros(int(sr * 0.12), dtype=np.float32))
    wav = shorten_pauses(np.concatenate(parts), sr)
    pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def shorten_pauses(wav, rate: int, max_pause: float = 0.3, keep: float = 0.24):
    """XTTS cümleleri ayrı üretip arasına ~1 sn sessizlik koyuyor; uzun sessizlikleri doğal uzunluğa indirir,
    baştaki/sondaki sessizliği de kırpar."""
    import numpy as np

    win = int(rate * 0.02)
    if len(wav) < win * 3:
        return wav
    frames = len(wav) // win
    energy = np.sqrt(np.mean(wav[: frames * win].reshape(frames, win) ** 2, axis=1))
    silent = energy < max(0.008, energy.max() * 0.05)
    out, i = [], 0
    while i < frames:
        j = i
        while j < frames and silent[j] == silent[i]:
            j += 1
        seg = wav[i * win: j * win]
        if silent[i]:
            edge = i == 0 or j == frames
            limit = 0.05 if edge else (keep if (j - i) * 0.02 > max_pause else max_pause)
            seg = seg[: int(rate * limit)]
        out.append(seg)
        i = j
    out.append(wav[frames * win:])
    return np.concatenate(out)


def _patch_xtts_loader() -> None:
    """XTTS ses örneğini torchaudio/torchcodec ile okur; bu ikisinin sürüm uyuşmazlığı sık görülür.
    Okumayı PyAV ile yaparak kurulumu sağlamlaştırırız."""
    try:
        import av
        import numpy as np
        import torch
        import TTS.tts.models.xtts as xtts_mod
    except ImportError:
        return

    def load_audio(path, sampling_rate):
        c = av.open(str(path))
        rs = av.AudioResampler(format="flt", layout="mono", rate=sampling_rate)
        chunks = [f.to_ndarray().reshape(-1) for fr in c.decode(audio=0) for f in rs.resample(fr)]
        chunks += [f.to_ndarray().reshape(-1) for f in rs.resample(None)]
        c.close()
        return torch.from_numpy(np.concatenate(chunks).astype("float32")).unsqueeze(0)

    xtts_mod.load_audio = load_audio


def save_voice_sample(data: bytes, filename: str) -> float:
    """Yüklenen ses örneğini 22.05 kHz mono WAV'a çevirip saklar; süresini (sn) döndürür."""
    import io
    import wave

    try:
        import av
        import numpy as np
    except ImportError as e:
        raise VoiceError("Ses paketi eksik: pip install -r requirements.txt") from e
    try:
        container = av.open(io.BytesIO(data))
        resampler = av.AudioResampler(format="s16", layout="mono", rate=22050)
        chunks = []
        for frame in container.decode(audio=0):
            for f in resampler.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
        container.close()
    except Exception as e:
        raise VoiceError(f"Ses dosyası okunamadı: {e}") from e
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    seconds = len(pcm) / 22050
    if seconds < 6:
        raise VoiceError("Ses örneği çok kısa: en az 6, ideal 15-30 saniye olmalı.")
    pcm = pcm[: 22050 * 40]  # 40 sn yeter
    VOICE_SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(VOICE_SAMPLE), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(pcm.astype("<i2").tobytes())
    return min(seconds, 40.0)


# ---------------------------------------------------------------- Whisper (ücretsiz yerel STT)
_whisper_models: dict = {}
_whisper_lock = threading.Lock()
WHISPER_STATE = {"state": "beklemede", "detail": ""}  # beklemede | hazırlanıyor | hazır | hata


def _whisper_model():
    from faster_whisper import WhisperModel

    size = load_settings().get("whisper_model", "large-v3-turbo")
    model = _whisper_models.get(size)
    if model is None:
        WHISPER_STATE.update(state="hazırlanıyor", detail=size)
        try:
            model = WhisperModel(size, device="auto", compute_type="int8")
        except Exception as e:
            WHISPER_STATE.update(state="hata", detail=str(e)[:300])
            raise
        _whisper_models[size] = model
        WHISPER_STATE.update(state="hazır", detail=size)
    return model


def warm_whisper() -> None:
    try:
        with _whisper_lock:
            _whisper_model()
    except Exception:  # durum _whisper_model içinde "hata" olarak işaretlendi
        pass


def _whisper(audio: bytes, filename: str = "", long_form: bool = False) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise VoiceError("Konuşma tanıma paketi eksik: pip install -r requirements.txt") from e
    import io

    with _whisper_lock:
        model = _whisper_model()
        segments, _ = model.transcribe(io.BytesIO(audio), language="tr", vad_filter=True,
                                       beam_size=5 if long_form else 1)
        return " ".join(seg.text.strip() for seg in segments).strip()


async def transcribe_long(audio: bytes, filename: str, content_type: str) -> str:
    """Uzun ders kaydı (dakikalar-saatler) → metin."""
    if load_settings().get("stt_provider", "elevenlabs") == "whisper":
        return await asyncio.to_thread(_whisper, audio, filename, True)
    r = await _http().post(
        f"{API}/speech-to-text",
        headers=_headers(),
        data={"model_id": "scribe_v1", "language_code": "tur", "tag_audio_events": "false"},
        files={"file": (filename, audio, content_type)},
        timeout=httpx.Timeout(1800.0, connect=15.0),
    )
    if r.status_code != 200:
        raise VoiceError(f"ElevenLabs metne çevirme hatası {r.status_code}: {r.text[:200]}")
    return (r.json().get("text") or "").strip()
