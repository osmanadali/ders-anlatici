"""Ders Anlatıcı'yı masaüstü uygulaması gibi açar.

Sunucuyu arka planda başlatır ve Chrome/Edge'i adres çubuğu olmayan kendi penceresinde
("uygulama modu") açar. Pencere kapatılınca sunucu da kapanır.

    python baslat.py            (Windows'ta "Ders Anlatıcı.bat" dosyasına çift tıkla)
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


def main() -> None:
    import uvicorn

    port = free_port(int(os.getenv("PORT", "8000")))
    url = f"http://127.0.0.1:{port}/"
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)

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


if __name__ == "__main__":
    main()
