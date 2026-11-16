"""Ayarlar: .env dosyası + arayüzden değiştirilebilen kalıcı ayarlar."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", "veri"))
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")

# Notların tamamı bu karakter sınırının altındaysa hepsi modele verilir (önbellekli);
# üstündeyse soruyla ilgili sayfalar seçilir.
FULL_NOTES_CHAR_LIMIT = int(os.getenv("FULL_NOTES_CHAR_LIMIT", "600000"))

DEFAULTS = {
    "voice_id": os.getenv("VOICE_ID", "zu3iuxxlZoTwzmAUvpNF"),  # Osman Adalı (TR klon)
    "voice_name": "Osman Adalı",
    "tts_model": os.getenv("TTS_MODEL", "eleven_multilingual_v2"),
    "llm_provider": os.getenv("LLM_PROVIDER", ""),  # "" = otomatik (hangi anahtar varsa) | claude | gemini
    "gemini_model": os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
    "deep_solve": os.getenv("DEEP_SOLVE", "auto"),  # auto (Gemini'de açık) | on | off
    "claude_fallback": True,  # Gemini kotası dolarsa (Claude anahtarı varsa) Claude'a geç
    "claude_model": os.getenv("CLAUDE_MODEL", "claude-opus-5-5"),
    "effort": os.getenv("EFFORT", "medium"),
    "level": "normal",  # basit | normal | ileri
    "tts_enabled": True,  # eski ayar; tts_provider="browser" ile aynı anlamda
    "tts_provider": os.getenv("TTS_PROVIDER", "edge"),  # edge (ücretsiz) | xtts (ücretsiz klon) | browser | elevenlabs (ücretli, isteğe bağlı)
    "edge_voice": "tr-TR-EmelNeural",
    "stt_provider": os.getenv("STT_PROVIDER", "whisper"),  # whisper (ücretsiz) | elevenlabs (ücretli, isteğe bağlı)
    "whisper_model": os.getenv("WHISPER_MODEL", "large-v3-turbo"),  # small = hızlı, large-v3-turbo = isabetli
    "web_search": False,  # hoca gerektiğinde internette arama yapabilsin
}

_SETTINGS_FILE = DATA_DIR / "ayarlar.json"


def load_settings() -> dict:
    s = dict(DEFAULTS)
    if _SETTINGS_FILE.exists():
        try:
            s.update(json.loads(_SETTINGS_FILE.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    if s.get("tts_enabled") is False:
        s["tts_provider"] = "browser"
    s["tts_enabled"] = s["tts_provider"] != "browser"
    return s


def save_settings(patch: dict) -> dict:
    s = load_settings()
    for k, v in patch.items():
        if k in DEFAULTS:
            s[k] = v
    if "tts_provider" in patch:
        s["tts_enabled"] = patch["tts_provider"] != "browser"
    _SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")
    return s
