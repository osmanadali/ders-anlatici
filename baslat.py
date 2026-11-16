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
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "kisayol.ps1")],
                           creationflags=0x08000000, timeout=30, capture_output=True, text=True)
        if r.returncode == 0:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("ok", "utf-8")
        else:
            print(f"Kısayol oluşturulamadı: {r.stdout} {r.stderr}")
    except subprocess.TimeoutExpired:
        flag.write_text("zaman aşımı", "utf-8")  # her açılışı yavaşlatmasın
    except Exception as e:
        print(f"Kısayol oluşturulamadı: {e}")


_browser_proc: subprocess.Popen | None = None


def open_window(url: str) -> None:
    global _browser_proc
    browser = find_browser()
    if browser:
        profile = ROOT / "veri" / "pencere-profili"  # mikrofon izni bir kez verilir, hatırlanır
        flags = 0x08000000 if os.name == "nt" else 0
        _browser_proc = subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1400,880",
                                          "--autoplay-policy=no-user-gesture-required"], creationflags=flags)
    else:
        webbrowser.open(url)


class SingleInstance:
    """İşletim sistemi kilidi: aynı anda yalnızca bir başlatıcı güncelleme yapar ve sunucu açar."""

    def __init__(self) -> None:
        d = ROOT / os.getenv("DATA_DIR", "veri")
        d.mkdir(parents=True, exist_ok=True)
        self.f = open(d / "baslat.lock", "a+")
        self.held = False

    def acquire(self) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.held = True
        except OSError:
            self.held = False
        return self.held

    def release(self) -> None:
        if not self.held:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.held = False


def relaunch(extra: list[str]) -> None:
    """Güncellenmiş başlatıcıyla yeniden başla. (os.execv Windows'ta boşluklu yolları bozduğu için subprocess.)"""
    args = [sys.executable, str(Path(__file__).resolve()), *[a for a in sys.argv[1:] if a not in extra], *extra]
    subprocess.Popen(args, cwd=ROOT, creationflags=0x08000000 if os.name == "nt" else 0)
    sys.exit(0)


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

    _setup_output()
    phone = "--telefon" in sys.argv

    # Tek kopya: başka bir başlatıcı çalışıyorsa (güncelleme/başlatma sürüyor) onun hazır olmasını bekle, pencereyi aç
    lock = SingleInstance()
    if not lock.acquire():
        for _ in range(240):
            if already_running(PORT):
                if not phone:
                    open_window(f"http://127.0.0.1:{PORT}/")
                return
            time.sleep(0.5)
        return
    if already_running(PORT):  # kilit yoksa ama sunucu açıksa (eski sürüm vb.)
        if not phone:
            open_window(f"http://127.0.0.1:{PORT}/")
        else:
            print("Ders Anlatıcı zaten çalışıyor. Telefon modu için önce onu kapat.")
        return

    # Her açılışta güncellemeleri çek; başlatıcının kendisi değiştiyse yeni sürümle yeniden başla.
    # Güncelleyicide ne olursa olsun uygulama mevcut sürümle açılmaya devam eder.
    if "--guncellendi" not in sys.argv:
        try:
            import guncelle

            me_before = Path(__file__).read_bytes()
            info = guncelle.check_and_update()
            if info:
                print(f"Güncellendi: {info['message']}")
                if Path(__file__).read_bytes() != me_before:
                    lock.release()
                    relaunch(["--guncellendi"])
        except Exception as e:
            print(f"Güncelleme atlandı: {type(e).__name__}: {e}")

    import uvicorn

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
        """Pencere kapanınca sunucuyu kapat. Pencere her 20 sn'de 'buradayım' der.
        Bilgisayar uykudan uyandığında ya da pencere kısa süre donduğunda yanlışlıkla kapanmaz."""
        from app import main as app_main  # uvicorn'un yüklediği modülle aynı nesne (sys.modules)

        started = prev = time.time()
        strikes = 0
        while not server.should_exit:
            time.sleep(10)
            now = time.time()
            if now - prev > 30:  # uyku/hazırda bekletme: yeni bir bekleme süresi tanı
                started = now
                app_main.LAST_PING[0] = now
                strikes = 0
            prev = now
            if _browser_proc is not None and _browser_proc.poll() is None:
                strikes = 0  # uygulama penceresinin işlemi hâlâ açık
                continue
            last = app_main.LAST_PING[0]
            idle = now - max(last, started)
            # Pencere işlemi kapandıysa daha kısa bekle; küçültülmüş pencerede Chrome zamanlayıcıları
            # dakikada bire kadar yavaşlatabildiği için bu süre 60 sn'nin üstünde tutulur.
            limit = (100 if _browser_proc is not None else IDLE_EXIT) if last else 600
            strikes = strikes + 1 if idle > limit else 0
            if strikes >= 2:
                print("Uygulama penceresi kapandı; sunucu kapatılıyor.")
                server.should_exit = True

    threading.Thread(target=after_start, daemon=True).start()
    if not phone:  # telefon modunda bilgisayar penceresi kapansa da sunucu açık kalsın
        threading.Thread(target=idle_watch, daemon=True).start()
    # Sunucu ana iş parçacığında çalışır.
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel:
            tunnel.terminate()
        if phone:  # dosyayı yalnızca onu oluşturan telefon modu siler
            phone_file.unlink(missing_ok=True)
        lock.release()


if __name__ == "__main__":
    main()
