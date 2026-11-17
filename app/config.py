"""Ayarlar: .env dosyası + arayüzden değiştirilebilen kalıcı ayarlar."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", "veri"))
if not DATA_DIR.is_absolute():
    DATA_DIR = ROOT / DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)


# Notların tamamı bu karakter sınırının altındaysa hepsi modele verilir (önbellekli);
# üstündeyse soruyla ilgili sayfalar seçilir.
FULL_NOTES_CHAR_LIMIT = int(os.getenv("FULL_NOTES_CHAR_LIMIT", "200000"))  # ~55 bin token; üstünde ilgili sayfalar seçilir

# ---------------------------------------------------------------- API anahtarları
# Anahtarlar her kullanımda ortamdan okunur; Ayarlar'dan girilince yeniden başlatma gerekmez.
KEY_NAMES = {"gemini": "GEMINI_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}  # ikisi de isteğe bağlı


def gemini_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def elevenlabs_key() -> str:
    return os.getenv("ELEVENLABS_API_KEY", "").strip()


def save_keys(keys: dict) -> None:
    """Anahtarları .env dosyasına yazar (diğer satırlara dokunmadan) ve hemen etkinleştirir."""
    env = ROOT / ".env"
    lines = env.read_text("utf-8").splitlines() if env.exists() else []
    for short, value in keys.items():
        name = KEY_NAMES.get(short)
        if not name or value is None:
            continue
        value = str(value).strip().replace("\n", "")
        line = f"{name}={value}"
        for i, ln in enumerate(lines):
            if re.match(rf"^\s*#?\s*{name}\s*=", ln):
                lines[i] = line
                break
        else:
            lines.append(line)
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
    env.write_text("\n".join(lines) + "\n", "utf-8")
    try:
        os.chmod(env, 0o600)  # anahtarlar yalnızca kullanıcıya açık olsun
    except OSError:
        pass


DEFAULTS = {
    "voice_id": os.getenv("VOICE_ID", "zu3iuxxlZoTwzmAUvpNF"),  # Osman Adalı (TR klon)
    "voice_name": "Osman Adalı",
    "tts_model": os.getenv("TTS_MODEL", "eleven_multilingual_v2"),
    "llm_provider": os.getenv("LLM_PROVIDER", ""),  # "" = otomatik (yerel öncelikli) | yerel | gemini
    "yerel_model": os.getenv("YEREL_MODEL", ""),  # boş = donanıma göre otomatik (gemma4:e2b … gemma4:26b)
    "yerel_ctx": int(os.getenv("YEREL_CTX", "0")),  # 0 = modele göre otomatik
    "yerel_sicaklik": 0.6,
    "gemini_model": os.getenv("GEMINI_MODEL", ""),  # boş = anahtarın erişebildiği en uygun Flash modeli otomatik
    "deep_solve": os.getenv("DEEP_SOLVE", "auto"),  # auto (Gemini'de açık) | on | off
    "hesap_araclari": True,  # sayısal mühendislik sorularında gerçek hesap araçları (EOQ, MRP, LP, kuyruk…) kullanılsın
    "level": "normal",  # basit | normal | ileri
    "tts_enabled": True,  # eski ayar; tts_provider="browser" ile aynı anlamda
    "tts_provider": os.getenv("TTS_PROVIDER", "edge"),  # edge (ücretsiz) | xtts (ücretsiz klon) | browser | elevenlabs (ücretli, isteğe bağlı)
    "edge_voice": "tr-TR-AhmetNeural",
    "_ses_v2": False,  # bir kerelik ses geçişi yapıldı mı
    "_ses_v3": False,  # ikinci bir kerelik geçiş: örneksiz xtts/piper/browser → Edge Ahmet
    "edge_rate": "+4%",
    "edge_pitch": "-2Hz",
    "stt_provider": os.getenv("STT_PROVIDER", "whisper"),  # whisper (ücretsiz) | elevenlabs (ücretli, isteğe bağlı)
    "whisper_model": os.getenv("WHISPER_MODEL", "large-v3-turbo"),  # small = hızlı, large-v3-turbo = isabetli
    "web_search": False,  # hoca gerektiğinde internette arama yapabilsin
    "otomatik_paket": True,  # yeni not eklenince özet, konu anlatımı ve deneme sınavları kendiliğinden güncellensin
    "gomme_modeli": os.getenv("GOMME_MODELI", "qwen3-embedding:0.6b"),  # kütüphane anlam araması (yerel gömme modeli)
    "kutuphane_ocr": False,  # kütüphanedeki taranmış PDF sayfalarını yerel yapay zekayla oku (yavaş)
    "literatur_pdf": True,  # literatür taramasında açık erişim PDF'in tam metnini de al
    "openalex_api_key": "",  # isteğe bağlı: OpenAlex kotası dolarsa
    "kutuphane_dosya_sakla": False,  # kitap öğrenildikten sonra PDF kopyası silinir (metin veritabanında)
    "kitap_otomatik": True,  # literatür taramasında derslere uyan serbest lisanslı ders kitaplarını da ekle
    "kendi_calisma": True,  # bilgisayar boşken hoca kaynaklardan soru üretip doğrulayarak kendini hazırlar
    "ogretme_tarzi": "anlat",  # anlat | sokratik (önce öğrenciye sorarak yönlendir)
    "literatur_otomatik": True,  # haftada bir literatür taraması (yeni makaleler kütüphaneye)
}

_SETTINGS_FILE = DATA_DIR / "ayarlar.json"


def load_settings() -> dict:
    s = dict(DEFAULTS)
    if _SETTINGS_FILE.exists():
        try:
            s.update(json.loads(_SETTINGS_FILE.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    if s.get("llm_provider") not in ("", "yerel", "gemini"):
        s["llm_provider"] = ""  # eski sürümlerdeki "claude" seçimi: artık yok
    if s.get("tts_enabled") is False:
        s["tts_provider"] = "browser"
    if not s.get("_ses_v2"):
        # Bir kerelik geçiş: klon sesi beğenilmedi → doğal hazır ses (Ahmet)
        if s.get("tts_provider") in ("xtts", "elevenlabs") or s.get("edge_voice") == "tr-TR-EmelNeural":
            s["tts_provider"], s["edge_voice"] = "edge", "tr-TR-AhmetNeural"
        s["_ses_v2"] = True
        try:
            _SETTINGS_FILE.write_text(json.dumps({k: v for k, v in s.items() if k in DEFAULTS},
                                                 ensure_ascii=False, indent=2), "utf-8")
        except OSError:
            pass
    if not s.get("_ses_v3"):
        # Sesler robotik bulundu: ses örneği yokken xtts/piper/tarayıcı seçili kalmışsa doğal Edge sesine geç
        if s.get("tts_provider") in ("xtts", "piper", "browser") and not (DATA_DIR / "ses_ornegi.wav").exists():
            s["tts_provider"], s["edge_voice"] = "edge", "tr-TR-AhmetNeural"
        s["_ses_v3"] = True
        try:
            _SETTINGS_FILE.write_text(json.dumps({k: v for k, v in s.items() if k in DEFAULTS},
                                                 ensure_ascii=False, indent=2), "utf-8")
        except OSError:
            pass
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
