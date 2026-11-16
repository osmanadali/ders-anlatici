import os
import sys
import tempfile
from pathlib import Path

# Testler gerçek veri klasörüne dokunmasın, API anahtarı gerekmesin.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ders_test_")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ELEVENLABS_API_KEY", "test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_text_pdf(pages: list[str]) -> bytes:
    """Metin katmanlı küçük bir PDF üretir (harici kütüphane gerektirmeden)."""
    objs = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    font_id = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        content = f"BT /F1 14 Tf 50 750 Td ({text}) Tj ET"
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>"
        )
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = "%PDF-1.4\n"
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{n} 0 obj\n{o}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")
