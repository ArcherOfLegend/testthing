"""The bone lattice is stored as explicit float matrices, so it is a fixed ruler
in engine space. Sweep the dequantisation scale and offset and see which values
put the cards where their skin weights say they are. Whatever wins is what the
engine uses.

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
mn, mx, ext = M.read_bbox(b)
vbase = M._u64(b, 0x48)
nb = M._u16(b, 0x06)
boff = M._u64(b, 0x28)
inv = boff + nb * 24 + nb * 64
S0 = max(abs(v) for v in struct.unpack_from("<3f", b, inv))
loc = boff + nb * 24
parent = [b[boff + i * 24 + 1] for i in range(nb)]


def mul(a, c):
    out = [0.0] * 16
    for r in range(4):
        for k in range(4):
            out[r * 4 + k] = sum(a[r * 4 + j] * c[j * 4 + k] for j in range(4))
    return out


mats = [struct.unpack_from("<16f", b, loc + i * 64) for i in range(nb)]
world = []
for i in range(nb):
    chain, j = [], i
    while j != 255:
        chain.append(j)
        j = parent[j]
    w = mats[chain[0]]
    for j in chain[1:]:
        w = mul(w, mats[j])
    world.append(w)
bpos = [(world[i][12], world[i][13], world[i][14]) for i in range(nb)]
xs = sorted({round(bpos[i][0], 1) for i in range(1, nb)})
ys = sorted({round(bpos[i][1], 1) for i in range(1, nb)})
at = {(round(bpos[i][0], 1), round(bpos[i][1], 1)): i for i in range(1, nb)}


def bilinear(p):
    def span(v, pl):
        for a, c in zip(pl, pl[1:]):
            if a <= v <= c:
                return a, c, (v - a) / (c - a)
        return (pl[0], pl[1], 0.0) if v < pl[0] else (pl[-2], pl[-1], 1.0)
    x0, x1, tx = span(p[0], xs)
    y0, y1, ty = span(p[1], ys)
    o = {}
    for bx, wx in ((x0, 1 - tx), (x1, tx)):
        for by, wy in ((y0, 1 - ty), (y1, ty)):
            o[at[(bx, by)]] = o.get(at[(bx, by)], 0.0) + wx * wy
    return o


samples = []
for m in M.read_meshes(b):
    if m["stride"] != 40:
        continue
    for k in range(m["nverts"]):
        o = vbase + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
        raw = struct.unpack_from("<3H", b, o)
        w = [M._u16(b, o + 6) / 32767.0] + [b[o + 12 + j] / 255.0 for j in range(4)] \
            + [M._half(b, o + 28), M._half(b, o + 30)]
        idx = [b[o + 16 + j] for j in range(8)]
        act = {}
        for i, v in zip(idx, w):
            if v:
                act[i] = act.get(i, 0.0) + v
        act.pop(0, None)
        t = sum(act.values())
        if t:
            samples.append((raw, {k2: v / t for k2, v in act.items()}))


def err(sx, sy):
    tot = 0.0
    for raw, act in samples:
        p = (mn[0] + raw[0] / M.POS_SCALE * sx, mn[1] + raw[1] / M.POS_SCALE * sy)
        pr = bilinear(p)
        tot += sum(abs(pr.get(k, 0.0) - act.get(k, 0.0)) for k in set(pr) | set(act))
    return tot / len(samples)


print("invBind scale S = %.3f   bbox ext = (%.3f, %.3f, %.3f)" % ((S0,) + ext))
print()
print("candidate scales, applied to both axes:")
for name, s in (("bbox ext per-axis", None), ("max(ext)", max(ext)),
                ("bbox diagonal", sum(v * v for v in ext) ** 0.5),
                ("invBind S", S0), ("S * 0.9", S0 * 0.9), ("S * 1.1", S0 * 1.1)):
    if s is None:
        print("  %-20s -> %.4f" % (name, err(ext[0], ext[1])))
    else:
        print("  %-20s %8.3f -> %.4f" % (name, s, err(s, s)))

print()
print("independent sweep of the x and y scales (mean L1 weight error):")
best = None
for sx in range(300, 1300, 25):
    row = []
    for sy in range(300, 1300, 25):
        v = err(float(sx), float(sy))
        row.append(v)
        if best is None or v < best[0]:
            best = (v, sx, sy)
print("  best on a 25-unit grid: sx=%d sy=%d err=%.4f" % (best[1], best[2], best[0]))
fine = None
for sx in range(best[1] - 30, best[1] + 31, 5):
    for sy in range(best[2] - 30, best[2] + 31, 5):
        v = err(float(sx), float(sy))
        if fine is None or v < fine[0]:
            fine = (v, sx, sy)
print("  refined:                sx=%d sy=%d err=%.4f" % (fine[1], fine[2], fine[0]))
