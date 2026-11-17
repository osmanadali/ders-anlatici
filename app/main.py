"""Ders Anlatıcı — FastAPI sunucusu.

Çalıştır:  uvicorn app.main:app --reload   →  http://localhost:8000
"""
from __future__ import annotations

import asyncio
import os
import hashlib
import json
import logging
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, bilgi_haritasi, calisma, curriculum, erp_alistirma, hazir, hazir_bilgi, hesap, klasor, kutuphane, llm, notes, ogrenme, paket, prompts, siniflandir, store, voice, yerel
from .config import DATA_DIR, ROOT, load_settings, save_settings

log = logging.getLogger("ders")


def _setup_file_log() -> None:
    """Hatalar veri/sunucu.log dosyasına yazılır (sorun olunca bu dosyayı göndermek yeterli)."""
    from logging.handlers import RotatingFileHandler

    root = logging.getLogger()
    if any(getattr(h, "_ders", False) for h in root.handlers):
        return
    h = RotatingFileHandler(DATA_DIR / "sunucu.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    h.setLevel(logging.WARNING)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h._ders = True
    root.addHandler(h)
    for name in ("uvicorn.error", "ders"):
        logging.getLogger(name).addHandler(h)
    import sys as _sys
    import threading as _thr

    def _yakala(tip, deger, iz):  # yakalanmamış her hata dosyaya yazılsın (gece çökmelerinin izi için)
        logging.getLogger("ders").error("yakalanmamış hata", exc_info=(tip, deger, iz))

    _sys.excepthook = _yakala
    _thr.excepthook = lambda a: a.exc_type is not SystemExit and logging.getLogger("ders").error(
        "iş parçacığında yakalanmamış hata (%s)", getattr(a.thread, "name", "?"), exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


_setup_file_log()
app = FastAPI(title="Ders Anlatıcı")
app.middleware("http")(auth.middleware)
STATIC = ROOT / "static"
TTS_CACHE = DATA_DIR / "ses_onbellek"
TTS_CACHE.mkdir(parents=True, exist_ok=True)

# (oturum, adım) → ses üretim görevi. Ses, model sonraki adımları yazarken paralel üretilir.
_audio_tasks: dict[tuple[str, int], asyncio.Task] = {}
_ocr_tasks: set[asyncio.Task] = set()


# ================================================================ sayfa
@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ================================================================ 3B hoca modeli (Tripo vb. iskeletli GLB)
TEACHER_GLB = DATA_DIR / "hoca.glb"  # kullanıcının yüklediği model
VARSAYILAN_GLB = STATIC / "hoca_varsayilan.glb"  # uygulamayla gelen hoca (Tripo, iskeletli)


def _hoca_glb():
    return TEACHER_GLB if TEACHER_GLB.exists() else (VARSAYILAN_GLB if VARSAYILAN_GLB.exists() else None)


@app.get("/api/teacher-model/info")
async def teacher_model_info():
    glb = _hoca_glb()
    if not glb:
        return {"exists": False}
    st = glb.stat()
    return {"exists": True, "version": f"{int(st.st_mtime)}-{st.st_size}", "varsayilan": glb == VARSAYILAN_GLB}


@app.api_route("/api/teacher-model", methods=["GET", "HEAD"])
async def teacher_model():
    glb = _hoca_glb()
    if not glb:
        raise HTTPException(404, "Model yok")
    st = glb.stat()
    return FileResponse(glb, media_type="model/gltf-binary", headers={"ETag": f'"{int(st.st_mtime)}-{st.st_size}"'})


@app.post("/api/teacher-model")
async def upload_teacher_model(file: UploadFile = File(...)):
    data = await file.read()
    if data[:4] != b"glTF":
        raise HTTPException(400, "Bu bir GLB dosyası değil. Tripo'dan modeli 'GLB' biçiminde indir.")
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(400, "Model 200 MB'tan büyük; Tripo'da daha düşük çözünürlükle indir.")
    TEACHER_GLB.write_bytes(data)
    return {"ok": True, "mb": round(len(data) / 1e6, 1)}


@app.delete("/api/teacher-model")
async def delete_teacher_model():
    TEACHER_GLB.unlink(missing_ok=True)
    return {"ok": True}


# ================================================================ hazır ders paketi (önceden işlenmiş notlar)
@app.get("/api/hazir")
async def list_hazir():
    return hazir.list_packs()


@app.post("/api/hazir")
async def upload_hazir(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return await asyncio.to_thread(hazir.install_pack, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ================================================================ telefondan erişim
@app.get("/giris")
async def login_page():
    return auth.login_page()


@app.post("/api/login")
async def login(sifre: str = Form("")):
    return auth.login_response(sifre, secure=True)


@app.get("/api/connect-info")
async def connect_info():
    info = auth.phone_info()
    return {"url": info.get("url", ""), "password": info.get("password", "") or bool(auth.password())}


# ================================================================ ayarlar ve sesler
@app.get("/api/settings")
async def get_settings():
    return load_settings()


@app.post("/api/settings")
async def post_settings(patch: dict):
    return save_settings(patch)


# ---------------------------------------------------------------- hazırlık durumu
_literatur_gorevi: asyncio.Task | None = None
_calisma_gorevi: asyncio.Task | None = None


@app.on_event("startup")
async def _warm_up():
    """Ücretsiz konuşma tanıma (Whisper) modelini açılışta arka planda hazırla (ilk seferde ~1.6 GB iner)."""
    def _dongu_hatasi(loop, ctx):  # arka plan görevlerindeki yakalanmamış hatalar sunucu.log'a
        log.error("arka plan görevi hatası: %s", ctx.get("message"), exc_info=ctx.get("exception"))

    asyncio.get_running_loop().set_exception_handler(_dongu_hatasi)
    try:
        paket.acilista_duzelt()  # kapanırken yarıda kalan paket üretimleri "yarida" görünsün
    except Exception:
        log.exception("paket durumları düzeltilemedi")
    if load_settings().get("stt_provider") == "whisper" and os.getenv("DERS_ON_YUKLEME", "1") != "0":
        # arka plan iş parçacığı (daemon): indirme sürerken uygulama kapatılırsa kapanmayı engellemez
        import threading

        threading.Thread(target=voice.warm_whisper, daemon=True).start()
    if os.getenv("DERS_ON_YUKLEME", "1") != "0":
        import threading as _th

        _th.Thread(target=voice.warm_piper, daemon=True).start()  # internet kesilirse ses sürsün
    # Yerel yapay zeka: ilk açılışta programı ve modeli indirir, sonraki açılışlarda yalnızca başlatır.
    if os.getenv("DERS_ON_YUKLEME", "1") != "0" and load_settings().get("llm_provider") != "gemini":
        yerel.baslat_arka_planda()
    # Kütüphane: kuyruktaki kitapları işler, gömmeleri tamamlar; literatür taraması haftada bir
    if os.getenv("DERS_ON_YUKLEME", "1") != "0":
        try:
            await asyncio.to_thread(hazir_bilgi.yukle)  # ERP/MRP rehberleri (bir kez)
        except Exception:
            log.exception("hazır bilgi rehberleri eklenemedi")
    try:
        kutuphane.baslat_isleyici()
    except Exception:
        log.exception("kütüphane işleyici başlatılamadı")
    if os.getenv("DERS_ON_YUKLEME", "1") != "0":
        try:
            from . import literatur

            global _literatur_gorevi
            _literatur_gorevi = asyncio.create_task(literatur.zamanlayici())
        except Exception:
            log.exception("literatür zamanlayıcı başlatılamadı")
    if os.getenv("DERS_ON_YUKLEME", "1") != "0":
        global _calisma_gorevi
        _calisma_gorevi = asyncio.create_task(calisma.zamanlayici())  # bilgisayar boşken kendi kendine çalışma
    # Masaüstündeki "Not Kutusu" ve İndirilenler'deki ders paketleri kendiliğinden içe aktarılır
    if os.getenv("DERS_ON_YUKLEME", "1") != "0":
        klasor.baslat(otomatik_ekle)
    if os.getenv("DERS_ON_YUKLEME", "1") != "0": from . import guncel as _guncel; _guncel.zamanlayici_baslat()  # sektör haberleri, bülten, Vikipedi


@app.on_event("shutdown")
async def _shutdown():
    yerel.stop_server()  # yalnızca bizim başlattığımız yerel yapay zeka sunucusu kapanır


# ---------------------------------------------------------------- yerel yapay zeka (kurulum durumu)
@app.get("/api/yerel")
async def yerel_durum():
    return yerel.durum()


@app.post("/api/yerel/hazirla")
async def yerel_hazirla(body: dict | None = None):
    """Kurulumu başlatır/yeniden dener. {"model": "gemma4:e4b"} ile başka model seçilebilir ("" = otomatik)."""
    if body and "model" in body:
        m = str(body["model"] or "")
        if m and m not in yerel.MODELS:
            raise HTTPException(400, "Bilinmeyen model")
        save_settings({"yerel_model": m})
        if yerel.STATE.get("state") == "hazir" and m != yerel.STATE.get("model"):
            yerel.STATE["state"] = "bilinmiyor"
    yerel.baslat_arka_planda()
    return yerel.durum()


LAST_PING = [0.0]  # uygulama penceresinden son "buradayım" zamanı (başlatıcı pencere kapanınca sunucuyu kapatır)
YENIDEN_BASLAT = [False]  # başlatıcı bunu görünce sunucuyu kapatır, güncelleyip yeniden açar
_guncel_onbellek: dict = {"zaman": 0.0, "sonuc": None}


def _surum_denetle() -> dict:
    """GitHub'daki son sürüm bu kurulumdan yeni mi? (10 dk önbellekli; internet yoksa yeni=False)"""
    import time as _t

    if _guncel_onbellek["sonuc"] is not None and _t.time() - _guncel_onbellek["zaman"] < 600:
        return _guncel_onbellek["sonuc"]
    sonuc = {"yeni": False, "mesaj": "", "simdiki": ""}
    try:
        import subprocess as _sp
        import sys as _sys

        if str(ROOT) not in _sys.path:
            _sys.path.insert(0, str(ROOT))
        import guncelle

        if (ROOT / ".git").exists():
            simdiki = _sp.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10,
                              creationflags=0x08000000 if os.name == "nt" else 0).stdout.strip()
        else:
            simdiki = guncelle.load_state().get("sha", "")
        sha, mesaj = guncelle.latest_commit()
        sonuc = {"yeni": bool(sha and simdiki and sha != simdiki), "mesaj": mesaj, "simdiki": simdiki[:7]}
    except Exception as e:
        sonuc["hata"] = f"{type(e).__name__}"
    _guncel_onbellek.update(zaman=_t.time(), sonuc=sonuc)
    return sonuc


@app.get("/api/guncelle/durum")
async def guncelle_durum():
    d = dict(await asyncio.to_thread(_surum_denetle))
    d["baslatici"] = os.getenv("DERS_BASLATICI") == "1"
    d["mesgul"] = not llm.ogrenci_bosta(20)  # anlatım sürüyorsa kendiliğinden yeniden başlatma
    return d


@app.post("/api/guncelle/yeniden-baslat")
async def guncelle_yeniden_baslat(request: Request):
    if not auth.is_local(request):
        raise HTTPException(403, "Yalnızca bilgisayardan yapılabilir.")
    if os.getenv("DERS_BASLATICI") != "1":
        raise HTTPException(409, "Uygulama başlatıcıyla açılmamış; kapatıp 'Ders Anlatıcı' kısayoluyla yeniden aç.")
    YENIDEN_BASLAT[0] = True
    return {"ok": True}


@app.post("/api/ping")
async def ping():
    import time as _t

    LAST_PING[0] = _t.time()
    return {"ok": True}


@app.get("/api/version")
async def version():
    import sys as _sys

    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    import guncelle

    st = guncelle.load_state()
    return {"sha": (st.get("sha") or "")[:7], "message": st.get("message", ""), "updated": st.get("updated", 0)}


@app.get("/api/status")
async def status():
    return {"whisper": voice.WHISPER_STATE["state"], "whisper_detail": voice.WHISPER_STATE.get("detail", ""),
            "brain": llm.provider(), "brain_label": llm.brain_label(), "yerel": yerel.durum()}


@app.get("/api/keys")
async def keys_status():
    """Hangi anahtarların girildiğini söyler (anahtarın kendisini asla göndermez)."""
    from .config import elevenlabs_key, gemini_key

    def mask(k: str) -> str:
        return (k[:4] + "…" + k[-4:]) if len(k) > 12 else ("girildi" if k else "")

    return {"gemini": mask(gemini_key()), "elevenlabs": mask(elevenlabs_key())}


class KeysBody(BaseModel):
    gemini: str | None = None
    elevenlabs: str | None = None


@app.post("/api/keys")
async def keys_save(body: KeysBody, request: Request):
    # Anahtarlar yalnızca bilgisayarın kendisinden girilebilir (telefondan/tünelden değil).
    if not auth.is_local(request):
        raise HTTPException(403, "API anahtarları yalnızca bilgisayardan girilebilir.")
    from .config import save_keys

    save_keys({k: v for k, v in body.model_dump().items() if v is not None})
    return await keys_status()


@app.get("/api/llm-options")
async def llm_options():
    from .config import gemini_key

    out = {"gemini": bool(gemini_key()), "active": llm.provider(), "brain": llm.brain_label(), "gemini_models": [],
           "yerel": yerel.durum()}
    if gemini_key():
        try:
            out["gemini_models"] = await llm.llm_gemini.list_models()
            out["gemini_auto"] = llm.llm_gemini.pick_default(out["gemini_models"])
        except llm.llm_gemini.GeminiError as e:
            out["gemini_error"] = str(e)
    return out


@app.get("/api/voice-options")
async def voice_options():
    return {"edge": voice.EDGE_VOICES, "sample": voice.VOICE_SAMPLE.exists()}


@app.post("/api/voice-sample")
async def voice_sample(file: UploadFile = File(...)):
    """Ücretsiz yerel klon (XTTS) için kendi sesinden 10-30 sn örnek."""
    try:
        sec = await asyncio.to_thread(voice.save_voice_sample, await file.read(), file.filename or "")
    except voice.VoiceError as e:
        raise HTTPException(400, str(e))
    save_settings({"tts_provider": "xtts"})  # kendi sesin hazır: ücretsiz yerel klona geç
    return {"seconds": round(sec, 1), "tts_provider": "xtts"}


@app.get("/api/voices")
async def get_voices():
    try:
        return await voice.list_voices()
    except voice.VoiceError as e:
        raise HTTPException(502, str(e))


# ================================================================ dersler ve notlar
@app.get("/api/courses")
async def courses():
    return notes.list_courses()


class NewCourse(BaseModel):
    name: str


@app.post("/api/courses")
async def create_course(body: NewCourse):
    return notes.create_course(body.name)


@app.get("/api/courses/{course_id}")
async def course(course_id: str):
    c = notes.get_course(course_id)
    if not c:
        raise HTTPException(404, "Ders bulunamadı")
    return c


@app.delete("/api/courses/{course_id}")
async def delete_course(course_id: str):
    notes.delete_course(course_id)
    return {"ok": True}


@app.post("/api/courses/{course_id}/docs")
async def upload_doc(course_id: str, file: UploadFile = File(...)):
    return await _add_doc(course_id, file.filename or "belge", await file.read())


async def _add_doc(course_id: str, filename: str, data: bytes) -> dict:
    """Notu derse ekler: sayfalara ayırır, hazır paketi uygular, taranmış sayfaları okumaya sıraya koyar."""
    try:
        doc = await asyncio.to_thread(notes.add_document, course_id, filename, data)
    except KeyError:
        raise HTTPException(404, "Ders bulunamadı")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # ör. eksik paket, bozuk PDF: sebebi kullanıcıya ve log'a yaz
        log.exception("not yüklenemedi: %s", filename)
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    # Hazır ders paketinde varsa: taranmış sayfa metinleri, özet, ders planı… kendiliğinden eklenir
    try:
        if hazir.apply_to_document(course_id, doc, filename):
            doc = notes.find_doc(notes.get_course(course_id), doc["id"]) or doc
    except Exception:
        log.exception("hazır paket uygulanamadı: %s", filename)
    _schedule_ocr(course_id, doc)
    paket.yeni_belge(course_id)  # ayar açıksa biraz bekleyip ders paketini artımlı günceller
    return doc


# ---------------------------------------------------------------- dersini kendisi bulan not ekleme
async def _ilk_sayfa_metni(filename: str, data: bytes) -> str:
    """Metni olmayan not (fotoğraf, taranmış PDF): ilk sayfayı yapay zekaya okutur."""
    if not llm.ai_hazir():
        return ""
    try:
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext == "pdf":
            def render() -> bytes:
                import io as _io

                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(data)
                try:
                    buf = _io.BytesIO()
                    pdf[0].render(scale=1.4).to_pil().save(buf, format="PNG")
                    return buf.getvalue()
                finally:
                    pdf.close()

            png = await asyncio.to_thread(render)
        else:
            png = data
        return await llm.ocr_page(png)
    except Exception as e:
        log.warning("ilk sayfa okunamadı (%s): %s", filename, e)
        return ""


async def otomatik_ekle(filename: str, data: bytes, ipucu: str = "") -> dict:
    """Notun dersini bulur (kod → paket → benzerlik → yapay zeka), gerekirse dersi oluşturur ve ekler."""
    text = await asyncio.to_thread(siniflandir.metin_cikar, filename, data)
    if len(text.strip()) < 80:
        text = (text + "\n" + await _ilk_sayfa_metni(filename, data)).strip()
    s = await asyncio.to_thread(siniflandir.bul, filename, text, ipucu)
    if (s.course_id is None or s.guven < 0.6) and text.strip() and llm.ai_hazir():
        s = await siniflandir.bul_yapay_zeka(filename, text, s)
    s = siniflandir.en_yakin(s)
    cid, yeni = await asyncio.to_thread(siniflandir.ders_hazirla, s)
    doc = await _add_doc(cid, filename, data)
    name = (notes.get_course(cid) or {}).get("name", "")
    return {"ders_id": cid, "ders_adi": name, "neden": s.neden if s.course_id or s.yeni_ders else "ders bulunamadı",
            "guven": round(s.guven, 2), "yeni_ders": yeni, "doc": doc, "adaylar": s.adaylar}


@app.post("/api/notes/auto")
async def upload_auto(file: UploadFile = File(...), ipucu: str = Form("")):
    data = await file.read()
    name = file.filename or "not"
    if name.lower().endswith(".json"):
        try:
            return {"paket": await asyncio.to_thread(hazir.install_pack, data)}
        except ValueError as e:
            raise HTTPException(400, str(e))
    return await otomatik_ekle(name, data, ipucu)


class MoveBody(BaseModel):
    hedef: str


@app.post("/api/courses/{course_id}/docs/{doc_id}/move")
async def move_doc(course_id: str, doc_id: str, body: MoveBody):
    try:
        await asyncio.to_thread(notes.move_document, course_id, doc_id, body.hedef)
    except KeyError as e:
        raise HTTPException(404, str(e))
    paket.yeni_belge(body.hedef)  # iki dersin paketi de güncellensin
    paket.yeni_belge(course_id)
    return {"ok": True}


@app.get("/api/kutu")
async def kutu(son: int = 0):
    """Not Kutusu klasörü ve sonraki olaylar (arayüz bildirim olarak gösterir)."""
    return {"yol": str(klasor.kutu_yolu()), "olaylar": [o for o in klasor.OLAYLAR if o["id"] > son]}


# ================================================================ kütüphane (kitaplar, makaleler)
def _literatur_durum() -> dict:
    try:
        from . import literatur

        return literatur.durum()
    except Exception as e:
        return {"son_tarama": None, "sonraki": None, "calisiyor": False, "son_sonuc": None,
                "otomatik": bool(load_settings().get("literatur_otomatik", True)), "hata": f"Literatür modülü yok: {e}"}


@app.get("/api/kutuphane")
async def kutuphane_liste():
    kaynaklar = await asyncio.to_thread(kutuphane.liste)
    return {"kaynaklar": kaynaklar, "durum": await asyncio.to_thread(kutuphane.durum), "literatur": _literatur_durum()}


@app.get("/api/bilgi-haritasi")
async def bilgi_haritasi_ver():
    """Endüstri mühendisliği konu ağacı + kütüphane kapsamı (zayıf düğümler işaretli)."""
    return await asyncio.to_thread(bilgi_haritasi.agac)


@app.get("/api/erp-alistirma")
async def erp_alistirma_yeni(seed: int | None = None, seviye: int = 2):
    """Rastgele MRP alıştırması (çözüm sunucuda kalır)."""
    return erp_alistirma.yeni(seed, seviye)


class ErpKontrol(BaseModel):
    id: str
    cevap: dict[str, list[float | None]] = {}


@app.post("/api/erp-alistirma/kontrol")
async def erp_alistirma_kontrol(body: ErpKontrol):
    try:
        return erp_alistirma.kontrol(body.id, body.cevap)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/kutuphane")
async def kutuphane_ekle(files: list[UploadFile] = File(default=[]), tur: str = Form("kitap")):
    eklenen, atlanan = [], []
    for f in files:
        ad = f.filename or "dosya"
        try:
            veri = await f.read()
            eklenen.append(await asyncio.to_thread(kutuphane.ekle_dosya, ad, veri, tur))
        except ValueError as e:
            atlanan.append({"dosya": ad, "neden": str(e)})
        except Exception as e:
            log.exception("kütüphaneye eklenemedi: %s", ad)
            atlanan.append({"dosya": ad, "neden": f"Eklenemedi: {e}"})
    if not eklenen and not atlanan:
        raise HTTPException(400, "Dosya seçilmedi")
    return {"eklenen": eklenen, "atlanan": atlanan}


@app.get("/api/kutuphane/ara")
async def kutuphane_ara(q: str = "", ders: str = ""):
    return {"sonuclar": await asyncio.to_thread(kutuphane.ara, q, ders or None, 8)}


@app.patch("/api/kutuphane/{kid}")
async def kutuphane_guncelle(kid: str, body: dict):
    try:
        return await asyncio.to_thread(kutuphane.guncelle, kid, body)
    except KeyError:
        raise HTTPException(404, "Kaynak bulunamadı")


@app.delete("/api/kutuphane/{kid}")
async def kutuphane_sil(kid: str):
    try:
        await asyncio.to_thread(kutuphane.sil, kid)
    except KeyError:
        raise HTTPException(404, "Kaynak bulunamadı")
    return {"ok": True}


@app.post("/api/literatur/guncelle")
async def literatur_guncelle():
    try:
        from . import literatur

        literatur.baslat_arka_planda(zorla=True)
    except Exception as e:
        log.exception("literatür taraması başlatılamadı")
        raise HTTPException(503, f"Literatür taraması başlatılamadı: {e}")
    return _literatur_durum()


@app.get("/api/literatur")
async def literatur_durum():
    return _literatur_durum()


@app.delete("/api/courses/{course_id}/docs/{doc_id}")
async def delete_doc(course_id: str, doc_id: str):
    notes.delete_document(course_id, doc_id)
    return {"ok": True}


# ---------------------------------------------------------------- ders ses kaydı → not
@app.post("/api/courses/{course_id}/recordings")
async def upload_recording(course_id: str, file: UploadFile = File(...)):
    data = await file.read()
    try:
        doc = await asyncio.to_thread(notes.add_audio_document, course_id, file.filename or "kayit.mp3", data)
    except KeyError:
        raise HTTPException(404, "Ders bulunamadı")
    except ValueError as e:
        raise HTTPException(400, str(e))
    t = asyncio.create_task(_process_recording(course_id, doc["id"], file.content_type or "audio/mpeg"))
    _ocr_tasks.add(t)
    t.add_done_callback(_ocr_tasks.discard)
    return doc


async def _process_recording(course_id: str, doc_id: str, content_type: str) -> None:
    src = notes.audio_source(course_id, doc_id)
    try:
        text = await voice.transcribe_long(src.read_bytes(), src.name, content_type)
        if len(text) < 30:
            raise voice.VoiceError("Kayıtta anlaşılır konuşma bulunamadı.")
        (src.parent / "transkript.txt").write_text(text, "utf-8")
        notes.update_doc(course_id, doc_id, status="Ders notuna dönüştürülüyor…")
        organized = await llm.lecture_notes(text, notes.get_course(course_id))
        pages = [{"n": i + 1, "text": f"## {sec.title}\n\n{sec.content}", "needs_ocr": False, "title": sec.title}
                 for i, sec in enumerate(organized.sections)]
        notes.update_doc(course_id, doc_id, pages=pages, status="",
                         **({"name": organized.title} if organized.title else {}))
        paket.yeni_belge(course_id)
    except (voice.VoiceError, llm.TutorError) as e:
        notes.update_doc(course_id, doc_id, status=f"Hata: {e}")
    except Exception as e:  # beklenmeyen hata da kullanıcıya görünsün
        log.exception("kayıt işleme")
        notes.update_doc(course_id, doc_id, status=f"Hata: {e}")


@app.get("/api/courses/{course_id}/docs/{doc_id}/transcript")
async def transcript(course_id: str, doc_id: str):
    f = notes.doc_dir(course_id, doc_id) / "transkript.txt"
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text("utf-8"), media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------- formül kâğıdı
class FocusBody(BaseModel):
    focus: str = ""


@app.get("/api/courses/{course_id}/formula-sheet")
async def get_formula_sheet(course_id: str):
    c = notes.get_course(course_id)
    if not c:
        raise HTTPException(404)
    return {"course": c["name"], "sheet": c.get("formula_sheet")}


@app.post("/api/courses/{course_id}/formula-sheet")
async def make_formula_sheet(course_id: str, body: FocusBody):
    course = notes.get_course(course_id)
    _require_material(course)
    nt = notes.notes_context(course, body.focus, limit=llm.notes_limit())
    try:
        sheet = await llm.formula_sheet(course, nt.text, nt.full, body.focus)
    except llm.TutorError as e:
        raise HTTPException(502, str(e))
    data = sheet.model_dump() | {"created": time.time(), "focus": body.focus}
    notes.set_course_field(course_id, "formula_sheet", data)
    return {"course": course["name"], "sheet": data}


# ---------------------------------------------------------------- uygulamanın kendi ürettiği ders paketi
class PaketBody(BaseModel):
    deneme_sayisi: int = 2
    yeniden: bool = False


@app.post("/api/courses/{course_id}/paket")
async def paket_baslat(course_id: str, body: PaketBody | None = None):
    body = body or PaketBody()
    try:
        return paket.baslat(course_id, body.deneme_sayisi, body.yeniden)
    except KeyError:
        raise HTTPException(404, "Ders bulunamadı")


@app.get("/api/courses/{course_id}/paket")
async def paket_durum(course_id: str):
    if not notes.get_course(course_id):
        raise HTTPException(404, "Ders bulunamadı")
    return paket.durum(course_id)


class FormatBody(BaseModel):
    metin: str = ""


@app.post("/api/courses/{course_id}/sinav-formati")
async def sinav_formati(course_id: str, body: FormatBody):
    c = notes.set_course_field(course_id, "sinav_formati", body.metin.strip()[:4000])
    if not c:
        raise HTTPException(404, "Ders bulunamadı")
    return {"ok": True, "metin": c["sinav_formati"]}


# ---------------------------------------------------------------- sınav takvimi
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class ScheduleBody(BaseModel):
    exam_date: str  # YYYY-MM-DD
    exam_type: str = "vize"
    scope: str = ""
    minutes: int = 90
    today: str = ""  # tarayıcının yerel tarihi


@app.post("/api/courses/{course_id}/schedule")
async def make_schedule(course_id: str, body: ScheduleBody):
    course = notes.get_course(course_id)
    _require_material(course)
    try:
        today = date.fromisoformat(body.today) if body.today else date.today()
        exam = date.fromisoformat(body.exam_date)
    except ValueError:
        raise HTTPException(400, "Tarih biçimi YYYY-AA-GG olmalı")
    days_left = (exam - today).days
    if days_left < 0:
        raise HTTPException(400, "Sınav tarihi geçmiş")
    nt = notes.notes_context(course, body.scope, limit=llm.notes_limit())
    try:
        plan = await llm.study_plan(
            course, nt.text, nt.full,
            today=today.isoformat(), weekday=TR_DAYS[today.weekday()], exam_date=exam.isoformat(),
            exam_type=body.exam_type, days_left=days_left, minutes=max(15, min(body.minutes, 600)),
            scope=body.scope or "Sınava kadar işlenen tüm konular (müfredat ve notlar)",
            weak=store.memory_summary(course_id),
        )
    except llm.TutorError as e:
        raise HTTPException(502, str(e))
    days = [d.model_dump() for d in plan.days if today.isoformat() <= d.date <= exam.isoformat()]
    for d in days:
        for i, t in enumerate(d["tasks"]):
            t["id"] = f"{d['date']}-{i}"
    sched = {"exam_date": exam.isoformat(), "exam_type": body.exam_type, "scope": body.scope,
             "minutes": body.minutes, "created": time.time(), "days": days, "done": {}}
    notes.set_course_field(course_id, "schedule", sched)
    return sched


class DoneBody(BaseModel):
    task_id: str
    done: bool = True


@app.post("/api/courses/{course_id}/schedule/done")
async def schedule_done(course_id: str, body: DoneBody):
    course = notes.get_course(course_id)
    if not course or not course.get("schedule"):
        raise HTTPException(404)
    sched = course["schedule"]
    if body.done:
        sched["done"][body.task_id] = True
    else:
        sched["done"].pop(body.task_id, None)
    notes.set_course_field(course_id, "schedule", sched)
    return sched


@app.get("/api/today")
async def today_tasks(day: str = ""):
    """Bütün derslerin bugünkü görevleri ve yaklaşan sınavlar."""
    d = day or date.today().isoformat()
    tasks, exams = [], []
    for c in notes.list_courses():
        sched = c.get("schedule")
        if not sched:
            continue
        if sched["exam_date"] >= d:
            exams.append({"course_id": c["id"], "course": c["name"], "exam_date": sched["exam_date"],
                          "exam_type": sched["exam_type"]})
        for day_ in sched["days"]:
            if day_["date"] == d:
                for t in day_["tasks"]:
                    tasks.append(t | {"course_id": c["id"], "course": c["name"], "done": t["id"] in sched["done"]})
    exams.sort(key=lambda e: e["exam_date"])
    return {"date": d, "tasks": tasks, "exams": exams}


@app.get("/api/courses/{course_id}/docs/{doc_id}/pages/{page}.png")
async def page_image(course_id: str, doc_id: str, page: int):
    p = await asyncio.to_thread(notes.page_image_path, course_id, doc_id, page)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


def _schedule_ocr(course_id: str, doc: dict) -> None:
    """Metin katmanı olmayan sayfaları (taranmış PDF, fotoğraf) arka planda yapay zeka ile okur."""
    todo = [p["n"] for p in doc["pages"] if p.get("needs_ocr")]
    if not todo:
        return

    async def run():
        sem = asyncio.Semaphore(3)

        async def one(n: int):
            async with sem:
                try:
                    png = (await asyncio.to_thread(notes.page_image_path, course_id, doc["id"], n)).read_bytes()
                    await llm.arka_plan_sirasi()
                    text = await llm.ocr_page(png)
                    notes.set_page_text(course_id, doc["id"], n, text)
                except Exception as e:  # tek sayfa hatası tüm belgeyi durdurmasın
                    log.warning("OCR hatası %s s.%s: %s", doc["name"], n, e)

        await asyncio.gather(*(one(n) for n in todo))

    t = asyncio.create_task(run())
    _ocr_tasks.add(t)
    t.add_done_callback(_ocr_tasks.discard)
    paket.arka_ocr_ekle(course_id, t)  # paket işi aynı sayfaları ikinci kez okumasın, bunun bitmesini beklesin


# ================================================================ ses
async def _tts_to_file(path: Path, text: str, prev: str, nxt: str) -> Path:
    audio = await voice.speak(text, prev, nxt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return path


@app.get("/api/audio/{sid}/{idx}")
async def get_audio(sid: str, idx: int):
    path = store.audio_path(sid, idx)
    task = _audio_tasks.get((sid, idx))
    if task is not None:
        try:
            await asyncio.shield(task)
        except Exception as e:
            log.warning("ses üretilemedi (%s): %s", load_settings().get("tts_provider"), e)
            raise HTTPException(502, f"Ses üretilemedi: {e}")
        finally:
            if task.done():
                _audio_tasks.pop((sid, idx), None)
    if not path.exists():
        raise HTTPException(404, "Ses yok")
    return _audio_response(path)


def _audio_response(path: Path) -> FileResponse:
    with open(path, "rb") as f:
        head = f.read(4)
    return FileResponse(path, media_type=voice.sniff_mime(head))


class SpeakBody(BaseModel):
    text: str


async def _cached_tts(text: str) -> FileResponse:
    s = load_settings()
    if s["tts_provider"] == "browser":
        raise HTTPException(409, "Tarayıcı sesi seçili")
    vkey = {"edge": s["edge_voice"], "xtts": "xtts"}.get(s["tts_provider"], s["voice_id"] + s["tts_model"])
    key = hashlib.sha1(f"{s['tts_provider']}|{vkey}|{text}".encode()).hexdigest()
    path = TTS_CACHE / f"{key}.mp3"
    if not path.exists():
        try:
            await _tts_to_file(path, text[:2500], "", "")
        except Exception as e:
            log.warning("ses üretilemedi (%s): %s", s.get("tts_provider"), e)
            raise HTTPException(502, f"Ses üretilemedi: {e}")
    return _audio_response(path)


@app.post("/api/tts")
async def tts(body: SpeakBody):
    """Kısa metinleri (sınav geri bildirimi vb.) seslendirir; önbellekli."""
    return await _cached_tts(body.text)


@app.get("/api/tts")
async def tts_get(text: str):
    """<audio src> ile doğrudan çalınabilen sürüm (selamlama vb.)."""
    return await _cached_tts(text[:500])


@app.post("/api/stt")
async def stt(file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = await voice.listen(data, file.filename or "soru.webm", file.content_type or "audio/webm")
    except Exception as e:
        log.warning("konuşma yazıya çevrilemedi: %s", e)
        raise HTTPException(502, f"Konuşma yazıya çevrilemedi: {e}")
    return {"text": text}


# ================================================================ anlatım (soru, sayfa, ders bölümü)
def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()


async def _kaynak_bolumleri(course: dict | None, soru: str) -> str:
    """Kütüphaneden soruyla ilgili kitap/makale bölümleri (bütçe içinde). Kütüphane boşsa ya da hata olursa ''."""
    try:
        if not soru or await asyncio.to_thread(kutuphane.bos_mu):
            return ""
        ders = (siniflandir.ders_kodu(course) or course.get("name", "")) if course else None
        sonuc = await asyncio.to_thread(kutuphane.ara, soru[:1500], ders, 6)
        return kutuphane.kaynak_metni(sonuc, llm.kaynak_limit())
    except Exception:
        log.exception("kütüphane araması yapılamadı")
        return ""


@app.post("/api/ask")
async def ask(
    text: str = Form(""),
    session_id: str = Form(""),
    course_id: str = Form(""),
    mode: str = Form("chat"),  # chat | page | lecture
    doc_id: str = Form(""),
    page: int = Form(0),
    section: str = Form(""),  # ders modu: {"i":..,"n":..,"title":..,"summary":..,"pages":[..],"prev":..}
    interrupted: str = Form(""),  # öğrencinin kestiği yerdeki cümle
    style: str = Form(""),  # "konusma" = sesli karşılıklı ders (kısa, soru soran üslup)
    files: list[UploadFile] = File(default=[]),
):
    settings = load_settings()
    course = notes.get_course(course_id) if course_id else None

    session = store.load_session(session_id) if session_id else None
    if session is None:
        session = store.new_session(course_id or None, title=(text or "Anlatım")[:60])

    # ---- kullanıcı mesajını kur
    content: list[dict] = []
    attach_names: list[str] = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        name = f.filename or "dosya"
        ctype = (f.content_type or "").lower()
        if ctype == "application/pdf" or name.lower().endswith(".pdf"):
            content.append(llm.pdf_block(data, name))
        elif ctype.startswith("image/"):
            mt = ctype if ctype in ("image/png", "image/jpeg", "image/webp", "image/gif") else "image/png"
            content.append(llm.image_block(data, mt))
        else:
            continue
        attach_names.append(name)

    focus = None
    user_text = text.strip()
    if course and mode == "chat" and not doc_id:
        # "12. sayfayı anlat" → o sırada açık belge yoksa ilk belgeyi kullan
        n = notes.detect_page(user_text)
        if n and course["docs"]:
            doc_id, page = course["docs"][0]["id"], n
    elif course and mode == "chat" and doc_id and not page:
        page = notes.detect_page(user_text) or 0

    if course and doc_id and page:
        doc = notes.find_doc(course, doc_id)
        if doc and 1 <= page <= len(doc["pages"]):
            focus = (doc_id, page)
            img = await asyncio.to_thread(notes.page_image_path, course_id, doc_id, page)
            if img.exists():
                content.append(llm.image_block(img.read_bytes(), "image/png"))
            ptxt = doc["pages"][page - 1].get("text", "")
            content.append(
                {"type": "text", "text": f"[Ekteki görüntü: '{doc['name']}' (belge_id={doc_id}) sayfa {page}]\n{ptxt}"}
            )
            if mode == "page" or not user_text:
                user_text = (user_text + "\n" if user_text else "") + prompts.PAGE_EXPLAIN.format(
                    doc=doc["name"], page=page
                )

    if mode == "lecture" and section:
        sec = json.loads(section)
        user_text = prompts.LECTURE_SECTION.format(
            course=course["name"] if course else "",
            i=sec.get("i", 1),
            n=sec.get("n", 1),
            title=sec.get("title", ""),
            summary=sec.get("summary", ""),
            pages=", ".join(sec.get("pages", [])) or "-",
            prev=f"Bir önceki bölümde şunları anlattın: {sec['prev']}\n" if sec.get("prev") else "",
        )

    if interrupted:
        user_text = f'(Anlatırken "{interrupted[:300]}" dediğin yerde sözünü kestim.)\n' + user_text
    if not user_text and not content:
        raise HTTPException(400, "Boş soru")
    content.append({"type": "text", "text": user_text or "Ekteki görseli/dosyayı bana anlat."})
    user_msg = {"role": "user", "content": content}

    kaynak_txt = await _kaynak_bolumleri(course, text.strip() or user_text)
    nt = await asyncio.to_thread(notes.notes_context, course, user_text, focus, limit=llm.notes_limit() - len(kaynak_txt))
    soru_metni = text.strip() or user_text
    ogrenme_txt = ""
    tarz = "anlat"
    if mode == "chat":  # ders bölümü/sayfa anlatımında ek bloklar eklenmez
        if text.strip():
            ogrenme.profil_say(text, not_mu=False)
        try:
            def _bloklar() -> str:
                return "\n\n".join(b for b in (
                    ogrenme.ogrenme_blogu(course_id or None, soru_metni),
                    calisma.dogrulanmis_blok(course, soru_metni)) if b)

            ogrenme_txt = await asyncio.to_thread(_bloklar)
        except Exception:
            log.exception("öğrenme blokları kurulamadı")
        tarz = "sokratik" if settings.get("ogretme_tarzi") == "sokratik" else "anlat"
    system = llm.build_system(
        course, nt.text, nt.full, store.memory_summary(course_id or None), settings.get("level", "normal"),
        conversation=(style == "konusma"), kaynaklar=kaynak_txt, ogrenme=ogrenme_txt, tarz=tarz,
        sohbet=(mode == "chat"),
    )
    messages = session["messages"] + [user_msg]
    sid = session["id"]
    deep = _wants_deep(settings, mode, style, user_text, attach_names, bool(focus))
    hesapla = _wants_hesap(settings, mode, soru_metni)
    session["timeline"].append(
        {"type": "user", "text": text.strip() or user_text[:200], "attachments": attach_names, "mode": mode}
    )
    user_sira = len(session["timeline"]) - 1  # geri bildirim bu turu bu indeksle bulur

    async def gen():
        with llm.on_plan():  # öğrenci soruyor: arka plan işleri (paket, OCR) yerel modeli bırakır
            async for chunk in gen_inner():
                yield chunk

    async def gen_inner():
        yield _sse({"type": "session", "id": sid, "sira": user_sira})
        steps: list[dict] = []
        final = None
        prev_say = ""
        send = messages
        try:
            brain = llm.brain_label()
            if hesapla:
                hs = await _hesap_adimi(soru_metni)
                if hs:
                    yield _sse({"type": "hesap", "arac": hs.arac, "baslik": hs.baslik, "message": f"🧮 Hesaplandı: {hs.baslik}"})
                    send = messages[:-1] + [{"role": "user", "content": content + [
                        {"type": "text", "text": prompts.hesap_blogu(hesap.sonuc_metni(hs))}]}]
            if deep and send is messages:
                # Önce gerekçeli tam çözüm (öğrenciye gösterilmez), sonra hoca bunu izleyerek anlatır.
                yield _sse({"type": "status", "message": "Soruyu önce kendi kendime çözüyorum…"})
                try:
                    draft = await asyncio.wait_for(llm.deep_solution(system, content), DEEP_TIMEOUT)
                    send = messages[:-1] + [{"role": "user", "content": content + [
                        {"type": "text", "text": f"<cozum_taslagi>\n{draft}\n</cozum_taslagi>"}]}]
                except (llm.TutorError, asyncio.TimeoutError) as e:
                    log.warning("derin çözüm atlandı: %s", e or "süre aşımı")
            yield _sse({"type": "stage", "message": f"Hoca düşünüyor ({brain})…"})
            async for item in _with_timeouts(llm.stream_steps(system, send), brain):
                if "notice" in item:
                    yield _sse({"type": "notice", "message": item["notice"]})
                    continue
                if "final" in item:
                    final = item["final"]
                    if item.get("truncated"):
                        yield _sse({"type": "notice", "message": "Cevap çok uzadı ve kesildi."})
                    continue
                if "memory" in item:
                    m = item["memory"]
                    store.record_topic(course_id or None, str(m.get("topic", "")), None, str(m.get("note", "")))
                    yield _sse({"type": "memory", "topic": m.get("topic", "")})
                    continue
                idx = session["next_step"]
                session["next_step"] += 1
                audio = None
                if item["say"] and settings["tts_provider"] != "browser":
                    task = asyncio.create_task(_tts_to_file(store.audio_path(sid, idx), item["say"], prev_say, ""))
                    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                    _audio_tasks[(sid, idx)] = task
                    audio = f"/api/audio/{sid}/{idx}"
                    prev_say = item["say"]
                step = {"type": "step", "idx": idx, "say": item["say"], "board": item["board"], "audio": audio}
                steps.append(step)
                session["timeline"].append(step)
                yield _sse(step)
            yield _sse({"type": "done"})
        except llm.TutorError as e:
            log.warning("anlatım hatası: %s", e)
            yield _sse({"type": "error", "message": str(e)})
        except Exception as e:  # beklenmeyen her hata kullanıcıya görünsün ve log'a yazılsın
            log.exception("beklenmeyen anlatım hatası")
            yield _sse({"type": "error", "message": f"Beklenmeyen hata: {type(e).__name__}: {e}"})
        finally:
            if final is not None:
                assistant = {"role": "assistant", "content": final}
            elif steps:  # yarıda kesildi: söylenenleri geçmişe yaz ki model nerede kaldığını bilsin
                lines = "\n".join(json.dumps({"say": s["say"], "board": s["board"]}, ensure_ascii=False) for s in steps)
                assistant = {"role": "assistant", "content": [{"type": "text", "text": lines}]}
            else:
                assistant = None
            if assistant:
                session["messages"] = messages + [assistant]
            store.save_session(session)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ================================================================ hocanın kendini geliştirmesi
class GeriBildirim(BaseModel):
    session_id: str
    sira: int
    puan: int
    # Python'da 'not' ayrılmış sözcük: JSON'daki "not" alanı takma adla okunur
    not_: str = Field("", alias="not")

    model_config = {"populate_by_name": True}


@app.post("/api/geri-bildirim")
async def geri_bildirim(body: GeriBildirim):
    if body.puan not in (1, -1):
        raise HTTPException(400, "Puan 1 ya da -1 olmalı")
    try:
        session = store.load_session(body.session_id)
    except ValueError:
        session = None
    if session is None:
        raise HTTPException(404, "Oturum bulunamadı")
    try:
        k = ogrenme.geri_bildirim_kaydet(session, body.sira, body.puan, body.not_)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "puan": k["puan"]}


@app.get("/api/calisma")
async def calisma_durumu():
    return calisma.durum()


@app.get("/api/soru-bankasi")
async def soru_bankasi(ders: str, n: int = 5):
    try:
        course = notes.get_course(ders)
    except ValueError:
        course = None
    if course is None:
        raise HTTPException(404, "Ders bulunamadı")
    q = calisma.quiz_sorulari(course, n)
    if not q["questions"]:
        raise HTTPException(404, "Bu ders için soru bankasında henüz doğrulanmış soru yok")
    return q


@app.delete("/api/profil")
async def profil_sifirla():
    ogrenme.profil_sifirla()
    return {"ok": True}


# ================================================================ hazır müfredat
@app.get("/api/curriculum")
async def curriculum_list():
    return curriculum.programs()


class ImportBody(BaseModel):
    program: str
    codes: list[str]


@app.post("/api/curriculum/import")
async def curriculum_import(body: ImportBody):
    try:
        return curriculum.import_courses(body.program, body.codes)
    except KeyError:
        raise HTTPException(404, "Program bulunamadı")


FIRST_STEP_TIMEOUT = 120  # sn: ilk adım bu sürede gelmezse kullanıcıya açık hata (Gemini)
NEXT_STEP_TIMEOUT = 90
DEEP_TIMEOUT = 90
# Yerel modelde ilk istek notları okumakla (işlemcide yavaş) başlar; sonraki istekler önbellekten hızlanır.
YEREL_FIRST_STEP_TIMEOUT = 420
YEREL_NEXT_STEP_TIMEOUT = 180


async def _with_timeouts(agen, brain: str):
    """Model takılırsa sonsuza dek beklemek yerine anlaşılır bir hata verir."""
    first = True
    it = agen.__aiter__()
    local = llm.provider() == "yerel"
    t_first = YEREL_FIRST_STEP_TIMEOUT if local else FIRST_STEP_TIMEOUT
    t_next = YEREL_NEXT_STEP_TIMEOUT if local else NEXT_STEP_TIMEOUT
    while True:
        try:
            item = await asyncio.wait_for(it.__anext__(), t_first if first else t_next)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            await agen.aclose()
            raise llm.TutorError(
                f"{brain} {t_first if first else t_next} saniyedir cevap vermedi. "
                + ("Bilgisayar bu model için yavaş kalıyor olabilir: Ayarlar → Yapay zeka'dan daha küçük bir model seç."
                   if local else "İnternet bağlantını kontrol edip tekrar dene; sürerse Ayarlar'dan başka bir model seç.")
            )
        if "say" in item:
            first = False
        yield item


HESAP_ANAHTAR = (
    "optimum", "maliyet", "eoq", "kontrol karti", "cpk", "cp ", "mrp", "kuyruk", "atama", "ulastirma", "cpm", "pert",
    "kritik yol", "simpleks", "dogrusal programlama", "tamsayili", "stok", "siparis", "emniyet", "nbd", "igo",
    "net bugunku", "ic getiri", "basabas", "ogrenme egrisi", "johnson", "cizelge", "guven araligi", "t testi",
    "t-testi", "erlang", "m/m", "yeterlilik", "ucl", "lcl", "brut ihtiyac", "net ihtiyac", "urun agaci", "simulasyon",
    "benzetim", "spt", "edd", "gecikme", "ortalama", "standart sapma",
)
HESAP_TIMEOUT = 90


def _wants_hesap(settings: dict, mode: str, text: str) -> bool:
    """Sayı içeren ve bir mühendislik hesabına benzeyen sohbet sorularında hesap aracı denenir."""
    if not settings.get("hesap_araclari", True) or mode != "chat":
        return False
    t = kutuphane.katla(text or "")
    if len(t) < 20 or not any(ch.isdigit() for ch in t):
        return False
    return any(k in t for k in HESAP_ANAHTAR)


async def _hesap_adimi(soru: str):
    """Modele araç seçtirir, hesabı çalıştırır. Hata/eksik girdi/uygun araç yoksa sessizce None."""
    try:
        sec = await asyncio.wait_for(llm.hesap_secimi(soru), HESAP_TIMEOUT)
        if not sec:
            return None
        return hesap.calistir(sec["arac"], sec["girdiler"])
    except (llm.TutorError, asyncio.TimeoutError, hesap.HesapHatasi) as e:
        log.info("hesap aracı atlandı: %s", e or "süre aşımı")
    except Exception:
        log.exception("hesap aracı beklenmedik hata verdi")
    return None


def _wants_deep(settings: dict, mode: str, style: str, text: str, attachments: list, page: bool) -> bool:
    """'Önce çöz, sonra anlat' ne zaman çalışsın: problem/soru çözümlerinde (kısa sohbet cümlelerinde değil)."""
    choice = settings.get("deep_solve", "auto")
    if choice == "off" or mode == "lecture":
        return False
    if choice == "auto" and llm.provider() != "gemini":
        return False  # yerel modelde hız için kapalı (Ayarlar'dan açılabilir)
    if attachments:
        return True
    if style == "konusma" and len(text) < 60:
        return False  # "tamam", "anladım", "devam" gibi
    has_math = any(ch.isdigit() for ch in text) or any(k in text.lower() for k in (
        "çöz", "hesapla", "bul", "ispat", "türet", "neden", "nasıl", "nereden", "grafi", "soru"))
    return page or (len(text) > 25 and has_math)


# ================================================================ ders anlatım planı
class PlanBody(BaseModel):
    course_id: str
    focus: str = ""


def _require_material(course: dict | None) -> None:
    if not course:
        raise HTTPException(404, "Ders bulunamadı")
    if not course["docs"] and not course.get("profile"):
        raise HTTPException(400, "Bu derste ne not ne de müfredat bilgisi var. Not yükle ya da dersi müfredattan ekle.")


@app.post("/api/lecture/plan")
async def lecture_plan(body: PlanBody):
    course = notes.get_course(body.course_id)
    _require_material(course)
    nt = notes.notes_context(course, body.focus, limit=llm.notes_limit())
    try:
        with llm.on_plan():
            plan = await llm.lecture_plan(course, nt.text, nt.full, body.focus)
    except llm.TutorError as e:
        raise HTTPException(502, str(e))
    return plan.model_dump()


# ================================================================ sınav modu
class QuizBody(BaseModel):
    course_id: str
    count: int = 5
    difficulty: str = "orta"
    topic: str = ""


@app.post("/api/quiz/generate")
async def quiz_generate(body: QuizBody):
    course = notes.get_course(body.course_id)
    _require_material(course)
    nt = notes.notes_context(course, body.topic, limit=llm.notes_limit())
    try:
        with llm.on_plan():
            quiz = await llm.make_quiz(
                course, nt.text, nt.full, max(1, min(body.count, 20)), body.difficulty, body.topic,
                store.memory_summary(body.course_id),
            )
    except llm.TutorError as e:
        raise HTTPException(502, str(e))
    return quiz.model_dump()


@app.post("/api/quiz/grade")
async def quiz_grade(
    question: str = Form(...),
    answer: str = Form(""),
    course_id: str = Form(""),
    image: UploadFile | None = File(default=None),
):
    q = json.loads(question)
    img = None
    if image is not None:
        data = await image.read()
        if data:
            img = (data, image.content_type if (image.content_type or "").startswith("image/") else "image/png")
    if not answer.strip() and img is None:
        raise HTTPException(400, "Cevap boş")
    try:
        with llm.on_plan():
            g = await llm.grade(q, answer, img)
    except llm.TutorError as e:
        raise HTTPException(502, str(e))
    store.record_topic(course_id or None, g.mistake_topic or q.get("topic", ""), g.correct and g.score >= 0.7)
    return g.model_dump()


@app.get("/api/memory/{course_id}")
async def memory(course_id: str):
    return store.weak_topics(course_id, limit=50)


# ================================================================ kayıtlar
@app.get("/api/sessions")
async def sessions():
    return store.list_sessions()


@app.get("/api/sessions/{sid}")
async def session_detail(sid: str):
    s = store.load_session(sid)
    if not s:
        raise HTTPException(404)
    return {k: s[k] for k in ("id", "title", "course_id", "created", "timeline")}


@app.delete("/api/sessions/{sid}")
async def session_delete(sid: str):
    store.delete_session(sid)
    return {"ok": True}


@app.exception_handler(ValueError)
async def value_error(_, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/sw.js")
async def service_worker():
    # Kök kapsamlı olması için /sw.js adresinden sunulur.
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


from . import guncel as _guncel_modulu  # noqa: E402

app.include_router(_guncel_modulu.router)
