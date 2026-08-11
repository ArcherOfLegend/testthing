"""The character-select card grid: what a card is, where it sits, and how to
move one without breaking it.

This is the knowledge `buildgrid.py` proved out, pulled up into a library so the
parametric rebuild and the Blender addon are the same code. Three things it
exists to get right, each of which cost a debugging cycle:

  * Positions decode with a single uniform scale anchored in the inverse-bind
    matrices, not per axis from the header box - the box is inert. Making room
    means retargeting that decode (`fit_decode`), which re-encodes every vertex
    so the geometry the engine sees does not move.

  * The open book bows in BOTH axes - across a page z runs 29 -> 65 -> 32, and
    down a column 29 -> 36 - so a card moved in x or y has to be carried along
    that surface or it sinks behind the opaque page and the page is drawn over
    it, as a large soft blob that swallows several cards. `reseat` does that,
    against the page mesh's own samples (`pagefit`) rather than a fit through
    the four stock column centres.

  * The page is curled at runtime by a 4x4 bone lattice, so a card that moves
    needs the weights belonging to its new position. `WeightField` refits them.

A card's identity is its **joint id**, and the id that counts is bits 21..28 of
the dword at +28 in its `.mrl` material entry - the `_mNN_` in the material name
only mirrors it. `cChrTrace__findByJointId` scans for that field, so renaming
without rewriting the bits changes nothing at all.
"""
import re
import struct

from . import mod as M

# Vanilla is 7 rows x 4 joint columns per page, ids numbered col * 7 + row.
SRC_ROWS, SRC_COLS = 7, 4
BANNER_CELLS = 3                  # joint columns the CAPCOM/MARVEL plate covers

CARD_MODEL = re.compile(r"^chs_meku_(face|sel\d+|seld\d+|selr\d+)_([ab])(_typeC)?$")
MAT_ID = re.compile(r"^(.*_m)(\d+)(_.*)$")
ID_OFF, ID_SHIFT = 28, 21
KNN = 24

# A card is "wide" - a banner plate rather than a portrait - past this multiple
# of the median card width.
BANNER_RATIO = 1.6


def leaf(entry_name):
    return entry_name.replace("\\", "/").split("/")[-1]


def model_kind(entry_name):
    """('face'|'sel1'|'seld0'|'selr1'|..., 'a'|'b') for a card model, else None."""
    m = CARD_MODEL.match(leaf(entry_name))
    return (m.group(1), m.group(2)) if m else None


# ============================================================ slots & cells ===
# A page is chosen by column and the card column runs the other way:
# `remapSlotIndexCircular` mirrors the far half (`if col > 7: col = 15 - col`)
# then indexes the card as `(7 - col) * ROWS + row`, so joint column 0 is the
# one nearest the spine on both pages.

def slot_of(page, joint_col, row, rows, cols):
    """Engine slot index for a card. `cols` counts both pages (16, not 8)."""
    half = cols // 2
    slot_col = (half - 1 - joint_col) if page == "a" else (half + joint_col)
    return row * cols + slot_col


def cell_of_slot(slot, rows, cols):
    """-> (page, joint_col, row). The inverse of `slot_of`."""
    row, slot_col = divmod(slot, cols)
    half = cols // 2
    if slot_col < half:
        return "a", half - 1 - slot_col, row
    return "b", slot_col - half, row


def jid_of(joint_col, row, rows):
    return joint_col * rows + row


def cell_of_jid(jid, rows):
    return jid // rows, jid % rows


# ================================================================== solvers ===
def solve(a, rhs):
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


class WeightField(object):
    """Moving least squares over the stock skin weights, keyed on (x, y).

    The lattice assigns weights by position, so a positional field is the right
    model. A linear basis means a query just outside the sampled area follows
    the trend instead of flattening onto the nearest card."""

    CELL = 60.0

    def __init__(self, samples):
        self.samples = samples
        self.buckets = {}
        for i, (x, y, _) in enumerate(samples):
            self.buckets.setdefault((int(x // self.CELL), int(y // self.CELL)), []).append(i)

    def _near(self, x, y):
        cx, cy = int(x // self.CELL), int(y // self.CELL)
        got, ring = [], 0
        while True:
            for gx in range(cx - ring, cx + ring + 1):
                for gy in range(cy - ring, cy + ring + 1):
                    if ring and max(abs(gx - cx), abs(gy - cy)) != ring:
                        continue
                    got.extend(self.buckets.get((gx, gy), ()))
            if len(got) >= KNN and ring >= 2:
                return got
            ring += 1
            if ring > 40:
                return got or list(range(len(self.samples)))

    def __call__(self, x, y):
        d = sorted(((self.samples[i][0] - x) ** 2 + (self.samples[i][1] - y) ** 2, i)
                   for i in self._near(x, y))[:KNN]
        h2 = max(d[-1][0], 1.0)
        pts = []
        for dist2, i in d:
            sx, sy, w = self.samples[i]
            pts.append((sx - x, sy - y, w, (1.0 - dist2 / (h2 * 1.05)) ** 2 + 1e-6))
        a = [[0.0] * 3 for _ in range(3)]
        for dx, dy, _, om in pts:
            bs = (1.0, dx, dy)
            for r in range(3):
                for c in range(3):
                    a[r][c] += om * bs[r] * bs[c]
        bones = set()
        for _, _, w, _ in pts:
            bones.update(w)
        out = {}
        for j in bones:
            rhs = [0.0] * 3
            for dx, dy, w, om in pts:
                v = w.get(j, 0.0)
                if v:
                    bs = (1.0, dx, dy)
                    for r in range(3):
                        rhs[r] += om * v * bs[r]
            c = solve(a, rhs)
            if c is None:
                num = sum(om * w.get(j, 0.0) for _, _, w, om in pts)
                den = sum(om for _, _, _, om in pts)
                val = num / den if den else 0.0
            else:
                val = c[0]
            if val > 1e-4:
                out[j] = min(1.0, val)
        t = sum(out.values())
        if not t:
            raise RuntimeError("weight field produced nothing at (%.1f, %.1f)" % (x, y))
        return {j: v / t for j, v in out.items()}


def weight_field(cards):
    """The stock weight field of one card model, sampled at every card vertex."""
    return WeightField([(p[0], p[1], w) for c in cards
                        for p, w in zip(c["pts"], c["wts"])])


# ================================================================== reading ===
def read_card_verts(b, q, m):
    """(positions, weights) for one mesh, decoded through the model's dequant."""
    vert_off = M._u64(b, M.H_VERTOFF)
    pts, wts = [], []
    for k in range(m["nverts"]):
        vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
        pts.append(q.decode(struct.unpack_from("<3H", b, vo)))
        wts.append(M.read_skin(b, vo))
    return pts, wts


def read_cards(b, rows=SRC_ROWS, with_verts=True):
    """Every numbered card in a card model, with its cell and its extent.

    `rows` is the modulus the joint ids were numbered with - 7 for stock, the
    built row count for a rebuilt archive. Pass `rows=None` to leave col/row
    unresolved when the count is not known yet (see `detect_rows`)."""
    q = M.model_dequant(b)
    names = M.read_mod_material_names(b)
    cards = []
    for m in M.read_meshes(b):
        if not 0 <= m["material"] < len(names):
            continue
        g = MAT_ID.match(names[m["material"]])
        if not g:
            continue
        jid = int(g.group(2))
        c = dict(m, jid=jid)
        if rows:
            c["col"], c["row"] = cell_of_jid(jid, rows)
        if with_verts:
            c["pts"], c["wts"] = read_card_verts(b, q, c)
            p = c["pts"]
            c["x0"], c["x1"] = min(v[0] for v in p), max(v[0] for v in p)
            c["y0"], c["y1"] = min(v[1] for v in p), max(v[1] for v in p)
            c["cx"], c["cy"] = (c["x0"] + c["x1"]) / 2, (c["y0"] + c["y1"]) / 2
            c["cz"] = (min(v[2] for v in p) + max(v[2] for v in p)) / 2
            c["w"], c["h"] = c["x1"] - c["x0"], c["y1"] - c["y0"]
        cards.append(c)
    return cards


def split_banners(cards):
    """(portrait cards, banner plates). The plate is the over-wide mesh.

    `face` and `sel` carry one; `seld` carries three coincident copies, one per
    joint column the banner covers, so that hovering any of the three lights the
    whole banner. They have to stay coincident."""
    if not cards:
        return [], []
    widths = sorted(c["w"] for c in cards)
    med = widths[len(widths) // 2]
    banners = sorted((c for c in cards if c["w"] > med * BANNER_RATIO),
                     key=lambda c: c["jid"])
    wide = {c["index"] for c in banners}
    return [c for c in cards if c["index"] not in wide], banners


def _median(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def detect_rows(cards, tol=2.0, min_agree=0.75):
    """Recover the row count the joint ids were numbered with, from geometry.

    Ids are `col * ROWS + row`, so at the true ROWS every id with the same
    residue shares a y and every id with the same quotient shares an x.

    Scored by **how many cards agree with their group's median**, not by the
    worst spread in it. The whole point of this addon is moving cards, and a
    single displaced one used to fail detection outright - which then silently
    fell back to vanilla 7 x 8 and renumbered every slot in the scene.

    Multiples of the true count (18, 27, ...) also give every residue the same
    y - jid and jid+18 land on the same row - so it is the x test that
    distinguishes them, and the smallest count that agrees is the answer."""
    normal, _ = split_banners(cards)
    # Row 0 shares its row with the banner plate and its cards do not sit on the
    # column centres in every model, so the column test uses the other rows.
    if len(normal) < 4:
        return None
    top = max(c["jid"] for c in normal)
    best = None
    for r in range(2, top + 2):
        ys, xs = {}, {}
        for c in normal:
            ys.setdefault(c["jid"] % r, []).append(c["cy"])
            if c["jid"] % r:
                xs.setdefault(c["jid"] // r, []).append(c["cx"])
        # Every row must be occupied and carry real company, or a big enough r
        # gives every card a group of its own and agrees with itself perfectly.
        if len(ys) != r or not xs or min(len(v) for v in ys.values()) < 2:
            continue
        agree = total = 0
        for groups in (ys, xs):
            for v in groups.values():
                m = _median(v)
                agree += sum(1 for x in v if abs(x - m) <= tol)
                total += len(v)
        score = agree / float(total)
        if score >= min_agree and (best is None or score > best[0] + 1e-9):
            best = (score, r)
            if score > 0.999:
                return r            # exact - no smaller r can beat it
    return best[1] if best else None


def detect_grid(entries, report=None):
    """(rows, cols) for the whole screen, read off the archive's own cards.

    `cols` counts both pages. Twelve models vote, and the majority wins: a
    single model whose cards have been rearranged should not decide the grid for
    the other eleven. Falls back to the vanilla 7 x 8 only if nothing at all is
    recognisable, which is worth saying out loud - a wrong row count renumbers
    every slot in the scene."""
    votes = {}
    for e in entries:
        if e.ext != "mod" or not model_kind(e.name):
            continue
        cards = read_cards(e.data, rows=None)
        r = detect_rows(cards)
        if not r:
            continue
        normal, _ = split_banners(cards)
        votes.setdefault(r, []).append(max(c["jid"] // r for c in normal) + 1)
    if not votes:
        if report:
            report("[umvc3] no card model gave a readable grid - assuming the "
                   "vanilla %d x %d" % (SRC_ROWS, SRC_COLS * 2))
        return SRC_ROWS, SRC_COLS * 2
    rows = max(votes, key=lambda r: (len(votes[r]), -r))
    if len(votes) > 1 and report:
        report("[umvc3] models disagree on the row count %s - going with %d"
               % (sorted((r, len(v)) for r, v in votes.items()), rows))
    return rows, max(votes[rows]) * 2


# ================================================================== writing ===
def fit_decode(b, points, pad_frac=0.002):
    """Widen the model's uniform decode until `points` fit, re-encoding as it
    goes. Growing the header bounding box instead does nothing - it is inert."""
    q = M.model_dequant(b)
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    if all(lo[i] >= q.origin[i] for i in range(3)) and \
       all(hi[i] <= q.origin[i] + q.scale for i in range(3)):
        return b, q
    nlo = [min(lo[i], q.origin[i]) for i in range(3)]
    nhi = [max(hi[i], q.origin[i] + q.scale) for i in range(3)]
    span = max(nhi[i] - nlo[i] for i in range(3))
    pad = span * pad_frac
    b = M.mod_retarget_dequant(b, [v - pad for v in nlo], span + 2 * pad)
    return b, M.model_dequant(b)


def write_card(bb, q, mesh, points, field=None, uvs=None):
    """Re-encode one mesh's positions, its uvs, and its weights if asked.

    `uvs` is per-vertex and already in the file's orientation. Writing them is
    not optional the way it might look: a card's uvs are what frames the
    portrait inside it, so retargeting them in Blender and not writing them
    leaves the edit in the .blend and the game showing the old crop.

    Untouched cards survive it exactly - a half read into a float32 and packed
    back is the same half - so this is safe to run over every card rather than
    only the ones that look edited.

    -> how many vertices had their uv changed, so the caller can say whether the
    edit reached the file without reading it back.
    """
    vert_off = M._u64(bb, M.H_VERTOFF)
    lay = M.layout_for(mesh["fmt"], mesh["stride"]) if uvs else None
    uv_off = lay["uv0"] if lay else None
    changed = 0
    for j in range(mesh["nverts"]):
        vo = vert_off + mesh["vbufoff"] + (mesh["vtxlo"] + j) * mesh["stride"]
        struct.pack_into("<3H", bb, vo, *q.encode(points[j]))
        if field is not None:
            M.write_skin(bb, vo, field(points[j][0], points[j][1]))
        if uv_off is not None and j < len(uvs):
            o = vo + uv_off
            uv = struct.pack("<2e", float(uvs[j][0]), float(uvs[j][1]))
            if bytes(bb[o:o + 4]) != uv:
                bb[o:o + 4] = uv
                changed += 1
    return changed


def reseat(points, dx, dy, surface, sx=1.0, sy=1.0, cx=None, cy=None):
    """Move a card and carry its depth along the page.

    Every vertex keeps exactly the clearance over the paper the artists gave it,
    so the card's tilt follows the page wherever it lands - including having that
    tilt halved when the card is halved in width."""
    if cx is None:
        cx = (min(p[0] for p in points) + max(p[0] for p in points)) / 2.0
    if cy is None:
        cy = (min(p[1] for p in points) + max(p[1] for p in points)) / 2.0
    out = []
    for p in points:
        nx = cx + dx + (p[0] - cx) * sx
        ny = cy + dy + (p[1] - cy) * sy
        out.append((nx, ny, p[2] + surface(nx, ny) - surface(p[0], p[1])))
    return out


def mrl_entries(mrl):
    """{name hash: entry index}."""
    n, off = M._u32(mrl, 8), M._u64(mrl, 32)
    return {M._u32(mrl, off + j * M.MRL_ENT + 8): j for j in range(n)}


def read_joint_id(mrl, entry):
    off = M._u64(mrl, 32) + entry * M.MRL_ENT + ID_OFF
    return (M._u32(mrl, off) >> ID_SHIFT) & 0xFF


def write_joint_id(mb, entry, jid):
    off = M._u64(mb, 32) + entry * M.MRL_ENT + ID_OFF
    v = M._u32(mb, off)
    struct.pack_into("<I", mb, off, (v & ~(0xFF << ID_SHIFT)) | (jid << ID_SHIFT))


def renumber(mod, mrl, new_jid_by_mesh, label="model"):
    """Give meshes new joint ids, in the material name AND the .mrl id field.

    Renaming alone changes nothing - the engine reads the bits. Renames are
    collected and applied in one pass over a snapshot, because doing them one at
    a time lets an early rename collide with a name not yet visited; a pass that
    did this in place once scrambled 249 bindings silently."""
    mod_b = bytearray(mod)
    mb = bytearray(mrl)
    names = M.read_mod_material_names(mod)
    meshes = {m["index"]: m for m in M.read_meshes(mod)}
    mat_off = M._u64(mod_b, M.H_MATOFF)
    by_hash = mrl_entries(mrl)

    rename = {}
    for mi, new_jid in new_jid_by_mesh.items():
        mat = meshes[mi]["material"]
        old = names[mat]
        g = MAT_ID.match(old)
        if not g or int(g.group(2)) == new_jid:
            continue
        new = "%s%02d%s" % (g.group(1), new_jid, g.group(3))
        enc = new.encode("ascii")
        if len(enc) > 127:
            raise RuntimeError("%s: material name too long: %s" % (label, new))
        mod_b[mat_off + mat * 128: mat_off + mat * 128 + 128] = enc + bytes(128 - len(enc))
        rename[M.mt_hash(old)] = (M.mt_hash(new), new_jid)

    for h, (nh, nj) in rename.items():
        j = by_hash.get(h)
        if j is None:
            continue
        struct.pack_into("<I", mb, M._u64(mb, 32) + j * M.MRL_ENT + 8, nh)
        write_joint_id(mb, j, nj)

    n = M._u32(mb, 8)
    if len(mrl_entries(bytes(mb))) != n:
        raise RuntimeError("%s: renumbering collapsed two materials onto one hash" % label)
    return bytes(mod_b), bytes(mb)
