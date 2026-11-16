"""Uygulamanın kendi ders paketini üretmesi: belge özetleri, ders planı, sınav rehberi, konu anlatımı,
kısa sınav özeti ve hocanın sınav formatında deneme sınavları (cevap anahtarlı, notlara karşı denetlenmiş).

Yerel yapay zeka küçük bağlamlı ve yavaştır: iş küçük adımlara bölünür, her adımın sonucu ders.json'a yazılır
(course["paket_ara"]); iş kesilirse ya da hata verirse tekrar başlatınca kaldığı yerden devam eder.
Hiçbir şirkete bağlı değildir: llm._parse önce yerel yapay zekayı kullanır, Gemini yalnızca anahtar girildiyse yedektir.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from . import llm, llm_yerel, notes, prompts, yerel
from .config import load_settings

log = logging.getLogger("ders")

BEKLEME = 90  # yeni belge geldikten sonra otomatik güncellemeden önce beklenen süre (sn)
KISA_OZET_KELIME = 1500
PARCA_SORU = 8  # deneme bölüm bölüm üretilirken bir çağrıdaki en fazla soru
_isler: dict[str, asyncio.Task] = {}
_zamanlayicilar: dict[str, asyncio.Task] = {}
_arka_ocr: dict[str, set[asyncio.Task]] = {}  # main._schedule_ocr'ın ders başına süren sayfa okumaları


class _DersYok(Exception):
    pass


# ---------------------------------------------------------------- şemalar
class PBolum(BaseModel):
    baslik: str
    sayfalar: str = Field(description="Sayfa aralığı, ör. '3-5'")
    ozet: str


class PKavram(BaseModel):
    terim: str
    tanim: str
    sayfa: int


class ParcaOzet(BaseModel):
    baslik: str
    ozet: str
    bolumler: list[PBolum]
    kavramlar: list[PKavram]
    olasi_sorular: list[str]


class BelgeOzet(BaseModel):
    baslik: str
    ozet: str
    bolumler: list[PBolum]
    olasi_sorular: list[str]


class Metin(BaseModel):
    metin: str = Field(description="Markdown metin")


class DSoru(BaseModel):
    soru: str
    siklar: list[str] = Field(description="Yalnızca çoktan seçmelide şık metinleri (harfsiz); diğerlerinde boş liste")
    cevap: str = Field(description="dy: 'D'/'Y'; coktan: doğru şıkkın harfi; diğerleri: kısa doğru cevap")
    aciklama: str
    ornek_cevap: str = Field(description="Açık uçlu sorularda tam puanlık cevap; diğerlerinde boş")
    puanlama: str = Field(description="Klasik sorularda puan dağılımı; diğerlerinde boş")
    kaynak: str = Field(description="'belge adı s.N'")


class DBolum(BaseModel):
    baslik: str
    tur: Literal["dy", "coktan", "metin", "klasik", "bonus", "kisa"]
    yonerge: str
    metin: str = Field(description="Yalnızca 'metin' türünde okunacak metin; diğerlerinde boş")
    sorular: list[DSoru]


class Deneme(BaseModel):
    baslik: str
    aciklama: str
    bolumler: list[DBolum]


class DYapiBolum(BaseModel):
    baslik: str
    tur: Literal["dy", "coktan", "metin", "klasik", "bonus", "kisa"]
    soru_sayisi: int
    yonerge: str


class DYapi(BaseModel):
    bolumler: list[DYapiBolum]


# ---------------------------------------------------------------- yardımcılar
def _sha(x) -> str:
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def belge_imzasi(doc: dict) -> str:
    return _sha("\n".join(f"{p['n']}:{p.get('text', '')}" for p in doc.get("pages", [])))


def _metinli(doc: dict) -> bool:
    return any((p.get("text") or "").strip() for p in doc.get("pages", []))


def _paketten(doc: dict) -> bool:
    """Belge hazır (önceden işlenmiş) bir paketten mi geldi? Onlar yeniden özetlenmez."""
    h = doc.get("hazir")
    return bool(h) and h.get("paket") != "uretilen"


def sinav_formati(course: dict) -> str:
    return (course.get("sinav_formati") or "").strip() or prompts.VARSAYILAN_SINAV_FORMATI


def _ders(cid: str) -> dict:
    c = notes.get_course(cid)
    if not c:
        raise _DersYok()
    return c


def _guncelle(cid: str, fn) -> dict:
    """Dersi kilit altında diskten YENİDEN okuyup değiştirir ve kaydeder (o arada yapılan değişiklikler ezilmesin)."""
    c = notes.update_course(cid, fn)
    if c is None:
        raise _DersYok()
    return c


def butce() -> int:
    """Paket işinin not bütçesi (karakter). Hangi beyin cevap verirse versin (Gemini birincil olsa bile, iş sürerken
    yerel modele düşülebilir) istek yerel modelin bağlamına sığsın diye her zaman yerel bütçeyle sınırlıdır."""
    return min(llm.notes_limit(), llm.yerel_notes_limit())


def _cikti(girdi_karakter: int, istenen: int, en_az: int = 1500) -> int:
    """Cevap için ayrılacak token: yerel modelin bağlamından girdinin kapladığı kadar düşülür."""
    kalan = yerel.baglam() - int(girdi_karakter / llm_yerel.CHARS_PER_TOKEN) - 256
    return max(en_az, min(istenen, kalan))


def _sigar(girdi_karakter: int, cikti_token: int) -> bool:
    return girdi_karakter / llm_yerel.CHARS_PER_TOKEN + cikti_token + 256 <= yerel.baglam()


def _sigmadi(e: Exception) -> bool:
    """Model cevabı token sınırına takıldı mı? (llm_yerel: 'Cevap modelin sınırına sığmadı')"""
    return "sığmadı" in str(e)


def arka_ocr_ekle(cid: str, task: asyncio.Task) -> None:
    """main._schedule_ocr'ın arka plan okumasını kaydeder; paket işi aynı sayfaları ikinci kez okumasın diye bekler."""
    kume = _arka_ocr.setdefault(cid, set())
    kume.add(task)
    task.add_done_callback(kume.discard)


def _ara(c: dict) -> dict:
    return c.setdefault("paket_ara", {})


def _sistem(course: dict) -> str:
    s = prompts.PAKET_SYSTEM.format(ders=course["name"])
    prof = prompts.course_profile_block(course)
    return s + ("\n\n" + prof[:1500] if prof else "")


def _sayfa_parcalari(doc: dict, limit: int) -> list[str]:
    """Belgenin sayfalarını model bütçesine sığan parçalara böler."""
    out, cur = [], ""
    boy = max(500, limit - 40)
    for p in doc["pages"]:
        t = (p.get("text") or "").strip()
        if not t:
            continue
        for k in range(0, len(t), boy):  # bütçeden uzun sayfa da kırpılmaz, bölünür
            blok = f"[Sayfa {p['n']}]\n{t[k:k + boy]}\n"
            if cur and len(cur) + len(blok) > limit:
                out.append(cur)
                cur = ""
            cur += blok
    return out + ([cur] if cur else [])


def _ozet_blogu(d: dict) -> str:
    h = d.get("hazir") or {}
    bol = "; ".join(f"{b.get('baslik', '')} (s.{b.get('sayfalar', '')})" for b in h.get("bolumler", []))
    kav = "; ".join(f"{k.get('terim', '')}: {k.get('tanim', '')} (s.{k.get('sayfa', '')})" for k in h.get("kavramlar", []))
    soru = " | ".join(h.get("olasi_sorular", []))
    return (f"## {d['name']} — {h.get('baslik', '')}\n{h.get('ozet', '')}\nBölümler: {bol}\nKavramlar: {kav}\n"
            f"Olası sorular: {soru}")


def _ozetler(course: dict, limit: int, docs: list[dict] | None = None) -> str:
    docs = [d for d in (docs or course["docs"]) if d.get("hazir")]
    if not docs:
        return ""
    bloklar = [_ozet_blogu(d) for d in docs]
    if sum(len(b) + 2 for b in bloklar) > limit:  # her belgeye eşit pay; toplam bütçeyi asla aşmaz
        pay = max(0, limit // len(bloklar) - 2)
        bloklar = [b[:pay] for b in bloklar]
    return "\n\n".join(bloklar)[:limit]


def _bizim(course: dict, alan: str) -> bool:
    """Alan boş mu ya da en son bizim ürettiğimiz değer mi? (hazır paketten geleni ezmemek için)"""
    v = course.get(alan)
    return not v or (course.get("paket_kaynak") or {}).get(alan) == _sha(v)


def _yaz(c: dict, alan: str, deger) -> None:
    c[alan] = deger
    c.setdefault("paket_kaynak", {})[alan] = _sha(deger)


def _kelime_kirp(md: str, n: int) -> str:
    if len(md.split()) <= n:
        return md
    out, say = [], 0
    for satir in md.split("\n"):
        k = len(satir.split())
        if say + k > n:
            break
        out.append(satir)
        say += k
    return "\n".join(out).rstrip()


_KLASIK_BOLUM = re.compile(r"^##[ \t]*Klasik soru şablonu.*?(?=^##[ \t]|\Z)", re.M | re.S | re.I)


def ozet_kirp(md: str, n: int) -> str:
    """Kısa özeti n kelimeye indirir; en sondaki '## Klasik soru şablonu' bölümü korunur, kesme öncekilerden yapılır."""
    m = _KLASIK_BOLUM.search(md)
    if not m or len(md.split()) <= n:
        return _kelime_kirp(md, n)
    klasik = _kelime_kirp(m.group(0).strip(), n)
    geri = (md[:m.start()] + md[m.end():]).strip()
    kalan = n - len(klasik.split())
    govde = _kelime_kirp(geri, kalan) if kalan > 0 else ""
    return (govde.rstrip() + "\n\n" + klasik).strip()


def _ders_imzasi(course: dict) -> str:
    """Ders düzeyi çıktıların dayandığı her şey: belgeler, özetleri ve sınav formatı."""
    parca = [(d["id"], (d.get("hazir") or {}).get("imza") or _sha(d.get("hazir") or {}))
             for d in course["docs"] if d.get("hazir")]
    return _sha([parca, sinav_formati(course)])


# ---------------------------------------------------------------- deneme sınavı: biçim düzeltme + şık dengeleme
HARFLER = "ABCDE"
_ON_EK = re.compile(r"^\s*\(?([A-Ea-e])\s*[).:\-]\s*")
_LISTE = r"[A-E](?:\s*(?:,|ve|ile|veya|ya da)\s*[A-E])*"  # "A", "A ve B", "B, C ve D"
_SIK_SOZ = r"(?i:şık|seçene|çeldirici)"  # harften SONRA gelince şık atfı sayılan sözcükler
_HARF_ATIF = re.compile(  # açıklamadaki AÇIK şık atıfları; P(A), "A'nın", "A ve B sınıfı" gibi harflere dokunulmaz
    # "cevap C", "doğru şık: B", "şıkları A ve D", "seçenek (E)"
    r"(?P<on>(?i:şıkları|şıkkı|şıkkın|şıklar|şık|seçenekleri|seçeneği|seçenek|cevap|cevabı|yanıt|yanıtı)\s*:?\s*\(?)"
    rf"(?P<a>{_LISTE})(?![\w])"
    # "B şıkkı", "A ve C seçenekleri", "B çeldiricidir", "D'deki şık" değil: harf + boşluk + şık sözcüğü
    rf"|(?<![\w(])(?P<b>{_LISTE})(?=\s+{_SIK_SOZ})"
    # "(D)" ve "D)" yalnızca önünde harf/rakam yokken (P(A) bir olasılıktır, şık değil)
    r"|(?<![\w(])\((?P<c>[A-E])\)"
    r"|(?<![\w(])(?P<d>[A-E])\)"
)
# Konuma bağlı şıklar ("Yukarıdakilerin hepsi", "A ve B") yer değiştirince anlamsızlaşır: o soru dengelenmez.
_KONUMA_BAGLI = re.compile(r"hepsi|hiçbiri|tümü|yukarıdaki|ikisi de"
                           r"|(?-i:(?<![\w(])[A-E]\s*(?:,|ve|ile|veya|ya da)\s*[A-E](?![\w]))", re.I)


def _dy_cevap(c: str) -> str:
    s = (c or "").strip().upper()
    return "Y" if s[:1] in ("Y", "F") else "D" if s[:1] in ("D", "T") else s


def _dogru_indeks(q: dict) -> int | None:
    c = (q.get("cevap") or "").strip()
    n = len(q.get("siklar") or [])
    m = re.match(r"^\(?([A-Ea-e])(?![\w])", c)
    if m and HARFLER.index(m.group(1).upper()) < n:
        return HARFLER.index(m.group(1).upper())
    for i, s in enumerate(q.get("siklar") or []):  # cevap şık metni olarak yazıldıysa
        if c and _ON_EK.sub("", s).strip().lower() == _ON_EK.sub("", c).strip().lower():
            return i
    return None


def _harf_degistir(text: str, perm: dict[str, str]) -> str:
    harf = lambda g: re.sub(r"[A-E]", lambda m: perm.get(m.group(0), m.group(0)), g)

    def f(m):
        if m.group("a"):
            return m.group("on") + harf(m.group("a"))
        if m.group("c"):
            return f"({harf(m.group('c'))})"
        if m.group("d"):
            return harf(m.group("d")) + ")"
        return harf(m.group("b"))

    return _HARF_ATIF.sub(f, text or "")


def deneme_duzelt(x: dict) -> dict:
    """Model çıktısını tutarlı hale getirir: D/Y cevapları, şık önekleri ('A) ...'), çoktan seçmelide harf cevap."""
    for b in x.get("bolumler", []):
        if b.get("tur") != "metin":
            b["metin"] = ""
        b["sorular"] = [q for q in b.get("sorular", []) if (q.get("soru") or "").strip()]
        for q in b["sorular"]:
            if b.get("tur") == "dy":
                q["cevap"], q["siklar"] = _dy_cevap(q.get("cevap", "")), []
            elif b.get("tur") == "coktan":
                q["siklar"] = [f"{HARFLER[i]}) {_ON_EK.sub('', s).strip()}" for i, s in enumerate(q.get("siklar", [])[:5])]
                i = _dogru_indeks(q)
                if i is not None:
                    q["cevap"] = HARFLER[i]
            else:
                q["siklar"] = []
    return x


def sik_dengele(x: dict, seed: int = 0) -> dict:
    """Çoktan seçmelide doğru şıkların harf dağılımını dengeler: doğru şık, en az kullanılan harfe taşınır
    (iki şık yer değiştirir); cevap ve açıklamadaki harf atıfları da birlikte güncellenir."""
    rng = random.Random(seed)
    sayac = {h: 0 for h in HARFLER}
    for b in x.get("bolumler", []):
        if b.get("tur") != "coktan":
            continue
        for q in b.get("sorular", []):
            n = len(q.get("siklar") or [])
            c = _dogru_indeks(q)
            if n < 2 or c is None:
                continue
            if any(_KONUMA_BAGLI.search(_ON_EK.sub("", s)) for s in q["siklar"]):
                sayac[HARFLER[c]] += 1  # yerinde kalır, dağılımda sayılır
                continue
            en_az = min(sayac[HARFLER[i]] for i in range(n))
            t = rng.choice([i for i in range(n) if sayac[HARFLER[i]] == en_az])
            sayac[HARFLER[t]] += 1
            if t == c:
                continue
            metin = [_ON_EK.sub("", s).strip() for s in q["siklar"]]
            metin[c], metin[t] = metin[t], metin[c]
            q["siklar"] = [f"{HARFLER[i]}) {s}" for i, s in enumerate(metin)]
            q["cevap"] = HARFLER[t]
            q["aciklama"] = _harf_degistir(q.get("aciklama", ""), {HARFLER[c]: HARFLER[t], HARFLER[t]: HARFLER[c]})
    return x


def _soru_sayisi(x: dict) -> int:
    return sum(len(b.get("sorular", [])) for b in x.get("bolumler", []))


# ---------------------------------------------------------------- iş durumu
def durum(cid: str) -> dict:
    c = notes.get_course(cid)
    if not c:
        return {"durum": "yok"}
    st = dict(c.get("paket_is") or {"durum": "yok"})
    t = _isler.get(cid)
    if st.get("durum") == "calisiyor" and not (t and not t.done()):
        st["durum"] = "yarida"  # sunucu yeniden başlatıldı ya da iş beklenmedik biçimde bitti
    return st


def _durum_yaz(cid: str, **alan) -> None:
    def f(c):
        st = c.get("paket_is") or {}
        st.update(alan, guncellendi=time.time())
        c["paket_is"] = st

    _guncelle(cid, f)


class _Ilerleme:
    def __init__(self, cid: str):
        self.cid, self.toplam, self.yapilan = cid, 1, 0

    def adim(self, metin: str) -> None:
        _durum_yaz(self.cid, durum="calisiyor", adim=metin, ilerleme=round(min(0.99, self.yapilan / max(1, self.toplam)), 3))

    def bir(self) -> None:
        self.yapilan += 1


def baslat(cid: str, deneme_sayisi: int = 2, yeniden: bool = False) -> dict:
    """Ders için paket üretimini başlatır; zaten çalışıyorsa mevcut işin durumunu döndürür.

    'Baştan üret' isteği paket_is.yeniden'e yazılır: iş yarıda kalırsa sonraki başlatmalar (otomatik olanlar da)
    'baştan' kurallarıyla (hazır içeriği yenileyerek) kaldığı yerden sürer; ara sonuçlar yalnızca ilk seferde silinir."""
    t = _isler.get(cid)
    if t and not t.done():
        return durum(cid)
    course = notes.get_course(cid)
    if not course:
        raise KeyError("ders bulunamadı")
    if not any(_metinli(d) or any(p.get("needs_ocr") for p in d.get("pages", [])) for d in course["docs"]):
        raise ValueError("Paket üretmek için önce derse not (PDF ya da fotoğraf) yükle.")
    n = max(1, min(int(deneme_sayisi or 2), 5))
    onceki = course.get("paket_is") or {}
    yeniden_mod = bool(yeniden) or (bool(onceki.get("yeniden")) and onceki.get("durum") != "bitti")
    _durum_yaz(cid, durum="calisiyor", adim="Başlıyor…", ilerleme=0, hata="", deneme_sayisi=n, yeniden=yeniden_mod)
    task = asyncio.create_task(_calistir(cid, n, yeniden_mod, sifirla=bool(yeniden)))
    _isler[cid] = task
    task.add_done_callback(lambda _t, cid=cid: _isler.pop(cid, None) if _isler.get(cid) is _t else None)
    return durum(cid)


async def bekle(cid: str) -> None:
    """(testler için) çalışan iş bitene kadar bekler."""
    t = _isler.get(cid)
    if t:
        await asyncio.wait({t})


def acilista_duzelt() -> None:
    """Uygulama kapanırken yarıda kalmış işleri 'yarida' olarak işaretler."""
    for c in notes.list_courses():
        if (c.get("paket_is") or {}).get("durum") == "calisiyor":
            def f(x):
                if (x.get("paket_is") or {}).get("durum") == "calisiyor":
                    x["paket_is"].update(durum="yarida", adim="Uygulama kapandığı için yarıda kaldı; tekrar başlatınca kaldığı yerden devam eder.")
            notes.update_course(c["id"], f)


async def _yz(*a, **kw):
    """Arka plan yapay zeka çağrısı: öğrenci hoca ile konuşurken sırasını bekler."""
    await llm.arka_plan_sirasi()
    return await llm._parse(*a, **kw)


async def _ocr(png: bytes) -> str:
    await llm.arka_plan_sirasi()
    return await llm.ocr_page(png)


def yeni_belge(cid: str) -> None:
    """Derse yeni not eklendi: ayar açıksa BEKLEME sn sonra (o arada başka belge gelirse süre yenilenir)
    paketi artımlı günceller. Testlerde (DERS_ON_YUKLEME=0) kendiliğinden başlamaz."""
    if os.getenv("DERS_ON_YUKLEME", "1") == "0" or not load_settings().get("otomatik_paket", True):
        return
    eski = _zamanlayicilar.pop(cid, None)
    if eski and not eski.done():
        eski.cancel()

    async def sonra():
        await asyncio.sleep(BEKLEME)
        while (t := _isler.get(cid)) and not t.done():  # süren iş bitsin; yeni belge sonra işlenir
            await asyncio.wait({t})
        if _zamanlayicilar.get(cid) is asyncio.current_task():
            _zamanlayicilar.pop(cid, None)
        c = notes.get_course(cid)
        try:
            baslat(cid, (c or {}).get("paket_is", {}).get("deneme_sayisi") or 2)
        except (KeyError, ValueError) as e:
            log.info("otomatik paket başlamadı: %s", e)

    _zamanlayicilar[cid] = asyncio.create_task(sonra())


# ---------------------------------------------------------------- iş
async def _calistir(cid: str, n: int, yeniden: bool, sifirla: bool = False) -> None:
    try:
        ozet = await _uret(cid, n, yeniden, sifirla)
        _durum_yaz(cid, durum="bitti", adim=ozet, ilerleme=1.0, hata="", yeniden=False)
    except _DersYok:
        pass  # ders silindi
    except llm.TutorError as e:
        log.warning("paket üretimi durdu (%s): %s", cid, e)
        _durum_hata(cid, f"Yapay zeka cevap veremedi: {e}. Yapay zeka hazır olunca tekrar başlat; kaldığı yerden devam eder.")
    except asyncio.CancelledError:
        _durum_hata(cid, "", yarida=True)
        raise
    except Exception as e:
        log.exception("paket üretimi (%s)", cid)
        _durum_hata(cid, f"Beklenmeyen hata: {type(e).__name__}: {e}. Tekrar başlatınca kaldığı yerden devam eder.")


def _durum_hata(cid: str, mesaj: str, yarida: bool = False) -> None:
    try:
        if yarida:
            _durum_yaz(cid, durum="yarida", adim="Yarıda kaldı; tekrar başlatınca kaldığı yerden devam eder.")
        else:
            _durum_yaz(cid, durum="hata", hata=mesaj)
    except _DersYok:
        pass


async def _uret(cid: str, n: int, yeniden: bool, sifirla: bool = False) -> str:
    ilr = _Ilerleme(cid)
    course = _ders(cid)
    if sifirla:  # baştan: ara sonuçları ve üretilmiş belge özetlerinin imzalarını unut
        def sifirla_fn(c):
            c.pop("paket_ara", None)
            for d in c["docs"]:
                if (d.get("hazir") or {}).get("paket") == "uretilen":
                    d["hazir"]["imza"] = ""
        course = _guncelle(cid, sifirla_fn)

    # (a) taranmış sayfaları oku; arka planda (yüklemeden hemen sonra) süren okuma varsa önce o bitsin
    suren = [t for t in _arka_ocr.get(cid, ()) if not t.done()]
    if suren:
        ilr.adim("Taranmış sayfaların okunması bitiyor…")
        await asyncio.wait(suren)
        course = _ders(cid)
    ocr = [(d["id"], d["name"], p["n"]) for d in course["docs"] for p in d.get("pages", []) if p.get("needs_ocr")]
    ilr.toplam = len(ocr) + 10 + 2 * n
    for i, (did, ad, sayfa) in enumerate(ocr, 1):
        ilr.adim(f"Taranmış sayfalar okunuyor: {ad} s.{sayfa} ({i}/{len(ocr)})")
        d = notes.find_doc(_ders(cid), did)
        p = next((x for x in (d or {}).get("pages", []) if x["n"] == sayfa), None)
        if p and p.get("needs_ocr"):  # o arada başka bir okuma bitirmiş olabilir
            yol = await asyncio.to_thread(notes.page_image_path, cid, did, sayfa)
            if yol.exists():
                text = await _ocr(yol.read_bytes())
                notes.set_page_text(cid, did, sayfa, text)
        ilr.bir()

    # (b) belge özetleri (artımlı: imzası aynı olan belge atlanır)
    limit = butce()
    course = _ders(cid)
    yapilacak = []
    for d in course["docs"]:
        if not _metinli(d) or _paketten(d):
            continue
        if (d.get("hazir") or {}).get("imza") == belge_imzasi(d):
            continue
        yapilacak.append(d["id"])
    metinli = [d for d in course["docs"] if _metinli(d)]
    parca_say = {did: len(_sayfa_parcalari(notes.find_doc(course, did), int(limit * 0.85))) for did in yapilacak}
    ilr.toplam = ilr.yapilan + sum(k + (k > 1) for k in parca_say.values()) + 3 + len(metinli) + 2 * n
    if not metinli:
        raise llm.TutorError("Notlarda okunabilir metin bulunamadı")
    for did in yapilacak:
        await _belge_ozeti(cid, did, limit, ilr)
    metinli = [d for d in _ders(cid)["docs"] if _metinli(d)]  # özetleriyle birlikte

    # (c) ders düzeyi
    course = _ders(cid)
    imza = _ders_imzasi(course)

    def ara_hazirla(c):
        a = _ara(c)
        if a.get("imza") != imza:  # belgeler ya da sınav formatı değişti: ders düzeyi baştan
            eski = a.get("parcalar", {})
            c["paket_ara"] = {"imza": imza, "tamam": [], "konu": {}, "denemeler": [], "parcalar": eski}

    course = _guncelle(cid, ara_hazirla)
    sistem = _sistem(course)
    fmt = sinav_formati(course)
    tamam = set(_ara(course).get("tamam", []))

    def bitir(adim: str, fn=None):
        def f(c):
            if fn:
                fn(c)
            t = _ara(c).setdefault("tamam", [])
            if adim not in t:
                t.append(adim)
        _guncelle(cid, f)
        ilr.bir()

    # ders planı (hazır paketten geldiyse ve 'baştan' istenmediyse dokunulmaz)
    if "plan" in tamam or ((course.get("lecture_plan") or {}).get("hazir") and not yeniden):
        ilr.bir()
    else:
        ilr.adim("Ders planı çıkarılıyor")
        metin = prompts.PAKET_PLAN.format(ozetler=_ozetler(course, limit))
        plan = await _yz(llm.LecturePlan, metin, sistem, max_tokens=_cikti(len(metin) + len(sistem), 4000))
        bitir("plan", lambda c: c.__setitem__("lecture_plan", plan.model_dump() | {"uretilen": True}))

    # sınav rehberi
    if "rehber" in tamam or not (yeniden or _bizim(course, "sinav_rehberi")):
        ilr.bir()
    else:
        ilr.adim("Sınav rehberi yazılıyor")
        metin = prompts.PAKET_REHBER.format(format=fmt, ozetler=_ozetler(course, limit))
        r = await _yz(Metin, metin, sistem, max_tokens=_cikti(len(metin) + len(sistem), 3000))
        bitir("rehber", lambda c: _yaz(c, "sinav_rehberi", r.metin.strip()))

    # konu anlatımı: belge başına, belge de bütçeye sığan parçalar halinde; sonra birleştir
    course = _ders(cid)
    if "konu" in tamam or not (yeniden or _bizim(course, "konu_anlatimi")):
        for _ in metinli:
            ilr.bir()
    else:
        for d in metinli:
            await _konu(cid, d, sistem, fmt, limit, ilr)

        def konu_birlestir(c):
            parcalar = _ara(c).get("konu", {})
            bolum = []
            for d in c["docs"]:
                v = parcalar.get(d["id"])
                if v:
                    md = v if isinstance(v, str) else "\n\n".join(v.get("parcalar", []))
                    bas = (d.get("hazir") or {}).get("baslik")
                    bolum.append(f"## {d['name']}" + (f" — {bas}" if bas else "") + "\n\n" + md)
            _yaz(c, "konu_anlatimi", f"# {c['name']} — sınav odaklı konu anlatımı\n\n" + "\n\n".join(bolum))
        bitir("konu", konu_birlestir)

    # kısa sınav özeti
    course = _ders(cid)
    if "ozet" in tamam or not (yeniden or _bizim(course, "kisa_ozet")):
        ilr.bir()
    else:
        ilr.adim("Kısa sınav özeti yazılıyor")
        klasik = prompts.PAKET_KLASIK if re.search(r"klasik|açıkla|açık uçlu|yorumla|tartış", fmt, re.I) else ""
        metin = prompts.PAKET_KISA_OZET.format(kelime=KISA_OZET_KELIME, klasik=klasik, format=fmt,
                                               ozetler=_ozetler(course, limit))
        o = await _yz(Metin, metin, sistem, max_tokens=_cikti(len(metin) + len(sistem), 4000))
        bitir("ozet", lambda c: _yaz(c, "kisa_ozet", ozet_kirp(o.metin.strip(), KISA_OZET_KELIME + 100)))

    # deneme sınavları: her biri ayrı çağrı + ayrı denetim çağrısı
    await _denemeler(cid, n, sistem, fmt, limit, ilr)
    return f"Hazır: {len(metinli)} belge, {n} deneme sınavı ({llm.brain_label()} ile üretildi)."


async def _belge_ozeti(cid: str, did: str, limit: int, ilr: _Ilerleme) -> None:
    course = _ders(cid)
    d = notes.find_doc(course, did)
    if not d:
        return
    imza = belge_imzasi(d)
    bol = int(limit * 0.85)
    parcalar = _sayfa_parcalari(d, bol)
    sistem = _sistem(course)
    ara = _ara(course).get("parcalar", {}).get(did) or {}
    # parça sınırları bütçeye bağlı: bütçe değiştiyse (başka model) eski ara özetler yeni parçalara uymaz
    uyar = ara.get("imza") == imza and ara.get("limit") == bol and ara.get("adet", len(parcalar)) == len(parcalar)
    hazir_parca = ara.get("ozetler", []) if uyar else []
    for i, metin in enumerate(parcalar):
        if i < len(hazir_parca):
            ilr.bir()
            continue
        ilr.adim(f"Belge özetleniyor: {d['name']}" + (f" (parça {i + 1}/{len(parcalar)})" if len(parcalar) > 1 else ""))
        istem = prompts.PAKET_PARCA.format(belge=d["name"], i=i + 1, n=len(parcalar), metin=metin)
        p = await _yz(ParcaOzet, istem, sistem, max_tokens=_cikti(len(istem) + len(sistem), 4000))
        hazir_parca.append(p.model_dump())

        def kaydet(c, lst=list(hazir_parca)):
            _ara(c).setdefault("parcalar", {})[did] = {"imza": imza, "limit": bol, "adet": len(parcalar), "ozetler": lst}
        _guncelle(cid, kaydet)
        ilr.bir()

    if len(hazir_parca) == 1:
        tek = hazir_parca[0]
        birlesik = {k: tek[k] for k in ("baslik", "ozet", "bolumler", "olasi_sorular")}
    else:
        ilr.adim(f"Belge özeti birleştiriliyor: {d['name']}")
        metin = json.dumps([{k: p[k] for k in ("baslik", "ozet", "bolumler", "olasi_sorular")} for p in hazir_parca],
                           ensure_ascii=False)[:bol]
        istem = prompts.PAKET_BIRLESTIR.format(belge=d["name"], ozetler=metin)
        b = await _yz(BelgeOzet, istem, sistem, max_tokens=_cikti(len(istem) + len(sistem), 4000))
        birlesik = b.model_dump()
        ilr.bir()
    kavramlar, gorulen = [], set()
    for p in hazir_parca:
        for k in p["kavramlar"]:
            if k["terim"].strip().lower() not in gorulen:
                gorulen.add(k["terim"].strip().lower())
                kavramlar.append(k)

    def yaz(c):
        dd = notes.find_doc(c, did)
        if dd and not _paketten(dd):
            dd["hazir"] = birlesik | {"kavramlar": kavramlar, "paket": "uretilen", "imza": imza}
        _ara(c).get("parcalar", {}).pop(did, None)  # ara parçalar artık gerekmez
    _guncelle(cid, yaz)


async def _kutuphane_blogu(course: dict, sorgu: str, butce: int) -> str:
    """Konu anlatımına küçük kaynak bloğu (kütüphane boşsa ya da hata olursa '')."""
    from . import kutuphane, llm, siniflandir

    try:
        if llm.provider() == "gemini":  # gizlilik: kitaplar buluta gitmez
            return ""
        if await asyncio.to_thread(kutuphane.bos_mu):
            return ""
        ders = siniflandir.ders_kodu(course) or course.get("name", "")
        sonuc = await asyncio.to_thread(kutuphane.ara, sorgu, ders, 3)
        metin = kutuphane.kaynak_metni(sonuc, butce)
    except Exception:
        log.exception("kütüphane bloğu hazırlanamadı")
        return ""
    if not metin:
        return ""
    return ("\n\nKütüphanedeki kaynak kitaplardan ilgili bölümler (yalnızca notlardaki konuları desteklemek için kullan; "
            "notla çelişirse notu esas al; yararlandıysan '(Kaynak: kitap, s.N)' diye belirt):\n<kaynaklar>\n"
            f"{metin}\n</kaynaklar>")


async def _konu(cid: str, d: dict, sistem: str, fmt: str, limit: int, ilr: _Ilerleme) -> None:
    """Belgenin konu anlatımı: belge bütçeye sığan parçalara bölünür, her parça ayrı çağrıyla anlatılır
    (uzun belgede sayfalar sessizce dışarıda kalmasın); parçalar ara kayda yazılır, kaldığı yerden sürer."""
    bol = int(limit * 0.75)
    parcalar = _sayfa_parcalari(d, bol)
    imza = [belge_imzasi(d), bol]
    kayit = _ara(_ders(cid)).get("konu", {}).get(d["id"])
    if isinstance(kayit, str):  # eski biçim (tek parça): bitmiş say
        ilr.bir()
        return
    if not kayit or kayit.get("imza") != imza:
        kayit = {"imza": imza, "parcalar": [], "tamam": False}
    if kayit.get("tamam"):
        ilr.bir()
        return
    ilr.toplam += max(0, len(parcalar) - 1)
    h = d.get("hazir") or {}
    ozet = (h.get("ozet") or "")[:1500]
    kaynak = await _kutuphane_blogu(_ders(cid), f"{d['name']} {ozet[:400]}", int(limit * 0.08))
    for j, metin in enumerate(parcalar):
        if j < len(kayit["parcalar"]):
            continue
        ek = f" (parça {j + 1}/{len(parcalar)})" if len(parcalar) > 1 else ""
        ilr.adim(f"Konu anlatımı yazılıyor: {d['name']}{ek}")
        parca = (f"Bu, belgenin {j + 1}/{len(parcalar)}. parçası: YALNIZCA bu parçadaki konuları anlat; önceki parçaların "
                 "konularını tekrar etme.") if len(parcalar) > 1 else ""
        istem = prompts.PAKET_KONU.format(belge=d["name"], format=fmt, ozet=ozet, metin=metin, parca=parca) + kaynak
        k = await _yz(Metin, istem, sistem, max_tokens=_cikti(len(istem) + len(sistem), 6000))
        kayit["parcalar"].append(k.metin.strip())
        if j + 1 < len(parcalar):
            _guncelle(cid, lambda c, did=d["id"], v=json.loads(json.dumps(kayit)): _ara(c).setdefault("konu", {}).__setitem__(did, v))
            ilr.bir()
    kayit["tamam"] = True
    _guncelle(cid, lambda c, did=d["id"], v=kayit: _ara(c).setdefault("konu", {}).__setitem__(did, v))
    ilr.bir()


async def _denemeler(cid: str, n: int, sistem: str, fmt: str, limit: int, ilr: _Ilerleme) -> None:
    course = _ders(cid)
    if "denemeler" in _ara(course).get("tamam", []) and len(_ara(course).get("denemeler", [])) >= n:
        for _ in range(2 * n):
            ilr.bir()
        return
    for i in range(n):
        course = _ders(cid)
        hazirlar = _ara(course).get("denemeler", [])
        x = hazirlar[i] if i < len(hazirlar) else None
        if x is None:
            x = deneme_duzelt(await _deneme_uret(cid, i, n, sistem, fmt, limit, ilr)) | {"uretilen": True, "_denetlendi": False}
            if not x.get("baslik"):
                x["baslik"] = f"Deneme {i + 1}"

            def koy(c, i=i, x=x):
                _deneme_koy(c, i, x)
                _ara(c).get("deneme_parca", {}).pop(str(i), None)  # bölüm bölüm ara kayıt artık gerekmez
            _guncelle(cid, koy)
        ilr.bir()

        if not x.get("_denetlendi"):
            x = await _denetle(cid, i, n, x, sistem, limit, ilr)
            _guncelle(cid, lambda c, i=i, x=x: _deneme_koy(c, i, x))
        ilr.bir()

    def yaz(c):
        ours = [{k: v for k, v in y.items() if not k.startswith("_")} for y in _ara(c).get("denemeler", [])[:n]]
        c["denemeler"] = [y for y in c.get("denemeler") or [] if not y.get("uretilen")] + ours  # paketten gelenler kalır
        t = _ara(c).setdefault("tamam", [])
        if "denemeler" not in t:
            t.append("denemeler")
    _guncelle(cid, yaz)


def _deneme_istemi(course: dict, i: int, n: int, fmt: str, limit: int, ekstra_onceki: list[str] = ()) -> dict:
    hazirlar = _ara(course).get("denemeler", [])
    onceki = [q["soru"][:90] for y in hazirlar[:i] for b in y.get("bolumler", []) for q in b.get("sorular", [])]
    onceki = (list(ekstra_onceki) + onceki)[:40]
    onceki_txt = ("Önceki denemelerde ve bu denemenin önceki bölümlerinde şu sorular soruldu; bunları TEKRARLAMA, "
                  "farklı konu ve ayrıntılardan sor:\n- " + "\n- ".join(onceki)) if onceki else ""
    # her deneme notların farklı bir kesitine ağırlık versin
    docs = [d for d in course["docs"] if d.get("hazir")]
    odak = docs[i::n] or docs
    sorgu = " ".join(k.get("terim", "") for d in odak for k in (d.get("hazir") or {}).get("kavramlar", []))
    ozet = _ozetler(course, int(limit * 0.35))
    notlar = notes.notes_context(course, sorgu, limit=max(2000, int(limit * 0.8) - len(ozet) - len(onceki_txt))).text
    return dict(i=i + 1, n=n, format=fmt, onceki=onceki_txt, ozetler=ozet, notlar=notlar)


async def _deneme_uret(cid: str, i: int, n: int, sistem: str, fmt: str, limit: int, ilr: _Ilerleme) -> dict:
    """Denemeyi tek çağrıyla üretir; cevap modelin sınırına sığmazsa (büyük format, küçük bağlam) bölüm bölüm üretir."""
    course = _ders(cid)
    if not _ara(course).get("bolumlu"):
        ilr.adim(f"Deneme sınavı {i + 1}/{n} hazırlanıyor")
        istem = prompts.PAKET_DENEME.format(**_deneme_istemi(course, i, n, fmt, limit), parca="")
        try:
            g = await _yz(Deneme, istem, sistem, max_tokens=_cikti(len(istem) + len(sistem), 12000))
            return g.model_dump()
        except llm.TutorError as e:
            if not _sigmadi(e):
                raise
            log.info("deneme tek çağrıya sığmadı, bölüm bölüm üretilecek (%s)", cid)
            _guncelle(cid, lambda c: _ara(c).__setitem__("bolumlu", True))  # sonraki denemeler doğrudan bölüm bölüm
    return await _deneme_bolumlu(cid, i, n, sistem, fmt, limit, ilr)


async def _deneme_bolumlu(cid: str, i: int, n: int, sistem: str, fmt: str, limit: int, ilr: _Ilerleme) -> dict:
    yapi = _ara(_ders(cid)).get("yapi")
    if not yapi:
        ilr.adim("Sınav formatının bölümleri çıkarılıyor")
        istem = prompts.PAKET_YAPI.format(format=fmt)
        y = await _yz(DYapi, istem, sistem, max_tokens=1500)
        yapi = [b.model_dump() | {"soru_sayisi": min(60, b.soru_sayisi)} for b in y.bolumler if b.soru_sayisi > 0]
        if not yapi:
            raise llm.TutorError("Sınav formatından bölümler çıkarılamadı")
        _guncelle(cid, lambda c: _ara(c).__setitem__("yapi", yapi))
    # (bölüm, ilk soru, adet): uzun bölümler PARCA_SORU'luk parçalara bölünür; 'metin' bölümü tek parça (aynı metne dayanır)
    isler = []
    for k, b in enumerate(yapi):
        adim_boy = b["soru_sayisi"] if b["tur"] == "metin" else PARCA_SORU
        isler += [(k, s, min(adim_boy, b["soru_sayisi"] - s)) for s in range(0, b["soru_sayisi"], adim_boy)]
    anahtar = str(i)
    bitmis = list(_ara(_ders(cid)).get("deneme_parca", {}).get(anahtar, []))
    ilr.toplam += len(isler)
    for j, (k, s, m) in enumerate(isler):
        if j < len(bitmis):
            continue
        b = yapi[k]
        ilr.adim(f"Deneme sınavı {i + 1}/{n} hazırlanıyor: {b['baslik']} ({j + 1}/{len(isler)})")
        aralik = f"{s + 1}-{s + m}. sorularını (bölümde toplam {b['soru_sayisi']} soru)" if m < b["soru_sayisi"] else f"{m} sorusunu"
        parca = prompts.PAKET_DENEME_PARCA.format(baslik=b["baslik"], tur=b["tur"], aralik=aralik, yonerge=b.get("yonerge", ""))
        bu_deneme = [q["soru"][:90] for x in bitmis for q in x["sorular"]]
        istem = prompts.PAKET_DENEME.format(**_deneme_istemi(_ders(cid), i, n, fmt, limit, bu_deneme), parca=parca)
        g = await _yz(Deneme, istem, sistem, max_tokens=_cikti(len(istem) + len(sistem), 8000))
        bol = next((x for x in g.bolumler if x.tur == b["tur"]), g.bolumler[0] if g.bolumler else None)
        bitmis.append({"k": k, "metin": bol.metin if bol else "", "yonerge": bol.yonerge if bol else "",
                       "sorular": [q.model_dump() for q in bol.sorular][:m] if bol else []})
        _guncelle(cid, lambda c, lst=list(bitmis): _ara(c).setdefault("deneme_parca", {}).__setitem__(anahtar, lst))
        ilr.bir()
    bolumler = []
    for k, b in enumerate(yapi):
        ps = [x for x in bitmis if x["k"] == k]
        bolumler.append({"baslik": b["baslik"], "tur": b["tur"],
                         "yonerge": b.get("yonerge") or next((x["yonerge"] for x in ps if x["yonerge"]), ""),
                         "metin": next((x["metin"] for x in ps if x["metin"]), ""),
                         "sorular": [q for x in ps for q in x["sorular"]]})
    return {"baslik": f"Deneme {i + 1}", "aciklama": "", "bolumler": bolumler}


async def _denetim_cagrisi(ham: dict, notlar_kaynak: dict, sistem: str, limit: int) -> dict | None:
    """Bir denemeyi (ya da tek bölümünü) notlara karşı denetler; düzeltilmiş hali ya da (sığmadıysa) None."""
    js = json.dumps(ham, ensure_ascii=False)
    sorgu = " ".join(q.get("soru", "") + " " + q.get("cevap", "") for b in ham["bolumler"] for q in b["sorular"])
    notlar = notes.notes_context(notlar_kaynak, sorgu, limit=max(2000, limit - len(js))).text
    istem = prompts.PAKET_DENETIM.format(deneme=js, notlar=notlar)
    try:
        dz = await _yz(Deneme, istem, sistem,
                              max_tokens=_cikti(len(istem) + len(sistem), int(len(js) / llm_yerel.CHARS_PER_TOKEN * 1.3) + 1000))
    except llm.TutorError as e:
        if _sigmadi(e):
            return None
        raise
    yeni = deneme_duzelt(dz.model_dump())
    if _soru_sayisi(yeni) >= max(1, _soru_sayisi(ham) // 2):  # denetim soruları düşürdüyse ilk hali kalsın
        return yeni
    return ham


async def _denetle(cid: str, i: int, n: int, x: dict, sistem: str, limit: int, ilr: _Ilerleme) -> dict:
    """Denemeyi notlara karşı denetler. Bütünü (deneme + not + aynı boyda cevap) bağlama sığmıyorsa bölüm bölüm;
    biten bölümler x['_denetlenen']'e yazılır (kaldığı yerden sürer). Tek bölüm bile sığmazsa o bölüm olduğu gibi kalır."""
    ham = {k: v for k, v in x.items() if not k.startswith("_") and k != "uretilen"}
    js_boy = len(json.dumps(ham, ensure_ascii=False))
    girdi = len(sistem) + len(prompts.PAKET_DENETIM) + js_boy + 2000
    sonuc = None
    if "_denetlenen" not in x and _sigar(girdi, int(js_boy / llm_yerel.CHARS_PER_TOKEN * 1.3) + 1000):
        ilr.adim(f"Deneme sınavı {i + 1}/{n} notlara karşı denetleniyor")
        sonuc = await _denetim_cagrisi(ham, _ders(cid), sistem, limit)
    if sonuc is None:  # bölüm bölüm
        biten = list(x.get("_denetlenen") or [])
        for k, b in enumerate(ham["bolumler"]):
            if k < len(biten):
                continue
            ilr.adim(f"Deneme sınavı {i + 1}/{n} notlara karşı denetleniyor: {b.get('baslik', '')} ({k + 1}/{len(ham['bolumler'])})")
            tek = {"baslik": ham.get("baslik", ""), "aciklama": "", "bolumler": [b]}
            dz = await _denetim_cagrisi(tek, _ders(cid), sistem, limit)
            yb = (dz or {}).get("bolumler") or []
            biten.append(yb[0] | {"tur": b["tur"]} if yb else b)
            x = x | {"_denetlenen": biten}
            _guncelle(cid, lambda c, x=x: _deneme_koy(c, i, x))
        sonuc = deneme_duzelt(ham | {"bolumler": biten})
    x = sik_dengele(sonuc, seed=i) | {"baslik": sonuc.get("baslik") or ham.get("baslik") or f"Deneme {i + 1}",
                                      "uretilen": True, "_denetlendi": True}
    return x


def _deneme_koy(c: dict, i: int, x: dict) -> None:
    lst = _ara(c).setdefault("denemeler", [])
    if i < len(lst):
        lst[i] = x
    else:
        lst.append(x)
