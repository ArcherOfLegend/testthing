"""Two questions:

1. Is the bone section shared across the card models, or does each one encode
   its own bounding box?  invBind[0] looked like scale(784.98) . translate(bbmin)
   for face_a; if that holds per-model the engine reads the stored matrices, if
   the section is byte-identical across models with different boxes it is stale
   authoring data and the runtime rebuilds from the local matrices.
2. What is the real stride-40 vertex layout?  The remap only accepts raw bone
   indices 10..26, but bonemap.py reported 0/7/8 at +16, so +16 is not the index
   field.

  UMVC3_ARC
"""
import sys, os, struct, hashlib

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
ver, entries = M.read_arc(ARC)

print("=== bone sections ===")
print("%-28s %5s  %-42s %-24s %s" % ("model", "bones", "bbmin", "invBind0 t", "section sha1"))
ref = None
for e in entries:
    if e.ext != "mod":
        continue
    b = e.data
    n = M._u16(b, 0x06)
    if not n:
        continue
    off = M._u64(b, 0x28)
    end = off + n * 24 + n * 128 + 256
    sec = b[off:end]
    mn, mx, ext = M.read_bbox(b)
    inv = off + n * 24 + n * 64
    t = struct.unpack_from("<3f", b, inv + 48)
    r0 = struct.unpack_from("<3f", b, inv)
    scale = max(abs(v) for v in r0)
    print("%-28s %5d  %-42s %-24s %s  scale %.3f" % (
        e.name.rsplit("\\", 1)[-1], n,
        "(%.3f, %.3f, %.3f)" % mn,
        "(%.1f, %.1f, %.1f)" % t,
        hashlib.sha1(sec).hexdigest()[:12], scale))

print()
print("=== stride-40 vertex bytes, chs_meku_face_a ===")
e = next(x for x in entries if x.ext == "mod" and x.name.endswith("chs_meku_face_a"))
b = e.data
vbase = M._u64(b, 0x48)
mn, mx, ext = M.read_bbox(b)
for m in M.read_meshes(b)[:2]:
    print("mesh %d fmt %d stride %d verts %d" % (m["index"], m["fmt"], m["stride"], m["nverts"]))
    for k in range(min(4, m["nverts"])):
        o = vbase + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
        raw = b[o:o + m["stride"]]
        pos = struct.unpack_from("<3h", b, o)
        world = tuple(mn[i] + pos[i] / M.POS_SCALE * ext[i] for i in range(3))
        print("   %s" % " ".join("%02X" % v for v in raw))
        print("     pos %s -> (%8.2f %8.2f %8.2f)  u16@6=%d" % (
            pos, world[0], world[1], world[2], M._u16(b, o + 6)))

print()
print("=== byte-column survey over every stride-40 vertex ===")
cols = {}
for m in M.read_meshes(b):
    if m["stride"] != 40:
        continue
    for k in range(m["nverts"]):
        o = vbase + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
        for c in range(40):
            cols.setdefault(c, set()).add(b[o + c])
for c in range(6, 40):
    v = sorted(cols[c])
    print("  +%02d  %d distinct: %s" % (c, len(v), v if len(v) <= 24 else "%s ... %s" % (v[:12], v[-6:])))
