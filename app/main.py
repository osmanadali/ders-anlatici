"""Ders Anlatıcı — FastAPI sunucusu.

Çalıştır:  uvicorn app.main:app --reload   →  http://localhost:8000
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, curriculum, llm, notes, prompts, store, voice
from .config import DATA_DIR, ROOT, load_settings, save_settings

log = logging.getLogger("ders")
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
    return {"seconds": round(sec, 1)}


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
    data = await file.read()
    try:
        doc = await asyncio.to_thread(notes.add_document, course_id, file.filename or "belge", data)
    except KeyError:
        raise HTTPException(404, "Ders bulunamadı")
    except ValueError as e:
        raise HTTPException(400, str(e))
    _schedule_ocr(course_id, doc)
    return doc


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
    nt = notes.notes_context(course, body.focus)
    try:
        sheet = await llm.formula_sheet(course, nt.text, nt.full, body.focus)
    except llm.TutorError as e:
        raise HTTPException(502, str(e))
    data = sheet.model_dump() | {"created": time.time(), "focus": body.focus}
    notes.set_course_field(course_id, "formula_sheet", data)
    return {"course": course["name"], "sheet": data}


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
    nt = notes.notes_context(course, body.scope)
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
    p = notes.page_image_path(course_id, doc_id, page)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


def _schedule_ocr(course_id: str, doc: dict) -> None:
    """Metin katmanı olmayan sayfaları (taranmış PDF, fotoğraf) arka planda Claude ile okur."""
    todo = [p["n"] for p in doc["pages"] if p.get("needs_ocr")]
    if not todo:
        return

    async def run():
        sem = asyncio.Semaphore(3)

        async def one(n: int):
            async with sem:
                try:
                    png = notes.page_image_path(course_id, doc["id"], n).read_bytes()
                    text = await llm.ocr_page(png)
                    notes.set_page_text(course_id, doc["id"], n, text)
                except Exception as e:  # tek sayfa hatası tüm belgeyi durdurmasın
                    log.warning("OCR hatası %s s.%s: %s", doc["name"], n, e)

        await asyncio.gather(*(one(n) for n in todo))

    t = asyncio.create_task(run())
    _ocr_tasks.add(t)
    t.add_done_callback(_ocr_tasks.discard)


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
        except voice.VoiceError as e:
            raise HTTPException(502, str(e))
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
    except voice.VoiceError as e:
        raise HTTPException(502, str(e))
    return {"text": text}


# ================================================================ anlatım (soru, sayfa, ders bölümü)
def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()


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
            img = notes.page_image_path(course_id, doc_id, page)
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

    nt = notes.notes_context(course, user_text, focus)
    system = llm.build_system(
        course, nt.text, nt.full, store.memory_summary(course_id or None), settings.get("level", "normal"),
        conversation=(style == "konusma"),
    )
    messages = session["messages"] + [user_msg]
    sid = session["id"]
    session["timeline"].append(
        {"type": "user", "text": text.strip() or user_text[:200], "attachments": attach_names, "mode": mode}
    )

    async def gen():
        yield _sse({"type": "session", "id": sid})
        steps: list[dict] = []
        final = None
        prev_say = ""
        try:
            async for item in llm.stream_steps(system, messages):
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
            yield _sse({"type": "error", "message": str(e)})
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
    nt = notes.notes_context(course, body.focus)
    try:
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
    nt = notes.notes_context(course, body.topic)
    try:
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
