"""Claude API çağrıları: canlı anlatım akışı + yapılandırılmış çıktılar (plan, sınav, puanlama, OCR)."""
from __future__ import annotations

import base64
import json
from typing import AsyncIterator, Literal

import anthropic
from pydantic import BaseModel, Field

from . import llm_gemini, prompts
from .config import anthropic_key, gemini_key, load_settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_client: anthropic.AsyncAnthropic | None = None


class TutorError(RuntimeError):
    pass


def provider() -> str:
    """Hocanın beyni: 'claude' ya da 'gemini' (ücretsiz kota)."""
    p = load_settings().get("llm_provider") or ""
    if p in ("claude", "gemini"):
        return p
    return "gemini" if gemini_key() and not anthropic_key() else "claude"


def _can_fallback_to_claude() -> bool:
    return bool(anthropic_key()) and load_settings().get("claude_fallback", True)


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        # Anahtar .env'de yoksa SDK ortam değişkenlerine / `ant auth login` profiline bakar.
        _client = anthropic.AsyncAnthropic(api_key=anthropic_key() or None)
    return _client


# ---------------------------------------------------------------- içerik blokları
def image_block(data: bytes, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()},
    }


def pdf_block(data: bytes, title: str = "") -> dict:
    block = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(data).decode()},
    }
    if title:
        block["title"] = title
    return block


# ---------------------------------------------------------------- adım ayrıştırıcı
class StepParser:
    """Modelin akan metnini satır satır JSON adımlarına çevirir.

    Model kuralı bozup düz metin ya da birden çok satıra yayılan JSON yazarsa da tolere eder.
    """

    def __init__(self) -> None:
        self.buf = ""
        self.pending = ""  # birden fazla satıra yayılmış JSON

    def feed(self, chunk: str) -> list[dict]:
        self.buf += chunk
        out = []
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            out.extend(self._line(line))
        return out

    def flush(self) -> list[dict]:
        out = self._line(self.buf) if self.buf.strip() else []
        self.buf = ""
        if self.pending.strip():
            out.extend(self._fallback(self.pending))
            self.pending = ""
        return out

    def _line(self, line: str) -> list[dict]:
        s = line.strip()
        if not s or s.startswith("```"):
            return []
        if self.pending:
            # Satır sonu JSON'un yapısında da olabilir, bir metnin içinde de (o zaman kaçışlı olmalı).
            joined = self.pending + "\n" + s
            obj = _try_json(joined)
            if obj is None:
                obj = _try_json(self.pending + "\\n" + s)
            self.pending = joined
            if obj is not None:
                self.pending = ""
                return [obj]
            if len(self.pending) > 8000:  # umutsuz: düz metin olarak oku
                p, self.pending = self.pending, ""
                return self._fallback(p)
            return []
        if s.startswith("{"):
            obj = _try_json(s)
            if obj is not None:
                return [obj]
            self.pending = s
            return []
        return self._fallback(s)

    @staticmethod
    def _fallback(text: str) -> list[dict]:
        text = text.strip().lstrip("-*# ").strip()
        return [{"say": text, "board": [{"op": "write", "text": text}]}] if text else []


def _try_json(s: str) -> dict | None:
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def normalize_step(obj: dict) -> dict | None:
    """Geçersiz alanları ayıklar; 'memory' satırlarını ayrı işaretler."""
    if "memory" in obj and isinstance(obj["memory"], dict):
        return {"memory": obj["memory"]}
    say = obj.get("say") if isinstance(obj.get("say"), str) else ""
    board = obj.get("board") if isinstance(obj.get("board"), list) else []
    board = [op for op in board if isinstance(op, dict) and isinstance(op.get("op"), str)]
    if not say and not board:
        return None
    return {"say": say.strip(), "board": board}


# ---------------------------------------------------------------- canlı anlatım
def course_knowledge(course: dict | None, notes_text: str, full: bool) -> str:
    """Dersin müfredat profili + ders notları (önbelleğe alınan büyük blok)."""
    if not course:
        return ""
    parts = []
    profile = prompts.course_profile_block(course)
    if profile:
        parts.append(profile)
    if notes_text:
        parts.append(prompts.notes_block(course["name"], notes_text, full))
    elif not profile:
        parts.append(f"# DERS: {course['name']}\nBu ders için henüz not yüklenmedi; konuyu kendi uzmanlığınla anlat.")
    return "\n\n".join(parts)


def build_system(
    course: dict | None, notes_text: str, full: bool, memory: str, level: str, conversation: bool = False
) -> list[dict]:
    system: list[dict] = [{"type": "text", "text": prompts.TUTOR_SYSTEM}]
    knowledge = course_knowledge(course, notes_text, full)
    if knowledge:
        system.append({"type": "text", "text": knowledge, "cache_control": {"type": "ephemeral", "ttl": "1h"}})
    else:
        system[0]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    extra = prompts.LEVELS.get(level, prompts.LEVELS["normal"])
    if conversation:
        extra += "\n\n" + prompts.CONVERSATION_STYLE
    if memory:
        extra += "\n\n" + memory
    system.append({"type": "text", "text": extra})
    return system


async def stream_steps(system: list[dict], messages: list[dict]) -> AsyncIterator[dict]:
    """Anlatım adımlarını üretildikçe verir. Son olarak {"final": [...içerik blokları...]} verir."""
    if provider() == "gemini":
        parser, full, produced = StepParser(), [], 0
        try:
            async for text in llm_gemini.stream_text(system, messages):
                full.append(text)
                for obj in parser.feed(text):
                    step = normalize_step(obj)
                    if step:
                        produced += 1
                        yield step
            for obj in parser.flush():
                step = normalize_step(obj)
                if step:
                    yield step
            yield {"final": [{"type": "text", "text": "".join(full)}], "truncated": False}
            return
        except llm_gemini.GeminiError as e:
            if not (e.quota and produced == 0 and _can_fallback_to_claude()):
                raise TutorError(str(e)) from e
            yield {"notice": "Gemini ücretsiz kotası doldu; bu cevap için Claude'a geçtim."}
    async for item in _claude_stream_steps(system, messages):
        yield item


async def _claude_stream_steps(system: list[dict], messages: list[dict]) -> AsyncIterator[dict]:
    s = load_settings()
    parser = StepParser()
    extra = {}
    if s.get("web_search"):
        # Güncel ya da notlarda/kitaplarda bulunmayan bilgiler için internette arama (isteğe bağlı).
        extra["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
    try:
        async with client().beta.messages.stream(
            model=s["claude_model"],
            max_tokens=32000,
            system=system,
            messages=messages,
            output_config={"effort": s["effort"]},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **extra,
        ) as stream:
            async for text in stream.text_stream:
                for obj in parser.feed(text):
                    step = normalize_step(obj)
                    if step:
                        yield step
            for obj in parser.flush():
                step = normalize_step(obj)
                if step:
                    yield step
            final = await stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise TutorError("Claude API anahtarı geçersiz ya da tanımlı değil (Ayarlar → API anahtarları).") from e
    except anthropic.RateLimitError as e:
        raise TutorError("Claude API hız sınırına takıldı, biraz sonra tekrar dene.") from e
    except anthropic.APIConnectionError as e:
        raise TutorError("Claude API'ye bağlanılamadı (internet bağlantını kontrol et).") from e
    except anthropic.APIStatusError as e:
        raise TutorError(f"Claude API hatası ({e.status_code}): {e.message}") from e

    if final.stop_reason == "refusal":
        raise TutorError("Model bu isteği yanıtlamayı reddetti; soruyu farklı ifade etmeyi dene.")
    yield {"final": [b.to_dict() for b in final.content], "truncated": final.stop_reason == "max_tokens"}


# ---------------------------------------------------------------- yapılandırılmış çıktılar
class LectureSection(BaseModel):
    title: str
    summary: str = Field(description="Bu bölümde anlatılacak kavramlar, 1-2 cümle")
    pages: list[str] = Field(description="İlgili sayfalar, 'belge adı s.N' biçiminde")


class LecturePlan(BaseModel):
    title: str
    sections: list[LectureSection]


class QuizQuestion(BaseModel):
    question: str
    kind: Literal["coktan_secmeli", "acik_uclu"]
    choices: list[str] = Field(description="Çoktan seçmelide 4 şık (A) ... ile başlamadan), açık uçluda boş liste")
    answer: str = Field(description="Doğru şık metni ya da tam çözüm")
    topic: str
    page: str = Field(description="İlgili not sayfası, 'belge adı s.N'; yoksa boş")


class Quiz(BaseModel):
    questions: list[QuizQuestion]


class Grade(BaseModel):
    score: float = Field(description="0 ile 1 arası puan")
    correct: bool
    feedback: str
    mistake_topic: str = Field(description="Hata varsa ilgili konu, yoksa boş")


async def _parse(model_cls, content: list[dict] | str, system: list[dict] | str | None = None, effort: str | None = None,
                 max_tokens: int = 16000):
    if provider() == "gemini":
        try:
            return await llm_gemini.parse(model_cls, content, system, max_tokens)
        except llm_gemini.GeminiError as e:
            if not (e.quota and _can_fallback_to_claude()):
                raise TutorError(str(e)) from e
    return await _claude_parse(model_cls, content, system, effort, max_tokens)


async def _claude_parse(model_cls, content, system=None, effort=None, max_tokens: int = 16000):
    s = load_settings()
    kwargs = {}
    if system:
        kwargs["system"] = system
    try:
        # Uzun çıktılar (ders notu, takvim) HTTP zaman aşımına takılmasın diye akış (stream) kullanılır.
        async with client().beta.messages.stream(
            model=s["claude_model"],
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
            output_format=model_cls,
            output_config={"effort": effort or s["effort"]},
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **kwargs,
        ) as stream:
            resp = await stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise TutorError("Claude API anahtarı geçersiz ya da tanımlı değil (Ayarlar → API anahtarları).") from e
    except anthropic.APIStatusError as e:
        raise TutorError(f"Claude API hatası ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise TutorError("Claude API'ye bağlanılamadı.") from e
    if resp.stop_reason == "max_tokens":
        raise TutorError("Cevap çok uzun olduğu için kesildi; kapsamı daraltıp tekrar dene.")
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise TutorError("Model geçerli bir cevap üretemedi, tekrar dene.")
    return resp.parsed_output


def _notes_system(course: dict, notes_text: str, full: bool) -> list[dict]:
    return [
        {
            "type": "text",
            "text": "Sen bu dersin uzman ve titiz öğretim üyesisin. Türkçe yaz.\n\n" + course_knowledge(course, notes_text, full),
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]


async def lecture_plan(course: dict, notes_text: str, full: bool, focus: str = "") -> LecturePlan:
    if notes_text:
        source = "Ders notlarının sırasını izle; notlarda eksik kalan ama konuyu anlamak için gereken temelleri de ekle."
    else:
        source = "Henüz ders notu yok: ders profilindeki içerik ve haftalık konulardan, kaynak kitap düzeyinde bir plan çıkar."
    focus = f"Sadece şu kapsama odaklan: {focus}" if focus else ""
    return await _parse(LecturePlan, prompts.LECTURE_PLAN.format(source=source, focus=focus), _notes_system(course, notes_text, full))


async def make_quiz(course: dict, notes_text: str, full: bool, count: int, difficulty: str, topic: str, weak: str) -> Quiz:
    text = prompts.QUIZ_GEN.format(
        count=count,
        difficulty=difficulty,
        topic=f"Konu: {topic}." if topic else "Notlardaki konuların hepsinden dengeli seç.",
        weak=(weak + "\nBu zayıf konulardan da soru koy.") if weak else "",
    )
    return await _parse(Quiz, text, _notes_system(course, notes_text, full))


async def grade(question: dict, student: str, image: tuple[bytes, str] | None) -> Grade:
    choices = ""
    if question.get("choices"):
        choices = "Şıklar: " + " | ".join(question["choices"]) + "\n"
    text = prompts.QUIZ_GRADE.format(
        question=question.get("question", ""),
        choices=choices,
        answer=question.get("answer", ""),
        student=student or "(cevap fotoğrafta)",
    )
    content: list[dict] = []
    if image:
        content.append(image_block(*image))
    content.append({"type": "text", "text": text})
    return await _parse(Grade, content, effort="medium")


class PageText(BaseModel):
    text: str


async def ocr_page(png: bytes) -> str:
    if provider() == "gemini":
        page = await _parse(PageText, [image_block(png, "image/png"), {"type": "text", "text": prompts.OCR_PAGE}])
        return page.text.strip()
    s = load_settings()
    resp = await client().messages.create(
        model=s["claude_model"],
        max_tokens=8000,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": [image_block(png, "image/png"), {"type": "text", "text": prompts.OCR_PAGE}]}],
    )
    if resp.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in resp.content if b.type == "text").strip()



# ---------------------------------------------------------------- ders kaydı → not
class NoteSection(BaseModel):
    title: str
    content: str


class LectureNotes(BaseModel):
    title: str
    sections: list[NoteSection]


async def lecture_notes(transcript: str, course: dict | None) -> LectureNotes:
    ctx = ""
    if course:
        ctx = f"Ders: {course['name']}."
        prof = prompts.course_profile_block(course)
        if prof:
            ctx += "\n" + prof[:4000]
    return await _parse(LectureNotes, prompts.LECTURE_NOTES.format(context=ctx, transcript=transcript), effort="medium",
                        max_tokens=32000)


# ---------------------------------------------------------------- formül kâğıdı
class FormulaItem(BaseModel):
    name: str
    tex: str = Field(description="LaTeX, dolar işaretsiz; formül değilse boş")
    note: str = Field(description="Tek satırlık not ya da boş")


class FormulaSection(BaseModel):
    title: str
    items: list[FormulaItem]


class FormulaSheet(BaseModel):
    title: str
    sections: list[FormulaSection]


async def formula_sheet(course: dict, notes_text: str, full: bool, focus: str = "") -> FormulaSheet:
    text = prompts.FORMULA_SHEET.format(focus=f"Kapsam: {focus}" if focus else "")
    return await _parse(FormulaSheet, text, _notes_system(course, notes_text, full), max_tokens=24000)


# ---------------------------------------------------------------- tekrar takvimi
class StudyTask(BaseModel):
    kind: Literal["anlat", "tekrar", "sinav", "formul"]
    topic: str
    detail: str
    minutes: int


class StudyDay(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    tasks: list[StudyTask]


class StudyPlan(BaseModel):
    days: list[StudyDay]


async def study_plan(course: dict, notes_text: str, full: bool, **kw) -> StudyPlan:
    return await _parse(StudyPlan, prompts.STUDY_PLAN.format(**kw), _notes_system(course, notes_text, full),
                        max_tokens=24000)



# ---------------------------------------------------------------- derin çözüm (önce çöz, sonra anlat)
class SolutionStep(BaseModel):
    islem: str = Field(description="Bu adımda yapılan işlem, LaTeX $...$ ile")
    gerekce: str = Field(description="Bu adım NEDEN böyle: hangi tanım/kural/teorem/formülden geliyor, o formül nereden çıkıyor")


class Solution(BaseModel):
    konu: str
    verilenler: str
    istenen: str
    yontem: str = Field(description="Hangi yöntemi seçtin ve neden bu yöntem (alternatiflere göre)")
    on_bilgi: str = Field(description="Çözüm için bilinmesi gereken kavram/formüller ve kısaca nereden geldikleri")
    adimlar: list[SolutionStep]
    sonuc: str
    kontrol: str = Field(description="Sonucu başka bir yolla ya da yerine koyarak doğrulama")
    sik_hatalar: str
    puf_noktasi: str


async def deep_solution(system: list[dict], user_content: list[dict]) -> str:
    """Anlatımdan önce, gerekçeli tam çözümü hazırlar; hoca anlatırken bunu izler.

    Yüzeysel cevap veren modellerde (ör. Gemini Flash) derinliği garanti etmek için kullanılır.
    """
    task = list(user_content) + [{"type": "text", "text": prompts.DEEP_SOLVE}]
    sol = await _parse(Solution, task, llm_gemini.system_text(system) if system else None, effort="high")
    lines = [
        f"Konu: {sol.konu}", f"Verilenler: {sol.verilenler}", f"İstenen: {sol.istenen}",
        f"Yöntem ve nedeni: {sol.yontem}", f"Ön bilgi: {sol.on_bilgi}", "Adımlar:",
        *[f"  {i}. {st.islem}  ← gerekçe: {st.gerekce}" for i, st in enumerate(sol.adimlar, 1)],
        f"Sonuç: {sol.sonuc}", f"Kontrol: {sol.kontrol}", f"Sık hatalar: {sol.sik_hatalar}", f"Püf noktası: {sol.puf_noktasi}",
    ]
    return "\n".join(lines)
