"""Yerel yapay zeka (Ollama) ile hoca: canlı anlatım akışı + yapılandırılmış (JSON şemalı) çıktılar.

Uygulamanın iç mesaj biçimi ({"role", "content": [blok...]}) Ollama'nın /api/chat biçimine çevrilir:
metin blokları birleştirilir, görüntüler "images" listesine, PDF'ler metne (gerekirse sayfa görüntüsüne) dönüşür.
Küçük bağlam pencereli yerel modellerde eski konuşma turları sığacak kadar kırpılır; sistem talimatı ve son
soru her zaman korunur.
"""
from __future__ import annotations

import base64
import io
import json
from typing import AsyncIterator

import httpx

from . import yerel
from .config import load_settings


class YerelError(RuntimeError):
    def __init__(self, msg: str, unavailable: bool = False):
        super().__init__(msg)
        self.unavailable = unavailable


CHARS_PER_TOKEN = 3.0  # Türkçe metinde kaba ortalama
OUTPUT_RESERVE = 4096  # cevap için ayrılan token


def system_text(system, sabit: bool = False) -> str:
    """sabit=True: yalnızca her soruda aynı kalan bloklar (Ollama önceki sorudan hesapladığını yeniden kullanır)."""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system or [] if not (sabit and b.get("degisken")))


def degisken_text(system) -> str:
    """Soruya göre değişen bağlam (kütüphane alıntıları, hafıza, seçilen not parçaları): son soruya eklenir."""
    if isinstance(system, str):
        return ""
    return "\n\n".join(b.get("text", "") for b in system or [] if b.get("degisken"))


def _pdf_parts(b64: str) -> tuple[str, list[str]]:
    """PDF → (metin, metni olmayan ilk sayfaların görüntüleri)."""
    data = base64.b64decode(b64)
    text, images = "", []
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:40])[:30000]
    except Exception:
        pass
    if len(text.strip()) < 200:
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(data)
            try:
                for i in range(min(4, len(pdf))):
                    buf = io.BytesIO()
                    pdf[i].render(scale=1.4).to_pil().save(buf, format="PNG")
                    images.append(base64.b64encode(buf.getvalue()).decode())
            finally:
                pdf.close()
        except Exception:
            pass
    return text, images


def _convert(content) -> tuple[str, list[str]]:
    if isinstance(content, str):
        return content, []
    texts, images = [], []
    for b in content:
        t = b.get("type")
        if t == "text" and b.get("text"):
            texts.append(b["text"])
        elif t == "image" and b.get("source", {}).get("type") == "base64":
            images.append(b["source"]["data"])
        elif t == "document" and b.get("source", {}).get("type") == "base64":
            txt, imgs = _pdf_parts(b["source"]["data"])
            title = b.get("title") or "belge"
            texts.append(f"[Ekli PDF: {title}]\n{txt}" if txt.strip() else f"[Ekli PDF: {title} (görüntü olarak eklendi)]")
            images.extend(imgs)
    return "\n\n".join(texts), images


def to_messages(system, messages: list[dict], ctx: int) -> list[dict]:
    """Ollama mesaj listesi; bağlama sığmayan en eski turlar atılır."""
    conv: list[dict] = []
    for m in messages:
        if m.get("role") not in ("user", "assistant"):
            continue
        text, images = _convert(m["content"])
        if not text and not images:
            continue
        if conv and conv[-1]["role"] == m["role"]:
            conv[-1]["content"] += "\n\n" + text
            conv[-1].setdefault("images", []).extend(images)
            continue
        item = {"role": m["role"], "content": text}
        if images:
            item["images"] = images
        conv.append(item)
    sys_txt = system_text(system)
    budget = int((ctx - OUTPUT_RESERVE) * CHARS_PER_TOKEN) - len(sys_txt)
    size = lambda x: len(x["content"]) + 1500 * len(x.get("images", []))  # görüntü ≈ 500 token
    while len(conv) > 1 and sum(size(x) for x in conv) > budget:
        conv.pop(0)
        while conv and conv[0]["role"] != "user":  # konuşma kullanıcıyla başlamalı
            conv.pop(0)
    # Eski turlardaki görüntüleri at (yalnızca son mesajınkiler gerekli; bellek ve hız için)
    for x in conv[:-1]:
        x.pop("images", None)
    # Hız: sistem talimatı ve önceki turlar her soruda AYNI kalırsa Ollama onları yeniden okumaz (önbellek).
    # Soruya göre değişen bağlam bu yüzden sistem talimatına değil, yalnızca son soruya eklenir.
    sabit, degisken = system_text(system, sabit=True), degisken_text(system)
    if degisken and conv and conv[-1]["role"] == "user":
        conv[-1] = {**conv[-1], "content": "<baglam>\n" + degisken + "\n</baglam>\n\n" + conv[-1]["content"]}
    out = [{"role": "system", "content": sabit}] if sabit else []
    return out + conv


def _options(temperature: float, num_predict: int | None = None) -> dict:
    o = {"num_ctx": yerel.baglam(), "temperature": temperature}
    if num_predict:
        o["num_predict"] = num_predict
    return o


async def _ready() -> str:
    if not await yerel.ensure_ready():
        raise YerelError(yerel.durum_mesaji(), unavailable=True)
    return yerel.STATE.get("model") or yerel.secili_model()


def _err(e: Exception) -> YerelError:
    if isinstance(e, YerelError):
        return e
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
        yerel.STATE["state"] = "bilinmiyor"  # bir sonraki istekte yeniden başlatılmayı dene
        return YerelError("Yerel yapay zeka programına bağlanılamadı; yeniden başlatılıyor, birazdan tekrar dene.",
                          unavailable=True)
    return YerelError(f"Yerel yapay zeka hatası: {str(e)[:300]}")


async def _post_stream(payload: dict) -> AsyncIterator[dict]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=600)) as c:
        async with c.stream("POST", f"{yerel.HOST}/api/chat", json=payload) as r:
            if r.status_code >= 400:
                body = (await r.aread()).decode("utf-8", "replace")
                try:
                    msg = json.loads(body).get("error", body)
                except json.JSONDecodeError:
                    msg = body
                raise YerelError(f"Yerel yapay zeka hatası: {msg[:300]}")
            async for line in r.aiter_lines():
                if line.strip():
                    d = json.loads(line)
                    if d.get("error"):
                        raise YerelError(f"Yerel yapay zeka hatası: {d['error'][:300]}")
                    yield d


async def _chat_stream(payload: dict) -> AsyncIterator[dict]:
    """'think' alanını desteklemeyen modellerde alanı kaldırıp bir kez daha dener."""
    try:
        async for d in _post_stream(payload):
            yield d
    except YerelError as e:
        if "think" in str(e).lower() and "think" in payload:
            payload = {k: v for k, v in payload.items() if k != "think"}
            async for d in _post_stream(payload):
                yield d
        else:
            raise


# ---------------------------------------------------------------- canlı anlatım
async def stream_text(system, messages: list[dict]) -> AsyncIterator[str]:
    model = await _ready()
    payload = {"model": model, "messages": to_messages(system, messages, yerel.baglam()), "stream": True,
               "think": False, "keep_alive": "30m", "options": _options(load_settings().get("yerel_sicaklik", 0.6))}
    try:
        async for d in _chat_stream(payload):
            text = (d.get("message") or {}).get("content")
            if text:
                yield text
    except Exception as e:
        raise _err(e) from e


# ---------------------------------------------------------------- yapılandırılmış çıktı
JSON_NOTE = ("\n\nCevabını YALNIZCA verilen JSON şemasına uyan tek bir JSON nesnesi olarak ver; "
             "açıklama, kod bloğu ya da başka metin ekleme. Metin alanları Türkçe olsun.")


async def parse(model_cls, content, system=None, max_tokens: int = 16000):
    model = await _ready()
    schema = model_cls.model_json_schema()
    msgs = [{"role": "user", "content": content if not isinstance(content, str) else [{"type": "text", "text": content}]}]
    msgs[0]["content"] = list(msgs[0]["content"]) + [{"type": "text", "text": JSON_NOTE}]
    last_err = None
    for attempt in range(2):
        payload = {"model": model, "messages": to_messages(system, msgs, yerel.baglam()), "stream": True,
                   "think": False, "format": schema, "keep_alive": "30m",
                   "options": _options(0.2 if attempt else 0.4, min(max_tokens, 16384))}
        parts, reason = [], ""
        try:
            async for d in _chat_stream(payload):
                parts.append((d.get("message") or {}).get("content") or "")
                if d.get("done"):
                    reason = d.get("done_reason", "")
        except Exception as e:
            raise _err(e) from e
        raw = "".join(parts).strip()
        try:
            return model_cls.model_validate_json(raw)
        except Exception as e:  # şemaya uymayan / yarım kalan cevap: bir kez daha dene
            last_err = e
            if reason == "length":
                raise YerelError("Cevap modelin sınırına sığmadı; kapsamı daraltıp tekrar dene.") from e
    raise YerelError("Yerel yapay zeka geçerli bir cevap üretemedi, tekrar dene.") from last_err
