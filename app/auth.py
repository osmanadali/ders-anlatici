"""Telefondan (uzaktan) erişim için şifre koruması.

Bilgisayarın kendisinden (localhost) gelen istekler serbesttir. Tünel (Cloudflare) ya da ağ üzerinden
gelen istekler, ERISIM_SIFRESI ile giriş yapılmış bir çerez ister. Böylece adresi öğrenen biri
API kredilerini harcayamaz.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .config import DATA_DIR

COOKIE = "ders_oturum"
PHONE_FILE = DATA_DIR / "telefon.json"  # baslat.py --telefon yazar: {"url": ..., "password": ...}
_SECRET_FILE = DATA_DIR / ".gizli_anahtar"
OPEN_PATHS = {"/giris", "/api/login", "/manifest.webmanifest", "/static/icon-192.png", "/static/icon-512.png", "/favicon.ico"}


def _secret() -> bytes:
    if not _SECRET_FILE.exists():
        _SECRET_FILE.write_bytes(secrets.token_bytes(32))
    return _SECRET_FILE.read_bytes()


def phone_info() -> dict:
    if PHONE_FILE.exists():
        try:
            return json.loads(PHONE_FILE.read_text("utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def password() -> str:
    return os.getenv("ERISIM_SIFRESI") or phone_info().get("password", "")


def _token(pw: str) -> str:
    return hmac.new(_secret(), pw.encode(), hashlib.sha256).hexdigest()


def is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    proxied = any(h in request.headers for h in ("x-forwarded-for", "cf-connecting-ip", "forwarded"))
    return host in ("127.0.0.1", "::1", "localhost", "testclient") and not proxied


def authorized(request: Request) -> bool:
    if is_local(request):
        return True
    pw = password()
    if not pw:
        return False
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), _token(pw))


async def middleware(request: Request, call_next):
    if request.url.path in OPEN_PATHS or authorized(request):
        return await call_next(request)
    if not password():
        return HTMLResponse(
            "<h3>Uzaktan erişim kapalı.</h3><p>Telefondan kullanmak için bilgisayarda <code>python baslat.py --telefon</code> çalıştır.</p>",
            status_code=403,
        )
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Giriş gerekli"}, status_code=401)
    return RedirectResponse("/giris")


LOGIN_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ders Anlatıcı: Giriş</title>
<style>body{font:16px system-ui;background:#23302b;color:#f3f1e8;display:grid;place-items:center;min-height:100vh;margin:0}
form{display:flex;flex-direction:column;gap:12px;width:min(320px,90vw)}input,button{font:inherit;padding:12px;border-radius:10px;border:0}
button{background:#4aa38a;color:#0e1512;font-weight:700}p{opacity:.7;font-size:14px}.e{color:#ff8a80}</style></head>
<body><form method="post" action="/api/login"><h2>✎ Ders Anlatıcı</h2>
<input name="sifre" type="password" placeholder="Erişim şifresi" autofocus autocomplete="current-password">
<button>Giriş</button>{err}<p>Şifre, bilgisayarda baslat.py --telefon çalıştırınca ekranda yazar.</p></form></body></html>"""


def login_page(error: bool = False) -> HTMLResponse:
    return HTMLResponse(LOGIN_HTML.replace("{err}", '<div class="e">Şifre yanlış.</div>' if error else ""))


def login_response(given: str, secure: bool):
    pw = password()
    if not pw or not hmac.compare_digest(given.strip(), pw):
        return login_page(error=True)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(COOKIE, _token(pw), max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax", secure=secure)
    return r
