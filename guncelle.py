"""Kendiliğinden güncelleme: her açılışta GitHub'daki son sürümü kontrol eder ve indirir.

- Git ile klonlanmışsa `git pull`, değilse GitHub'dan zip indirip dosyaları yeniler.
- Kullanıcının verilerine ASLA dokunmaz: veri/ (notlar, kayıtlar, ayarlar), .env (anahtarlar), .venv.
- requirements.txt değiştiyse yeni paketleri kurar.
- İnternet yoksa ya da bir şey ters giderse sessizce eski sürümle devam eder.

Elle çalıştırmak için:  python guncelle.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "osmanadali/ders-anlatici"
BRANCH = "main"
ROOT = Path(__file__).resolve().parent
KEEP = {"veri", ".env", ".venv", ".git", "__pycache__", ".pytest_cache"}  # asla üzerine yazılmaz/silinmez
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # Windows'ta pip için konsol penceresi açma


def _state_file() -> Path:
    return ROOT / os.getenv("DATA_DIR", "veri") / "surum.json"


def load_state() -> dict:
    try:
        return json.loads(_state_file().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(st: dict) -> None:
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ders-anlatici-guncelleyici",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_commit() -> tuple[str, str]:
    d = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", 8))
    return d["sha"], (d.get("commit", {}).get("message") or "").splitlines()[0]


def _pip_install(log) -> None:
    log("Yeni paketler kuruluyor…")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")],
                   cwd=ROOT, creationflags=NO_WINDOW, check=False)


def _update_git(log) -> dict | None:
    def head() -> str:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              creationflags=NO_WINDOW).stdout.strip()

    before = head()
    req_before = (ROOT / "requirements.txt").read_bytes()
    subprocess.run(["git", "pull", "--ff-only", "-q"], cwd=ROOT, capture_output=True, creationflags=NO_WINDOW,
                   timeout=60)
    after = head()
    if not after or after == before:
        return None
    if (ROOT / "requirements.txt").read_bytes() != req_before:
        _pip_install(log)
    msg = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=ROOT, capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout.strip()
    return {"sha": after, "message": msg}


def _update_zip(log) -> dict | None:
    st = load_state()
    sha, message = latest_commit()
    if st.get("sha") == sha:
        return None
    log(f"Güncelleme bulundu: {message}")
    data = _get(f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}", 120)
    req_before = (ROOT / "requirements.txt").read_bytes() if (ROOT / "requirements.txt").exists() else b""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp)
        top = next(Path(tmp).iterdir())  # "ders-anlatici-main/"
        new_files = []
        for src in top.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(top)
            if rel.parts[0] in KEEP:
                continue
            dst = ROOT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except PermissionError:  # açık/kilitli dosya: bir sonraki açılışta tekrar denenir
                log(f"Atlandı (kullanımda): {rel}")
                continue
            new_files.append(rel.as_posix())
    # Yeni sürümde kaldırılmış dosyaları sil (yalnızca bizim daha önce koyduklarımızı)
    for old in set(st.get("files", [])) - set(new_files):
        p = ROOT / old
        if p.is_file() and Path(old).parts[0] not in KEEP:
            p.unlink(missing_ok=True)
    if (ROOT / "requirements.txt").read_bytes() != req_before:
        _pip_install(log)
    _save_state({"sha": sha, "message": message, "updated": time.time(), "files": sorted(new_files)})
    return {"sha": sha, "message": message}


def check_and_update(log=print) -> dict | None:
    """Güncelleme yapıldıysa {"sha", "message"} döndürür; yoksa ya da hata olursa None."""
    if os.getenv("DERS_GUNCELLEME", "1") == "0":
        return None
    try:
        info = _update_git(log) if (ROOT / ".git").exists() else _update_zip(log)
    except Exception as e:  # internet yok, GitHub erişilemiyor vb. → eski sürümle devam
        log(f"Güncelleme denetlenemedi ({type(e).__name__}); mevcut sürümle devam.")
        return None
    if info:
        st = load_state()
        st.update(sha=info["sha"], message=info["message"], updated=time.time())
        _save_state(st)
    return info


if __name__ == "__main__":
    r = check_and_update()
    print("Güncellendi: " + r["message"] if r else "Zaten en güncel sürüm.")
