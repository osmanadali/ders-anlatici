import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

import fakes
from app import config, llm, llm_gemini, main

fakes.install()


def test_to_contents_converts_and_merges():
    png = base64.b64encode(b"\x89PNG....").decode()
    msgs = [
        {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}},
                                     {"type": "text", "text": "bunu çöz"}]},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "x"},
                                          {"type": "text", "text": '{"say":"tamam","board":[]}'}]},
        {"role": "user", "content": "devam"},
        {"role": "user", "content": [{"type": "text", "text": "ve?"}]},
    ]
    c = llm_gemini.to_contents(msgs)
    assert [x.role for x in c] == ["user", "model", "user"]
    assert c[0].parts[0].inline_data.mime_type == "image/png"
    assert c[1].parts[0].text.startswith('{"say"')  # thinking bloğu gönderilmedi
    assert len(c[2].parts) == 2  # art arda kullanıcı mesajları birleşti


@pytest.fixture()
def gemini(monkeypatch):
    """stream_steps'i sahte değil, gerçek yönlendiriciyle çalıştır; Gemini ağı yerine sahte metin akışı."""
    monkeypatch.setattr(llm, "stream_steps", llm.real_stream_steps)
    config.save_settings({"llm_provider": "gemini", "deep_solve": "auto"})
    calls = {"stream": [], "parse": []}

    async def stream_text(system, messages):
        calls["stream"].append(messages)
        for chunk in ['{"say": "Önce verilen', 'lere bakalım.", "board": [{"op":"write","text":"x"}]}\n', '{"say": "Bitti.", "board": []}']:
            yield chunk

    async def parse(model_cls, content, system=None, max_tokens=16000):
        calls["parse"].append(content)
        return model_cls(konu="Türev", verilenler="f", istenen="f'", yontem="zincir kuralı, çünkü bileşke",
                         on_bilgi="(f∘g)'=f'(g)g'", adimlar=[llm.SolutionStep(islem="$u=x^2$", gerekce="iç fonksiyon")],
                         sonuc="2x cos(x^2)", kontrol="türev tanımıyla", sik_hatalar="iç türevi unutmak", puf_noktasi="dıştan içe")

    monkeypatch.setattr(llm_gemini, "stream_text", stream_text)
    monkeypatch.setattr(llm_gemini, "parse", parse)
    yield calls
    config.save_settings({"llm_provider": "", "deep_solve": "auto"})


def test_gemini_stream_with_deep_solve(gemini):
    with TestClient(main.app) as c:
        r = c.post("/api/ask", data={"text": "sin(x^2) fonksiyonunun türevini nasıl buluruz?"})
    ev = [json.loads(l[6:]) for l in r.text.split("\n\n") if l.startswith("data: ")]
    assert any(e["type"] == "status" for e in ev)
    steps = [e for e in ev if e["type"] == "step"]
    assert [s["say"] for s in steps] == ["Önce verilenlere bakalım.", "Bitti."]
    sent = gemini["stream"][-1][-1]["content"][-1]["text"]
    assert "<cozum_taslagi>" in sent and "gerekçe: iç fonksiyon" in sent
    # geçmişe taslak değil, öğrencinin asıl mesajı yazılır
    sid = ev[0]["id"]
    from app import store

    hist = store.load_session(sid)["messages"]
    assert "cozum_taslagi" not in json.dumps(hist, ensure_ascii=False)
    assert hist[-1]["content"][0]["text"].startswith('{"say": "Önce')


def test_short_chat_skips_deep_solve(gemini):
    with TestClient(main.app) as c:
        c.post("/api/ask", data={"text": "tamam anladım", "style": "konusma"})
    assert gemini["parse"] == []


def test_quota_falls_back_to_claude(monkeypatch):
    config.save_settings({"llm_provider": "gemini"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    async def boom(system, messages):
        raise llm_gemini.GeminiError("kota", quota=True)
        yield  # noqa

    async def claude(system, messages):
        yield {"say": "claude", "board": []}

    monkeypatch.setattr(llm_gemini, "stream_text", boom)
    monkeypatch.setattr(llm, "_claude_stream_steps", claude)

    async def run():
        return [x async for x in llm.real_stream_steps([], [{"role": "user", "content": "x"}])]

    out = asyncio.run(run())
    assert "notice" in out[0] and out[1]["say"] == "claude"
    config.save_settings({"llm_provider": ""})


def test_provider_auto(monkeypatch):
    config.save_settings({"llm_provider": ""})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert llm.provider() == "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert llm.provider() == "claude"


class _Err(Exception):
    def __init__(self, code):
        super().__init__(f"{code} NOT_FOUND")
        self.code = code


class _FakeModel:
    def __init__(self, name):
        self.name = "models/" + name
        self.supported_actions = ["generateContent"]


class _FakeAio:
    def __init__(self, available, calls):
        self.available, self.calls = available, calls

    async def list(self):
        async def gen():
            for n in self.available:
                yield _FakeModel(n)
        return gen()

    async def generate_content_stream(self, model, contents, config):
        self.calls.append(model)
        if model not in self.available:
            raise _Err(404)

        async def gen():
            class C:
                text = '{"say": "Merhaba", "board": []}\n'
            yield C()
        return gen()


def test_missing_model_is_auto_replaced(monkeypatch):
    """Kullanıcının yaşadığı hata: kayıtlı 'gemini-flash-latest' 404 → mevcut en uygun Flash modeline geç."""
    calls = []
    fake = type("C", (), {})()
    fake.aio = type("A", (), {})()
    fake.aio.models = _FakeAio(["gemini-2.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-pro-preview"], calls)
    monkeypatch.setattr(llm_gemini, "client", lambda: fake)
    monkeypatch.setattr(llm_gemini, "_resolved", "")
    config.save_settings({"gemini_model": "gemini-flash-latest"})

    async def run():
        return [t async for t in llm_gemini.stream_text("sistem", [{"role": "user", "content": "selam"}])]

    out = asyncio.run(run())
    assert out == ['{"say": "Merhaba", "board": []}\n']
    assert calls == ["gemini-flash-latest", "gemini-3.8-flash"]
    assert config.load_settings()["gemini_model"] == ""  # bozuk seçim temizlendi, otomatiğe döndü


def test_pick_default_prefers_stable_flash():
    assert llm_gemini.pick_default(["gemini-3.1-pro-preview", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]) == "gemini-3.8-flash"
    assert llm_gemini.pick_default(["gemini-2.5-flash-lite"]) == "gemini-2.5-flash-lite"
