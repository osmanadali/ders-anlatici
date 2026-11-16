"""Google Gemini (ücretsiz kota) ile hoca.

Uygulamanın geri kalanı ortak (blok) biçimdeki mesajlarla çalışır; bu modül onları Gemini biçimine
çevirir, aynı adım protokolünü (say + board satırları) aynı talimatlarla kullanır.
"""
from __future__ import annotations

import base64
from typing import AsyncIterator

from .config import gemini_key, load_settings

_client = None


class GeminiError(RuntimeError):
    def __init__(self, msg: str, quota: bool = False, not_found: bool = False):
        super().__init__(msg)
        self.quota = quota
        self.not_found = not_found


def client():
    global _client
    key = gemini_key()
    if not key:
        raise GeminiError("Gemini anahtarı girilmemiş: Ayarlar → API anahtarları. Ücretsiz anahtar: https://aistudio.google.com/apikey")
    if _client is None or getattr(_client, "_ders_key", None) != key:
        try:
            from google import genai
        except ImportError as e:
            raise GeminiError("Gemini paketi eksik: pip install -r requirements.txt") from e
        _client = genai.Client(api_key=key)
        _client._ders_key = key
    return _client


_resolved: str = ""


def _model() -> str:
    return load_settings().get("gemini_model") or _resolved or ""


def pick_default(names: list[str]) -> str:
    """Kullanılabilir modeller içinden varsayılanı seçer: kararlı, 'flash' (lite değil), en yeni sürüm."""
    import re

    def score(n: str):
        ver = tuple(int(x) for x in re.findall(r"(\d+)", n.split("-", 2)[1] if n.count("-") >= 1 else "")[:2]) if n else ()
        stable = not any(x in n for x in ("preview", "exp", "-latest", "tuning", "thinking"))
        kind = 2 if ("flash" in n and "lite" not in n) else 1 if "flash" in n else 0
        return (stable, kind, ver)

    usable = [n for n in names if n.startswith("gemini")]
    return max(usable, key=score) if usable else ""


async def resolve_model(force: bool = False) -> str:
    """Ayarlarda model seçilmemişse (ya da seçilen artık yoksa) anahtarın erişebildiği en uygun modeli bulur."""
    global _resolved
    chosen = load_settings().get("gemini_model") or ""
    if chosen and not force:
        return chosen
    if _resolved and not force:
        return _resolved
    names = await list_models()
    best = pick_default(names)
    if not best:
        raise GeminiError("Bu Gemini anahtarıyla kullanılabilir bir model bulunamadı.")
    _resolved = best
    if force and chosen and chosen != best:
        from .config import save_settings

        save_settings({"gemini_model": ""})  # bozuk seçimi temizle, otomatik seçime dön
    return best


async def _with_model(call):
    """Modeli çözer, çağırır; model bulunamazsa (404) bir kez otomatik seçilen modelle yeniden dener."""
    model = await resolve_model()
    try:
        return await call(model)
    except Exception as e:
        err = e if isinstance(e, GeminiError) else _err(e, model)
        if getattr(err, "not_found", False):
            model2 = await resolve_model(force=True)
            if model2 != model:
                try:
                    return await call(model2)
                except Exception as e2:
                    raise (e2 if isinstance(e2, GeminiError) else _err(e2, model2)) from e2
        raise err from e


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
    """Ortak biçimdeki geçmişi Gemini 'contents' listesine çevirir (aynı rol art arda gelirse birleştirir)."""
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


def _err(e: Exception, model: str = "") -> GeminiError:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    msg = str(e)
    if code == 429 or "RESOURCE_EXHAUSTED" in msg:
        return GeminiError("Gemini ücretsiz kotası şimdilik doldu (dakikalık ya da günlük sınır). Biraz bekleyip tekrar dene.",
                           quota=True)
    if code in (401, 403) or "API_KEY" in msg.upper():
        return GeminiError("Gemini anahtarı geçersiz (Ayarlar → API anahtarları).")
    if code == 404:
        return GeminiError(f"Gemini modeli bulunamadı: {model or _model()}. Ayarlar'dan başka bir model seç.", not_found=True)
    return GeminiError(f"Gemini hatası: {msg[:300]}")


# ---------------------------------------------------------------- canlı anlatım
async def stream_text(system, messages: list[dict]) -> AsyncIterator[str]:
    from google.genai import types

    cfg = types.GenerateContentConfig(system_instruction=system_text(system), max_output_tokens=32000)
    contents = to_contents(messages)
    for attempt in range(2):
        model = await resolve_model(force=attempt > 0)
        produced = False
        try:
            stream = await client().aio.models.generate_content_stream(model=model, contents=contents, config=cfg)
            async for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    produced = True
                    yield text
            return
        except GeminiError:
            raise
        except Exception as e:  # google.genai.errors.APIError ve ağ hataları
            err = _err(e, model)
            if err.not_found and not produced and attempt == 0:
                continue  # seçili model yok: en uygun modeli bulup bir kez daha dene
            raise err from e


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
        contents = to_contents([{"role": "user", "content": content}])
        resp = await _with_model(lambda m: client().aio.models.generate_content(model=m, contents=contents, config=cfg))
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
