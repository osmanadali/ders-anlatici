"""Claude ve ElevenLabs yerine geçen sahte servisler (anahtar olmadan test ve arayüz denemesi için)."""
from __future__ import annotations

import asyncio
import io
import math
import struct
import wave

from app import llm, main, voice

CALLS: list[dict] = []

DEMO_STEPS = [
    {"say": "Güzel bir soru. Önce fonksiyonu tanıyalım.", "board": [{"op": "title", "text": "f(x) = x² − 4x + 3"}]},
    {"say": "Bu bir ikinci derece fonksiyon, yani grafiği bir parabol.", "board": [{"op": "write", "text": "İkinci derece → parabol, $a=1>0$ ise kollar yukarı"}]},
    {"say": "Kökleri bulmak için çarpanlara ayıralım: x eksi bir çarpı x eksi üç.", "board": [{"op": "math", "tex": "x^2-4x+3=(x-1)(x-3)"}, {"op": "arrow_note", "text": "kökler: x = 1 ve x = 3"}]},
    {"say": "Tepe noktası eksi b bölü iki a'dan, x eşittir iki.", "board": [{"op": "write", "text": "Tepe: $x_T=-\\frac{b}{2a}=2$, $f(2)=-1$", "color": "yellow"}, {"op": "underline"}]},
    {"say": "Şimdi grafiği çizelim: önce eksenler, sonra kökler ve tepe noktası, en son parabol.", "board": [{"op": "plot", "xrange": [-1, 5], "yrange": [-2, 6], "functions": [{"expr": "x^2-4x+3", "color": "yellow", "label": "f(x)"}], "points": [{"x": 1, "y": 0, "label": "1"}, {"x": 3, "y": 0, "label": "3"}, {"x": 2, "y": -1, "label": "T(2,-1)"}]}]},
    {"say": "Bir de küçük bir şekil: kuvvet diyagramı gibi oklarla gösterebilirim.", "board": [{"op": "diagram", "w": 6, "h": 3, "shapes": [{"type": "rect", "x": 2, "y": 1, "w": 2, "h": 1}, {"type": "arrow", "x1": 4, "y1": 1.5, "x2": 5.8, "y2": 1.5, "color": "red"}, {"type": "text", "x": 5, "y": 2, "text": "F", "color": "red"}]}]},
    {"say": "Sonuç olarak fonksiyonun en küçük değeri eksi bir.", "board": [{"op": "write", "text": "Cevap: $f_{min} = -1$", "color": "green"}, {"op": "box"}]},
]


def _beep(seconds: float = 1.2) -> bytes:
    """Gerçek bir mp3 yerine tarayıcının çalabileceği kısa bir WAV sesi."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        n = int(16000 * seconds)
        w.writeframes(b"".join(struct.pack("<h", int(1500 * math.sin(i / 16000 * 2 * math.pi * 220))) for i in range(n)))
    return buf.getvalue()


async def fake_stream_steps(system, messages):
    CALLS.append({"system": system, "messages": messages})
    for s in DEMO_STEPS:
        await asyncio.sleep(0.05)
        yield s
    yield {"memory": {"topic": "Parabol çizimi", "note": "tepe noktasını unutuyor"}}
    yield {"final": [{"type": "text", "text": "\n".join(str(s) for s in DEMO_STEPS)}], "truncated": False}


async def fake_synthesize(text, voice_id, model_id, previous_text="", next_text=""):
    await asyncio.sleep(0.05)
    return _beep(max(1.0, min(4.0, len(text) * 0.045)))


async def fake_transcribe(audio, filename="", content_type=""):
    return "Parabolün tepe noktası nasıl bulunur?"


async def fake_plan(course, notes_text, full):
    return llm.LecturePlan(
        title="Fonksiyonlar",
        sections=[
            llm.LectureSection(title="Parabol", summary="İkinci derece fonksiyonlar", pages=["hafta1 s.1"]),
            llm.LectureSection(title="Türev", summary="Türev kuralları", pages=["hafta1 s.2"]),
        ],
    )


async def fake_quiz(course, notes_text, full, count, difficulty, topic, weak):
    return llm.Quiz(
        questions=[
            llm.QuizQuestion(question="$x^2-4x+3=0$ denkleminin kökleri toplamı kaçtır?", kind="coktan_secmeli",
                             choices=["2", "3", "4", "5"], answer="4", topic="Kökler", page="hafta1 s.1"),
            llm.QuizQuestion(question="$f(x)=x^3$ fonksiyonunun türevini bulunuz.", kind="acik_uclu",
                             choices=[], answer="$3x^2$", topic="Türev", page="hafta1 s.2"),
        ][:count]
    )


async def fake_grade(question, student, image):
    ok = student.strip() == question.get("answer")
    return llm.Grade(score=1.0 if ok else 0.0, correct=ok, feedback="Harika!" if ok else "Kökler toplamı $-b/a=4$ olmalı.",
                     mistake_topic="" if ok else question.get("topic", ""))


async def fake_ocr(png):
    return "Fotoğraftan okunan not metni"


async def fake_voices():
    return [{"voice_id": "zu3iuxxlZoTwzmAUvpNF", "name": "Osman Adalı", "category": "cloned", "language": "tr", "gender": "male", "preview_url": None}]


def install():
    llm.stream_steps = fake_stream_steps
    main.llm.stream_steps = fake_stream_steps
    voice.synthesize = fake_synthesize
    voice.transcribe = fake_transcribe
    voice.list_voices = fake_voices
    llm.lecture_plan = fake_plan
    llm.make_quiz = fake_quiz
    llm.grade = fake_grade
    llm.ocr_page = fake_ocr
