"""Hocanın kendini geliştirmesi: geri bildirim, öğrenci profili ve bunların sistem talimatına KISA katkısı.

Veriler DATA_DIR/ogrenme/ altında tutulur (geri_bildirim.jsonl, profil.json). Yerel modelin bağlamı dar olduğu için
eklenen bloklar küçük ve kırpılmıştır; hiç veri yoksa her fonksiyon boş metin döner (davranış aynı kalır).
"""
from __future__ import annotations

import json
import re
import threading
import time

from . import config

_kilit = threading.RLock()
ESIK = 3  # profilde bir tercihin talimata girmesi için en az sayaç
BLOK_SINIRI = 1100  # geri bildirim bloğu (örnekler + kaçın) en fazla karakter
ORNEK_SAYISI = 2


def klasor():
    d = config.DATA_DIR / "ogrenme"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gb_yolu():
    return klasor() / "geri_bildirim.jsonl"


def _profil_yolu():
    return klasor() / "profil.json"


# ---------------------------------------------------------------- yardımcılar
def _kelimeler(s: str) -> set[str]:
    """Basit kök benzetmesi: küçük harf, en az 3 harfli kelimelerin ilk 5 harfi (Türkçe ekler için)."""
    s = (s or "").replace("İ", "i").replace("I", "ı").lower()
    return {w[:5] for w in re.findall(r"[a-zçğıöşü0-9]+", s) if len(w) >= 3}


def benzerlik(a: str, b: str) -> float:
    x, y = _kelimeler(a), _kelimeler(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def kirp(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def tahta_ozeti(board: list[dict]) -> str:
    parcalar = []
    for op in board or []:
        for k in ("text", "latex", "title", "label", "expr"):
            v = op.get(k)
            if isinstance(v, str) and v.strip():
                parcalar.append(v.strip())
                break
    return "; ".join(parcalar)


def cevap_metni(timeline: list[dict], sira: int) -> tuple[str, str]:
    """Verilen indeksin ait olduğu turun (soru, hocanın cevabı) metnini döndürür."""
    if not timeline or sira < 0 or sira >= len(timeline):
        return "", ""
    u = sira
    while u >= 0 and timeline[u].get("type") != "user":
        u -= 1
    soru = timeline[u].get("text", "") if u >= 0 else ""
    say, tahta = [], []
    for t in timeline[u + 1:]:
        if t.get("type") == "user":
            break
        if t.get("type") == "step":
            if t.get("say"):
                say.append(t["say"])
            o = tahta_ozeti(t.get("board") or [])
            if o:
                tahta.append(o)
    cevap = " ".join(say)
    if tahta:
        cevap += " [Tahta: " + kirp("; ".join(tahta), 300) + "]"
    return soru, cevap.strip()


# ---------------------------------------------------------------- geri bildirim
def _satirlar() -> list[dict]:
    p = _gb_yolu()
    if not p.exists():
        return []
    son: dict[tuple, dict] = {}
    for ln in p.read_text("utf-8").splitlines():
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        son[(r.get("sid"), r.get("sira"))] = r  # aynı cevaba sonradan verilen puan öncekini geçersiz kılar
    return list(son.values())


def geri_bildirim_kaydet(session: dict, sira: int, puan: int, not_: str = "") -> dict:
    soru, cevap = cevap_metni(session.get("timeline", []), sira)
    if not cevap:
        raise ValueError("Bu sırada hocanın bir cevabı yok")
    kayit = {
        "sid": session["id"], "sira": int(sira), "ders": session.get("course_id") or "genel",
        "soru": kirp(soru, 400), "cevap": kirp(cevap, 1500), "puan": 1 if puan > 0 else -1,
        "not": kirp(not_, 200), "zaman": time.time(),
    }
    with _kilit:
        with _gb_yolu().open("a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
    profil_say(not_)
    return kayit


def geri_bildirim_listesi(ders: str | None = None) -> list[dict]:
    with _kilit:
        rows = _satirlar()
    if ders is not None:
        rows = [r for r in rows if r.get("ders") == (ders or "genel")]
    return sorted(rows, key=lambda r: r.get("zaman", 0))


def geri_bildirim_blogu(ders: str | None, soru: str) -> str:
    """İyi anlatım örnekleri (👍) ve kaçınılacaklar (👎 notları). Veri yoksa ''."""
    rows = geri_bildirim_listesi(ders)
    if not rows:
        return ""
    iyi = [(benzerlik(soru, r["soru"]), r) for r in rows if r["puan"] > 0]
    iyi = [x for x in sorted(iyi, key=lambda x: -x[0]) if x[0] > 0][:ORNEK_SAYISI]
    notlar: list[str] = []
    for r in reversed(rows):
        n = (r.get("not") or "").strip().lower()
        if r["puan"] < 0 and n and n not in notlar:
            notlar.append(n)
        if len(notlar) >= 4:
            break
    parcalar = []
    if iyi:
        ornekler = "\n".join(f"- Soru: {kirp(r['soru'], 120)}\n  Cevap: {kirp(r['cevap'], 380)}" for _, r in iyi)
        parcalar.append("İYİ ANLATIM ÖRNEKLERİ (öğrencinin beğendiği tarz; üslubu benzet, içeriği kopyalama):\n" + ornekler)
    if notlar:
        parcalar.append("KAÇIN: öğrenci şunlardan hoşlanmadı: " + "; ".join(notlar) + ".")
    return kirp_blok("\n".join(parcalar), BLOK_SINIRI)


def kirp_blok(s: str, n: int) -> str:
    """Satır yapısını koruyarak kırpar."""
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------- öğrenci profili
# not/mesaj kalıpları → sayaç
_NOT_KALIPLARI = [
    ("anlamadim", r"anlamad"), ("hizli", r"h[ıi]zl[ıi]"), ("uzun", r"uzun"),
]
_MESAJ_KALIPLARI = [
    ("ornek", r"örnek"), ("anlamadim", r"anlamad"), ("hizli", r"daha yavaş|yavaş anlat|çok hızlı"),
    ("kisa", r"k[ıi]saca|kısa anlat|özetle|çok uzun"), ("formul", r"formül"), ("adim", r"ad[ıi]m ad[ıi]m"),
]
_TERCIH = [
    ("ornek", "Örnekle daha iyi anlıyor: her kavramı küçük bir örnekle pekiştir."),
    ("hizli", "Hızlı anlatımda zorlanıyor: yavaş, kısa cümlelerle ve adım adım anlat."),
    ("anlamadim", "Sık takılıyor: önce basit anlat, gerekirse benzetme kullan."),
    ("kisa", "Kısa ve öz anlatımı seviyor: gereksiz uzatma."),
    ("formul", "Formülleri açıkça yazıp açıklamayı seviyor."),
    ("adim", "Adım adım ilerlemeyi seviyor."),
]


def profil_oku() -> dict:
    try:
        return json.loads(_profil_yolu().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _artir(sayaclar: list[str]) -> None:
    if not sayaclar:
        return
    with _kilit:
        p = profil_oku()
        s = p.setdefault("sayac", {})
        for k in sayaclar:
            s[k] = int(s.get(k, 0)) + 1
        _profil_yolu().write_text(json.dumps(p, ensure_ascii=False), "utf-8")


def profil_say(metin: str, not_mu: bool = True) -> list[str]:
    """Geri bildirim notundan (not_mu) ya da öğrencinin mesajından sayaçları artırır; artanları döndürür."""
    kalip = _NOT_KALIPLARI if not_mu else _MESAJ_KALIPLARI
    t = (metin or "").lower().replace("İ", "i")
    bulunan = [k for k, rx in kalip if re.search(rx, t)]
    if not_mu and "uzun" in bulunan:
        bulunan = [("kisa" if k == "uzun" else k) for k in bulunan]
    _artir(bulunan)
    return bulunan


def profil_blogu() -> str:
    """Yalnızca eşik aşılan tercihlerden en çok 2 satır; yoksa ''."""
    s = profil_oku().get("sayac", {})
    uygun = sorted([(s.get(k, 0), m) for k, m in _TERCIH if s.get(k, 0) >= ESIK], key=lambda x: -x[0])[:2]
    if not uygun:
        return ""
    return "ÖĞRENCİNİN TERCİHLERİ:\n" + "\n".join("- " + m for _, m in uygun)


def profil_sifirla() -> None:
    with _kilit:
        try:
            _profil_yolu().unlink()
        except FileNotFoundError:
            pass


def ogrenme_blogu(ders: str | None, soru: str) -> str:
    """Geri bildirim + profil bloklarının birleşimi (boşsa '')."""
    return "\n\n".join(b for b in (geri_bildirim_blogu(ders, soru), profil_blogu()) if b)
