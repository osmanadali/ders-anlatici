"""Yerel bilgi bankası (kütüphane): kitaplar, makaleler ve ders notları bu bilgisayarda aranabilir hale gelir.

- Kayıtlar SQLite'ta (veri/kutuphane/kutuphane.db, WAL). Dosyalar veri/kutuphane/dosyalar/ altına alınır, öğrenilince silinir (ayar: kutuphane_dosya_sakla),
  hiçbir yere gönderilmez.
- İçe alma: PDF (pypdf, sayfa sayfa), EPUB (zipfile + html.parser, OPF okuma sırası), TXT/MD/HTML.
- Parçalama: ~1200 karakter, ~200 örtüşme, paragraf/cümle sınırında; her parçada başladığı sayfa.
- Arama: SQLite FTS5 (BM25, Türkçe harf katlamalı) + yerel gömme modeli (Ollama /api/embed) ile kosinüs;
  ikisi RRF ile birleştirilir. Gömme modeli yoksa yalnızca BM25 çalışır, gömme sonradan tamamlanınca hibrite geçer.
- Arka plan işleyici: kuyruktaki dosyaları işler, sonra gömmeleri üretir. Her gömme çağrısından önce
  llm.arka_plan_sirasi() beklenir (öğrenci soru sorarken bilgisayarı ona bırakır).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import posixpath
import re
import sqlite3
import threading
import time
import uuid
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

import httpx
import numpy as np

from .config import DATA_DIR, load_settings

log = logging.getLogger("ders.kutuphane")

KOK = DATA_DIR / "kutuphane"
UZANTILAR = {".pdf", ".epub", ".txt", ".md", ".html", ".htm"}
TURLER = {"kitap", "makale", "ders_notu", "diger", "haber"}
MAX_BOYUT = 300 * 2**20
PARCA_BOY, ORTUSME, EN_KISA = 1200, 200, 150
TOPLU = 16  # gömme isteği başına parça
VEK_ESIK = 0.30  # bu kosinüsün altı vektör listesine girmez
YALNIZ_VEK_ESIK = 0.45  # kelime eşleşmesi hiç yoksa vektör sonucunun en az bu kadar benzer olması gerekir
KAYNAK_BASINA = 3
SORGU_TALIMATI = "Instruct: Given a question about industrial engineering, retrieve relevant passages that answer it\nQuery: "

_KATLA = str.maketrans({"İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s", "Ç": "c", "ç": "c", "Ğ": "g", "ğ": "g",
                       "Ö": "o", "ö": "o", "Ü": "u", "ü": "u", "Â": "a", "â": "a", "Î": "i", "î": "i", "Û": "u", "û": "u"})
DURAK = set("""ve ile bir bu su o da de ne nedir neden nasil icin mi mu midir midir ki ya veya ama gibi daha cok en her
hangi olan olarak ise kadar sonra once bana beni anlat acikla soyle var yok mi the and of to in for is are what how why
a an on with by as be or at from this that""".split())

_kilit = threading.RLock()
_baglanti: sqlite3.Connection | None = None
_baglanti_yolu: Path | None = None
_fts_var = True
_surum = 0  # parça/vektör değişince artar (vektör matrisi önbelleği için)
_matris: dict = {"surum": -1, "model": "", "ids": None, "kaynak": None, "M": None}
_gomme: dict = {"hazir": False, "son_hata": 0.0, "mesaj": "", "indiriliyor": False}
_islem: dict = {"aktif": False, "mesaj": ""}
_gorev: asyncio.Task | None = None
_uyandir: asyncio.Event | None = None


def katla(s: str) -> str:
    """Türkçe harfleri ASCII'ye katlar, küçültür (ı/I/İ dahil); dizinleme ve sorgu aynı işlevi kullanır."""
    return (s or "").translate(_KATLA).lower()


def gomme_modeli() -> str:
    return load_settings().get("gomme_modeli") or "qwen3-embedding:0.6b"


# ================================================================ veritabanı
def _db() -> sqlite3.Connection:
    global _baglanti, _baglanti_yolu, _fts_var
    yol = KOK / "kutuphane.db"
    if _baglanti is not None and _baglanti_yolu == yol:
        return _baglanti
    KOK.mkdir(parents=True, exist_ok=True)
    (KOK / "dosyalar").mkdir(exist_ok=True)
    c = sqlite3.connect(str(yol), check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    for p in ("journal_mode=WAL", "synchronous=NORMAL", "busy_timeout=5000", "foreign_keys=ON"):
        c.execute("PRAGMA " + p)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS kaynaklar (
        id TEXT PRIMARY KEY, baslik TEXT, yazar TEXT, yil INTEGER, tur TEXT, dil TEXT, dosya TEXT, url TEXT,
        doi TEXT, sha256 TEXT UNIQUE, eklenme REAL, durum TEXT, hata TEXT, sayfa_sayisi INTEGER DEFAULT 0,
        parca_sayisi INTEGER DEFAULT 0, dersler TEXT DEFAULT '[]', dergi TEXT, ozet TEXT, uzanti TEXT);
    CREATE INDEX IF NOT EXISTS kaynak_doi ON kaynaklar(doi);
    CREATE TABLE IF NOT EXISTS parcalar (
        id INTEGER PRIMARY KEY, kaynak_id TEXT NOT NULL REFERENCES kaynaklar(id) ON DELETE CASCADE,
        sira INTEGER, sayfa INTEGER, bolum TEXT, metin TEXT, vektor BLOB, gomme_modeli TEXT);
    CREATE INDEX IF NOT EXISTS parca_kaynak ON parcalar(kaynak_id);
    """)
    try:
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(metin, tokenize='unicode61 remove_diacritics 2')")
        _fts_var = True
    except sqlite3.OperationalError:
        log.warning("SQLite FTS5 yok: kütüphane basit aramayla çalışacak")
        _fts_var = False
    _baglanti, _baglanti_yolu = c, yol
    return c


def _kapat() -> None:
    """(testler için) bağlantıyı kapatır; KOK değişirse sonraki çağrı yeni veritabanını açar."""
    global _baglanti, _surum
    with _kilit:
        if _baglanti is not None:
            _baglanti.close()
        _baglanti = None
        _surum += 1


def _kayit(r: sqlite3.Row, gomulu: int | None = None) -> dict:
    d = dict(r)
    d["dersler"] = json.loads(d.get("dersler") or "[]")
    d.pop("sha256", None)
    d.pop("uzanti", None)
    n = d.get("parca_sayisi") or 0
    if gomulu is None:
        gomulu = _db().execute("SELECT COUNT(*) FROM parcalar WHERE kaynak_id=? AND vektor IS NOT NULL AND gomme_modeli=?",
                               (d["id"], gomme_modeli())).fetchone()[0]
    d["gomulu_orani"] = round(gomulu / n, 3) if n else 0.0
    return d


def _getir(kid: str) -> dict | None:
    with _kilit:
        r = _db().execute("SELECT * FROM kaynaklar WHERE id=?", (kid,)).fetchone()
        return _kayit(r) if r else None


def liste() -> list[dict]:
    with _kilit:
        c = _db()
        gom = dict(c.execute("SELECT kaynak_id, COUNT(*) FROM parcalar WHERE vektor IS NOT NULL AND gomme_modeli=? "
                             "GROUP BY kaynak_id", (gomme_modeli(),)).fetchall())
        return [_kayit(r, gom.get(r["id"], 0)) for r in c.execute("SELECT * FROM kaynaklar ORDER BY eklenme DESC")]


def bos_mu() -> bool:
    with _kilit:
        return _db().execute("SELECT 1 FROM parcalar LIMIT 1").fetchone() is None


def durum() -> dict:
    with _kilit:
        c = _db()
        ks = c.execute("SELECT COUNT(*) FROM kaynaklar").fetchone()[0]
        ps = c.execute("SELECT COUNT(*) FROM parcalar").fetchone()[0]
        gp = c.execute("SELECT COUNT(*) FROM parcalar WHERE vektor IS NOT NULL AND gomme_modeli=?",
                       (gomme_modeli(),)).fetchone()[0]
        bekleyen = c.execute("SELECT COUNT(*) FROM kaynaklar WHERE durum IN ('bekliyor','isleniyor')").fetchone()[0]
    return {"kaynak_sayisi": ks, "parca_sayisi": ps, "gomulu_parca": gp,
            "isleniyor": bool(_islem["aktif"] or bekleyen), "mesaj": _islem["mesaj"] or _gomme["mesaj"],
            "gomme_modeli": gomme_modeli(), "gomme_hazir": bool(_gomme["hazir"] and gp > 0), "fts": _fts_var}


# ================================================================ ders kodları
def _kod_bicim(k: str) -> str:
    return re.sub(r"^([A-Z]+)\s*(\d+)$", r"\1 \2", k.strip().upper())


def _ders_anahtari(s: str) -> str:
    """'ENM 463', 'enm463', 'ENM-463 Kalite' → 'ENM463'; kodsuz ders adı → katlanmış ad."""
    from . import siniflandir

    k = siniflandir.kodlar(s or "")
    return next(iter(sorted(k))) if k else katla(s).strip()


def ders_etiketle(metin: str, baslik: str = "", en_fazla: int = 3) -> list[str]:
    """Kaynağın hangi derslerle ilgili olduğunu bulur (kullanıcı dersleri + müfredat; en fazla 3)."""
    from . import notes, siniflandir

    try:
        dersler = notes.list_courses()
        mevcut = {siniflandir.ders_kodu(c) for c in dersler if siniflandir.ders_kodu(c)}
        adaylar = dersler + siniflandir._curriculum_courses(mevcut)
    except Exception:
        log.exception("ders listesi okunamadı")
        return []
    out: list[str] = []
    for k in sorted(siniflandir.kodlar(baslik)):  # başlıkta açıkça ders kodu varsa önce o
        out.append(_kod_bicim(k))
    if not adaylar:
        return out[:en_fazla]
    skorlar = siniflandir._tfidf_scores(f"{baslik}\n{baslik}\n{metin[:40000]}", adaylar)
    if skorlar:
        tepe = skorlar[0][0]
        for s, c in skorlar:
            if len(out) >= en_fazla or s < 0.10 or s < tepe * 0.6:
                break
            kod = siniflandir.ders_kodu(c) or next(iter(siniflandir.kodlar(c.get("_kod", ""))), "")
            etiket = _kod_bicim(kod) if kod else c.get("name", "")
            if etiket and etiket not in out:
                out.append(etiket)
    return out[:en_fazla]


# ================================================================ metin çıkarma
class _HtmlMetin(HTMLParser):
    BLOK = {"p", "div", "br", "li", "tr", "section", "article", "blockquote", "pre", "table", "dd", "dt"}
    BASLIK = {"h1", "h2", "h3", "h4", "h5", "h6"}
    ATLA = {"script", "style", "nav", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parca: list[str] = []
        self.atla = 0
        self.baslik = ""
        self._h = False

    def handle_starttag(self, tag, attrs):
        if tag in self.ATLA:
            self.atla += 1
        elif tag in self.BASLIK:
            self.parca.append("\n\n")
            self._h = True
        elif tag in self.BLOK:
            self.parca.append("\n")

    def handle_endtag(self, tag):
        if tag in self.ATLA:
            self.atla = max(0, self.atla - 1)
        elif tag in self.BASLIK:
            self.parca.append("\n\n")
            self._h = False
        elif tag in self.BLOK:
            self.parca.append("\n")

    def handle_data(self, data):
        if self.atla:
            return
        if self._h and not self.baslik and data.strip():
            self.baslik = data.strip()[:120]
        self.parca.append(data)

    def metin(self) -> str:
        return "".join(self.parca)


def _coz(veri: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return veri.decode(enc)
        except UnicodeDecodeError:
            pass
    m = re.search(rb'(?:encoding|charset)=["\']?([\w-]+)', veri[:500])
    try:
        return veri.decode(m.group(1).decode() if m else "utf-8", errors="replace")
    except LookupError:
        return veri.decode("utf-8", errors="replace")


def _html_metin(veri: bytes) -> tuple[str, str]:
    p = _HtmlMetin()
    p.feed(_coz(veri))
    return p.metin(), p.baslik


def _yil(s) -> int | None:
    m = re.search(r"(1[5-9]\d\d|20\d\d|2100)", str(s or ""))
    return int(m.group(1)) if m else None


def _dosyadan_baslik(ad: str) -> str:
    return re.sub(r"[_]+", " ", Path(ad).stem).strip() or "Adsız kaynak"


def _pdf_oku(yol: Path, ad: str) -> dict:
    from pypdf import PdfReader

    r = PdfReader(str(yol))
    if r.is_encrypted:
        try:
            if not r.decrypt(""):
                raise ValueError
        except Exception:
            raise ValueError("Şifreli PDF: şifresi kaldırılmadan okunamıyor") from None
    md = {}
    try:
        md = r.metadata or {}
    except Exception:
        pass
    baslik = str(md.get("/Title") or "").strip()
    if not baslik or len(baslik) < 3 or re.search(r"\.(pdf|docx?|indd|tex)$|^untitled|^microsoft", baslik, re.I):
        baslik = _dosyadan_baslik(ad)
    yil = _yil(md.get("/CreationDate"))
    sayfalar = []
    for i, p in enumerate(r.pages, 1):
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        sayfalar.append((i, t, ""))
    return {"baslik": baslik, "yazar": str(md.get("/Author") or "").strip(), "yil": yil, "sayfalar": sayfalar,
            "sayfa_sayisi": len(sayfalar)}


def _epub_oku(veri: bytes, ad: str) -> dict:
    z = zipfile.ZipFile(io.BytesIO(veri))
    bilgi = z.infolist()
    if len(bilgi) > 5000 or sum(i.file_size for i in bilgi) > 400 * 2**20:
        raise ValueError("EPUB çok büyük ya da bozuk")
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "o": "http://www.idpf.org/2007/opf",
          "dc": "http://purl.org/dc/elements/1.1/"}
    try:
        kok = ET.fromstring(z.read("META-INF/container.xml"))
        opf_yol = kok.find(".//c:rootfile", ns).get("full-path")
    except Exception:
        opf_yol = next((n for n in z.namelist() if n.endswith(".opf")), None)
    if not opf_yol:
        raise ValueError("EPUB içinde içerik listesi (OPF) bulunamadı")
    opf = ET.fromstring(z.read(opf_yol))
    taban = posixpath.dirname(opf_yol)

    def dc(etiket):
        return [(e.text or "").strip() for e in opf.iter(f"{{{ns['dc']}}}{etiket}") if (e.text or "").strip()]

    manifest = {}
    for it in opf.iter(f"{{{ns['o']}}}item"):
        manifest[it.get("id")] = (it.get("href") or "", it.get("media-type") or "")
    sira = [ir.get("idref") for ir in opf.iter(f"{{{ns['o']}}}itemref")]
    if not sira:
        sira = [k for k, (h, mt) in manifest.items() if "html" in mt]
    sayfalar = []
    for n, idref in enumerate(sira, 1):
        href, mt = manifest.get(idref, ("", ""))
        if not href or ("html" not in mt and not href.lower().endswith((".html", ".htm", ".xhtml"))):
            continue
        yol = posixpath.normpath(posixpath.join(taban, unquote(href.split("#")[0])))
        try:
            metin, bas = _html_metin(z.read(yol))
        except KeyError:
            continue
        sayfalar.append((len(sayfalar) + 1, metin, bas))
    basliklar, yazarlar = dc("title"), dc("creator")
    return {"baslik": basliklar[0] if basliklar else _dosyadan_baslik(ad), "yazar": ", ".join(yazarlar),
            "yil": _yil((dc("date") or [""])[0]), "dil": (dc("language") or [""])[0][:5], "sayfalar": sayfalar,
            "sayfa_sayisi": 0, "bolumlu": True}


def _duz_oku(veri: bytes, ad: str, uzanti: str) -> dict:
    if uzanti in (".html", ".htm"):
        metin, bas = _html_metin(veri)
        return {"baslik": bas or _dosyadan_baslik(ad), "yazar": "", "yil": None, "sayfalar": [(1, metin, "")],
                "sayfa_sayisi": 0}
    metin = _coz(veri)
    parcalar = metin.split("\f") if "\f" in metin else [metin]
    return {"baslik": _dosyadan_baslik(ad), "yazar": "", "yil": None,
            "sayfalar": [(i, t, "") for i, t in enumerate(parcalar, 1)],
            "sayfa_sayisi": len(parcalar) if len(parcalar) > 1 else 0, "sayfasiz": len(parcalar) == 1}


def _temizle(sayfalar: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """Tireli satır sonlarını birleştirir, tekrar eden üst/alt bilgiyi ve içindekiler/dizin satırlarını atar."""
    satirlar = [[s.strip() for s in t.splitlines()] for _, t, _ in sayfalar]
    tekrar = set()
    if len(sayfalar) >= 5:
        say = Counter(s for ss in satirlar for s in set(ss) if s and len(s) < 120)
        tekrar = {s for s, n in say.items() if n > len(sayfalar) * 0.3}
    out = []
    for (no, _, bas), ss in zip(sayfalar, satirlar):
        tut = []
        for s in ss:
            if s in tekrar or re.fullmatch(r"[\d\s\-–—./ivxlcIVXLC]{1,12}", s):
                continue
            if len(s) > 8 and sum(ch.isdigit() or ch in "._…" for ch in s) / len(s) > 0.5:
                continue
            tut.append(s)
        t = "\n".join(tut)
        t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
        t = re.sub(r"[ \t ]+", " ", t)
        t = re.sub(r"(?<![.:!?;\n])\n(?!\n)", " ", t)  # paragraf içi satır sonları
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        out.append((no, t, bas))
    return out


def _birimler(sayfalar):
    """Paragraf/cümle sınırında en fazla PARCA_BOY uzunluğunda (sayfa, bolum, metin) birimleri."""
    for no, t, bas in sayfalar:
        for par in re.split(r"\n\s*\n", t):
            par = par.strip()
            if not par:
                continue
            if len(par) <= PARCA_BOY:
                yield no, bas, par
                continue
            cumle = ""
            for c in re.split(r"(?<=[.!?;:])\s+", par):
                while len(c) > PARCA_BOY:
                    if cumle:
                        yield no, bas, cumle
                        cumle = ""
                    yield no, bas, c[:PARCA_BOY]
                    c = c[PARCA_BOY:]
                if cumle and len(cumle) + len(c) + 1 > PARCA_BOY:
                    yield no, bas, cumle
                    cumle = ""
                cumle = f"{cumle} {c}".strip()
            if cumle:
                yield no, bas, cumle


def parcala(sayfalar: list[tuple[int, str, str]], bolum_siniri: bool = False) -> list[dict]:
    """~1200 karakterlik, ~200 örtüşmeli parçalar; her parçada başladığı sayfa ve bölüm başlığı.
    bolum_siniri: (EPUB) parça bir bölümden ötekine taşmaz."""
    out: list[dict] = []
    cur: list[tuple[int, str, str]] = []
    yeni = 0  # cur içinde örtüşme olmayan birim sayısı

    def bosalt():
        nonlocal cur, yeni
        if not yeni:
            return
        metin = "\n".join(u[2] for u in cur).strip()
        ilk = cur[len(cur) - yeni]
        if len(metin) < EN_KISA and out and out[-1]["sayfa"] == ilk[0]:
            out[-1]["metin"] += "\n" + "\n".join(u[2] for u in cur[len(cur) - yeni:])
        elif len(metin) >= 40:
            out.append({"sayfa": ilk[0], "bolum": ilk[1], "metin": metin})
        kuyruk, boy = [], 0
        for u in reversed(cur):
            if boy + len(u[2]) > ORTUSME:
                break
            kuyruk.insert(0, u)
            boy += len(u[2])
        cur, yeni = kuyruk, 0

    for u in _birimler(sayfalar):
        if bolum_siniri and cur and cur[-1][0] != u[0]:
            bosalt()
            cur = []
        if yeni and sum(len(x[2]) + 1 for x in cur) + len(u[2]) > PARCA_BOY:
            bosalt()
        cur.append(u)
        yeni += 1
    bosalt()
    return out


# ================================================================ ekleme / düzenleme
def _yeni_id() -> str:
    return uuid.uuid4().hex[:12]


def ekle_dosya(dosya_adi: str, veri: bytes, tur: str = "kitap") -> dict:
    """Dosyayı kütüphaneye kaydeder; metin çıkarma ve dizinleme arka plan işleyicide yapılır."""
    uzanti = Path(dosya_adi).suffix.lower()
    if uzanti not in UZANTILAR:
        raise ValueError(f"Desteklenmeyen dosya türü ({uzanti or 'uzantısız'}): PDF, EPUB, TXT, MD ya da HTML olmalı")
    if not veri:
        raise ValueError("Dosya boş")
    if len(veri) > MAX_BOYUT:
        raise ValueError(f"Dosya çok büyük (en fazla {MAX_BOYUT // 2**20} MB)")
    sha = hashlib.sha256(veri).hexdigest()
    kid = _yeni_id()
    with _kilit:
        c = _db()
        if c.execute("SELECT 1 FROM kaynaklar WHERE sha256=?", (sha,)).fetchone():
            raise ValueError("Bu dosya zaten kütüphanede")
        (KOK / "dosyalar" / f"{kid}{uzanti}").write_bytes(veri)
        c.execute("INSERT INTO kaynaklar (id, baslik, yazar, yil, tur, dil, dosya, url, doi, sha256, eklenme, durum, hata,"
                  " dersler, uzanti) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (kid, _dosyadan_baslik(dosya_adi), "", None, tur if tur in TURLER else "diger", "", dosya_adi, "",
                   None, sha, time.time(), "bekliyor", "", "[]", uzanti))
    _durt()
    return _getir(kid)


def normal_doi(doi: str) -> str:
    d = (doi or "").strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    return d.strip()


def var_mi_doi(doi: str) -> bool:
    d = normal_doi(doi)
    if not d:
        return False
    with _kilit:
        return _db().execute("SELECT 1 FROM kaynaklar WHERE doi=?", (d,)).fetchone() is not None


def _parcalari_yaz(c: sqlite3.Connection, kid: str, parcalar: list[dict]) -> None:
    """Kilit altında, tek transaction içinde çağrılır: eski parçaları siler, yenilerini ve FTS'i yazar."""
    global _surum
    eski = [r[0] for r in c.execute("SELECT id FROM parcalar WHERE kaynak_id=?", (kid,))]
    if eski and _fts_var:
        c.executemany("DELETE FROM fts WHERE rowid=?", [(i,) for i in eski])
    c.execute("DELETE FROM parcalar WHERE kaynak_id=?", (kid,))
    for i, p in enumerate(parcalar):
        cur = c.execute("INSERT INTO parcalar (kaynak_id, sira, sayfa, bolum, metin) VALUES (?,?,?,?,?)",
                        (kid, i, p.get("sayfa"), p.get("bolum") or "", p["metin"]))
        if _fts_var:
            c.execute("INSERT INTO fts(rowid, metin) VALUES (?,?)", (cur.lastrowid, katla(p["metin"])))
    _surum += 1


def ekle_makale(meta: dict, tam_metin: str | None = None) -> dict | None:
    """Literatür taramasından gelen makale. Aynı DOI varsa None. Metin hemen aranabilir olur; gömme sonra."""
    doi = normal_doi(meta.get("doi") or "") or None
    baslik = (meta.get("baslik") or "").strip() or "Adsız makale"
    yazarlar = meta.get("yazarlar") or []
    yazar = ", ".join(yazarlar) if isinstance(yazarlar, list) else str(yazarlar)
    ozet = (meta.get("ozet") or "").strip()
    metin = (tam_metin or "").strip()
    govde = f"{baslik}\n\n{ozet}" + (f"\n\n{metin}" if metin else "")
    parcalar = parcala(_temizle([(1, govde, "")])) or [{"sayfa": None, "bolum": "", "metin": govde}]
    for p in parcalar:
        p["sayfa"] = None
    dersler = meta.get("dersler")
    if not isinstance(dersler, list):
        dersler = ders_etiketle(govde, baslik)
    kid = _yeni_id()
    tur = meta.get("tur") if meta.get("tur") in TURLER else "makale"
    with _kilit:
        c = _db()
        if doi and c.execute("SELECT 1 FROM kaynaklar WHERE doi=?", (doi,)).fetchone():
            return None
        kimlik = (meta.get("kimlik") or "").strip()  # DOI'si olmayan kaynaklar (haber, Vikipedi) için kalıcı kimlik: url vb.
        sha = hashlib.sha256((doi or kimlik or (baslik + yazar)).encode()).hexdigest()
        if c.execute("SELECT 1 FROM kaynaklar WHERE sha256=?", (sha,)).fetchone():
            return None
        c.execute("BEGIN")
        try:
            c.execute("INSERT INTO kaynaklar (id, baslik, yazar, yil, tur, dil, dosya, url, doi, sha256, eklenme, durum,"
                      " hata, dersler, dergi, ozet, parca_sayisi) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (kid, baslik, yazar, meta.get("yil") if isinstance(meta.get("yil"), int) else _yil(meta.get("yil")),
                       tur, meta.get("dil") or "", "", meta.get("url") or "", doi, sha, time.time(), "hazir", "",
                       json.dumps(dersler, ensure_ascii=False), meta.get("dergi") or "", ozet, len(parcalar)))
            _parcalari_yaz(c, kid, parcalar)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    _durt()
    return _getir(kid)


def guncelle(kid: str, alanlar: dict) -> dict:
    izinli = {"baslik", "yazar", "yil", "dersler", "tur", "dil"}
    alanlar = alanlar or {}
    # yıl boş (None) gönderilirse temizlenir; diğer alanlarda None yok sayılır
    deg = {k: v for k, v in alanlar.items() if k in izinli and (v is not None or k == "yil")}
    if "dersler" in deg:
        d = deg["dersler"]
        if isinstance(d, str):
            d = d.split(",")
        elif not isinstance(d, (list, tuple)):
            d = []
        deg["dersler"] = json.dumps([str(x).strip() for x in d if str(x).strip()][:10], ensure_ascii=False)
    if "yil" in deg:
        deg["yil"] = int(deg["yil"]) if deg["yil"] is not None and str(deg["yil"]).strip().lstrip("-").isdigit() else None
    if "tur" in deg and deg["tur"] not in TURLER:
        deg["tur"] = "diger"
    with _kilit:
        c = _db()
        if not c.execute("SELECT 1 FROM kaynaklar WHERE id=?", (kid,)).fetchone():
            raise KeyError("Kaynak bulunamadı")
        if deg:
            c.execute(f"UPDATE kaynaklar SET {', '.join(k + '=?' for k in deg)} WHERE id=?", (*deg.values(), kid))
    return _getir(kid)


def sil(kid: str) -> None:
    global _surum
    with _kilit:
        c = _db()
        r = c.execute("SELECT uzanti FROM kaynaklar WHERE id=?", (kid,)).fetchone()
        if not r:
            raise KeyError("Kaynak bulunamadı")
        c.execute("BEGIN")
        if _fts_var:
            c.execute("DELETE FROM fts WHERE rowid IN (SELECT id FROM parcalar WHERE kaynak_id=?)", (kid,))
        c.execute("DELETE FROM parcalar WHERE kaynak_id=?", (kid,))
        c.execute("DELETE FROM kaynaklar WHERE id=?", (kid,))
        c.execute("COMMIT")
        _surum += 1
        if r["uzanti"]:
            try:
                (KOK / "dosyalar" / f"{kid}{r['uzanti']}").unlink(missing_ok=True)
            except OSError:
                pass


# ================================================================ işleme
def _cikar(kid: str, uzanti: str, ad: str) -> dict:
    yol = KOK / "dosyalar" / f"{kid}{uzanti}"
    if uzanti == ".pdf":
        return _pdf_oku(yol, ad)
    veri = yol.read_bytes()
    if uzanti == ".epub":
        return _epub_oku(veri, ad)
    return _duz_oku(veri, ad, uzanti)


async def _ocr_sayfalar(kid: str, bos: list[int]) -> dict[int, str]:
    """(ayar kutuphane_ocr açıksa) metin katmanı olmayan PDF sayfalarını yerel yapay zekayla okur. Yavaştır."""
    from . import llm

    out = {}
    try:
        import pypdfium2 as pdfium
    except Exception:
        return out
    pdf = pdfium.PdfDocument(str(KOK / "dosyalar" / f"{kid}.pdf"))
    try:
        for n in bos:
            await llm.arka_plan_sirasi()
            _islem["mesaj"] = f"Taranmış sayfa okunuyor: s.{n}"

            def png(i=n):
                b = io.BytesIO()
                pdf[i - 1].render(scale=1.6).to_pil().save(b, "PNG")
                return b.getvalue()

            try:
                out[n] = await llm.ocr_page(await asyncio.to_thread(png))
            except Exception:
                log.warning("OCR başarısız: %s s.%s", kid, n)
    finally:
        pdf.close()
    return out


async def _kaynak_isle(r: dict) -> None:
    from . import klasor

    kid = r["id"]
    with _kilit:
        _db().execute("UPDATE kaynaklar SET durum='isleniyor', hata='' WHERE id=?", (kid,))
    _islem["mesaj"] = f"Okunuyor: {r['baslik']}"
    try:
        bilgi = await asyncio.to_thread(_cikar, kid, r["uzanti"] or "", r["dosya"] or "")
        sayfalar = bilgi["sayfalar"]
        bos = [n for n, t, _ in sayfalar if len(t.strip()) < 20]
        if r["uzanti"] == ".pdf" and sayfalar and len(bos) > 0.9 * len(sayfalar):
            if load_settings().get("kutuphane_ocr"):
                oku = await _ocr_sayfalar(kid, bos)
                sayfalar = [(n, oku.get(n, t), b) for n, t, b in sayfalar]
            if sum(len(t.strip()) >= 20 for _, t, _ in sayfalar) < max(1, 0.1 * len(sayfalar)):
                raise ValueError("Taranmış PDF: metin katmanı yok (OCR gerekir; metin katmanlı bir PDF kullan)")
        temiz = await asyncio.to_thread(_temizle, sayfalar)
        parcalar = await asyncio.to_thread(parcala, temiz, bool(bilgi.get("bolumlu")))
        if not parcalar:
            raise ValueError("Dosyada okunabilir metin bulunamadı")
        for p in parcalar:  # EPUB'da sayfa yok: bölüm (okuma sırası) gösterilir; tek parça TXT'de sayfa yok
            if bilgi.get("bolumlu"):
                p["bolum"] = f"bölüm {p['sayfa']}" + (f" ({p['bolum']})" if p.get("bolum") else "")
                p["sayfa"] = None
            elif bilgi.get("sayfasiz"):
                p["sayfa"] = None
        ornek = "\n".join(p["metin"] for p in parcalar[:40])
        dersler = await asyncio.to_thread(ders_etiketle, ornek, bilgi["baslik"])
        with _kilit:
            c = _db()
            if not c.execute("SELECT 1 FROM kaynaklar WHERE id=?", (kid,)).fetchone():
                return  # işlenirken silindi
            c.execute("BEGIN")
            try:
                c.execute("UPDATE kaynaklar SET baslik=?, yazar=?, yil=?, dil=?, sayfa_sayisi=?, parca_sayisi=?, "
                          "dersler=CASE WHEN dersler='[]' THEN ? ELSE dersler END, durum='hazir', hata='' WHERE id=?",
                          (bilgi["baslik"], bilgi.get("yazar") or "", bilgi.get("yil"), bilgi.get("dil") or "",
                           bilgi.get("sayfa_sayisi") or 0, len(parcalar), json.dumps(dersler, ensure_ascii=False), kid))
                _parcalari_yaz(c, kid, parcalar)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        if not load_settings().get("kutuphane_dosya_sakla", False):
            # Öğrenildi: metin ve sayfa numaraları veritabanında; kopyaya gerek yok (yer kaplamasın)
            try:
                (KOK / "dosyalar" / f"{kid}{r['uzanti'] or ''}").unlink(missing_ok=True)
            except OSError as e:  # Windows'ta kilitliyse bir dahaki sefere
                log.warning("kütüphane kopyası silinemedi: %s", e)
        n = bilgi.get("sayfa_sayisi") or 0
        boy = f"{n} sayfa" if n else f"{len(parcalar)} bölüm parçası"
        klasor.olay("kutuphane", f"📚 Kütüphaneye eklendi: {bilgi['baslik']} ({boy})")
    except Exception as e:
        log.warning("kütüphane kaynağı işlenemedi: %s: %s", kid, e)
        with _kilit:
            _db().execute("UPDATE kaynaklar SET durum='hata', hata=? WHERE id=?", (str(e) or type(e).__name__, kid))
        klasor.olay("hata", f"⚠ Kütüphaneye eklenemedi: {r['baslik']}: {e}")


async def isle_bekleyenler() -> int:
    """Kuyruktaki (ve yarım kalmış) dosyaları sırayla işler."""
    n = 0
    while True:
        with _kilit:
            r = _db().execute("SELECT * FROM kaynaklar WHERE durum IN ('bekliyor','isleniyor') AND uzanti IS NOT NULL "
                              "AND uzanti != '' ORDER BY eklenme LIMIT 1").fetchone()
        if not r:
            break
        _islem["aktif"] = True
        try:
            await _kaynak_isle(dict(r))
        finally:
            _islem["aktif"] = False
            _islem["mesaj"] = ""
        n += 1
    return n


# ================================================================ gömme (Ollama /api/embed)
def _host() -> str:
    from . import yerel

    return yerel.HOST


async def _gomme_modeli_hazirla() -> bool:
    """Gömme modeli kurulu mu? Değilse (izin varsa) indirir. Ollama kapalıysa False."""
    from . import yerel

    model = gomme_modeli()
    if not await yerel.alive():
        _gomme["mesaj"] = "Yerel yapay zeka çalışmıyor: kütüphane şimdilik yalnızca kelime aramasıyla çalışıyor."
        return False
    try:
        kurulu = await yerel.installed_models()
    except Exception:
        return False
    if any(yerel._same(m, model) for m in kurulu):
        return True
    if os.getenv("DERS_YEREL_INDIRME", "1") == "0":
        _gomme["mesaj"] = f"Gömme modeli ({model}) indirilmemiş (otomatik indirme kapalı); kelime aramasıyla çalışıyor."
        return False
    _gomme.update(indiriliyor=True, mesaj=f"Kütüphane için anlam arama modeli indiriliyor ({model}, ~640 MB)…")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=600)) as c:
            async with c.stream("POST", f"{_host()}/api/pull", json={"model": model, "stream": True}) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    if d.get("error"):
                        raise RuntimeError(d["error"])
                    if d.get("total"):
                        _gomme["mesaj"] = (f"Anlam arama modeli indiriliyor ({model}): "
                                           f"%{100 * d.get('completed', 0) / d['total']:.0f}")
        _gomme["mesaj"] = ""
        return True
    except Exception as e:
        _gomme["mesaj"] = f"Gömme modeli indirilemedi: {e}"
        return False
    finally:
        _gomme["indiriliyor"] = False


def _vektorler(cevap: dict) -> list[np.ndarray]:
    out = []
    for v in cevap.get("embeddings") or []:
        a = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(a))
        out.append(a / n if n else a)
    return out


async def _gom(metinler: list[str]) -> list[np.ndarray]:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{_host()}/api/embed", json={"model": gomme_modeli(), "input": metinler, "truncate": True,
                                                       "keep_alive": "2m"})
        r.raise_for_status()
        v = _vektorler(r.json())
        if len(v) != len(metinler):
            raise RuntimeError("Gömme cevabı eksik")
        return v


async def gomme_tamamla() -> int:
    """Vektörü olmayan (ya da eski modelle üretilmiş) parçaları gömer. Model yoksa 0 döner, BM25 yine çalışır."""
    from . import llm

    model = gomme_modeli()
    with _kilit:
        kalan = _db().execute("SELECT COUNT(*) FROM parcalar WHERE vektor IS NULL OR gomme_modeli IS NOT ?",
                              (model,)).fetchone()[0]
    if not kalan:
        _gomme["hazir"] = True
        return 0
    if time.time() - _gomme["son_hata"] < 300 and _gomme["son_hata"]:
        return 0
    if not await _gomme_modeli_hazirla():
        _gomme.update(hazir=False, son_hata=time.time())
        return 0
    global _surum
    yapilan, atla = 0, set()
    while True:
        await llm.arka_plan_sirasi()
        with _kilit:
            satirlar = _db().execute(
                "SELECT id, metin FROM parcalar WHERE (vektor IS NULL OR gomme_modeli IS NOT ?) ORDER BY id LIMIT ?",
                (model, TOPLU + len(atla))).fetchall()
        satirlar = [s for s in satirlar if s["id"] not in atla][:TOPLU]
        if not satirlar:
            break
        _islem["mesaj"] = f"Kütüphane anlam dizini hazırlanıyor ({yapilan}/{kalan} parça)"
        try:
            vek = await _gom([s["metin"] for s in satirlar])
            sonuc = list(zip(satirlar, vek))
        except Exception as e:
            log.warning("toplu gömme başarısız, tek tek deneniyor: %s", e)
            sonuc = []
            for s in satirlar:
                try:
                    sonuc.append((s, (await _gom([s["metin"]]))[0]))
                except Exception:
                    atla.add(s["id"])
            if not sonuc:
                _gomme.update(hazir=False, son_hata=time.time(), mesaj="Gömme yapılamadı; kelime aramasıyla çalışıyor.")
                break
        with _kilit:
            c = _db()
            c.execute("BEGIN")
            c.executemany("UPDATE parcalar SET vektor=?, gomme_modeli=? WHERE id=?",
                          [(v.astype(np.float32).tobytes(), model, s["id"]) for s, v in sonuc])
            c.execute("COMMIT")
            _surum += 1
        yapilan += len(sonuc)
    if yapilan:
        _gomme.update(hazir=True, mesaj="")
    _islem["mesaj"] = ""
    return yapilan


async def isle_hepsi() -> None:
    """Bekleyen dosyaları işler, ardından gömmeleri tamamlar (testler ve işleyici döngüsü kullanır)."""
    await isle_bekleyenler()
    _islem["aktif"] = True
    try:
        await gomme_tamamla()
    finally:
        _islem["aktif"] = False


def _durt() -> None:
    ev, gorev = _uyandir, _gorev
    if ev is None or gorev is None or gorev.done():
        return
    try:
        gorev.get_loop().call_soon_threadsafe(ev.set)
    except RuntimeError:
        pass


async def _dongu() -> None:
    global _uyandir
    _uyandir = asyncio.Event()
    with _kilit:  # kapanırken yarıda kalanlar baştan işlenir
        _db().execute("UPDATE kaynaklar SET durum='bekliyor' WHERE durum='isleniyor'")
    while True:
        _uyandir.clear()  # işten ÖNCE sıfırla: iş sürerken gelen sinyal kaybolmasın
        try:
            await isle_hepsi()
        except Exception:
            log.exception("kütüphane işleyici hatası")
        with _kilit:
            bekleyen = _db().execute("SELECT 1 FROM kaynaklar WHERE durum='bekliyor' LIMIT 1").fetchone()
        if bekleyen and not _uyandir.is_set():
            await asyncio.sleep(1)  # iş sırasında eklenen kaynak var: beklemeden devam
            continue
        try:
            await asyncio.wait_for(_uyandir.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass


def baslat_isleyici() -> None:
    """Uygulama açılışında: arka plan işleyiciyi başlatır (zaten çalışıyorsa bir şey yapmaz)."""
    global _gorev
    if _gorev and not _gorev.done():
        return
    try:
        _gorev = asyncio.get_event_loop().create_task(_dongu())
    except RuntimeError:
        log.warning("kütüphane işleyici başlatılamadı (olay döngüsü yok)")


def gomme_baslat_arka_planda() -> None:
    """yerel.hazirla() sonrası: kütüphanede kaynak varsa gömme modelini indirip eksikleri tamamlar."""
    _gomme["son_hata"] = 0.0
    _durt()


# ================================================================ arama
def _fts_sorgu(sorgu: str) -> str:
    gor, tok = set(), []
    for t in re.findall(r"\w+", katla(sorgu)):
        if len(t) > 1 and t not in DURAK and t not in gor:
            gor.add(t)
            tok.append(t)
        if len(tok) >= 16:
            break
    return " OR ".join(f'"{t}"*' if len(t) >= 4 else f'"{t}"' for t in tok)


def _bm25(c: sqlite3.Connection, sorgu: str, limit: int = 50) -> list[tuple[int, float]]:
    q = _fts_sorgu(sorgu)
    if not q:
        return []
    if _fts_var:
        try:
            return [(r[0], -r[1]) for r in c.execute(
                "SELECT rowid, bm25(fts) AS s FROM fts WHERE fts MATCH ? ORDER BY s LIMIT ?", (q, limit))]
        except sqlite3.OperationalError:
            log.warning("FTS sorgusu çalışmadı: %r", q)
            return []
    # FTS5 yoksa: kaba kelime sayımı (yavaş ama çalışır)
    toks = [t.strip('"*') for t in q.split(" OR ")]
    skor = []
    for r in c.execute("SELECT id, metin FROM parcalar"):
        m = katla(r[1])
        s = sum(m.count(t) for t in toks)
        if s:
            skor.append((r[0], float(s)))
    skor.sort(key=lambda x: -x[1])
    return skor[:limit]


def _matris_al() -> dict:
    model = gomme_modeli()
    with _kilit:
        if _matris["surum"] == _surum and _matris["model"] == model:
            return dict(_matris)
        rows = _db().execute("SELECT id, kaynak_id, vektor FROM parcalar WHERE vektor IS NOT NULL AND gomme_modeli=?",
                             (model,)).fetchall()
        vek = [np.frombuffer(r[2], dtype=np.float32) for r in rows]
        boy = Counter(len(v) for v in vek).most_common(1)[0][0] if vek else 0
        sec = [(r[0], r[1], v) for r, v in zip(rows, vek) if len(v) == boy]
        yeni = dict(surum=_surum, model=model, ids=np.array([s[0] for s in sec], dtype=np.int64),
                    kaynak=[s[1] for s in sec], M=np.vstack([s[2] for s in sec]) if sec else None)
        _matris.clear()
        _matris.update(yeni)  # okuyanlar kendi kopyasını (dict(...)) tutar; eski M/ids dizileri değişmez
        return dict(yeni)


_sorgu_hata = {"zaman": 0.0}


def _sorgu_vektoru(sorgu: str) -> np.ndarray | None:
    if time.time() - _sorgu_hata["zaman"] < 60:
        return None
    try:
        r = httpx.post(f"{_host()}/api/embed", json={"model": gomme_modeli(), "input": [SORGU_TALIMATI + sorgu[:2000]],
                                                     "truncate": True, "keep_alive": "5m"}, timeout=15)
        r.raise_for_status()
        v = _vektorler(r.json())
        return v[0] if v else None
    except Exception:
        _sorgu_hata["zaman"] = time.time()
        return None


def ara(sorgu: str, ders_kodu: str | None = None, k: int = 8, tur: str | None = None) -> list[dict]:
    """Hibrit arama (BM25 + anlam benzerliği, RRF). Her öğe: metin, kaynak_id, baslik, yazar, yil, sayfa, tur, skor."""
    sorgu = (sorgu or "").strip()
    if not sorgu:
        return []
    with _kilit:
        c = _db()
        if c.execute("SELECT 1 FROM parcalar LIMIT 1").fetchone() is None:
            return []
        kaynaklar = {r["id"]: dict(r) for r in c.execute(
            "SELECT id, baslik, yazar, yil, tur, dersler, eklenme FROM kaynaklar WHERE durum='hazir'")}
        bm = _bm25(c, sorgu)
    if tur:
        kaynaklar = {i: r for i, r in kaynaklar.items() if r["tur"] == tur}
    # ders önceliği: o derse etiketli ×1.5, etiketsiz ×1, başka derse etiketli ×0.7
    hedef = _ders_anahtari(ders_kodu) if ders_kodu else ""
    agirlik = {}
    for i, r in kaynaklar.items():
        ds = {_ders_anahtari(x) for x in json.loads(r["dersler"] or "[]")}
        agirlik[i] = 1.0 if not hedef or not ds else (1.5 if hedef in ds else 0.7)

    kosinus: dict[int, float] = {}
    vek_liste: list[int] = []
    mt = _matris_al()
    if mt["M"] is not None and len(mt["ids"]):
        q = _sorgu_vektoru(sorgu)
        if q is not None and q.shape[0] == mt["M"].shape[1]:
            s = mt["M"] @ q
            maske = np.array([kid in kaynaklar for kid in mt["kaynak"]])
            s = np.where(maske, s, -1.0)
            for j in np.argsort(-s)[:50]:
                if s[j] < VEK_ESIK:
                    break
                pid = int(mt["ids"][j])
                kosinus[pid] = float(s[j])
                vek_liste.append(pid)
    if not bm and (not kosinus or max(kosinus.values()) < YALNIZ_VEK_ESIK):
        return []
    with _kilit:
        adaylar = set(p for p, _ in bm) | set(vek_liste)
        if not adaylar:
            return []
        rows = {r["id"]: dict(r) for r in _db().execute(
            f"SELECT id, kaynak_id, sira, sayfa, bolum, metin FROM parcalar WHERE id IN ({','.join('?' * len(adaylar))})",
            list(adaylar))}
    if not kosinus:
        # yalnız BM25 (gömme yok): en iyi skorun %40'ının altını ve tek kelimelik zayıf eşleşmeleri ele
        gecerli = [x for x in bm if x[0] in rows and rows[x[0]]["kaynak_id"] in kaynaklar]
        if not gecerli:
            return []
        ust = max(sk for _, sk in gecerli)
        jt = [t.strip('"*') for t in _fts_sorgu(sorgu).split(" OR ")]
        if len(jt) >= 2:
            def _eslesen(pid):
                m = katla(rows[pid]["metin"])
                return sum(1 for t in jt if t and t in m)
            bm = [x for x in gecerli if x[1] >= 0.4 * ust and _eslesen(x[0]) >= 2]
        else:
            bm = [x for x in gecerli if x[1] >= 0.4 * ust]
        if not bm:
            return []
    rrf: dict[int, float] = {}
    for sira, (pid, _) in enumerate([x for x in bm if x[0] in rows and rows[x[0]]["kaynak_id"] in kaynaklar], 1):
        rrf[pid] = rrf.get(pid, 0) + 1 / (60 + sira)
    for sira, pid in enumerate(vek_liste, 1):
        rrf[pid] = rrf.get(pid, 0) + 1 / (60 + sira)
    for pid in rrf:
        rrf[pid] *= agirlik.get(rows[pid]["kaynak_id"], 1.0)
    sayac: Counter = Counter()
    out = []
    # tek kaynaklı kütüphanede k kadar parçaya izin ver; çoksa kaynak başına KAYNAK_BASINA
    kaynak_sinir = max(KAYNAK_BASINA, -(-k // max(1, len(kaynaklar))))
    for pid in sorted(rrf, key=lambda p: -rrf[p]):
        p = rows[pid]
        if sayac[p["kaynak_id"]] >= kaynak_sinir:
            continue
        sayac[p["kaynak_id"]] += 1
        kr = kaynaklar[p["kaynak_id"]]
        out.append({"metin": p["metin"], "kaynak_id": p["kaynak_id"], "baslik": kr["baslik"], "yazar": kr["yazar"] or "",
                    "yil": kr["yil"], "sayfa": p["sayfa"], "bolum": p["bolum"] or "", "tur": kr["tur"],
                    "skor": round(rrf[pid], 6), "yeni": kr["tur"] == "makale" and time.time() - (kr["eklenme"] or 0) < 60 * 86400
                            and bool(kr["yil"]) and kr["yil"] >= time.localtime().tm_year - 1})
        if len(out) >= k:
            break
    return out


def rastgele_parcalar(n: int = 30, en_az: int = 300) -> list[dict]:
    """Hazır kaynaklardan rastgele parçalar (kendi kendine çalışma için): metin, baslik, sayfa, dersler."""
    with _kilit:
        rows = _db().execute(
            "SELECT p.id, p.sayfa, p.metin, k.baslik, k.dersler FROM parcalar p JOIN kaynaklar k ON k.id=p.kaynak_id "
            "WHERE k.durum='hazir' AND length(p.metin) >= ? ORDER BY RANDOM() LIMIT ?", (en_az, n)).fetchall()
    return [{"id": r["id"], "sayfa": r["sayfa"], "metin": r["metin"], "baslik": r["baslik"],
             "dersler": json.loads(r["dersler"] or "[]")} for r in rows]


def son_eklenenler(gun: int = 7, turler: tuple[str, ...] = ("makale", "haber"), limit: int = 40) -> list[dict]:
    """Son `gun` günde eklenen hazır kaynaklar (yeni önce): id, baslik, yazar, yil, tur, url, ozet, eklenme."""
    esik = time.time() - gun * 86400
    yer = ",".join("?" * len(turler))
    with _kilit:
        rows = _db().execute(
            f"SELECT id, baslik, yazar, yil, tur, url, ozet, dersler, eklenme FROM kaynaklar WHERE durum='hazir' "
            f"AND eklenme>=? AND tur IN ({yer}) ORDER BY eklenme DESC LIMIT ?", (esik, *turler, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["dersler"] = json.loads(d.get("dersler") or "[]")
        out.append(d)
    return out


def atif(s: dict) -> str:
    """Kısa kaynak gösterimi: 'Montgomery, İstatistiksel Kalite Kontrol (2019), s.45'."""
    ad = s.get("baslik") or "Kaynak"
    yazar = (s.get("yazar") or "").split(",")[0].strip()
    t = f"{yazar}, {ad}" if yazar else ad
    if s.get("yil"):
        t += f" ({s['yil']})"
    if s.get("sayfa"):
        t += f", s.{s['sayfa']}"
    elif s.get("bolum"):
        t += f", {s['bolum']}"
    return t


def kaynak_metni(sonuclar: list[dict], butce: int) -> str:
    """Sistem talimatına girecek kaynak bölümleri (karakter bütçesini aşmaz). Sonuç yoksa ''."""
    if not sonuclar or butce < 300:
        return ""
    parcalar, kalan = [], butce
    for i, s in enumerate(sonuclar, 1):
        bas = f"[{i}] {atif(s)} — {s.get('tur') or 'kaynak'}{' (YENİ MAKALE: güncel gelişme)' if s.get('yeni') else ''}\n"
        if kalan - len(bas) < 120:
            break
        metin = s["metin"][: kalan - len(bas) - 2]
        parcalar.append(bas + metin)
        kalan -= len(bas) + len(metin) + 2
    return "\n\n".join(parcalar)[:butce]


def ifade_say(ifadeler: list[str], en_fazla: int = 200) -> int:
    """Verilen ifadelerden (tam ifade eşleşmesi) herhangi birini içeren, hazır kaynaklardaki parça sayısı."""
    q = []
    for f in ifadeler:
        tok = [t for t in re.findall(r"\w+", katla(f)) if t]
        if tok:
            q.append('"' + " ".join(tok) + '"')
    if not q:
        return 0
    with _kilit:
        c = _db()
        try:
            if _fts_var:
                return int(c.execute(
                    "SELECT COUNT(*) FROM (SELECT f.rowid FROM fts f JOIN parcalar p ON p.id=f.rowid "
                    "JOIN kaynaklar k ON k.id=p.kaynak_id WHERE fts MATCH ? AND k.durum='hazir' LIMIT ?)",
                    (" OR ".join(q), en_fazla)).fetchone()[0])
        except sqlite3.OperationalError:
            log.warning("FTS ifade sorgusu çalışmadı: %r", q)
            return 0
        n = 0
        ifs = [katla(f) for f in ifadeler if f.strip()]
        for r in c.execute("SELECT p.metin FROM parcalar p JOIN kaynaklar k ON k.id=p.kaynak_id WHERE k.durum='hazir'"):
            m = katla(r[0])
            if any(i in m for i in ifs):
                n += 1
                if n >= en_fazla:
                    break
        return n
