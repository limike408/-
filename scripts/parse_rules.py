# -*- coding: utf-8 -*-
"""Parse the competition rule PDFs."""
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\NAE\Desktop\数学建模\2026\python_libs")
import pymupdf  # noqa: E402

BASE = Path(r"C:\Users\NAE\Desktop\数学建模\2026")
OUT = BASE / "parsed"

targets = [
    BASE / "全国大学生数学建模竞赛人工智能工具使用规定 （2026年试行）.pdf",
    BASE / "全国大学生数学建模竞赛系统使用手册-学生账号.pdf",
    BASE / "论文格式规范.pdf",
]
for pdf in targets:
    if not pdf.exists():
        print(f"missing: {pdf.name}")
        continue
    out_path = OUT / (pdf.stem.split(" ")[0][:12] + ".txt")
    doc = pymupdf.open(str(pdf))
    parts = []
    for i, page in enumerate(doc):
        parts.append(f"\n===== 第 {i+1} 页 =====\n")
        parts.append(page.get_text("text"))
    out_path.write_text("".join(parts), encoding="utf-8")
    print(f"{pdf.name}: {len(doc)} pages -> {out_path.name}")
print("DONE")
