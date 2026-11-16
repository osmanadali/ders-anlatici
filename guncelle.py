"""Kendiliğinden güncelleme: her açılışta GitHub'daki son sürümü kontrol eder ve indirir.

Güvenlik ilkeleri (uygulamayı asla açılmaz hâle getirmemek için):
- Kullanıcının verilerine ASLA dokunmaz: veri/ (notlar, kayıtlar, ayarlar), .env (anahtarlar), .venv.
- Yeni sürümdeki her .py dosyası kopyalanmadan ÖNCE derlenip denetlenir; biri bozuksa güncelleme hiç uygulanmaz.
- Her dosya önce "<ad>.yeni" olarak yazılır, sonra tek hamlede yerine konur (yarım dosya kalmaz).
- Başlatıcı (baslat.py) ve güncelleyici (guncelle.py) en son değiştirilir; eskileri veri/onceki/ altına yedeklenir.
- Kilitli (kullanımda) bir dosya varsa sürüm "tamamlandı" sayılmaz; bir sonraki açılışta yeniden denenir.
- Paket kurulumu (pip) başarısız olursa da her açılışta yeniden denenir.
- İnternet yoksa ya da bir şey ters giderse sessizce eski sürümle devam eder.

Elle çalıştırmak için:  python guncelle.py
"""
from __future__ import annotations

import hashlib
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
BRANCH = os.getenv("DERS_DAL", "main")  # test için başka dal seçilebilir; kullanıcılar hep main
ROOT = Path(__file__).resolve().parent
KEEP = {"veri", ".env", ".venv", ".git", "__pycache__", ".pytest_cache"}  # asla üzerine yazılmaz/silinmez
LAST = {"baslat.py", "guncelle.py"}  # en son ve yedeklenerek değiştirilir
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # Windows'ta konsol penceresi açma


def _data_dir() -> Path:
    d = ROOT / os.getenv("DATA_DIR", "veri")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_file() -> Path:
    return _data_dir() / "surum.json"


def _log(msg: str) -> None:
    try:
        with open(_data_dir() / "guncelle.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(_state_file().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(st: dict) -> None:
    tmp = _state_file().with_suffix(".json.yeni")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, _state_file())


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ders-anlatici-guncelleyici",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_commit() -> tuple[str, str]:
    from urllib.parse import quote

    d = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{quote(BRANCH, safe='')}", 8))
    return d["sha"], (d.get("commit", {}).get("message") or "").splitlines()[0]


# ---------------------------------------------------------------- paketler (pip)
def _req_hash() -> str:
    f = ROOT / "requirements.txt"
    return hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else ""


def ensure_deps(log=print) -> bool:
    """requirements.txt son başarılı kurulumdan beri değiştiyse paketleri kurar. Başarısızsa sonra tekrar dener."""
    h = _req_hash()
    st = load_state()
    if not h or st.get("req_hash") == h:
        return True
    log("Gerekli paketler kuruluyor (birkaç dakika sürebilir)…")
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r",
                            str(ROOT / "requirements.txt")], cwd=ROOT, creationflags=NO_WINDOW,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
        _log(f"pip çıkış kodu {r.returncode}\n{(r.stdout or '')[-2000:]}\n{(r.stderr or '')[-4000:]}")
        ok = r.returncode == 0
    except Exception as e:  # zaman aşımı, pip yok vb.
        _log(f"pip çalıştırılamadı: {e}")
        ok = False
    if ok:
        st = load_state()
        st["req_hash"] = h
        _save_state(st)
    else:
        log("Paket kurulumu tamamlanamadı; bir sonraki açılışta yeniden denenecek (ayrıntı: veri/guncelle.log).")
    return ok


# ---------------------------------------------------------------- git ile kurulmuşsa
def _update_git(log) -> dict | None:
    def git(*a, timeout=60):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, creationflags=NO_WINDOW,
                              timeout=timeout)

    before = git("rev-parse", "HEAD").stdout.strip()
    if git("fetch", "-q", "origin", BRANCH, timeout=120).returncode != 0:
        return None
    target = git("rev-parse", f"origin/{BRANCH}").stdout.strip()
    if not target or target == before:
        return None
    # Yeni sürümün Python dosyaları derlenebiliyor mu? (bozuk sürümü hiç uygulama)
    with tempfile.TemporaryDirectory() as tmp:
        if git("--work-tree", tmp, "checkout", f"origin/{BRANCH}", "--", ".").returncode == 0:
            bad = _compile_errors(Path(tmp))
            git("reset", "-q")  # checkout'un index'e yazdığını geri al
            if bad:
                _log("Güncelleme atlandı, bozuk dosyalar: " + ", ".join(bad))
                return None
    # veri/, .env, .venv .gitignore'da olduğu için reset --hard onlara dokunmaz
    if git("reset", "--hard", "-q", f"origin/{BRANCH}").returncode != 0:
        return None
    msg = git("log", "-1", "--pretty=%s").stdout.strip()
    return {"sha": target, "message": msg}


# ---------------------------------------------------------------- zip ile kurulmuşsa
def _compile_errors(top: Path) -> list[str]:
    bad = []
    for src in top.rglob("*.py"):
        rel = src.relative_to(top)
        if rel.parts[0] in KEEP:
            continue
        try:
            compile(src.read_bytes(), str(rel), "exec")
        except (SyntaxError, ValueError) as e:
            bad.append(f"{rel} ({e})")
    return bad


def _place(src: Path, dst: Path) -> None:
    """Önce .yeni olarak yaz, sonra tek hamlede yerine koy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".yeni")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _update_zip(log) -> dict | None:
    st = load_state()
    sha, message = latest_commit()
    if st.get("sha") == sha:
        return None
    log(f"Güncelleme bulundu: {message}")
    data = _get(f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}", 120)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp)
        top = next(Path(tmp).iterdir())  # "ders-anlatici-main/"
        bad = _compile_errors(top)
        if bad:  # bozuk sürüm: hiçbir dosyaya dokunma
            _log("Güncelleme atlandı, bozuk dosyalar: " + ", ".join(bad))
            log("Yeni sürümde hata var; güncelleme atlandı, mevcut sürümle devam.")
            return None
        files = [p for p in top.rglob("*") if p.is_file() and p.relative_to(top).parts[0] not in KEEP]
        files.sort(key=lambda p: p.relative_to(top).as_posix() in LAST)  # başlatıcı/güncelleyici en sonda
        new_files, skipped = [], []
        backup = _data_dir() / "onceki"
        for src in files:
            rel = src.relative_to(top)
            dst = ROOT / rel
            try:
                if rel.as_posix() in LAST and dst.exists():
                    backup.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, backup / rel.name)
                _place(src, dst)
                new_files.append(rel.as_posix())
            except OSError as e:  # açık/kilitli dosya: bir sonraki açılışta yeniden denenir
                _log(f"Atlandı (kullanımda): {rel}: {e}")
                skipped.append(rel.as_posix())
    # Yeni sürümde kaldırılmış dosyaları sil (yalnızca bizim daha önce koyduklarımızı; Windows büyük/küçük harf duyarsız)
    keep_lower = {f.lower() for f in new_files + skipped}
    for old in set(st.get("files", [])):
        if old.lower() in keep_lower or Path(old).parts[0] in KEEP:
            continue
        try:
            (ROOT / old).unlink(missing_ok=True)
        except OSError as e:
            _log(f"Silinemedi: {old}: {e}")
    st = load_state()
    st["files"] = sorted(set(new_files + skipped))
    if skipped:  # sürüm tamamlanmadı: sha'yı kaydetme ki bir sonraki açılışta yeniden denensin
        _save_state(st)
        log("Bazı dosyalar kullanımdaydı; güncelleme bir sonraki açılışta tamamlanacak.")
        return None
    st.update(sha=sha, message=message, updated=time.time())
    _save_state(st)
    return {"sha": sha, "message": message}


def check_and_update(log=print) -> dict | None:
    """Güncelleme yapıldıysa {"sha", "message"} döndürür; yoksa ya da hata olursa None. Her durumda paketleri denetler."""
    if os.getenv("DERS_GUNCELLEME", "1") == "0":
        return None
    info = None
    try:
        info = _update_git(log) if (ROOT / ".git").exists() else _update_zip(log)
    except Exception as e:  # internet yok, GitHub erişilemiyor vb. → eski sürümle devam
        _log(f"Güncelleme denetlenemedi: {type(e).__name__}: {e}")
        log(f"Güncelleme denetlenemedi ({type(e).__name__}); mevcut sürümle devam.")
    if info:
        st = load_state()
        st.update(sha=info["sha"], message=info["message"], updated=time.time())
        _save_state(st)
        _log(f"Güncellendi: {info['sha'][:7]} {info['message']}")
    try:
        ensure_deps(log)
    except Exception as e:
        _log(f"Paket denetimi hatası: {e}")
    return info


if __name__ == "__main__":
    r = check_and_update()
    print("Güncellendi: " + r["message"] if r else "Zaten en güncel sürüm.")
