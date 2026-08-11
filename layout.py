"""Survey the card grid in the corrected (uniform) decode: which mesh holds
which joint id, where it sits, how big it is, and how much of the lattice span
is still free.

  UMVC3_ARC, UMVC3_ROWS (rows the ids are numbered against, default 7)
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC = os.environ["UMVC3_ARC"]
ROWS = int(os.environ.get("UMVC3_ROWS", "7"))
CARD_MODEL = re.compile(r"^chs_meku_(face|sel\d+|seld\d+|selr\d+)_([ab])(_typeC)?$")
MAT_ID = re.compile(r"^(.*_m)(\d\d)(_.*)$")

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
    parents, local, invb, remap = M.read_bones(b)
    bp = [(w[12], w[13], w[14]) for w in M.bone_world(parents, local)]
    ys = sorted({round(bp[i][1], 1) for i in range(1, len(bp))})

    print("=" * 78)
    print("%s   %s" % (short, q))
    print("  lattice y planes %s   (span %.1f)" % (ys, ys[-1] - ys[0]))
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
                      "cx": (lo[0] + hi[0]) / 2, "cy": (lo[1] + hi[1]) / 2, "cz": (lo[2] + hi[2]) / 2,
                      "w": hi[0] - lo[0], "h": hi[1] - lo[1], "n": m["nverts"]})
    print("  %4s %4s %4s %4s %9s %9s %8s %8s %5s" %
          ("mesh", "jid", "col", "row", "cx", "cy", "cz", "height", "nv"))
    for c in sorted(cards, key=lambda c: (c["col"], c["row"])):
        print("  %4d %4d %4d %4d %9.2f %9.2f %8.2f %8.2f %5d" %
              (c["mesh"], c["jid"], c["col"], c["row"], c["cx"], c["cy"],
               c["cz"], c["h"], c["n"]))
    normal = [c for c in cards if c["row"] > 0]
    if normal:
        rows = sorted({round(c["cy"], 1) for c in normal})
        pitch = (max(rows) - min(rows)) / (len(rows) - 1) if len(rows) > 1 else 0
        lo = min(c["cy"] - c["h"] / 2 for c in cards)
        hi = max(c["cy"] + c["h"] / 2 for c in cards)
        print("  normal rows at y %s" % rows)
        print("  pitch %.2f   card h %.2f   grid spans y %.1f..%.1f   lattice %.1f..%.1f"
              % (pitch, sum(c["h"] for c in normal) / len(normal), lo, hi, ys[0], ys[-1]))
    break
