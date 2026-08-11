"""Positive control for the bbox probe.

The header box turned out to be inert, which is only meaningful if the archive
is really being loaded. invBind factors as scale(S) . translate(bbmin), so
multiplying rows 0..2 of every inverse-bind matrix by k rescales the model to
k*S about the box corner. Do that to face_a only.

  left page shrinks   -> the archive is live and the inverse-bind matrices carry the decode
  nothing changes     -> the game is not reading this file and the bbox probe proved nothing

face_b keeps the +200 extent change as a second look at the per-axis theory.

  UMVC3_ARC, UMVC3_OUT, UMVC3_K (default 0.75)
"""
import sys, os, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC, OUT = os.environ["UMVC3_ARC"], os.environ["UMVC3_OUT"]
K = float(os.environ.get("UMVC3_K", "0.75"))
ver, entries = M.read_arc(ARC)

for e in entries:
    if e.ext != "mod":
        continue
    short = e.name.rsplit("\\", 1)[-1]
    if short not in ("chs_meku_face_a", "chs_meku_face_b"):
        continue
    b = bytearray(e.data)
    if short == "chs_meku_face_a":
        n = M._u16(b, 0x06)
        inv = M._u64(b, 0x28) + n * 24 + n * 64
        before = max(abs(v) for v in struct.unpack_from("<3f", b, inv))
        for i in range(n):
            for r in range(3):
                o = inv + i * 64 + r * 16
                v = struct.unpack_from("<4f", b, o)
                struct.pack_into("<4f", b, o, v[0] * K, v[1] * K, v[2] * K, v[3])
        after = max(abs(v) for v in struct.unpack_from("<3f", b, inv))
        print("chs_meku_face_a    invBind scale %.3f -> %.3f  (x%.2f, %d bones)"
              % (before, after, K, n))
    else:
        mn, mx, ext = M.read_bbox(bytes(b))
        struct.pack_into("<f", b, M.H_BBMAX + 4, mx[1] + 200.0)
        print("chs_meku_face_b    ext.y %.3f -> %.3f (unchanged control)" % (ext[1], ext[1] + 200))
    e.data = bytes(b)
    e.dirty = True

M.write_arc(OUT, ver, entries)
print("\nwrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
