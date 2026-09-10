# -*- coding: utf-8 -*-
"""Download pymupdf wheel from Tsinghua mirror and manually extract to user site-packages."""
import re
import sys
import zipfile
import urllib.request
from pathlib import Path

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple/pymupdf/"
BASE = Path(r"C:\Users\NAE\Desktop\数学建模\2026")
WHEEL_DIR = BASE / "wheels"
WHEEL_DIR.mkdir(exist_ok=True)

def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "pip/24.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

print("1. Fetching index page ...", flush=True)
html = fetch(MIRROR).decode("utf-8", errors="replace")
hrefs = re.findall(r'href=["\']?([^"\'>\s]+)', html)
# strip #sha256 suffix, keep only win_amd64 wheels
wheels = [h.split("#")[0] for h in hrefs if "win_amd64.whl" in h]
# prefer abi3 (works on py313)
abi3 = [h for h in wheels if "abi3" in h]
candidates = abi3 or wheels
if not candidates:
    print("No wheel found!", flush=True)
    sys.exit(1)
# take the latest (last in list)
wheel_url = candidates[-1]
if not wheel_url.startswith("http"):
    from urllib.parse import urljoin
    wheel_url = urljoin(MIRROR, wheel_url)
wheel_name = wheel_url.split("/")[-1]
print(f"2. Downloading {wheel_name} ...", flush=True)
data = fetch(wheel_url)
wheel_path = WHEEL_DIR / wheel_name
wheel_path.write_bytes(data)
print(f"   Saved {len(data)} bytes -> {wheel_path}", flush=True)

print("3. Extracting to workspace python_libs ...", flush=True)
target = BASE / "python_libs"
target.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(wheel_path) as zf:
    names = zf.namelist()
    print(f"   {len(names)} entries in wheel", flush=True)
    zf.extractall(target)
print("4. Verify:", flush=True)
sys.path.insert(0, str(target))
try:
    import fitz
    print("   fitz version:", fitz.version, flush=True)
    print("SUCCESS", flush=True)
except Exception as e:
    print("   import failed:", repr(e), flush=True)
