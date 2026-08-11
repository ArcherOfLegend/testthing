"""How far in front of the page does each card sit?

Run against the stock archive it measures the clearance the artists used; run
against a build it says which cards have sunk behind the page (negative) and so
are being drawn over by it.

  UMVC3_ARC, UMVC3_ROWS (default 7)
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
import pagefit

ARC = os.environ["UMVC3_ARC"]
ROWS = int(os.environ.get("UMVC3_ROWS", "7"))
CARD_MODEL = re.compile(r"^chs_meku_(face|sel\d+|seld\d+|selr\d+)_([ab])(_typeC)?$")
MAT_ID = re.compile(r"^(.*_m)(\d+)(_.*)$")

ver, entries = M.read_arc(ARC)
surf = {"a": pagefit.page_surface(entries, "a"),
        "b": pagefit.page_surface(entries, "b")}

for e in entries:
    if e.ext != "mod":
        continue
    short = e.name.rsplit("\\", 1)[-1]
    g = CARD_MODEL.match(short)
    if not g:
        continue
    f = surf[g.group(2)]
    b = e.data
    q = M.model_dequant(b)
    names = M.read_mod_material_names(b)
    vert_off = M._u64(b, M.H_VERTOFF)
    rows = []
    for m in M.read_meshes(b):
        mg = MAT_ID.match(names[m["material"]])
        if not mg:
            continue
        jid = int(mg.group(2))
        pts = []
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            pts.append(q.decode(struct.unpack_from("<3H", b, vo)))
        # worst corner, not the centre: a card can clear at its middle and still
        # be swallowed at an edge where the page has curved forward
        worst = min(p[2] - f(p[0], p[1]) for p in pts)
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        cz = (min(p[2] for p in pts) + max(p[2] for p in pts)) / 2
        rows.append((jid // ROWS, jid % ROWS, jid, cz - f(cx, cy), worst))
    if not rows:
        continue
    rows.sort()
    bad = [r for r in rows if r[4] < 0]
    print("%-26s %2d cards  centre clearance %5.1f..%5.1f   worst-vertex %5.1f"
          % (short, len(rows), min(r[3] for r in rows), max(r[3] for r in rows),
             min(r[4] for r in rows)))
    if bad:
        print("   BEHIND THE PAGE: " + ", ".join(
            "jid %d (c%d r%d) %.1f" % (r[2], r[0], r[1], r[4]) for r in bad[:40]))
