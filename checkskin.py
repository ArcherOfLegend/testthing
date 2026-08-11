"""Find vertices whose refitted weights will fling them once the page curls.

At the bind pose skinning is the identity no matter what the weights are, so a
bad weight set is invisible in the geometry - it only shows when the lattice
animates. Model that with a per-bone world displacement d[j]: the skinned offset
of a vertex is sum(w[j] * d[j]), so comparing that against the offset the
bilinear lattice model predicts flags exactly the vertices that will fly off.

Using d[j] = bone position makes the metric a distance in game units: "how far
is this vertex's weighted bone centroid from where the lattice says it is".

  UMVC3_ARC, UMVC3_LIMIT (units, default 40)
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
LIMIT = float(os.environ.get("UMVC3_LIMIT", "40"))
CARD_MODEL = re.compile(r"^chs_meku_(face|sel\d+|seld\d+|selr\d+)_([ab])(_typeC)?$")

ver, entries = M.read_arc(ARC)
worst_all = []
for e in entries:
    if e.ext != "mod":
        continue
    short = e.name.rsplit("\\", 1)[-1]
    if not CARD_MODEL.match(short):
        continue
    b = e.data
    q = M.model_dequant(b)
    parents, local, invb, remap = M.read_bones(b)
    bp = [(w[12], w[13], w[14]) for w in M.bone_world(parents, local)]
    xs = sorted({round(bp[i][0], 1) for i in range(1, len(bp))})
    ys = sorted({round(bp[i][1], 1) for i in range(1, len(bp))})
    at = {(round(bp[i][0], 1), round(bp[i][1], 1)): i for i in range(1, len(bp))}

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

    vert_off = M._u64(b, M.H_VERTOFF)
    bad, worst = 0, (0.0, None)
    n = 0
    for m in M.read_meshes(b):
        if m["stride"] != 40:
            continue
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            p = q.decode(struct.unpack_from("<3H", b, vo))
            w = M.read_skin(b, vo)
            pred = bilinear(p)
            cen = [sum(v * bp[j][a] for j, v in w.items()) for a in range(3)]
            ref = [sum(v * bp[j][a] for j, v in pred.items()) for a in range(3)]
            d = sum((cen[a] - ref[a]) ** 2 for a in range(3)) ** 0.5
            n += 1
            if d > LIMIT:
                bad += 1
            if d > worst[0]:
                worst = (d, (m["index"], k, round(p[0], 1), round(p[1], 1),
                             sorted(w.items(), key=lambda kv: -kv[1])[:3]))
    print("%-26s %5d verts  %4d beyond %.0f units  worst %7.1f  %s"
          % (short, n, bad, LIMIT, worst[0], worst[1] if worst[0] > LIMIT else ""))
    worst_all.append((worst[0], short))

print()
print("worst overall: %.1f units (%s)" % max(worst_all))
