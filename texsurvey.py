"""Header survey of the CE character portraits actually installed in the game.

  UMVC3_DIR   directory of loose .tex
  UMVC3_IDS   file with one CE character id per line
"""
import sys, os, struct
from collections import Counter

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

DIR = os.environ["UMVC3_DIR"]
IDS = os.environ["UMVC3_IDS"]
ids = [l.strip() for l in open(IDS) if l.strip()]

kinds = Counter()
rows = []
for cid in ids:
    path = os.path.join(DIR, "f_%s00_BM_HQ_NOMIP.tex" % cid)
    if not os.path.exists(path):
        rows.append((cid, "MISSING", 0, 0, 0, 0))
        kinds["missing"] += 1
        continue
    b = open(path, "rb").read()
    size = len(b)
    if len(b) < 24 or b[:4] != b"TEX\0":
        rows.append((cid, "not a TEX", size, 0, 0, 0))
        kinds["bad magic"] += 1
        continue
    v = M._u32(b, 8)
    mips, w, h = v & 0x3F, (v >> 6) & 0x1FFF, (v >> 19) & 0x1FFF
    fmt = (M._u32(b, 12) >> 8) & 0xFF
    rows.append((cid, "ok", size, fmt, w, h))
    kinds["fmt %d %dx%d mips %d" % (fmt, w, h, mips)] += 1

print("%-14s %-10s %9s %5s %5s %5s" % ("id", "state", "bytes", "fmt", "w", "h"))
for r in rows:
    print("%-14s %-10s %9d %5d %5d %5d" % r)
print()
for k, n in kinds.most_common():
    print("  %4d x  %s" % (n, k))
