"""Kendiliğinden güncelleyicinin güvenlik testleri (GitHub yerine sahte zip ile)."""
import importlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr("ders-anlatici-main/" + name, content)
    return buf.getvalue()


@pytest.fixture()
def kurulum(tmp_path, monkeypatch):
    """Boşluklu ve Türkçe karakterli bir klasörde eski bir kurulum."""
    root = tmp_path / "Osman Adalı" / "ders-anlatici"
    (root / "veri" / "dersler").mkdir(parents=True)
    (root / "veri" / "dersler" / "not.txt").write_text("BENIM NOTUM", "utf-8")
    (root / ".env").write_text("GEMINI_API_KEY=GIZLI", "utf-8")
    (root / "app").mkdir()
    (root / "app" / "eski.py").write_text("x = 1\n", "utf-8")
    (root / "requirements.txt").write_text("fastapi\n", "utf-8")
    (root / "baslat.py").write_text("print('eski baslat')\n", "utf-8")
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("DERS_GUNCELLEME", raising=False)
    sys.modules.pop("guncelle", None)
    import guncelle

    importlib.reload(guncelle)
    monkeypatch.setattr(guncelle, "ROOT", root)
    calls = {"pip": 0, "pip_ok": True}

    def fake_run(cmd, **kw):
        if "pip" in cmd:
            calls["pip"] += 1
            return subprocess.CompletedProcess(cmd, 0 if calls["pip_ok"] else 1, "", "hata" if not calls["pip_ok"] else "")
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(guncelle.subprocess, "run", fake_run)
    json.dump({"sha": "eski", "files": ["app/eski.py", "baslat.py", "requirements.txt", "App/Buyuk.py"]},
              open(root / "veri" / "surum.json", "w"))
    return guncelle, root, calls


def _serve(g, monkeypatch, files: dict, sha="yeni123"):
    monkeypatch.setattr(g, "latest_commit", lambda: (sha, "Yeni sürüm"))
    monkeypatch.setattr(g, "_get", lambda url, timeout: _zip(files))


def test_normal_guncelleme_veriyi_korur(kurulum, monkeypatch):
    g, root, calls = kurulum
    _serve(g, monkeypatch, {"app/yeni.py": "y = 2\n", "baslat.py": "print('yeni')\n", "requirements.txt": "fastapi\npillow\n",
                            "veri/zarar.txt": "veriye yazılmamalı", ".env": "EZME"})
    info = g.check_and_update(log=lambda m: None)
    assert info["sha"] == "yeni123"
    assert (root / "veri" / "dersler" / "not.txt").read_text("utf-8") == "BENIM NOTUM"
    assert (root / ".env").read_text("utf-8") == "GEMINI_API_KEY=GIZLI"
    assert not (root / "veri" / "zarar.txt").exists()
    assert (root / "app" / "yeni.py").exists() and not (root / "app" / "eski.py").exists()
    assert (root / "baslat.py").read_text("utf-8") == "print('yeni')\n"
    assert (root / "veri" / "onceki" / "baslat.py").read_text("utf-8") == "print('eski baslat')\n"  # yedek
    assert not list(root.rglob("*.yeni"))  # yarım dosya kalmadı
    assert calls["pip"] == 1 and g.load_state()["req_hash"]


def test_bozuk_surum_hicbir_seye_dokunmaz(kurulum, monkeypatch):
    g, root, _ = kurulum
    _serve(g, monkeypatch, {"app/yeni.py": "y = 2\n", "baslat.py": "def bozuk(:\n"})
    assert g.check_and_update(log=lambda m: None) is None
    assert (root / "baslat.py").read_text("utf-8") == "print('eski baslat')\n"
    assert (root / "app" / "eski.py").exists() and not (root / "app" / "yeni.py").exists()
    assert g.load_state()["sha"] == "eski"


def test_kilitli_dosya_surumu_tamamlanmis_saymaz(kurulum, monkeypatch):
    g, root, _ = kurulum
    _serve(g, monkeypatch, {"app/eski.py": "x = 2\n", "app/kilitli.py": "z = 1\n"})
    real = g._place

    def place(src, dst):
        if dst.name == "kilitli.py":
            raise PermissionError("kullanımda")
        return real(src, dst)

    monkeypatch.setattr(g, "_place", place)
    assert g.check_and_update(log=lambda m: None) is None
    st = g.load_state()
    assert st["sha"] == "eski"  # bir sonraki açılışta yeniden denenecek
    assert "app/kilitli.py" in st["files"]
    monkeypatch.setattr(g, "_place", real)
    assert g.check_and_update(log=lambda m: None)["sha"] == "yeni123"
    assert (root / "app" / "kilitli.py").exists()


def test_pip_basarisizsa_sonraki_acilista_tekrar_dener(kurulum, monkeypatch):
    g, root, calls = kurulum
    _serve(g, monkeypatch, {"requirements.txt": "fastapi\npillow\n"})
    calls["pip_ok"] = False
    g.check_and_update(log=lambda m: None)
    assert calls["pip"] == 1 and "req_hash" not in g.load_state()
    calls["pip_ok"] = True
    g.check_and_update(log=lambda m: None)  # yeni commit yok ama paketler yeniden denenir
    assert calls["pip"] == 2 and g.load_state()["req_hash"]
    g.check_and_update(log=lambda m: None)
    assert calls["pip"] == 2  # başarılı kurulumdan sonra tekrar kurmaz


def test_buyuk_kucuk_harf_degisikligi_dosyayi_silmez(kurulum, monkeypatch):
    g, root, _ = kurulum
    (root / "App").mkdir(exist_ok=True)
    (root / "App" / "Buyuk.py").write_text("a = 1\n", "utf-8")
    _serve(g, monkeypatch, {"App/buyuk.py": "a = 2\n"})
    g.check_and_update(log=lambda m: None)
    assert any(p.name.lower() == "buyuk.py" for p in (root / "App").iterdir())


def test_internet_yoksa_sessizce_devam(kurulum, monkeypatch):
    g, root, _ = kurulum

    def boom():
        raise OSError("ağ yok")

    monkeypatch.setattr(g, "latest_commit", boom)
    assert g.check_and_update(log=lambda m: None) is None
    assert (root / "baslat.py").exists()


def test_gercek_depo_dosyalari_derlenir():
    """main'e gidecek her .py dosyası derlenebilmeli (güncelleyici aksi hâlde sürümü reddeder)."""
    sys.path.insert(0, str(ROOT))
    import guncelle

    assert guncelle._compile_errors(ROOT) == []


def test_bat_dosyalari_windows_satir_sonuyla_paketlenir():
    out = subprocess.run(["git", "archive", "--format=zip", "HEAD"], cwd=ROOT, capture_output=True).stdout
    if not out:
        pytest.skip("git yok")
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        for n in z.namelist():
            if n.endswith((".bat", ".ps1")):
                data = z.read(n)
                assert data.count(b"\r\n") == data.count(b"\n"), n
