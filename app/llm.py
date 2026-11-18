"""Hocanın beyni: canlı anlatım akışı + yapılandırılmış çıktılar (plan, sınav, puanlama, OCR).

Varsayılan beyin bu bilgisayarda çalışan yerel yapay zekadır (Ollama + Gemma 4; hiçbir şirkete bağlı değil).
Gemini yalnızca kullanıcı anahtar girerse isteğe bağlı yardımcıdır. Biri çalışmazsa diğeri devreye girer.
İçerik iç biçimi (mesaj/blok sözlükleri) llm_yerel / llm_gemini tarafından kendi biçimlerine çevrilir.
"""
from __future__ import annotations

import base64
import json
from typing import AsyncIterator, Literal

from pydantic import BaseModel, Field

from . import llm_gemini, llm_yerel, prompts, yerel
from .config import gemini_key, load_settings


class TutorError(RuntimeError):
    pass


def provider() -> str:
    """Şu an kullanılacak beyin: 'yerel' (varsayılan) ya da 'gemini' (anahtar girilip seçildiyse).

    Otomatik modda yerel yapay zeka henüz kuruluyorsa ve Gemini anahtarı varsa geçici olarak Gemini kullanılır.
    """
    p = load_settings().get("llm_provider") or ""
    if p == "gemini" and gemini_key():
        return "gemini"
    if p == "yerel" or not gemini_key() or yerel.hazir():
        return "yerel"
    return "gemini"


def _backends() -> list[str]:
    first = provider()
    other = "gemini" if first == "yerel" else "yerel"
    if other == "gemini" and not gemini_key():
        return [first]
    if other == "yerel" and not yerel.hazir():
        return [first]
    return [first, other]


# ---------------------------------------------------------------- ön plan önceliği
# Yerel model aynı anda tek isteği işler: öğrenci soru sorarken arka plan işleri (paket üretimi, OCR) bekler,
# yoksa canlı anlatım uzun bir arka plan çağrısının arkasında kalıp zaman aşımına düşer.
import asyncio as _asyncio  # noqa: E402
import time as _time  # noqa: E402

_on_plan = 0
_son_etkinlik = 0.0
SESSIZ_SURE = float(__import__("os").getenv("DERS_SESSIZ_SURE", "45"))  # sn: son sorudan sonra arka plan işleri bu kadar bekler (öğrenci devam edebilir)


class on_plan:
    """main.ask içinde: bu blok sürerken ve bittikten SESSIZ_SURE sn sonrasına kadar arka plan işleri bekler."""

    def __enter__(self):
        global _on_plan, _son_etkinlik
        _on_plan += 1
        _son_etkinlik = _time.time()

    def __exit__(self, *a):
        global _on_plan, _son_etkinlik
        _on_plan -= 1
        _son_etkinlik = _time.time()


async def arka_plan_sirasi() -> None:
    """Arka plan yapay zeka çağrısından önce: öğrenci hoca ile konuşuyorsa sırasını bekle (yalnızca yerel modelde)."""
    while provider() == "yerel" and (_on_plan > 0 or _time.time() - _son_etkinlik < SESSIZ_SURE):
        await _asyncio.sleep(2)


def ogrenci_bosta(sn: float = 300) -> bool:
    """Öğrenci hoca ile konuşmuyor ve son etkinliğinden en az sn saniye geçti mi (kendi kendine çalışma için)."""
    return _on_plan == 0 and _time.time() - _son_etkinlik >= sn


def ai_hazir() -> bool:
    """Şu an bir yapay zeka cevap verebilir mi (yerel hazır ya da Gemini anahtarı var)?"""
    return yerel.hazir() or bool(gemini_key())


def brain_label(p: str | None = None) -> str:
    p = p or provider()
    return "Gemini" if p == "gemini" else f"yerel yapay zeka ({yerel.STATE.get('model') or yerel.secili_model()})"


def notes_limit() -> int:
    """Ders notlarından modele verilecek en fazla karakter (yerel modelin bağlamı küçüktür)."""
    from .config import FULL_NOTES_CHAR_LIMIT

    if provider() == "gemini":
        return FULL_NOTES_CHAR_LIMIT
    return max(8000, int(yerel.baglam() * llm_yerel.CHARS_PER_TOKEN * 0.36))


def yerel_notes_limit() -> int:
    """Yerel modelin bağlamına sığan not bütçesi (karakter), hocanın uzun sistem talimatı olmadan. Hangi beyin cevap
    verirse versin istek sığsın diye uzun arka plan işleri (paket üretimi) bunu üst sınır olarak kullanır."""
    return max(8000, int(yerel.baglam() * llm_yerel.CHARS_PER_TOKEN * 0.45))


def kaynak_limit() -> int:
    """Kütüphaneden bulunan kitap/makale bölümleri için karakter bütçesi (yerel modelde not bütçesinin ~%30'u).
    Gizlilik: Gemini (bulut) açıkken kitap bölümleri ASLA gönderilmez, bütçe 0'dır."""
    if provider() == "gemini":
        return 0
    return int(notes_limit() * 0.3)


def guide_limit() -> int:
    """Hazır özetler (course_guide) için karakter bütçesi; 0 = sınırsız (Gemini)."""
    if provider() == "gemini":
        return 0
    return max(3000, int(yerel.baglam() * llm_yerel.CHARS_PER_TOKEN * 0.12))


_ERRORS = (llm_gemini.GeminiError, llm_yerel.YerelError)


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
                return _expand(obj)
            if len(self.pending) > 8000:  # umutsuz: düz metin olarak oku
                p, self.pending = self.pending, ""
                return self._fallback(p)
            return []
        if not s.strip("[],; \t"):
            return []  # nesne dışında tek başına köşeli parantez/virgül satırı
        if s.startswith("[") and s.endswith("]"):
            arr = _try_any(s)  # bazı modeller tüm adımları tek bir JSON dizisi olarak yazar
            if isinstance(arr, list):
                return [x for o in arr if isinstance(o, dict) for x in _expand(o)]
        if s.startswith("["):
            s = s[1:].strip()  # "[{...}," gibi dizinin ilk satırı
            if not s:
                return []
        if s.startswith("{"):
            obj = _try_json(s)
            if obj is not None:
                return _expand(obj)
            self.pending = s
            return []
        return self._fallback(s)

    @staticmethod
    def _fallback(text: str) -> list[dict]:
        text = text.strip().lstrip("-*# ").replace("**", "").strip()
        return [{"say": text, "board": [{"op": "write", "text": text}]}] if text else []


def _try_any(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def _expand(obj: dict) -> list[dict]:
    """{"steps": [...]} gibi sarmalanmış çıktıları adımlara açar."""
    if any(k in obj for k in ("say", "board", "memory")):
        return [obj]
    for v in obj.values():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            return [x for o in v for x in _expand(o)]
    return [obj]


def _try_json(s: str) -> dict | None:
    s = s.strip()
    for cand in (s, s.rstrip(",").rstrip(), s.rstrip(",").rstrip().removesuffix("]").rstrip()):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        return obj if isinstance(obj, dict) else None
    return None


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
    from . import hazir

    guide = hazir.course_guide(course, guide_limit())
    if guide:
        parts.append(guide)
    if notes_text:
        parts.append(prompts.notes_block(course["name"], notes_text, full))
    elif not profile:
        parts.append(f"# DERS: {course['name']}\nBu ders için henüz not yüklenmedi; konuyu kendi uzmanlığınla anlat.")
    return "\n\n".join(parts)


def build_system(
    course: dict | None, notes_text: str, full: bool, memory: str, level: str, conversation: bool = False,
    kaynaklar: str = "", ogrenme: str = "", tarz: str = "anlat", sohbet: bool = False,
) -> list[dict]:
    system: list[dict] = [{"type": "text", "text": prompts.TUTOR_SYSTEM}]
    knowledge = course_knowledge(course, notes_text, full)
    if knowledge:  # notların tamamı sığdıysa her soruda aynıdır; sığmadıysa soruya göre seçilir (değişken)
        system.append({"type": "text", "text": knowledge, "cache_control": {"type": "ephemeral", "ttl": "1h"},
                       "degisken": not full})
    else:
        system[0]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    if kaynaklar:  # kütüphaneden soruyla ilgili bölümler (her soruda değişir: önbelleğe alınmaz)
        system.append({"type": "text", "text": prompts.kaynak_block(kaynaklar), "degisken": True})
    extra = prompts.LEVELS.get(level, prompts.LEVELS["normal"])
    if conversation:
        extra += "\n\n" + prompts.CONVERSATION_STYLE
    degisken = "\n\n".join(x for x in (memory, ogrenme) if x)  # hafıza ve öğrenilenler: sorudan soruya değişir
    if tarz == "sokratik":
        extra += "\n\n" + prompts.SOKRATIK
    if sohbet:  # serbest sohbette: yanlışta hata türü teşhisi; seviye yoklaması yalnızca Ayarlar'dan açılırsa
        extra += "\n\n" + prompts.HATA_ANALIZI
        if load_settings().get("on_bilgi_yoklama", False):
            extra += "\n\n" + prompts.ON_BILGI_YOKLAMA
    system.append({"type": "text", "text": extra})
    if degisken:
        system.append({"type": "text", "text": degisken, "degisken": True})
    return system


async def stream_steps(system: list[dict], messages: list[dict]) -> AsyncIterator[dict]:
    """Anlatım adımlarını üretildikçe verir. Son olarak {"final": [...içerik blokları...]} verir.

    Seçili beyin hiç adım üretmeden hata verirse (kurulmamış, kota, bağlantı) sıradaki beyne geçilir.
    """
    backends = _backends()
    last: Exception | None = None
    for i, be in enumerate(backends):
        parser, full, produced = StepParser(), [], 0
        stream = (llm_yerel if be == "yerel" else llm_gemini).stream_text(system, messages)
        try:
            async for text in stream:
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
        except _ERRORS as e:
            if produced:
                raise TutorError(str(e)) from e
            if i == len(backends) - 1:
                raise TutorError(" | ".join([*(str(x) for x in ([last] if last else [])), str(e)])) from e
            last = e
            yield {"notice": f"{brain_label(be)} cevap veremedi ({e}); bu cevap için {brain_label(backends[i + 1])} kullanılıyor."}
    raise TutorError(str(last or "Yapay zeka kullanılamıyor."))


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
    backends, errors = _backends(), []
    for be in backends:
        try:
            mod = llm_yerel if be == "yerel" else llm_gemini
            return await mod.parse(model_cls, content, system, max_tokens)
        except _ERRORS as e:
            errors.append(str(e))
    raise TutorError(" | ".join(errors))


def _notes_system(course: dict, notes_text: str, full: bool) -> list[dict]:
    return [
        {
            "type": "text",
            "text": "Sen bu dersin uzman ve titiz öğretim üyesisin. Türkçe yaz.\n\n" + course_knowledge(course, notes_text, full),
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
    page = await _parse(PageText, [image_block(png, "image/png"), {"type": "text", "text": prompts.OCR_PAGE}])
    return page.text.strip()


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


class HesapSecimi(BaseModel):
    arac: str = Field(description="hesap aracının adı ya da 'yok'")
    girdiler_json: str = Field("{}", description="araç girdileri: JSON nesnesinin metni")


async def hesap_secimi(soru: str) -> dict | None:
    """Soruya uyan hesap aracını ve girdilerini seçtirir; uygun araç yoksa None."""
    from . import hesap

    sec = await _parse(HesapSecimi, prompts.HESAP_SEC.format(araclar=hesap.arac_listesi_metni(), soru=soru[:2500]))
    ad = (getattr(sec, "arac", "") or "").strip()
    if not ad or ad.lower() == "yok" or ad not in hesap.ARACLAR:
        return None
    girdi = getattr(sec, "girdiler_json", None)
    if girdi is None:
        girdi = getattr(sec, "girdiler", {})
    return {"arac": ad, "girdiler": girdi}
