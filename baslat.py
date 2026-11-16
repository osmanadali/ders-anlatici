"""Ders Anlatıcı'yı masaüstü uygulaması gibi açar.

Sunucuyu arka planda başlatır ve Chrome/Edge'i adres çubuğu olmayan kendi penceresinde
("uygulama modu") açar. Pencere kapatılınca sunucu da kapanır.

    python baslat.py            (Windows'ta "Ders Anlatici.bat" dosyasına çift tıkla)
    python baslat.py --telefon  telefondan da kullan: güvenli (HTTPS) bir adres ve şifre üretir, QR kodu gösterir
                                (cloudflared kurulu olmalı: Windows "winget install Cloudflare.cloudflared",
                                 Mac "brew install cloudflared")
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def free_port(preferred: int = 8000) -> int:
    for port in (preferred, *range(preferred + 1, preferred + 50)):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred


def find_browser() -> str | None:
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        if p := shutil.which(name):
            return p
    return None


def start_tunnel(port: int) -> tuple[subprocess.Popen | None, str]:
    """Cloudflare hızlı tüneli: hesap gerektirmez, https://....trycloudflare.com adresi verir."""
    import re

    exe = shutil.which("cloudflared")
    if not exe:
        print("! cloudflared bulunamadı. Kurulum: Windows → winget install Cloudflare.cloudflared | Mac → brew install cloudflared")
        return None, ""
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 40
    while time.time() < deadline and proc.stdout:
        line = proc.stdout.readline()
        if m := re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line):
            threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()  # çıktıyı boşalt
            return proc, m.group(0)
    print("! Tünel adresi alınamadı.")
    proc.terminate()
    return None, ""


def print_qr(url: str) -> None:
    try:
        import qrcode

        q = qrcode.QRCode(border=1)
        q.add_data(url)
        q.print_ascii(invert=True)
    except ImportError:
        pass  # QR uygulama içindeki 📱 Telefon penceresinde de var


def main() -> None:
    import json
    import secrets

    import uvicorn

    phone = "--telefon" in sys.argv
    port = free_port(int(os.getenv("PORT", "8000")))
    url = f"http://127.0.0.1:{port}/"
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)

    tunnel, phone_file = None, ROOT / os.getenv("DATA_DIR", "veri") / "telefon.json"
    if phone:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        password = os.getenv("ERISIM_SIFRESI") or "-".join(secrets.choice(
            ["kalem", "tahta", "defter", "silgi", "kitap", "sinav", "formul", "integral", "turev", "matris"]) for _ in range(2)
        ) + str(secrets.randbelow(90) + 10)
        tunnel, public = start_tunnel(port)
        if public:
            phone_file.parent.mkdir(parents=True, exist_ok=True)
            phone_file.write_text(json.dumps({"url": public, "password": password}), "utf-8")
            print(f"\n📱 Telefondan aç: {public}\n   Şifre: {password}\n")
            print_qr(public)

    browser = find_browser()
    if browser:
        profile = ROOT / "veri" / "pencere-profili"  # mikrofon izni bir kez verilir, hatırlanır
        proc = subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1400,880",
                                 "--autoplay-policy=no-user-gesture-required"])
        print(f"Ders Anlatıcı açıldı: {url}  (kapatmak için pencereyi kapat)")
        proc.wait()
    else:
        webbrowser.open(url)
        print(f"Ders Anlatıcı: {url}  (kapatmak için Ctrl+C)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    server.should_exit = True
    if tunnel:
        tunnel.terminate()
        phone_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
