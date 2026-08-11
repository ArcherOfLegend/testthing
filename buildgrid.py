"""Rebuild the character-select card grid at an arbitrary rows x columns.

Vanilla is 7 rows x 4 columns per page, joint ids numbered colIdx*7 + row with
the id hidden in bits 21..28 of the .mrl material entry. This retargets all
twelve card models (the two pages plus their hover/select/down overlays) to
ROWS x COLS columns per page: each source column is split into COLS/4 narrower
ones, rows are rescaled to the new pitch, missing cells are cloned from a
template, and every joint id is renumbered to colIdx*ROWS + row.

Three things this has to get right, each of which cost a debugging cycle:

  * Positions decode with a single uniform scale anchored in the inverse-bind
    matrices, not per axis from the header box - the box is inert. Making room
    means retargeting that decode (mod_retarget_dequant), which re-encodes every
    vertex so the geometry the engine sees does not move.

  * The open book bows in BOTH axes - across a page depth runs 29 -> 65 -> 32,
    and down a column 29 -> 36 - so a card moved in x or y has to be carried
    along that surface, or it sinks behind the opaque page and the page is drawn
    over it. The surface comes from the page mesh itself (pagefit), because no
    fit through the four stock column samples is good enough: a polynomial
    oscillates past them and piecewise-linear sags between them, and either way
    a whole column ends up 10-20 units behind the paper.

  * The page is curved at runtime by a 4x4 bone lattice, so a card that moves
    needs the weights belonging to its new position. Refitted with a moving
    least squares pass over the stock weight field.

The wide banner plate (the RANDOM card plus the CAPCOM/MARVEL logo, one mesh
spanning three joint columns) is kept whole rather than split, and the cells it
covers are left without cards, exactly as vanilla leaves row 0 columns 1 and 2.
The `seld` overlays carry *three* coincident copies of that plate, one per joint
column of the banner, so that whichever of the three is hovered lights the whole
banner; they have to stay coincident. Spreading them one per target column - as
splitting the grid does if you let it - smears six overlapping plates across the
top row and buries the banner underneath them.

  UMVC3_ARC     stock archive to build from
  UMVC3_OUT     archive to write
  UMVC3_ROWS    target rows (default 9)
  UMVC3_COLS    target columns per page (default 8; must be a multiple of 4)
  UMVC3_SPAN    y span the grid should occupy; default is the stock grid's own
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
import pagefit
from io_umvc3_css import grid as G
from io_umvc3_css.grid import (SRC_ROWS, SRC_COLS, BANNER_CELLS, CARD_MODEL, MAT_ID,
                               ID_OFF, ID_SHIFT, KNN, WeightField, solve)

ARC = os.environ["UMVC3_ARC"]
OUT = os.environ["UMVC3_OUT"]
ROWS = int(os.environ.get("UMVC3_ROWS", "9"))
COLS = int(os.environ.get("UMVC3_COLS", "8"))
SPAN = os.environ.get("UMVC3_SPAN")
SPAN = float(SPAN) if SPAN else None

if COLS % SRC_COLS:
    raise SystemExit("columns per page must be a multiple of %d" % SRC_COLS)
SPLIT = COLS // SRC_COLS

# The grid maths, the weight field and the page surface all live in the addon
# package now, so the parametric rebuild and the Blender scene share one copy.
read_card = G.read_card_verts


# ================================================================== build ====
ver, entries = M.read_arc(ARC)
by = {}
for e in entries:
    by.setdefault(e.name, {})[e.ext] = e
surf = {"a": pagefit.page_surface(entries, "a"),
        "b": pagefit.page_surface(entries, "b")}

print("target: %d rows x %d columns per page = %d slots (%d columns total)\n"
      % (ROWS, COLS, ROWS * COLS * 2, COLS * 2))

for name in sorted(by):
    x = by[name]
    short = name.rsplit("\\", 1)[-1]
    if not CARD_MODEL.match(short) or "mod" not in x or "mrl" not in x:
        continue
    mod_e, mrl_e = x["mod"], x["mrl"]
    b = mod_e.data
    q = M.model_dequant(b)
    names = M.read_mod_material_names(b)

    cards = []
    for m in M.read_meshes(b):
        g = MAT_ID.match(names[m["material"]])
        if not g:
            continue
        jid = int(g.group(2))
        c = dict(m, jid=jid, col=jid // SRC_ROWS, row=jid % SRC_ROWS)
        c["pts"], c["wts"] = read_card(b, q, c)
        p = c["pts"]
        c["x0"], c["x1"] = min(v[0] for v in p), max(v[0] for v in p)
        c["y0"], c["y1"] = min(v[1] for v in p), max(v[1] for v in p)
        c["cx"], c["cy"] = (c["x0"] + c["x1"]) / 2, (c["y0"] + c["y1"]) / 2
        c["cz"] = (min(v[2] for v in p) + max(v[2] for v in p)) / 2
        c["w"], c["h"] = c["x1"] - c["x0"], c["y1"] - c["y0"]
        cards.append(c)
    if not cards:
        print("%-26s no numbered cards, skipped" % short)
        continue

    field = WeightField([(p[0], p[1], w) for c in cards
                         for p, w in zip(c["pts"], c["wts"])])

    # Banner plates are the over-wide cards. `face` and `sel` have one, `seld`
    # has three coincident copies, one per joint column the banner covers.
    widths = sorted(c["w"] for c in cards)
    med_w = widths[len(widths) // 2]
    full = len(cards) == SRC_COLS * SRC_ROWS
    banners = sorted((c for c in cards if c["w"] > med_w * 1.6),
                     key=lambda c: (c["col"], c["row"]))
    is_banner = {c["index"] for c in banners}
    normal = [c for c in cards if c["index"] not in is_banner]

    # --- source columns and rows -------------------------------------------
    # Row 0 is the banner row and its cards do not sit on the column centres in
    # every model, so the column geometry comes from the regular rows only.
    src_x, src_w = {}, {}
    for c in normal:
        if c["row"] == 0:
            continue
        src_x.setdefault(c["col"], []).append(c["cx"])
        src_w.setdefault(c["col"], []).append(c["w"])
    src_x = {k: sum(v) / len(v) for k, v in src_x.items()}
    src_w = {k: sum(v) / len(v) for k, v in src_w.items()}
    dirx = 1.0 if src_x[SRC_COLS - 1] > src_x[0] else -1.0   # +1 if x grows outward

    src_y = {}
    for c in normal:
        src_y.setdefault(c["row"], []).append(c["cy"])
    src_y = {r: sum(v) / len(v) for r, v in src_y.items()}
    # The page's own surface. Vertices move as residuals against it, so every
    # vertex keeps exactly the clearance over the paper the artists gave it and
    # a card's tilt follows the page wherever it lands - including having that
    # tilt halved when the card is halved in width.
    zpage = surf[CARD_MODEL.match(short).group(2)]
    rows_n = sorted(r for r in src_y if r > 0)
    src_pitch = (src_y[rows_n[0]] - src_y[rows_n[-1]]) / (len(rows_n) - 1)
    top, bottom = max(src_y.values()), min(src_y.values())
    grid_span = (top - bottom) + src_pitch

    # --- target columns and rows -------------------------------------------
    pitch = (SPAN / ROWS) if SPAN else (grid_span / ROWS if ROWS * src_pitch > grid_span
                                        else src_pitch)
    ky = pitch / src_pitch
    mid = (top + bottom) / 2.0
    tgt_y = [mid + ((ROWS - 1) / 2.0 - r) * pitch for r in range(ROWS)]

    # Sub-columns are laid out on the CELL grid, not on each model's card width:
    # the hover overlays are deliberately wider than the cards they frame, and
    # offsetting by their own width would slide them off the cards.
    gaps = [abs(src_x[c + 1] - src_x[c]) for c in range(SRC_COLS - 1)]
    local = [(gaps[max(0, c - 1)] + gaps[min(len(gaps) - 1, c)]) / 2.0
             for c in range(SRC_COLS)]
    tgt_x, tgt_w = {}, {}
    for c in range(SRC_COLS):
        for j in range(SPLIT):
            t = c * SPLIT + j
            tgt_w[t] = local[c] / SPLIT
            tgt_x[t] = src_x[c] + dirx * local[c] * ((j + 0.5) / SPLIT - 0.5)

    # On `face` the cells beside the banner hold nothing at all, exactly as
    # vanilla leaves row 0 columns 1 and 2. The overlays do fill them.
    skip = set()
    if banners and not full:
        skip = {(t, 0) for t in range(len(banners), BANNER_CELLS)}

    def place(src, tcol, trow, wide=1):
        """source card -> its vertices at target cell (tcol, trow).

        Depth is carried along the page in both axes by re-seating every vertex
        on the page surface at its new position, at the clearance it had over
        the page at its old one."""
        cx = sum(tgt_x[tcol + i] for i in range(wide)) / wide
        sx = 1.0 / SPLIT          # every card keeps its own card-to-cell ratio
        cy = tgt_y[trow]
        out = []
        for p in src["pts"]:
            nx = cx + (p[0] - src["cx"]) * sx
            ny = cy + (p[1] - src["cy"]) * ky
            out.append((nx, ny, p[2] + zpage(nx, ny) - zpage(p[0], p[1])))
        return out

    tpl_of_col = {c: max([k for k in normal if k["col"] == c and k["row"] > 0],
                         key=lambda k: (k["nverts"], -abs(k["cy"])))
                  for c in range(SRC_COLS)}
    by_cell = {(c["col"], c["row"]): c for c in normal}

    # --- assign every target cell -------------------------------------------
    reuse, fresh = {}, []
    used = set()
    # Every banner plate stays whole and stays where the banner is - they are
    # coincident by design. Only the joint id differs, so plate i takes target
    # cell (i, 0), which is one of the cells the banner covers.
    for i, bn in enumerate(banners[:BANNER_CELLS]):
        reuse[bn["index"]] = (i, 0, place(bn, 0, 0, BANNER_CELLS))
        used.add((i, 0))
    for t in range(COLS):
        sc = t // SPLIT
        for r in range(ROWS):
            if (t, r) in skip or (t, r) in used:
                continue
            # never re-use a banner plate as an ordinary card: at 1/SPLIT it is
            # still three cells wide and would bury its neighbours
            src = by_cell.get((sc, r)) or tpl_of_col[sc]
            pts = place(src, t, r)
            # the inward half of each source column reuses that card's mesh
            if t % SPLIT == 0 and (sc, r) in by_cell and by_cell[(sc, r)]["index"] not in reuse:
                reuse[by_cell[(sc, r)]["index"]] = (t, r, pts)
            else:
                fresh.append({"template": src["index"], "material": 0, "positions": pts,
                              "uvs": None, "_jid": t * ROWS + r})
            used.add((t, r))

    if len(banners) > BANNER_CELLS:
        raise RuntimeError("%s: %d banner plates but the banner spans %d cells"
                           % (short, len(banners), BANNER_CELLS))

    # any card left over from a cell that no longer exists is folded onto a
    # still-empty target cell, so no mesh is orphaned mid-grid
    for c in normal:
        if c["index"] in reuse:
            continue
        spare = next(((t, r) for t in range(COLS) for r in range(ROWS)
                      if (t, r) not in used and (t, r) not in skip), None)
        if spare is None:
            raise RuntimeError("%s: mesh %d has nowhere to go" % (short, c["index"]))
        reuse[c["index"]] = (spare[0], spare[1], place(c, spare[0], spare[1]))
        used.add(spare)

    # --- make the decode cover everything -----------------------------------
    allp = [p for _, _, pts in reuse.values() for p in pts] + \
           [p for s in fresh for p in s["positions"]]
    lo = [min(p[i] for p in allp) for i in range(3)]
    hi = [max(p[i] for p in allp) for i in range(3)]
    if any(lo[i] < q.origin[i] for i in range(3)) or \
       any(hi[i] > q.origin[i] + q.scale for i in range(3)):
        nlo = [min(lo[i], q.origin[i]) for i in range(3)]
        nhi = [max(hi[i], q.origin[i] + q.scale) for i in range(3)]
        span = max(nhi[i] - nlo[i] for i in range(3))
        pad = span * 0.002
        b = M.mod_retarget_dequant(b, [v - pad for v in nlo], span + 2 * pad)
        q = M.model_dequant(b)

    # --- write the reused cards ---------------------------------------------
    bb = bytearray(b)
    vert_off = M._u64(bb, M.H_VERTOFF)
    mesh_by_index = {m["index"]: m for m in M.read_meshes(bytes(bb))}
    for mi, (tcol, trow, pts) in reuse.items():
        m = mesh_by_index[mi]
        for j in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + j) * m["stride"]
            struct.pack_into("<3H", bb, vo, *q.encode(pts[j]))
            M.write_skin(bb, vo, field(pts[j][0], pts[j][1]))
    b = bytes(bb)

    # --- renumber the reused cards' joint ids -------------------------------
    mb = bytearray(mrl_e.data)
    mod_b = bytearray(b)
    mat_off = M._u64(mod_b, M.H_MATOFF)
    n_mrl, moff = M._u32(mb, 8), M._u64(mb, 32)
    rename = {}
    for c in normal + banners:
        tcol, trow, _ = reuse[c["index"]]
        new_jid = tcol * ROWS + trow
        if new_jid == c["jid"]:
            continue
        old_name = names[c["material"]]
        g = MAT_ID.match(old_name)
        new_name = "%s%02d%s" % (g.group(1), new_jid, g.group(3))
        enc = new_name.encode("ascii")
        mod_b[mat_off + c["material"] * 128: mat_off + c["material"] * 128 + 128] = \
            enc + bytes(128 - len(enc))
        rename[M.mt_hash(old_name)] = (M.mt_hash(new_name), new_jid)
    for j in range(n_mrl):
        h = M._u32(mb, moff + j * M.MRL_ENT + 8)
        if h not in rename:
            continue
        nh, nj = rename[h]
        struct.pack_into("<I", mb, moff + j * M.MRL_ENT + 8, nh)
        o = moff + j * M.MRL_ENT + ID_OFF
        v = M._u32(mb, o)
        struct.pack_into("<I", mb, o, (v & ~(0xFF << ID_SHIFT)) | (nj << ID_SHIFT))
    if len({M._u32(mb, moff + j * M.MRL_ENT + 8) for j in range(n_mrl)}) != n_mrl:
        raise RuntimeError("%s: renaming collapsed two materials" % short)
    b = bytes(mod_b)
    mrl = bytes(mb)
    names = M.read_mod_material_names(b)

    # --- append the new cards -----------------------------------------------
    if fresh:
        new_names, tpl_mats = [], []
        for s in fresh:
            tpl_mat = mesh_by_index[s["template"]]["material"]
            tpl_mats.append(tpl_mat)
            g = MAT_ID.match(names[tpl_mat])
            new_names.append("%s%02d%s" % (g.group(1), s["_jid"], g.group(3)))
        b, first_new = M.mod_add_material_slots(b, new_names)
        for i, s in enumerate(fresh):
            s["material"] = first_new + i
        pre_count = M._u16(b, M.H_MESHCOUNT)
        b = M.mod_append_meshes(b, fresh)

        groups = {}
        for i, s in enumerate(fresh):
            groups.setdefault(tpl_mats[i], []).append(i)
        for tpl_mat, idxs in groups.items():
            th = M.mt_hash(names[tpl_mat])
            n_mrl, moff = M._u32(mrl, 8), M._u64(mrl, 32)
            ti = next(j for j in range(n_mrl)
                      if M._u32(mrl, moff + j * M.MRL_ENT + 8) == th)
            mrl = M.mrl_add_materials(mrl, ti, [new_names[i] for i in idxs])
        mb = bytearray(mrl)
        n_mrl, moff = M._u32(mb, 8), M._u64(mb, 32)
        pos = {M._u32(mb, moff + j * M.MRL_ENT + 8): j for j in range(n_mrl)}
        for i, s in enumerate(fresh):
            o = moff + pos[M.mt_hash(new_names[i])] * M.MRL_ENT + ID_OFF
            v = M._u32(mb, o)
            struct.pack_into("<I", mb, o, (v & ~(0xFF << ID_SHIFT)) | (s["_jid"] << ID_SHIFT))
        mrl = bytes(mb)

        bb = bytearray(b)
        vert_off = M._u64(bb, M.H_VERTOFF)
        added = {m["index"]: m for m in M.read_meshes(bytes(bb))}
        for i, s in enumerate(fresh):
            m = added[pre_count + i]
            for j in range(m["nverts"]):
                vo = vert_off + m["vbufoff"] + (m["vtxlo"] + j) * m["stride"]
                M.write_skin(bb, vo, field(s["positions"][j][0], s["positions"][j][1]))
        b = bytes(bb)

    bb = bytearray(b)
    M.write_bbox(bb, *M.mod_geometry_bounds(b))
    mod_e.data = bytes(bb)
    mod_e.dirty = True
    mrl_e.data = mrl
    mrl_e.dirty = True

    zs = sorted(round((min(p[2] for p in pts) + max(p[2] for p in pts)) / 2, 1)
                for _, _, pts in reuse.values())
    print("%-26s %2d -> %2d cards  cell %6.2f x %6.2f  z %5.1f..%5.1f%s"
          % (short, len(cards), len(reuse) + len(fresh),
             tgt_w[0], pitch, zs[0], zs[-1],
             "  (%d banner plate%s kept whole)" % (len(banners),
                                                   "" if len(banners) == 1 else "s")
             if banners else ""))

M.write_arc(OUT, ver, entries)
print("\nwrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
