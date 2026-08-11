"""The book page's real surface, sampled from `chs_meku`.

The cards float a fixed distance in front of an opaque, doubly-curved page.
Guessing that page from the stock card centres is what put whole columns behind
it: across a page z runs 29 -> 65 -> 32, and any smooth fit through only four
column samples either sags between them or oscillates past them.  The page mesh
itself is right there in the same archive, so sample it instead.

`page_surface(entries, side)` returns f(x, y) -> z of the frontmost page
geometry, for side "a" (x < 0) or "b" (x > 0).
"""
import struct

from . import mod as M

BIN_X, BIN_Y = 18.0, 26.0
KNN = 14


def _solve(a, rhs):
    n = len(a)
    m = [list(a[r]) + [rhs[r]] for r in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r == c:
                continue
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    return [m[r][n] / m[r][r] for r in range(n)]


class Surface(object):
    """Moving least squares over the page's frontmost samples.

    Quadratic basis: the page is an arch in x and sags in y, and a linear basis
    would cut the corner off both.  Samples are pre-reduced to the max z per
    bin, so the layers of paper stacked behind the visible page cannot drag a
    fit down into them."""

    def __init__(self, samples):
        self.pts = samples
        self.cache = {}
        self.buckets = {}
        for i, (x, y, _) in enumerate(samples):
            self.buckets.setdefault((int(x // 60.0), int(y // 60.0)), []).append(i)
        # The page is sampled over its own half of the book and nowhere else, so
        # a query outside that is extrapolation of a QUADRATIC basis - it does
        # not flatten out, it takes off. A card dragged just past the spine came
        # back with 82 units of z spread across its own 58 x 68 face, which reads
        # in game as the card being folded rather than moved. Clamp instead: past
        # the edge the depth simply stops changing.
        self.x0 = min(p[0] for p in samples)
        self.x1 = max(p[0] for p in samples)
        self.y0 = min(p[1] for p in samples)
        self.y1 = max(p[1] for p in samples)

    def contains(self, x, y, margin=0.0):
        return (self.x0 - margin <= x <= self.x1 + margin and
                self.y0 - margin <= y <= self.y1 + margin)

    def _near(self, x, y):
        cx, cy = int(x // 60.0), int(y // 60.0)
        got, ring = [], 0
        while True:
            for gx in range(cx - ring, cx + ring + 1):
                for gy in range(cy - ring, cy + ring + 1):
                    if ring and max(abs(gx - cx), abs(gy - cy)) != ring:
                        continue
                    got.extend(self.buckets.get((gx, gy), ()))
            if len(got) >= KNN and ring >= 1:
                return got
            ring += 1
            if ring > 40:
                return got or list(range(len(self.pts)))

    def __call__(self, x, y):
        x = min(max(x, self.x0), self.x1)
        y = min(max(y, self.y0), self.y1)
        # cards share x down a column and y across a row, so the same handful of
        # queries repeat thousands of times
        key = (round(x, 2), round(y, 2))
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        z = self._eval(x, y)
        self.cache[key] = z
        return z

    def _eval(self, x, y):
        d = sorted(((self.pts[i][0] - x) ** 2 + (self.pts[i][1] - y) ** 2, i)
                   for i in self._near(x, y))[:KNN]
        h2 = max(d[-1][0], 1.0)
        rows = []
        for dist2, i in d:
            sx, sy, sz = self.pts[i]
            dx, dy = sx - x, sy - y
            rows.append(((1.0, dx, dy, dx * dx, dx * dy, dy * dy), sz,
                         (1.0 - dist2 / (h2 * 1.05)) ** 2 + 1e-6))
        n = 6
        a = [[0.0] * n for _ in range(n)]
        rhs = [0.0] * n
        for bs, z, w in rows:
            for r in range(n):
                rhs[r] += w * z * bs[r]
                for c in range(n):
                    a[r][c] += w * bs[r] * bs[c]
        co = _solve(a, rhs)
        if co is None:
            num = sum(w * z for _, z, w in rows)
            den = sum(w for _, _, w in rows)
            return num / den
        return co[0]


def page_samples(entries, side):
    """Frontmost z per bin over the page area, for side 'a' (x<0) or 'b' (x>0)."""
    e = next(x for x in entries
             if x.ext == "mod" and x.name.rsplit("\\", 1)[-1] == "chs_meku")
    b = e.data
    q = M.model_dequant(b)
    vert_off = M._u64(b, M.H_VERTOFF)
    sign = -1.0 if side == "a" else 1.0
    best = {}
    for m in M.read_meshes(b):
        pts = []
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            pts.append(q.decode(struct.unpack_from("<3H", b, vo)))
        # the open page is the only geometry that reaches the front of the book;
        # the covers and the paper stacked behind it sit well back
        if max(p[2] for p in pts) < 60.0:
            continue
        for p in pts:
            if p[0] * sign < 0 or abs(p[0]) > 620.0:
                continue
            k = (int(p[0] // BIN_X), int(p[1] // BIN_Y))
            if k not in best or p[2] > best[k][2]:
                best[k] = p
    return list(best.values())


def page_surface(entries, side):
    return Surface(page_samples(entries, side))
