"""API anahtarı olmadan arayüzü denemek için: sahte Claude/ElevenLabs ile sunucuyu başlatır.

    python tests/demo_server.py   →  http://localhost:8765
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ders_demo_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

import fakes  # noqa: E402
from app import main, notes  # noqa: E402
from conftest import make_text_pdf  # noqa: E402

fakes.install()
if not notes.list_courses():
    c = notes.create_course("Matematik 1 (demo)")
    notes.add_document(c["id"], "hafta1.pdf", make_text_pdf([
        "Ikinci derece fonksiyonlar: f(x)=ax^2+bx+c, parabol ve tepe noktasi",
        "Turev kurallari: carpim, bolum ve zincir kurali ornekleri",
    ]))

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(os.getenv("PORT", "8765")), log_level="warning")
