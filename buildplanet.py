"""Re-place the character-select cards on a spherical cap - the MvC3 look.

Takes an archive that has ALREADY been re-gridded by `buildgrid.py` (so the
cells exist and the joint ids are right) and moves every card onto a dome, each
one turned to face outward along the sphere's normal. Nothing here clones,
renumbers or re-splits anything: this is purely a placement pass, which is what
makes it safe to iterate on.

Three things it has to get right:

  * **Rigid-bind to bone 0.** The page's curl is not a texture effect, it is a
    4x4 lattice of 16 bones that deforms whatever is weighted to it - so a card
    placed on a dome and left weighted to the lattice gets the book's arch
    applied on top and folds. Bone 0 is the root, sits at (0, 0, -0.2) and is
    effectively identity, so binding every card vertex to it alone lands the
    card exactly where it is authored. The cards already reference bone 0, so
    this is not a new binding, just a total one.

  * **Clear the book in z.** `chs_meku`'s page reaches z = 69.2. A dome whose
    rim falls behind that is occluded by paper, so the apex is placed high
    enough that even the rim clears it.

  * **Keep the overlay layering.** The hover and select frames sit in front of
    the cards they frame (selr1 runs ~20 units proud of `face`). That offset is
    measured per model from the source and re-applied along the sphere normal,
    or the frames z-fight with the portraits.

The banner plate spans three joint columns and its `seld` copies are coincident
by design, so it is placed once, across three cells, and every copy gets the
same position - spreading them one per column smears six plates across the top.

  UMVC3_ARC     re-gridded archive to place (must already be ROWS x COLS)
  UMVC3_OUT     archive to write
  UMVC3_ROWS    rows the source was built at (default 9)
  UMVC3_COLS    columns across BOTH pages (default 16)
  UMVC3_WIDTH   how wide the grid should span, game units (default 1700)
  UMVC3_HEIGHT  how tall (default 1000)
  UMVC3_BULGE   how far the left/right rim falls back from the apex (default 120)
  UMVC3_APEX    z of the dome's centre (default 200; the book page ends at 69)
"""
import sys, os, math, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
from io_umvc3_css import grid as G

ARC = os.environ["UMVC3_ARC"]
OUT = os.environ["UMVC3_OUT"]
ROWS = int(os.environ.get("UMVC3_ROWS", "9"))
COLS = int(os.environ.get("UMVC3_COLS", "16"))
WIDTH = float(os.environ.get("UMVC3_WIDTH", "1700"))
HEIGHT = float(os.environ.get("UMVC3_HEIGHT", "1000"))
BULGE = float(os.environ.get("UMVC3_BULGE", "120"))
APEX = float(os.environ.get("UMVC3_APEX", "200"))
HALF = COLS // 2

# --- the sphere ------------------------------------------------------------
# Solve for the radius that spans WIDTH across the screen while the rim falls
# back by BULGE:  R sin(T) = WIDTH/2  and  R (1 - cos T) = BULGE, so
# tan(T/2) = BULGE / (WIDTH/2).
_t = 2.0 * math.atan2(BULGE, WIDTH / 2.0)
RADIUS = (WIDTH / 2.0) / math.sin(_t) if _t > 1e-9 else 1e9
YAW = _t                                        # half the horizontal sweep
PITCH = math.asin(min(1.0, (HEIGHT / 2.0) / RADIUS))
CENTRE = (0.0, 0.0, APEX - RADIUS)              # so the apex lands on APEX


def dome(col, row, wide=1):
    """(position, right, up, normal) for a cell centre on the sphere.

    `col` is the global slot column 0..COLS-1, left to right across the screen;
    `wide` spans that many columns, for the banner plate."""
    c = col + (wide - 1) / 2.0
    th = (c - (COLS - 1) / 2.0) * (2.0 * YAW / max(1, COLS - 1))
    ph = ((ROWS - 1) / 2.0 - row) * (2.0 * PITCH / max(1, ROWS - 1))
    n = (math.sin(th) * math.cos(ph), math.sin(ph), math.cos(th) * math.cos(ph))
    p = tuple(CENTRE[i] + RADIUS * n[i] for i in range(3))
    # right = normalised d/dtheta, up = n x right, both on the tangent plane
    r = (math.cos(th), 0.0, -math.sin(th))
    u = (n[1] * r[2] - n[2] * r[1], n[2] * r[0] - n[0] * r[2], n[0] * r[1] - n[1] * r[0])
    return p, r, u, n


def slot_col(page, joint_col):
    """Joint column -> the column as it appears on screen, left to right."""
    return (HALF - 1 - joint_col) if page == "a" else (HALF + joint_col)


# ============================================================== the pass ====
ver, entries = M.read_arc(ARC)
by = {}
for e in entries:
    by.setdefault(e.name, {})[e.ext] = e

# Cell pitch of the source grid, so cards are scaled by the CELL they occupy and
# not by their own width - the overlays are deliberately wider than the cards
# they frame and would slide off if scaled by themselves.
src_pitch_x = src_pitch_y = None
face = next(x for x in entries if x.ext == "mod" and x.name.endswith("face_a"))
_cards = G.read_cards(face.data, rows=ROWS)
_normal, _ = G.split_banners(_cards)
_xs, _ys = {}, {}
for c in _normal:
    col, row = G.cell_of_jid(c["jid"], ROWS)
    if row:
        _xs.setdefault(col, []).append(c["cx"])
    _ys.setdefault(row, []).append(c["cy"])
_xm = [sum(v) / len(v) for _, v in sorted(_xs.items())]
_ym = [sum(v) / len(v) for _, v in sorted(_ys.items())]
src_pitch_x = abs(_xm[1] - _xm[0])
src_pitch_y = abs(_ym[1] - _ym[0])

# The cell is the ARC between adjacent cell centres, R * dtheta - not
# WIDTH / COLS. WIDTH spans the first cell centre to the last, so 16 columns
# have only 15 gaps between them; dividing by 16 makes every card 8% narrow and
# 11% short, which is what leaves a gap around each portrait.
DTH = 2.0 * YAW / (COLS - 1)
DPH = 2.0 * PITCH / (ROWS - 1)
CELL_W = RADIUS * DTH
CELL_H = RADIUS * DPH

# Scale by the FACE card's own size, not by the source pitch, so the portrait
# fills its cell exactly. One scale for every model, taken from `face`: the
# hover overlays are deliberately wider than the cards they frame, and scaling
# each by its own width would shrink them onto the card and lose the frame.
_face_w = sum(c["w"] for c in _normal) / len(_normal)
_face_h = sum(c["h"] for c in _normal) / len(_normal)
SX = CELL_W / _face_w
SY = CELL_H / _face_h

# Where each model sits relative to `face`, so hover frames stay in front.
face_z = sum(c["cz"] for c in _normal) / len(_normal)

print("dome: radius %.0f, sweep %.1f deg x %.1f deg, apex z %.0f, rim z %.0f"
      % (RADIUS, math.degrees(YAW) * 2, math.degrees(PITCH) * 2, APEX,
         APEX - BULGE))
print("cell %.2f x %.2f game units; face card %.2f x %.2f -> scale %.3f x %.3f"
      % (CELL_W, CELL_H, _face_w, _face_h, SX, SY))
print("     card fills %.1f%% x %.1f%% of its cell (source pitch %.1f x %.1f)"
      % (100.0 * _face_w * SX / CELL_W, 100.0 * _face_h * SY / CELL_H,
         src_pitch_x, src_pitch_y))

# Screen budget. The stock grid spans y +-304.6 game units and the book measures
# 427 px tall on screen (y 215..642, screenroom.py), which fixes the mapping at
# 609.2 / 427 units per pixel. The character body art flanks the grid, so the
# horizontal budget is what the book used - about 665 px of 1280 - not the whole
# screen: a grid wider than that covers the art.
UNITS_PER_PX = 609.2 / 427.0
ext_x = WIDTH / 2.0 + CELL_W / 2.0          # outermost card edge, not centre
ext_y = HEIGHT / 2.0 + CELL_H / 2.0
print("cards reach x +-%.0f, y +-%.0f  ~  %.0f x %.0f px of 1280 x 720"
      % (ext_x, ext_y, 2 * ext_x / UNITS_PER_PX, 2 * ext_y / UNITS_PER_PX))
print("     for reference the book used 665 x 427 px, cards x +-480 y +-305\n")

for name in sorted(by):
    x = by[name]
    short = G.leaf(name)
    kind = G.model_kind(name)
    if not kind or "mod" not in x:
        continue
    what, page = kind
    b = x["mod"].data
    cards = G.read_cards(b, rows=ROWS)
    if not cards:
        continue
    normal, banners = G.split_banners(cards)
    banner_ix = {c["index"] for c in banners}

    # this model's own standoff from the face plane, preserved along the normal
    mz = sum(c["cz"] for c in normal) / len(normal)
    standoff = mz - face_z

    placed = {}
    for c in cards:
        col, row = G.cell_of_jid(c["jid"], ROWS)
        if c["index"] in banner_ix:
            # spans the three joint columns the plate covers, and every copy
            # lands identically - they are coincident by design
            lo = min(slot_col(page, k) for k in range(G.BANNER_CELLS))
            p, r, u, n = dome(lo, 0, G.BANNER_CELLS)
        else:
            p, r, u, n = dome(slot_col(page, col), row)
        out = []
        for v in c["pts"]:
            lx = (v[0] - c["cx"]) * SX
            ly = (v[1] - c["cy"]) * SY
            # the card's own z becomes a flat standoff: the source z carries the
            # book's bow, which is exactly the shape being replaced
            for_k = [p[k] + lx * r[k] + ly * u[k] + standoff * n[k] for k in range(3)]
            out.append(tuple(for_k))
        placed[c["index"]] = out

    # widen the decode to cover the dome, then write
    allp = [q for pts in placed.values() for q in pts]
    nb, q = G.fit_decode(b, allp)
    bb = bytearray(nb)
    meshes = {m["index"]: m for m in M.read_meshes(nb)}
    vert_off = M._u64(bb, M.H_VERTOFF)
    for mi, pts in placed.items():
        m = meshes[mi]
        for j in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + j) * m["stride"]
            struct.pack_into("<3H", bb, vo, *q.encode(pts[j]))
            # rigid to the root: the lattice would otherwise arch the dome
            M.write_skin(bb, vo, {0: 1.0})
    M.write_bbox(bb, *M.mod_geometry_bounds(bytes(bb)))
    x["mod"].data = bytes(bb)
    x["mod"].dirty = True

    zs = sorted(round((min(p[2] for p in pts) + max(p[2] for p in pts)) / 2, 1)
                for pts in placed.values())
    print("%-26s %3d cards placed  standoff %+5.1f  z %6.1f..%6.1f"
          % (short, len(placed), standoff, zs[0], zs[-1]))

M.write_arc(OUT, ver, entries)
print("\nwrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
