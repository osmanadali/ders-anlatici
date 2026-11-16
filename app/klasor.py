"""Kendiliğinden içe aktarma: Masaüstündeki "Not Kutusu" klasörü ve İndirilenler'deki ders paketleri.

- Not Kutusu: içine bırakılan PDF/fotoğraf notlar hangi derse aitse oraya eklenir, dosya "Eklendi/<ders>"
  klasörüne taşınır. Ders paketi (.json) bırakılırsa kurulur. Eklenemeyenler "Eklenemedi" klasörüne (nedeniyle).
- İndirilenler: indirilen ders paketleri (…ders_paketi….json) bir kez kendiliğinden kurulur.
Arayüz /api/kutu/olaylar ile neler olduğunu öğrenip kullanıcıya gösterir.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path

from .config import load_settings

log = logging.getLogger("ders.klasor")

NOT_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
SKIP_EXTS = {".crdownload", ".part", ".tmp", ".download", ".partial"}
OLAYLAR: list[dict] = []  # {"id", "zaman", "tur": "eklendi"|"paket"|"hata", "mesaj", "ders_id"}
_seen: dict[str, tuple[int, float]] = {}  # dosya → (boyut, ilk görülme): yazılması bitmiş mi?
_task: asyncio.Task | None = None
_olay_no = 0


def _known_folder(guid: str) -> Path | None:
    """Windows'ta gerçek Masaüstü/İndirilenler yolu (OneDrive'a taşınmış olsa da)."""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        h = guid.replace("-", "")
        g = GUID(int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16),
                 (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
            path = Path(p.value)
            ctypes.windll.ole32.CoTaskMemFree(p)
            return path
    except Exception:
        pass
    return None


def _xdg(name: str) -> Path | None:
    try:
        import subprocess

        out = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True, timeout=5).stdout.strip()
        return Path(out) if out and Path(out).exists() else None
    except Exception:
        return None


def masaustu() -> Path:
    if os.name == "nt":
        p = _known_folder("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")
        if p and p.exists():
            return p
    elif sys.platform != "darwin":
        p = _xdg("DESKTOP")
        if p:
            return p
    for name in ("Desktop", "Masaüstü"):
        if (Path.home() / name).exists():
            return Path.home() / name
    return Path.home()


def indirilenler() -> Path:
    if os.name == "nt":
        p = _known_folder("374DE290-123F-4565-9164-39C4925E467B")
        if p and p.exists():
            return p
    elif sys.platform != "darwin":
        p = _xdg("DOWNLOAD")
        if p:
            return p
    for name in ("Downloads", "İndirilenler"):
        if (Path.home() / name).exists():
            return Path.home() / name
    return Path.home() / "Downloads"


def kutu_yolu() -> Path:
    custom = os.getenv("DERS_NOT_KUTUSU")
    return Path(custom) if custom else masaustu() / "Not Kutusu"


BENIOKU = """NOT KUTUSU (Ders Anlatıcı)

Hocanın notlarını (PDF ya da fotoğraf) bu klasöre bırak: Ders Anlatıcı açıkken birkaç saniye içinde
hangi derse ait olduğunu bulur, o derse ekler ve dosyayı "Eklendi" klasörüne taşır.
Ders paketi (.json) bırakırsan onu da kurar.
Kitap ve makaleleri (PDF, EPUB, TXT) "Kitaplar" klasörüne bırak: hocanın kütüphanesine eklenir, hoca cevap
verirken bu kaynaklardan yararlanıp kaynak gösterir (dosyalar bu bilgisayardan çıkmaz).
Hangi derse ekleneceğinden emin olamazsa "Gelen notlar" dersine koyar; uygulamadan başka derse taşıyabilirsin.
"""


def kutu_hazirla() -> Path:
    k = kutu_yolu()
    k.mkdir(parents=True, exist_ok=True)
    (k / "Kitaplar").mkdir(exist_ok=True)
    if not (k / "BENİOKU.txt").exists():
        (k / "BENİOKU.txt").write_text(BENIOKU, "utf-8")
    return k


def olay(tur: str, mesaj: str, ders_id: str = "") -> None:
    global _olay_no
    _olay_no += 1
    OLAYLAR.append({"id": _olay_no, "zaman": time.time(), "tur": tur, "mesaj": mesaj, "ders_id": ders_id})
    del OLAYLAR[:-50]
    log.info("kutu: %s", mesaj)


def _hazir_mi(f: Path) -> bool:
    """Dosya yazılmayı bitirdi mi? (boyutu iki taramada değişmedi ve en az 3 sn geçti)"""
    try:
        size = f.stat().st_size
    except OSError:
        return False
    prev = _seen.get(str(f))
    if not prev or prev[0] != size:
        _seen[str(f)] = (size, time.time())
        return False
    return size > 0 and time.time() - prev[1] >= 3


def _tasi(f: Path, hedef: Path) -> Path:
    hedef.mkdir(parents=True, exist_ok=True)
    dst = hedef / f.name
    i = 2
    while dst.exists():
        dst = hedef / f"{f.stem} ({i}){f.suffix}"
        i += 1
    shutil.move(str(f), dst)
    return dst


def _guvenli_ad(s: str) -> str:
    return re.sub(r'[<>:"/\\\\|?*]+', " ", s).strip()[:80] or "Ders"


async def kutuyu_tara(ekle) -> int:
    """Not Kutusu'ndaki hazır dosyaları işler. ekle(dosya_adı, veri, ipucu_ders) → {"ders_id", "ders_adi", "neden"} döner."""
    from . import hazir

    k = kutu_yolu()
    if not k.exists():
        return 0
    islenen, son_ders = 0, ""
    for f in sorted(k.iterdir()):
        if not f.is_file() or f.name.startswith(("~$", ".")) or f.suffix.lower() in SKIP_EXTS or f.name == "BENİOKU.txt":
            continue
        ext = f.suffix.lower()
        if ext not in NOT_EXTS | {".json"} or not _hazir_mi(f):
            continue
        try:
            data = await asyncio.to_thread(f.read_bytes)
            if ext == ".json":
                if not hazir.looks_like_pack(data):
                    raise ValueError("Bu .json bir ders paketi değil.")
                r = await asyncio.to_thread(hazir.install_pack, data)
                await asyncio.to_thread(_tasi, f, k / "Eklendi" / _guvenli_ad(r.get("ders_adi") or "Paketler"))
                olay("paket", f"📦 Ders paketi kuruldu: {r.get('ders_adi') or r['id']} ({r['belge']} belge)", r.get("ders_id", ""))
            else:
                r = await ekle(f.name, data, son_ders)
                son_ders = r["ders_id"]
                await asyncio.to_thread(_tasi, f, k / "Eklendi" / _guvenli_ad(r["ders_adi"]))
                olay("eklendi", f"📥 {f.name} → {r['ders_adi']} ({r['neden']})", r["ders_id"])
            islenen += 1
        except Exception as e:
            log.exception("kutu dosyası işlenemedi: %s", f)
            try:
                dst = await asyncio.to_thread(_tasi, f, k / "Eklenemedi")
                dst.with_name(dst.name + ".neden.txt").write_text(f"{type(e).__name__}: {getattr(e, 'detail', e)}", "utf-8")
            except OSError:
                pass
            olay("hata", f"⚠ {f.name} eklenemedi: {getattr(e, 'detail', None) or e}")
        _seen.pop(str(f), None)
    return islenen


async def kitaplari_tara() -> int:
    """Not Kutusu/Kitaplar'a bırakılan kitapları kütüphaneye ekler, sonra Eklendi/Kitaplar'a taşır."""
    from . import kutuphane

    kd = kutu_yolu() / "Kitaplar"
    if not kd.exists():
        return 0
    n = 0
    for f in sorted(kd.iterdir()):
        if not f.is_file() or f.name.startswith(("~$", ".")) or f.suffix.lower() not in kutuphane.UZANTILAR:
            continue
        if not _hazir_mi(f):
            continue
        try:
            data = await asyncio.to_thread(f.read_bytes)
            zaten = False
            try:
                await asyncio.to_thread(kutuphane.ekle_dosya, f.name, data, "kitap")
            except ValueError as e:
                if "zaten kütüphanede" not in str(e):
                    raise
                zaten = True  # önceki turda eklenmiş ama taşınamamış: hata sayma, taşımayı yeniden dene
            try:
                await asyncio.to_thread(_tasi, f, kutu_yolu() / "Eklendi" / "Kitaplar")
            except OSError:
                if not zaten:
                    raise
                continue  # hâlâ kilitli: sessiz geç, sonraki taramada tekrar denenir
            if not zaten:
                olay("kutuphane", f"📚 {f.name} kütüphaneye alındı; okunup dizinleniyor…")
            n += 1
        except Exception as e:
            log.warning("kitap eklenemedi: %s: %s", f, e)
            try:
                dst = await asyncio.to_thread(_tasi, f, kutu_yolu() / "Eklenemedi")
                dst.with_name(dst.name + ".neden.txt").write_text(f"{type(e).__name__}: {e}", "utf-8")
            except OSError:
                pass
            olay("hata", f"⚠ {f.name} kütüphaneye eklenemedi: {e}")
        _seen.pop(str(f), None)
    return n


def indirilenleri_tara() -> int:
    """İndirilenler'deki ders paketlerini (son 60 gün) bir kez kurar."""
    from . import hazir

    d = indirilenler()
    if not d.exists():
        return 0
    kurulan = 0
    limit = time.time() - 60 * 86400
    for f in d.glob("*.json"):
        try:
            st = f.stat()
            if st.st_mtime < limit or st.st_size > hazir.MAX_BYTES or st.st_size < 200:
                continue
            data = f.read_bytes()
            if not hazir.looks_like_pack(data) or hazir.already_installed(data):
                continue
            r = hazir.install_pack(data)
            olay("paket", f"📦 İndirilenler'deki ders paketi kuruldu: {r.get('ders_adi') or r['id']} ({r['belge']} belge)",
                 r.get("ders_id", ""))
            kurulan += 1
        except Exception as e:
            log.warning("indirilen paket kurulamadı: %s: %s", f, e)
    return kurulan


async def izle(ekle, aralik: float = 5.0) -> None:
    """Uygulama açık kaldıkça Not Kutusu'nu ve (seyrek) İndirilenler'i izler."""
    try:
        await asyncio.to_thread(kutu_hazirla)
    except OSError as e:
        log.warning("Not Kutusu oluşturulamadı: %s", e)
    son_indirilen = 0.0
    while True:
        try:
            if load_settings().get("not_kutusu", True):
                await kutuyu_tara(ekle)
                await kitaplari_tara()
            if time.time() - son_indirilen > 120:
                son_indirilen = time.time()
                await asyncio.to_thread(indirilenleri_tara)
        except Exception:
            log.exception("klasör izleme hatası")
        await asyncio.sleep(aralik)


def baslat(ekle) -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.get_event_loop().create_task(izle(ekle))
