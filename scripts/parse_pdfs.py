# -*- coding: utf-8 -*-
"""Parse the three problem PDFs to text using pymupdf."""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\NAE\Desktop\数学建模\2026\python_libs")
import pymupdf  # noqa: E402

BASE = Path(r"C:\Users\NAE\Desktop\数学建模\2026")
DOCS = BASE / "docs"
OUT = BASE / "parsed"
OUT.mkdir(exist_ok=True)

for pdf in sorted(DOCS.rglob("*.pdf")):
    name = pdf.name
    out_path = OUT / (pdf.stem + ".txt")
    doc = pymupdf.open(str(pdf))
    print(f"[{name}] pages={len(doc)}", flush=True)
    parts = []
    for i, page in enumerate(doc):
        parts.append(f"\n===== 第 {i+1} 页 =====\n")
        parts.append(page.get_text("text"))
    text = "".join(parts)
    out_path.write_text(text, encoding="utf-8")
    print(f"  -> {out_path} ({len(text)} chars)", flush=True)
print("DONE", flush=True)
