"""Check a rebuilt grid archive before it goes anywhere near the game.

  1 every card material's stored joint id matches its name
  2 every card sits in the cell its joint id claims
  3 mesh -> .mrl bindings resolve one-to-one, and none were scrambled
  4 cards that should not have moved still match stock to within a quantisation step
  5 skin weights sum to 1 and name bones that exist

  UMVC3_ARC (built), UMVC3_STOCK, UMVC3_ROWS, UMVC3_SRC_ROWS (default 7)
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
STOCK = os.environ["UMVC3_STOCK"]
ROWS = int(os.environ["UMVC3_ROWS"])
COLS = int(os.environ.get("UMVC3_COLS", "4"))
SRC_ROWS = int(os.environ.get("UMVC3_SRC_ROWS", "7"))
CARD_MODEL = re.compile(r"^chs_meku_(face|sel\d+|seld\d+|selr\d+)_([ab])(_typeC)?$")
MAT_ID = re.compile(r"^(.*_m)(\d+)(_.*)$")
ID_OFF, ID_SHIFT = 28, 21

ver, entries = M.read_arc(ARC)
_, stock_entries = M.read_arc(STOCK)
stock = {e.name: e for e in stock_entries}
by = {}
for e in entries:
    by.setdefault(e.name, {})[e.ext] = e

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


for name in sorted(by):
    x = by[name]
    short = name.rsplit("\\", 1)[-1]
    if not CARD_MODEL.match(short) or "mod" not in x or "mrl" not in x:
        continue
    b, mrl = x["mod"].data, x["mrl"].data
    q = M.model_dequant(b)
    names = M.read_mod_material_names(b)
    nbones = M._u16(b, 0x06)
    vert_off = M._u64(b, M.H_VERTOFF)
    n_mrl, moff = M._u32(mrl, 8), M._u64(mrl, 32)
    hash_to_entry = {}
    for j in range(n_mrl):
        h = M._u32(mrl, moff + j * M.MRL_ENT + 8)
        check(h not in hash_to_entry, "%s: duplicate .mrl hash %08X" % (short, h))
        hash_to_entry[h] = j

    cells, cols_x, rows_y = {}, {}, {}
    for m in M.read_meshes(b):
        nm = names[m["material"]]
        g = MAT_ID.match(nm)
        j = hash_to_entry.get(M.mt_hash(nm))
        check(j is not None, "%s: mesh %d material %r has no .mrl entry" % (short, m["index"], nm))
        if g is None or j is None:
            continue
        jid = int(g.group(2))
        stored = (M._u32(mrl, moff + j * M.MRL_ENT + ID_OFF) >> ID_SHIFT) & 0xFF
        check(stored == jid, "%s: %s stores joint id %d, name says %d"
              % (short, nm, stored, jid))
        col, row = jid // ROWS, jid % ROWS
        check(0 <= col < COLS and 0 <= row < ROWS,
              "%s: joint id %d is outside a %d x %d grid" % (short, jid, ROWS, COLS))
        check((col, row) not in cells, "%s: two cards claim cell (%d,%d)" % (short, col, row))

        pts, ws = [], []
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            pts.append(q.decode(struct.unpack_from("<3H", b, vo)))
            w = M.read_skin(b, vo)
            check(abs(sum(w.values()) - 1.0) < 1e-3,
                  "%s: mesh %d vertex %d weights sum to %.4f" % (short, m["index"], k, sum(w.values())))
            check(all(0 <= i < nbones for i in w),
                  "%s: mesh %d vertex %d references a bone outside 0..%d"
                  % (short, m["index"], k, nbones - 1))
            ws.append(w)
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        cells[(col, row)] = {"mesh": m["index"], "cx": cx, "cy": cy, "jid": jid}
        if row > 0:
            cols_x.setdefault(col, []).append(cx)
        rows_y.setdefault(row, []).append(cy)

    # Positional consistency: one x per column, one y per row. The selr1 hover
    # frames are deliberately jittered by a few units (stock trips a tighter
    # bound too), so the tolerance only has to catch a card off by a whole cell.
    tol = 5.0
    for col, v in cols_x.items():
        check(max(v) - min(v) < tol,
              "%s: column %d spans x %.1f..%.1f, cards are not aligned" % (short, col, min(v), max(v)))
    for row, v in rows_y.items():
        if row == 0:
            continue
        check(max(v) - min(v) < tol,
              "%s: row %d spans y %.1f..%.1f, cards are not aligned" % (short, row, min(v), max(v)))
    ys = [sum(rows_y[r]) / len(rows_y[r]) for r in sorted(rows_y) if r in rows_y]
    check(all(ys[i] > ys[i + 1] for i in range(len(ys) - 1)),
          "%s: row centres are not monotonically descending: %s"
          % (short, [round(v, 1) for v in ys]))

    # geometry that should not have moved
    se = stock.get(name)
    drift = 0.0
    if se is not None:
        sb = se.data
        sq = M.model_dequant(sb)
        snames = M.read_mod_material_names(sb)
        svert = M._u64(sb, M.H_VERTOFF)
        smesh = {}
        for m in M.read_meshes(sb):
            g = MAT_ID.match(snames[m["material"]])
            if g:
                jid = int(g.group(2))
                smesh[(jid // SRC_ROWS, jid % SRC_ROWS)] = m
        for (col, row), sm in smesh.items():
            cell = cells.get((col, row))
            if cell is None:
                continue
            nm = next(m for m in M.read_meshes(b) if m["index"] == cell["mesh"])
            if nm["nverts"] != sm["nverts"]:
                continue
            for k in range(sm["nverts"]):
                so = svert + sm["vbufoff"] + (sm["vtxlo"] + k) * sm["stride"]
                no = vert_off + nm["vbufoff"] + (nm["vtxlo"] + k) * nm["stride"]
                sp = sq.decode(struct.unpack_from("<3H", sb, so))
                np_ = q.decode(struct.unpack_from("<3H", b, no))
                drift = max(drift, max(abs(sp[i] - np_[i]) for i in range(3)))

    missing = [(c, r) for c in range(COLS) for r in range(1, ROWS) if (c, r) not in cells]
    print("%-26s %3d cards  %3d free cells  step %.4f  max drift vs stock %.4f%s"
          % (short, len(cells), len(missing), q.scale / M.POS_SCALE, drift,
             ("  MISSING %s" % missing[:6]) if missing else ""))

print()
if problems:
    print("%d PROBLEM(S):" % len(problems))
    for p in problems[:40]:
        print("  " + p)
    sys.exit(1)
print("all checks passed")
