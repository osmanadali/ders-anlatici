"""Oturum kayıtları (anlatımlar tekrar izlenebilsin diye) ve öğrenci hafızası."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from .config import DATA_DIR

SESSIONS_DIR = DATA_DIR / "kayitlar"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_FILE = DATA_DIR / "hafiza.json"

_lock = threading.Lock()


def _safe(sid: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{12}", sid or ""):
        raise ValueError("geçersiz oturum")
    return sid


def session_dir(sid: str) -> Path:
    return SESSIONS_DIR / _safe(sid)


def audio_path(sid: str, idx: int) -> Path:
    return session_dir(sid) / "ses" / f"{int(idx):04d}.mp3"


def new_session(course_id: str | None, title: str = "") -> dict:
    s = {
        "id": uuid.uuid4().hex[:12],
        "course_id": course_id,
        "title": title or "Yeni anlatım",
        "created": time.time(),
        "updated": time.time(),
        "messages": [],  # yapay zeka konuşma geçmişi
        "timeline": [],  # tekrar izleme için: kullanıcı mesajları + anlatım adımları
        "next_step": 0,
    }
    save_session(s)
    return s


def load_session(sid: str) -> dict | None:
    f = session_dir(sid) / "oturum.json"
    if not f.exists():
        return None
    return json.loads(f.read_text("utf-8"))


def save_session(s: dict) -> None:
    d = session_dir(s["id"])
    (d / "ses").mkdir(parents=True, exist_ok=True)
    s["updated"] = time.time()
    tmp = d / "oturum.json.tmp"
    tmp.write_text(json.dumps(s, ensure_ascii=False), "utf-8")
    tmp.replace(d / "oturum.json")


def list_sessions() -> list[dict]:
    out = []
    for d in SESSIONS_DIR.iterdir():
        f = d / "oturum.json"
        if not f.exists():
            continue
        try:
            s = json.loads(f.read_text("utf-8"))
        except json.JSONDecodeError:
            continue
        steps = sum(1 for t in s["timeline"] if t["type"] == "step")
        out.append({k: s.get(k) for k in ("id", "title", "course_id", "created", "updated")} | {"steps": steps})
    out.sort(key=lambda x: -x["updated"])
    return out


def delete_session(sid: str) -> None:
    import shutil

    shutil.rmtree(session_dir(sid), ignore_errors=True)


# ---------------------------------------------------------------- hafıza (zayıf konular)
def load_memory() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text("utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _save_memory(m: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), "utf-8")


def record_topic(course_id: str | None, topic: str, correct: bool | None, note: str = "") -> None:
    """Bir konuda doğru/yanlış ya da 'zorlandı' bilgisini kaydeder."""
    topic = (topic or "").strip()[:80]
    if not topic:
        return
    key = course_id or "genel"
    with _lock:
        m = load_memory()
        topics = m.setdefault(key, {}).setdefault("topics", {})
        t = topics.setdefault(topic, {"dogru": 0, "yanlis": 0, "zorlandi": 0, "son": 0, "not": ""})
        if correct is True:
            t["dogru"] += 1
        elif correct is False:
            t["yanlis"] += 1
        else:
            t["zorlandi"] += 1
        if note:
            t["not"] = note[:200]
        t["son"] = time.time()
        _save_memory(m)


def weak_topics(course_id: str | None, limit: int = 8) -> list[dict]:
    m = load_memory().get(course_id or "genel", {}).get("topics", {})
    rows = []
    for name, t in m.items():
        weakness = t["yanlis"] * 2 + t["zorlandi"] - t["dogru"]
        if weakness > 0:
            rows.append({"konu": name, "puan": weakness, **t})
    rows.sort(key=lambda r: -r["puan"])
    return rows[:limit]


def memory_summary(course_id: str | None) -> str:
    rows = weak_topics(course_id)
    if not rows:
        return ""
    lines = [
        f"- {r['konu']}: {r['yanlis']} yanlış, {r['dogru']} doğru, {r['zorlandi']} kez zorlandı"
        + (f" ({r['not']})" if r["not"] else "")
        for r in rows
    ]
    return "Öğrencinin bu derste zorlandığı konular (anlatırken bunlara özen göster):\n" + "\n".join(lines)
