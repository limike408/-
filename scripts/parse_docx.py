# -*- coding: utf-8 -*-
"""Extract text from B题 docx attachments using zipfile."""
import re
import zipfile
from pathlib import Path

BASE = Path(r"C:\Users\NAE\Desktop\数学建模\2026")
DOCS = BASE / "docs" / "B题" / "附件"
OUT = BASE / "parsed"
OUT.mkdir(exist_ok=True)

files = [p for p in sorted(DOCS.glob("*.docx")) if not p.name.startswith("~$")]
for docx_path in files:
    out_path = OUT / ("B_" + docx_path.stem + ".txt")
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    # paragraphs
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)
    lines = []
    for p in paras:
        texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)
        line = "".join(texts).strip()
        if line:
            lines.append(line)
    text = "\n".join(lines)
    out_path.write_text(text, encoding="utf-8")
    print(f"{docx_path.name}: {len(lines)} lines -> {out_path}", flush=True)
print("DONE", flush=True)
