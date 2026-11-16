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
PORT = int(os.getenv("PORT", "8000"))
IDLE_EXIT = 180  # sn: uygulama penceresinden bu kadar süre ses gelmezse sunucu kapanır


def _setup_output() -> None:
    """pythonw ile (konsolsuz) açıldığında çıktılar veri/baslat.log dosyasına gider."""
    if sys.stdout is None or sys.stderr is None:
        log_dir = ROOT / os.getenv("DATA_DIR", "veri")
        log_dir.mkdir(parents=True, exist_ok=True)
        f = open(log_dir / "baslat.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def already_running(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.5) as r:
            return r.status == 200 and b"whisper" in r.read()
    except Exception:
        return False


def ensure_shortcut() -> None:
    """Windows: masaüstü kısayolu yoksa bir kez oluştur (kurulumu eski sürümle yapanlar için)."""
    flag = ROOT / os.getenv("DATA_DIR", "veri") / ".kisayol"
    if os.name != "nt" or flag.exists() or not (ROOT / "kisayol.ps1").exists():
        return
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "kisayol.ps1")],
                       creationflags=0x08000000, timeout=30, capture_output=True)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("ok", "utf-8")
    except Exception as e:
        print(f"Kısayol oluşturulamadı: {e}")


def open_window(url: str) -> None:
    browser = find_browser()
    if browser:
        profile = ROOT / "veri" / "pencere-profili"  # mikrofon izni bir kez verilir, hatırlanır
        flags = 0x08000000 if os.name == "nt" else 0
        subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1400,880",
                          "--autoplay-policy=no-user-gesture-required"], creationflags=flags)
    else:
        webbrowser.open(url)


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

    _setup_output()
    phone = "--telefon" in sys.argv

    # Zaten açıksa yeniden başlatma, sadece pencereyi aç (masaüstü kısayoluna iki kez tıklanınca)
    if not phone and already_running(PORT):
        open_window(f"http://127.0.0.1:{PORT}/")
        return

    # Her açılışta güncellemeleri çek; başlatıcının kendisi değiştiyse yeni sürümle yeniden başla
    if "--guncellendi" not in sys.argv:
        import guncelle

        me_before = Path(__file__).read_bytes()
        info = guncelle.check_and_update()
        if info:
            print(f"Güncellendi: {info['message']}")
            if Path(__file__).read_bytes() != me_before:
                os.execv(sys.executable, [sys.executable, str(Path(__file__)), *sys.argv[1:], "--guncellendi"])

    ensure_shortcut()
    port = free_port(PORT)
    url = f"http://127.0.0.1:{port}/"
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning"))

    tunnel, phone_file = None, ROOT / os.getenv("DATA_DIR", "veri") / "telefon.json"

    def after_start() -> None:
        nonlocal tunnel
        for _ in range(300):
            if server.started:
                break
            time.sleep(0.1)
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
        open_window(url)
        print(f"\nDers Anlatıcı çalışıyor: {url}")
        print("Uygulama penceresini kapatıp tekrar açmak için bu adresi tarayıcıda açabilirsin.")
        print("TAMAMEN KAPATMAK İÇİN bu siyah pencereyi kapat (ya da Ctrl+C).\n")

    def idle_watch() -> None:
        """Uygulama penceresi her 20 sn'de 'buradayım' der; uzun süre ses gelmezse (pencere kapandı) sunucuyu kapat."""
        from app import main as app_main

        started = time.time()
        while not server.should_exit:
            time.sleep(10)
            last = app_main.LAST_PING[0]
            idle = time.time() - (last or started)
            if idle > (IDLE_EXIT if last else 600):
                print("Uygulama penceresi kapandı; sunucu kapatılıyor.")
                server.should_exit = True

    threading.Thread(target=after_start, daemon=True).start()
    if not phone:  # telefon modunda bilgisayar penceresi kapansa da sunucu açık kalsın
        threading.Thread(target=idle_watch, daemon=True).start()
    # Sunucu ana iş parçacığında çalışır: uygulama penceresi başka bir işleme devredilse bile kapanmaz.
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel:
            tunnel.terminate()
        phone_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
