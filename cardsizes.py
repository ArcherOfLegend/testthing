"""Report every card's size, and flag any that are not the size their row says.

verifygrid checks where cards sit, not how big they are - an oversized card
would pass it while punching a hole through the grid on screen.

  UMVC3_ARC, UMVC3_ROWS
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
ROWS = int(os.environ["UMVC3_ROWS"])
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
    vert_off = M._u64(b, M.H_VERTOFF)
    cards = []
    for m in M.read_meshes(b):
        g = MAT_ID.match(names[m["material"]])
        if not g:
            cards.append(("UNNUMBERED", m["index"], 0, 0, 0, 0, 0))
            continue
        jid = int(g.group(2))
        pts = []
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            pts.append(q.decode(struct.unpack_from("<3H", b, vo)))
        w = max(p[0] for p in pts) - min(p[0] for p in pts)
        h = max(p[1] for p in pts) - min(p[1] for p in pts)
        cy = (max(p[1] for p in pts) + min(p[1] for p in pts)) / 2
        cards.append(("card", m["index"], jid, jid // ROWS, jid % ROWS, w, h, cy))

    hs = sorted(c[6] for c in cards if c[0] == "card")
    med = hs[len(hs) // 2]
    odd = [c for c in cards if c[0] != "card" or c[6] > med * 1.6 or c[6] < med * 0.5]
    print("%-26s %3d meshes  median card height %6.2f   %d odd"
          % (short, len(cards), med, len(odd)))
    for c in odd[:12]:
        if c[0] != "card":
            print("      mesh %3d has no numbered material" % c[1])
        else:
            print("      mesh %3d jid %2d (col %d row %2d)  %7.2f wide x %7.2f tall  cy %8.2f"
                  % (c[1], c[2], c[3], c[4], c[5], c[6], c[7]))
