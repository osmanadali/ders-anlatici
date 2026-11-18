"""Bilgisayarda çalışan yerel yapay zeka: Ollama + açık model (Gemma 4).

Hiçbir şirkete ya da internete bağımlı değildir; yalnızca ilk kurulumda program (~1,6 GB) ve model
(donanıma göre 4,6-18,7 GB) bir kez indirilir. Bundan sonra her şey bu bilgisayarda çalışır.

Akış (hazirla): donanımı ölç → modele karar ver → Ollama çalışıyor mu? → değilse kurulu olanı ya da
veri/yerel-yz/ altına indirileni başlat → model yoksa indir → belleğe yükle → "hazir".
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import httpx

from .config import DATA_DIR, load_settings

log = logging.getLogger("ders.yerel")

HOST = os.getenv("OLLAMA_HOST_URL", "http://127.0.0.1:11434").rstrip("/")
RUNTIME_DIR = DATA_DIR / "yerel-yz"
MODELS_DIR = RUNTIME_DIR / "modeller"


def modeller_klasoru() -> Path:
    """Ollama Windows'ta Türkçe/özel karakterli yollarda (ör. kullanıcı adında 'ı') model indirirken takılabiliyor:
    öyle bir yolda modeller sürücü kökünde ASCII bir klasöre iner."""
    yol = str(MODELS_DIR)
    # OneDrive gibi eşitlenen klasörler büyük model dosyalarını kilitler ("Erişim engellendi") ve buluta yüklemeye çalışır
    if os.name == "nt" and (not yol.isascii() or "onedrive" in yol.lower()):
        return Path(os.environ.get("SystemDrive", "C:") + "\\") / "DersAnlaticiModeller"
    return MODELS_DIR
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Donanıma göre model: (etiket, indirme GB). Gemma 4: çok dilli (Türkçe iyi), görüntü okur (taranmış not, ekran görüntüsü).
MODELS = {
    "gemma4:26b": 18.7,  # MoE (4B etkin): ekran kartında hızlı, 32 GB RAM'de işlemcide de akıcı
    "gemma4:12b": 8.0,
    "gemma4:e4b": 6.6,
    "gemma4:e2b": 4.6,
}

STATE: dict = {"state": "bilinmiyor", "detail": "", "progress": None, "model": "", "hw": None}
_proc: subprocess.Popen | None = None
_task: asyncio.Task | None = None
_ready_checked = 0.0


# ---------------------------------------------------------------- donanım
def _ram_gb() -> float:
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout
            return int(out.strip()) / 2**30
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 2**20
    except Exception:
        pass
    return 8.0


def _vram_gb() -> float:
    """En büyük NVIDIA ekran kartının belleği (yoksa 0). Apple Silicon'da birleşik belleğin bir kısmı."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return _ram_gb() * 0.66
    exe = shutil.which("nvidia-smi")
    if not exe and os.name == "nt":
        cand = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(cand) if cand.exists() else None
    if not exe:
        return 0.0
    try:
        out = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=10, creationflags=NO_WINDOW).stdout
        vals = [float(x) for x in out.split() if x.strip().replace(".", "").isdigit()]
        return max(vals) / 1024 if vals else 0.0
    except Exception:
        return 0.0


def donanim() -> dict:
    return {"ram_gb": round(_ram_gb(), 1), "vram_gb": round(_vram_gb(), 1), "cpu": os.cpu_count() or 2,
            "disk_gb": round(shutil.disk_usage(DATA_DIR).free / 2**30, 1)}


def model_sec(hw: dict) -> str:
    """Bu bilgisayarda akıcı çalışacak en iyi model."""
    v, r = hw.get("vram_gb", 0), hw.get("ram_gb", 8)
    if v >= 20 or (v < 6 and r >= 40):
        tag = "gemma4:26b"
    elif v >= 10:
        tag = "gemma4:12b"
    elif v >= 6 or r >= 12:
        tag = "gemma4:e4b"
    else:
        tag = "gemma4:e2b"
    # Disk yetmiyorsa küçült
    order = list(MODELS)
    while MODELS[tag] + 2 > hw.get("disk_gb", 999) and order.index(tag) < len(order) - 1:
        tag = order[order.index(tag) + 1]
    return tag


def secili_model() -> str:
    s = load_settings()
    if s.get("yerel_model"):
        return s["yerel_model"]
    if not STATE.get("hw"):
        STATE["hw"] = donanim()
    return model_sec(STATE["hw"])


def baglam() -> int:
    """Modelin bir seferde göreceği metin uzunluğu (token). Küçük modellerde bellek için sınırlı tutulur."""
    s = load_settings()
    if s.get("yerel_ctx"):
        return int(s["yerel_ctx"])
    return 32768 if secili_model() in ("gemma4:26b", "gemma4:12b") else 16384


# ---------------------------------------------------------------- Ollama sunucusu
async def alive(timeout: float = 2.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{HOST}/api/version")
            return r.status_code == 200
    except Exception:
        return False


async def installed_models() -> list[str]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{HOST}/api/tags")
        r.raise_for_status()
        return [m.get("name") or m.get("model") for m in r.json().get("models", [])]


def _runtime_binary() -> Path:
    if os.name == "nt":
        return RUNTIME_DIR / "ollama.exe"
    if sys.platform == "darwin":
        return RUNTIME_DIR / "Ollama.app" / "Contents" / "Resources" / "ollama"
    return RUNTIME_DIR / "bin" / "ollama"


def find_binary() -> str | None:
    cands = [_runtime_binary()]
    if os.name == "nt":
        cands.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        cands.append(Path("/Applications/Ollama.app/Contents/Resources/ollama"))
    for c in cands:
        if c.exists():
            return str(c)
    return shutil.which("ollama")


def _download_url() -> str:
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if os.name == "nt":
        return f"https://ollama.com/download/ollama-windows-{'arm64' if arm else 'amd64'}.zip"
    if sys.platform == "darwin":
        return "https://ollama.com/download/Ollama-darwin.zip"
    return f"https://ollama.com/download/ollama-linux-{'arm64' if arm else 'amd64'}.tar.zst"


async def _download(url: str, dst: Path, label: str) -> None:
    """Kesilirse kaldığı yerden devam eden indirme."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=120), follow_redirects=True) as c:
        async with c.stream("GET", url, headers=headers) as r:
            if r.status_code == 200:
                done = 0  # sunucu devam etmeyi desteklemiyor: baştan
            elif r.status_code != 206:
                r.raise_for_status()
            total = done + int(r.headers.get("content-length") or 0)
            with open(part, "ab" if done else "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        _set("kuruluyor", f"{label}: {done / 2**30:.2f} / {total / 2**30:.2f} GB", done / total)
    os.replace(part, dst)


def _extract(archive: Path) -> None:
    if archive.suffix == ".zip":
        if sys.platform == "darwin":  # çalıştırma izinlerini korumak için
            subprocess.run(["ditto", "-x", "-k", str(archive), str(RUNTIME_DIR)], check=True)
        else:
            with zipfile.ZipFile(archive) as z:
                z.extractall(RUNTIME_DIR)
    elif archive.name.endswith(".zst"):
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(RUNTIME_DIR)], check=True)
    else:
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(RUNTIME_DIR, filter="data")
            else:
                t.extractall(RUNTIME_DIR)
    b = _runtime_binary()
    if b.exists() and os.name != "nt":
        b.chmod(0o755)


async def install_runtime() -> str:
    url = _download_url()
    archive = RUNTIME_DIR / url.rsplit("/", 1)[1]
    if not _runtime_binary().exists():
        if not archive.exists():
            await _download(url, archive, "Yapay zeka programı indiriliyor")
        _set("kuruluyor", "Program açılıyor…", None)
        await asyncio.to_thread(_extract, archive)
        archive.unlink(missing_ok=True)
    if not _runtime_binary().exists():
        raise RuntimeError("Yapay zeka programı açılamadı (arşiv beklenen dosyayı içermiyor).")
    return str(_runtime_binary())


async def start_server(binary: str) -> None:
    global _proc
    klasor = modeller_klasoru()
    klasor.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("OLLAMA_MODELS", str(klasor))
    env["OLLAMA_HOST"] = HOST.split("://", 1)[-1]
    env.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    # Hız ve bellek: flash attention + 8 bitlik bağlam önbelleği (aynı bağlamda yarı bellek → modelin daha çok
    # katmanı ekran kartına sığar); sohbet modeli ile arama modeli aynı anda yüklü kalabilir.
    env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
    env.setdefault("OLLAMA_KV_CACHE_TYPE", "q8_0")
    env.setdefault("OLLAMA_MAX_LOADED_MODELS", "2")
    logf = open(DATA_DIR / "yerel-yz.log", "ab")
    _proc = subprocess.Popen([binary, "serve"], env=env, stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    for _ in range(60):
        if await alive():
            return
        if _proc.poll() is not None:
            raise RuntimeError("Yapay zeka programı başlatılamadı (ayrıntı: veri/yerel-yz.log).")
        await asyncio.sleep(1)
    raise RuntimeError("Yapay zeka programı 60 saniyede açılmadı.")


def stop_server() -> None:
    """Uygulama kapanınca yalnızca kendi başlattığımız sunucuyu kapat."""
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(10)
        except Exception:
            _proc.kill()
    _proc = None


def _kendi_sunucumuzu_kapat() -> None:
    """Önceki açılıştan kalmış, bizim indirdiğimiz programla çalışan sunucuyu kapatır (kullanıcının kendi Ollama'sına dokunmaz)."""
    stop_server()
    if os.name != "nt":
        return
    yol = str(_runtime_binary()).replace("'", "''")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-Process ollama -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -eq '{yol}' }} | Stop-Process -Force"],
                       capture_output=True, timeout=30, creationflags=NO_WINDOW)
    except Exception:
        pass


TAKILMA_SN = 90  # indirme bu kadar süre hiç ilerlemezse takılmış sayılır


async def pull(model: str) -> None:
    totals: dict[str, int] = {}
    done: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=TAKILMA_SN)) as c:
        async with c.stream("POST", f"{HOST}/api/pull", json={"model": model, "stream": True}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise RuntimeError(f"Model indirilemedi: {d['error']}")
                if d.get("digest") and d.get("total"):
                    totals[d["digest"]] = d["total"]
                    done[d["digest"]] = d.get("completed", 0)
                    t, k = sum(totals.values()), sum(done.values())
                    _set("kuruluyor", f"Model indiriliyor ({model}): {k / 2**30:.2f} / {t / 2**30:.2f} GB", k / t if t else None)
                elif d.get("status"):
                    _set("kuruluyor", f"Model hazırlanıyor ({model}): {d['status']}", STATE.get("progress"))


async def warm(model: str) -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=600)) as c:
        await c.post(f"{HOST}/api/generate", json={"model": model, "prompt": "", "keep_alive": "30m"})


def _set(state: str, detail: str, progress: float | None = None) -> None:
    STATE.update(state=state, detail=detail, progress=None if progress is None else round(progress, 3))


def _same(a: str, b: str) -> bool:
    norm = lambda x: x if ":" in x else x + ":latest"
    return norm(a) == norm(b)


async def hazirla() -> dict:
    """Yerel yapay zekayı kullanıma hazırlar (gerekirse indirir). Tekrar çağrılabilir."""
    try:
        STATE["hw"] = await asyncio.to_thread(donanim)
        model = secili_model()
        STATE["model"] = model
        if not await alive():
            binary = find_binary()
            if not binary and os.getenv("DERS_YEREL_INDIRME", "1") == "0":
                raise RuntimeError("Yerel yapay zeka kurulu değil (otomatik indirme kapalı).")
            if not binary:
                _set("kuruluyor", "Yapay zeka programı indiriliyor…", 0)
                binary = await install_runtime()
            _set("kuruluyor", "Yapay zeka programı başlatılıyor…", None)
            await start_server(binary)
        if not any(_same(m, model) for m in await installed_models()):
            if os.getenv("DERS_YEREL_INDIRME", "1") == "0":
                raise RuntimeError(f"{model} modeli indirilmemiş (otomatik indirme kapalı).")
            need = MODELS.get(model, 8) + 1
            if STATE["hw"]["disk_gb"] < need:
                raise RuntimeError(f"Diskte yer yok: {model} için ~{need:.0f} GB gerekiyor, {STATE['hw']['disk_gb']} GB boş.")
            _set("kuruluyor", f"Model indiriliyor ({model})…", 0)
            try:
                await pull(model)
            except (httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                # Takıldı: kendi programımızı yeniden başlatıp (güvenli model klasörüyle) bir kez daha dene
                log.warning("model indirme takıldı (%s); program yeniden başlatılıyor", e)
                binary = find_binary()
                if not binary or binary != str(_runtime_binary()):
                    raise RuntimeError("Model indirmesi ilerlemiyor. İnternet bağlantını kontrol edip 'Kur / yeniden dene'ye bas.") from e
                _set("kuruluyor", "İndirme takıldı; yapay zeka programı yeniden başlatılıyor…", None)
                await asyncio.to_thread(_kendi_sunucumuzu_kapat)
                await start_server(binary)
                try:
                    await pull(model)
                except (httpx.ReadTimeout, httpx.RemoteProtocolError) as e2:
                    raise RuntimeError("Model indirmesi ilerlemiyor (ayrıntı: veri/yerel-yz.log). İnternet bağlantını "
                                       "kontrol edip 'Kur / yeniden dene'ye bas.") from e2
        _set("kuruluyor", "Model belleğe yükleniyor…", None)
        await warm(model)
        _set("hazir", f"{model} bu bilgisayarda çalışıyor", None)
        _gomme_hazirla()
    except Exception as e:
        log.exception("yerel yapay zeka hazırlanamadı")
        _set("hata", str(e) or type(e).__name__, None)
    return durum()


def _gomme_hazirla() -> None:
    """Ana model hazır: kütüphanede kaynak varsa anlam arama (gömme) modeli de arka planda indirilip kullanılır."""
    try:
        from . import kutuphane

        if not kutuphane.bos_mu():
            STATE["detail"] += f"; kütüphane için gömme modeli ({kutuphane.gomme_modeli()}) hazırlanıyor"
            kutuphane.gomme_baslat_arka_planda()
    except Exception:
        log.exception("gömme modeli hazırlığı başlatılamadı")


def baslat_arka_planda() -> None:
    """Uygulama açılırken çağrılır: hazırlığı arka planda başlatır (zaten sürüyorsa bir şey yapmaz)."""
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.get_event_loop().create_task(hazirla())


def hazir() -> bool:
    return STATE.get("state") == "hazir"


async def ensure_ready() -> bool:
    """Bir istekten önce: hazır mı? Sunucu sonradan kapanmışsa (ör. uyku) yeniden hazırlamayı dener."""
    global _ready_checked
    if hazir() and time.time() - _ready_checked < 30:
        return True
    if hazir() and await alive():
        _ready_checked = time.time()
        return True
    if STATE.get("state") != "kuruluyor":
        if not (_task and not _task.done()):
            await hazirla()
    return hazir()


def durum() -> dict:
    return {k: STATE.get(k) for k in ("state", "detail", "progress", "model", "hw")} | {
        "secenekler": list(MODELS), "sunucu": HOST}


def durum_mesaji() -> str:
    st = STATE.get("state")
    if st == "kuruluyor":
        p = STATE.get("progress")
        return ("Yerel yapay zeka hazırlanıyor: " + STATE.get("detail", "") + (f" (%{p * 100:.0f})" if p else "") +
                ". Bitince hoca kendiliğinden çalışır.")
    if st == "hata":
        return "Yerel yapay zeka çalışmıyor: " + STATE.get("detail", "") + " (Ayarlar → Yapay zeka → Yeniden dene)"
    return "Yerel yapay zeka henüz hazır değil (Ayarlar → Yapay zeka)."
