"""ElevenLabs: metinden sese (klon ses) ve sesten metne (sesli soru)."""
from __future__ import annotations

import asyncio

import httpx

from .config import ELEVENLABS_API_KEY

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
    if not ELEVENLABS_API_KEY:
        raise VoiceError("ELEVENLABS_API_KEY tanımlı değil (.env dosyasına ekleyin).")
    return {"xi-api-key": ELEVENLABS_API_KEY}


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
