"""Dump the bone section of a card model: descriptors, local and inverse-bind
matrices, and the 256-byte remap. Section layout (offset = u64 @ 0x28):

    descriptors (24 B each) | local mats (64) | inverse mats (64) | remap (256)

  UMVC3_ARC, UMVC3_MODEL
"""
import sys, os, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
NAME = os.environ.get("UMVC3_MODEL", "chs_meku_face_a")

ver, entries = M.read_arc(ARC)
e = next(x for x in entries if x.ext == "mod" and x.name.endswith(NAME))
b = e.data
n = M._u16(b, 0x06)
off = M._u64(b, 0x28)
loc = off + n * 24
inv = loc + n * 64
rem = inv + n * 64
print("%s: %d bones, section @ 0x%X (loc 0x%X inv 0x%X remap 0x%X)" % (NAME, n, off, loc, inv, rem))

print("\ndescriptors: idx parent mirror ?  scale   len   (24 bytes)")
for i in range(n):
    o = off + i * 24
    raw = b[o:o + 24]
    f = struct.unpack_from("<ff", b, o + 4)
    print("  %2d  bytes %-4s %-4s %-4s %-4s  f32 %10.3f %10.3f  pos %s"
          % (i, raw[0], raw[1], raw[2], raw[3], f[0], f[1],
             " ".join("%9.3f" % v for v in struct.unpack_from("<fff", b, o + 12))))

def mat(base, i):
    return struct.unpack_from("<16f", b, base + i * 64)

print("\nlocal matrices (row-major as stored):")
for i in range(n):
    m = mat(loc, i)
    print("  %2d  " % i + " | ".join(" ".join("%8.3f" % m[r * 4 + c] for c in range(4))
                                     for r in range(4)))

print("\ninverse-bind matrices:")
for i in range(n):
    m = mat(inv, i)
    print("  %2d  " % i + " | ".join(" ".join("%8.3f" % m[r * 4 + c] for c in range(4))
                                     for r in range(4)))

r = list(b[rem:rem + 256])
print("\nremap (non-255 entries): " + ", ".join("%d->%d" % (i, v) for i, v in enumerate(r) if v != 255))
