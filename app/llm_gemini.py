"""Google Gemini (ücretsiz kota) ile hoca.

Uygulamanın geri kalanı Claude biçimindeki mesajlarla çalışır; bu modül onları Gemini biçimine
çevirir, aynı adım protokolünü (say + board satırları) aynı talimatlarla kullanır.
"""
from __future__ import annotations

import base64
from typing import AsyncIterator

from .config import GEMINI_API_KEY, load_settings

_client = None


class GeminiError(RuntimeError):
    def __init__(self, msg: str, quota: bool = False):
        super().__init__(msg)
        self.quota = quota


def client():
    global _client
    if not GEMINI_API_KEY:
        raise GeminiError("Gemini seçili ama GEMINI_API_KEY yok. Ücretsiz anahtar: https://aistudio.google.com/apikey")
    if _client is None:
        try:
            from google import genai
        except ImportError as e:
            raise GeminiError("Gemini paketi eksik: pip install -r requirements.txt") from e
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _model() -> str:
    return load_settings().get("gemini_model") or "gemini-flash-latest"


# ---------------------------------------------------------------- biçim dönüştürme
def _parts(content) -> list:
    from google.genai import types

    if isinstance(content, str):
        return [types.Part.from_text(text=content)] if content else []
    out = []
    for b in content:
        t = b.get("type")
        if t == "text" and b.get("text"):
            out.append(types.Part.from_text(text=b["text"]))
        elif t in ("image", "document") and b.get("source", {}).get("type") == "base64":
            src = b["source"]
            out.append(types.Part.from_bytes(data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
        # thinking, fallback, araç blokları vb. Gemini'ye gönderilmez
    return out


def to_contents(messages: list[dict]) -> list:
    """Claude biçimindeki geçmişi Gemini 'contents' listesine çevirir (aynı rol art arda gelirse birleştirir)."""
    from google.genai import types

    out: list = []
    for m in messages:
        if m.get("role") not in ("user", "assistant"):
            continue
        role = "user" if m["role"] == "user" else "model"
        parts = _parts(m["content"])
        if not parts:
            continue
        if out and out[-1].role == role:
            out[-1].parts.extend(parts)
        else:
            out.append(types.Content(role=role, parts=parts))
    return out


def system_text(system) -> str:
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system or [])


def _err(e: Exception) -> GeminiError:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    msg = str(e)
    if code == 429 or "RESOURCE_EXHAUSTED" in msg:
        return GeminiError("Gemini ücretsiz kotası şimdilik doldu (dakikalık ya da günlük sınır). Biraz bekleyip tekrar dene.",
                           quota=True)
    if code in (401, 403) or "API_KEY" in msg.upper():
        return GeminiError("Gemini anahtarı geçersiz (.env → GEMINI_API_KEY).")
    if code == 404:
        return GeminiError(f"Gemini modeli bulunamadı: {_model()}. Ayarlar'dan başka bir model seç.")
    return GeminiError(f"Gemini hatası: {msg[:300]}")


# ---------------------------------------------------------------- canlı anlatım
async def stream_text(system, messages: list[dict]) -> AsyncIterator[str]:
    from google.genai import types

    cfg = types.GenerateContentConfig(system_instruction=system_text(system), max_output_tokens=32000)
    try:
        stream = await client().aio.models.generate_content_stream(model=_model(), contents=to_contents(messages), config=cfg)
        async for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text
    except GeminiError:
        raise
    except Exception as e:  # google.genai.errors.APIError ve ağ hataları
        raise _err(e) from e


# ---------------------------------------------------------------- yapılandırılmış çıktı
async def parse(model_cls, content, system=None, max_tokens: int = 16000):
    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=system_text(system) or None,
        response_mime_type="application/json",
        response_schema=model_cls,
        max_output_tokens=max_tokens,
    )
    try:
        resp = await client().aio.models.generate_content(
            model=_model(), contents=to_contents([{"role": "user", "content": content}]), config=cfg
        )
    except GeminiError:
        raise
    except Exception as e:
        raise _err(e) from e
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, model_cls):
        return parsed
    try:
        return model_cls.model_validate_json(resp.text or "")
    except Exception as e:
        raise GeminiError("Gemini geçerli bir cevap üretemedi, tekrar dene.") from e


async def list_models() -> list[str]:
    """Bu anahtarla kullanılabilen, metin üretebilen Gemini modelleri."""
    names = []
    try:
        pager = await client().aio.models.list()
        async for m in pager:
            actions = getattr(m, "supported_actions", None) or []
            name = (m.name or "").removeprefix("models/")
            if "generateContent" in actions and "gemini" in name and not any(
                x in name for x in ("embedding", "image", "tts", "audio", "live", "veo")
            ):
                names.append(name)
    except GeminiError:
        raise
    except Exception as e:
        raise _err(e) from e
    return sorted(set(names), key=lambda n: ("latest" not in n, n))
