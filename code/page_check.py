# -*- coding: utf-8 -*-
"""统计 main.pdf 各章节页码分布。"""
import PyPDF2, re

r = PyPDF2.PdfReader(r'E:\desktop\2026建模\C题\paper\main.pdf')
print('总页数:', len(r.pages))
marks = ['摘  要', '摘要', '问题重述', '问题分析', '模型假设', '符号说明',
         '模型建立与求解', '模型检验与分析', '模型评价与推广', '参考文献',
         '人工智能工具使用声明', '附录']
for i, p in enumerate(r.pages, 1):
    t = p.extract_text() or ''
    t1 = re.sub(r'\s+', ' ', t)[:120]
    hits = [m for m in marks if m in t[:200]]
    print(f'p{i:>2} | {" ".join(hits):<16} | {t1[:70]}')