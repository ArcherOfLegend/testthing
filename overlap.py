"""Which meshes in the built grid are wider than one cell, or sit off their cell.

The book page is opaque, so a card that ends up a cell too wide (or a cell too
far over) shows as a page-coloured band swallowing its neighbours.  Prints, per
model, every mesh whose x-extent covers more than one target cell and every mesh
whose centre is not on a cell centre.

  UMVC3_ARC, UMVC3_ROWS (default 9), UMVC3_COLS (default 8)
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
ROWS = int(os.environ.get("UMVC3_ROWS", "9"))
COLS = int(os.environ.get("UMVC3_COLS", "8"))
CARD_MODEL = re.compile(r"^chs_meku_(face|sel\d+|seld\d+|selr\d+)_([ab])(_typeC)?$")
MAT_ID = re.compile(r"^(.*_m)(\d+)(_.*)$")

ver, entries = M.read_arc(ARC)
for e in entries:
    if e.ext != "mod":
        continue
    short = e.name.rsplit("\\", 1)[-1]
    if not CARD_MODEL.match(short):
        continue
    b = e.data
    q = M.model_dequant(b)
    names = M.read_mod_material_names(b)
    vert_off = M._u64(b, 0x48)
    cards = []
    for m in M.read_meshes(b):
        g = MAT_ID.match(names[m["material"]])
        if not g:
            continue
        jid = int(g.group(2))
        pts = []
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            pts.append(q.decode(struct.unpack_from("<3H", b, vo)))
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        cards.append({"mesh": m["index"], "jid": jid, "col": jid // ROWS, "row": jid % ROWS,
                      "x0": lo[0], "x1": hi[0], "y0": lo[1], "y1": hi[1],
                      "cx": (lo[0] + hi[0]) / 2, "cy": (lo[1] + hi[1]) / 2,
                      "cz": (lo[2] + hi[2]) / 2, "z0": lo[2], "z1": hi[2],
                      "w": hi[0] - lo[0], "h": hi[1] - lo[1]})
    if not cards:
        continue
    ws = sorted(c["w"] for c in cards)
    med = ws[len(ws) // 2]
    colx = {}
    for c in cards:
        colx.setdefault(c["col"], []).append(c["cx"])
    colx = {k: sum(v) / len(v) for k, v in colx.items()}
    pitch = abs(colx[max(colx)] - colx[min(colx)]) / (len(colx) - 1) if len(colx) > 1 else 0
    print("=" * 78)
    print("%-26s %3d meshes  cell pitch %.1f  median card w %.1f"
          % (short, len(cards), pitch, med))
    wide = [c for c in cards if c["w"] > pitch * 1.2]
    for c in sorted(wide, key=lambda c: -c["w"]):
        print("   WIDE  mesh %3d jid %3d (col %d row %d) w %6.1f  x %8.1f..%8.1f"
              % (c["mesh"], c["jid"], c["col"], c["row"], c["w"], c["x0"], c["x1"]))
    off = [c for c in cards if abs(c["cx"] - colx[c["col"]]) > pitch * 0.25]
    for c in sorted(off, key=lambda c: -abs(c["cx"] - colx[c["col"]])):
        print("   OFF   mesh %3d jid %3d (col %d row %d) cx %8.1f  col centre %8.1f"
              % (c["mesh"], c["jid"], c["col"], c["row"], c["cx"], colx[c["col"]]))
    zc = {}
    for c in cards:
        zc.setdefault(c["col"], []).append(c["cz"])
    print("   col z  " + "  ".join("%d:%.0f" % (k, sum(v) / len(v))
                                   for k, v in sorted(zc.items())))
    have = {(c["col"], c["row"]) for c in cards}
    miss = [(t, r) for t in range(COLS) for r in range(ROWS) if (t, r) not in have]
    if miss:
        print("   empty cells " + " ".join("%d,%d" % m for m in miss))
