#!/usr/bin/env python3
"""Testler için sahte Ollama sunucusu (gerçek modeli indirmeden uçtan uca deneme).

Kullanım: fake_ollama.py serve   (OLLAMA_HOST=127.0.0.1:PORT, OLLAMA_MODELS=klasör ortam değişkenleriyle)
Gelen istekler OLLAMA_MODELS/istekler.jsonl dosyasına yazılır; testler oradan denetler.
- /api/chat: "format" (JSON şeması) verilirse şemaya uyan örnek bir JSON, verilmezse iki anlatım adımı akıtır.
- /api/pull: indirilen modeli OLLAMA_MODELS/modeller.json'a ekler (ilerleme satırlarıyla).
- /api/embed: deterministik sahte gömme (kelime karması tabanlı 32 boyutlu, normalize): ortak kelimeli metinler benzer.
"""
import hashlib
import math
import re
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODELS = Path(os.environ.get("OLLAMA_MODELS", "."))
MODELS.mkdir(parents=True, exist_ok=True)
DB = MODELS / "modeller.json"
LOG = MODELS / "istekler.jsonl"
STEPS = ['{"say": "Merhaba, ', 'önce tanımla başlayalım.", "board": [{"op": "title", "text": "Kalite"}]}\n',
         '{"say": "Bitti.", "board": []}']


def sample(schema: dict, root: dict | None = None):
    root = root or schema
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return sample(root.get("$defs", {})[name], root)
    for k in ("anyOf", "oneOf"):
        if k in schema:
            return sample(schema[k][0], root)
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object":
        return {k: sample(v, root) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [sample(schema.get("items", {}), root)]
    if t == "integer":
        return 1
    if t == "number":
        return 0.5
    if t == "boolean":
        return True
    return "örnek"


BOYUT = 32
_KATLA = str.maketrans("İIışŞçÇğĞöÖüÜ", "iiissccggoouu")


def sahte_vektor(metin: str) -> list[float]:
    if "\nQuery: " in metin:  # sorgu talimatı benzerliği bozmasın
        metin = metin.split("\nQuery: ", 1)[1]
    v = [0.0] * BOYUT
    for w in re.findall(r"\w{3,}", metin.translate(_KATLA).lower()):
        v[int(hashlib.sha1(w.encode()).hexdigest(), 16) % BOYUT] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _stream(self, items):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for it in items:
            self.wfile.write((json.dumps(it) + "\n").encode())
            self.wfile.flush()
            time.sleep(0.01)

    def do_GET(self):
        if self.path == "/api/version":
            return self._json({"version": "0.0-sahte"})
        if self.path == "/api/tags":
            names = json.loads(DB.read_text()) if DB.exists() else []
            return self._json({"models": [{"name": n, "model": n} for n in names]})
        self._json({"error": "yok"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"path": self.path, "body": body}, ensure_ascii=False) + "\n")
        if self.path == "/api/pull":
            names = json.loads(DB.read_text()) if DB.exists() else []
            names.append(body["model"])
            DB.write_text(json.dumps(names))
            return self._stream([{"status": "pulling manifest"},
                                 {"status": "pulling", "digest": "sha256:a", "total": 1000, "completed": 500},
                                 {"status": "pulling", "digest": "sha256:a", "total": 1000, "completed": 1000},
                                 {"status": "success"}])
        if self.path == "/api/embed":
            girdi = body.get("input")
            girdi = [girdi] if isinstance(girdi, str) else (girdi or [])
            return self._json({"model": body.get("model"), "embeddings": [sahte_vektor(t) for t in girdi]})
        if self.path == "/api/generate":
            return self._json({"done": True})
        if self.path == "/api/chat":
            if body.get("format"):
                text = json.dumps(sample(body["format"]), ensure_ascii=False)
                chunks = [text[: len(text) // 2], text[len(text) // 2:]]
            else:
                chunks = STEPS
            items = [{"message": {"role": "assistant", "content": c}, "done": False} for c in chunks]
            items.append({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"})
            if body.get("stream", True):
                return self._stream(items)
            return self._json({"message": {"role": "assistant", "content": "".join(chunks)}, "done": True})
        self._json({"error": "yok"}, 404)


def main():
    host, port = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), H).serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        main()
