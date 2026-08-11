"""Every model in the archive: bones, meshes, decoded geometry bounds, and the
textures its .mrl references. Used to work out which models draw the book.

  UMVC3_ARC
"""
import sys, os, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
ver, entries = M.read_arc(ARC)
by = {}
for e in entries:
    by.setdefault(e.name, {})[e.ext] = e

print("%-26s %5s %6s %7s   %-34s %-34s" %
      ("model", "bones", "meshes", "verts", "x / y / z min", "x / y / z max"))
for name in sorted(by):
    x = by[name]
    if "mod" not in x:
        continue
    b = x["mod"].data
    if b[:4] != b"MOD\0":
        continue
    lo, hi = M.mod_geometry_bounds(b)
    print("%-26s %5d %6d %7d   %-34s %-34s" % (
        name.rsplit("\\", 1)[-1], M._u16(b, 0x06), M._u16(b, M.H_MESHCOUNT),
        M._u32(b, 0x0C),
        "%8.1f %8.1f %8.1f" % lo, "%8.1f %8.1f %8.1f" % hi))

print()
print("textures referenced per model:")
for name in sorted(by):
    x = by[name]
    if "mrl" not in x:
        continue
    try:
        info = M.parse_mrl_bytes(x["mrl"].data)
    except Exception as e:
        print("  %-26s (mrl parse failed: %s)" % (name.rsplit("\\", 1)[-1], e))
        continue
    tex = info[0] if isinstance(info, tuple) else info
    names = []
    for t in (tex or []):
        s = t if isinstance(t, str) else (t.get("path") if isinstance(t, dict) else str(t))
        names.append(s.rsplit("\\", 1)[-1].rsplit("/", 1)[-1])
    print("  %-26s %s" % (name.rsplit("\\", 1)[-1], ", ".join(names[:8])))
