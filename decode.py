"""Which dequantisation does the engine use?

The tools assume  p = bbmin + raw/32767 * ext   (per axis).
invBind[0] factors as  scale(784.98) . translate(bbmin), which implies
             p = bbmin + raw/32767 * 784.98    (uniform).

Both put the model inside its box, so the discriminators are:
  * raw range - whichever decode makes the header box tight is the real one;
  * the lattice - each card should be driven by the four control points of the
    cell that encloses it, and only the correct decode puts it in that cell.

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
uni = max(abs(v) for v in struct.unpack_from("<3f", b, inv))

meshes = [m for m in M.read_meshes(b) if m["stride"] == 40]
raws = []
for m in meshes:
    for k in range(m["nverts"]):
        o = vbase + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
        raws.append((o, struct.unpack_from("<3H", b, o)))

print("bbox min %s  max %s  ext %s" % (
    tuple(round(v, 3) for v in mn), tuple(round(v, 3) for v in mx),
    tuple(round(v, 3) for v in ext)))
print("uniform scale from invBind[0]: %.3f" % uni)
print()
print("raw range over %d vertices:" % len(raws))
for i, ax in enumerate("xyz"):
    lo = min(r[1][i] for r in raws)
    hi = max(r[1][i] for r in raws)
    print("  %s  %6d .. %6d    tight-if-per-axis needs 0..32767"
          "    tight-if-uniform needs 0..%d" % (ax, lo, hi, round(ext[i] / uni * 32767)))
print()

# --- bone geometry -----------------------------------------------------------
def bone_world():
    loc = boff + nb * 24
    mats = [struct.unpack_from("<16f", b, loc + i * 64) for i in range(nb)]
    parent = [b[boff + i * 24 + 1] for i in range(nb)]

    def mul(a, c):                       # row-vector: a then c
        out = [0.0] * 16
        for r in range(4):
            for k in range(4):
                out[r * 4 + k] = sum(a[r * 4 + j] * c[j * 4 + k] for j in range(4))
        return out

    world = [None] * nb
    for i in range(nb):
        chain, j = [], i
        while j != 255:
            chain.append(j)
            j = parent[j]
        w = mats[chain[0]]
        for j in chain[1:]:
            w = mul(w, mats[j])
        world[i] = w
    return world

W = bone_world()
bpos = [(W[i][12], W[i][13], W[i][14]) for i in range(nb)]
print("bone world positions:")
for i in range(nb):
    print("  %2d  (%9.3f, %9.3f, %9.3f)" % ((i,) + bpos[i]))
print()

# --- per-mesh: enclosing cell vs the bones actually used ---------------------
def dec_axis(raw):
    return tuple(mn[i] + raw[i] / M.POS_SCALE * ext[i] for i in range(3))


def dec_uni(raw):
    return tuple(mn[i] + raw[i] / M.POS_SCALE * uni for i in range(3))


xs = sorted({round(bpos[i][0], 1) for i in range(1, nb)})
ys = sorted({round(bpos[i][1], 1) for i in range(1, nb)})
print("lattice x planes %s" % xs)
print("lattice y planes %s" % ys)
bone_at = {}
for i in range(1, nb):
    bone_at[(round(bpos[i][0], 1), round(bpos[i][1], 1))] = i


def cell(p):
    """the four lattice bones bracketing p, or None outside"""
    def brk(v, planes):
        lo = [q for q in planes if q <= v]
        hi = [q for q in planes if q >= v]
        if not lo or not hi:
            return None
        return max(lo), min(hi)
    bx, by = brk(p[0], xs), brk(p[1], ys)
    if bx is None or by is None:
        return None
    return {bone_at[(x, y)] for x in set(bx) for y in set(by)}


print()
print("%5s %-24s %-22s %-22s" % ("mesh", "top-4 bones by weight", "cell (per-axis)", "cell (uniform)"))
score_axis = score_uni = 0
for m in meshes:
    use = {}
    cxa = [0.0, 0.0]
    cxu = [0.0, 0.0]
    for k in range(m["nverts"]):
        o = vbase + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
        raw = struct.unpack_from("<3H", b, o)
        pa, pu = dec_axis(raw), dec_uni(raw)
        cxa[0] += pa[0]; cxa[1] += pa[1]
        cxu[0] += pu[0]; cxu[1] += pu[1]
        w = [M._u16(b, o + 6) / 32767.0] + [b[o + 12 + j] / 255.0 for j in range(4)]
        idx = [b[o + 16 + j] for j in range(5)]
        for j in range(5):
            if w[j]:
                use[idx[j]] = use.get(idx[j], 0.0) + w[j]
    n = m["nverts"]
    ca = (cxa[0] / n, cxa[1] / n)
    cu = (cxu[0] / n, cxu[1] / n)
    top = {i for i, _ in sorted(use.items(), key=lambda kv: -kv[1])[:4]}
    ka, ku = cell(ca), cell(cu)
    score_axis += (ka == top)
    score_uni += (ku == top)
    print("%5d %-24s %-22s %-22s   c_axis(%7.1f,%7.1f) c_uni(%7.1f,%7.1f)" % (
        m["index"], sorted(top), sorted(ka) if ka else "-", sorted(ku) if ku else "-",
        ca[0], ca[1], cu[0], cu[1]))

print()
print("cell matches: per-axis %d/%d, uniform %d/%d" % (
    score_axis, len(meshes), score_uni, len(meshes)))

# --- weight layout sanity ----------------------------------------------------
bad = 0
worst = 0.0
for m in meshes:
    for k in range(m["nverts"]):
        o = vbase + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
        s = M._u16(b, o + 6) / 32767.0 + sum(b[o + 12 + j] for j in range(4)) / 255.0
        worst = max(worst, abs(s - 1.0))
        if abs(s - 1.0) > 0.01:
            bad += 1
print("weights = u16@+6 + 4x u8@+12: %d/%d vertices off by >1%%, worst %.4f"
      % (bad, sum(m["nverts"] for m in meshes), worst))
