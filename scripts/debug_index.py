# -*- coding: utf-8 -*-
import re
import urllib.request

def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "pip/24.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

html = fetch("https://pypi.tuna.tsinghua.edu.cn/simple/pymupdf/").decode("utf-8", errors="replace")
print("len:", len(html))
links = re.findall(r'href=["\']?([^"\'>\s]+)', html)
print("total links:", len(links))
for l in links[:10]:
    print(l)
print("...")
for l in links[-8:]:
    print(l)
