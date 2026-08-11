"""Which (column, row) cells actually have a card in each grid model.

vfn17 binds a portrait by asking cChrTrace__findByJointId for joint
`col * ROWS + row`, and that call returns null rather than failing, so a cell
whose card is missing from the model simply renders nothing while the slot
behind it stays hoverable and selectable. This lists, per model, every cell the
engine will walk and whether a card exists for it.

  UMVC3_ARC, UMVC3_ROWS (default 9), UMVC3_COLS (columns per page, default 8)
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
MAT_ID = re.compile(r"^(.*_m)(\d\d)(_.*)$")

# Cells the banner plate legitimately covers: joint row 0, columns 0-2.
BANNER = {(c, 0) for c in range(3)}

ver, entries = M.read_arc(ARC)
print("%s\n%d columns x %d rows per page, joint id = col * %d + row\n" % (ARC, COLS, ROWS, ROWS))

for e in entries:
    if e.ext != "mod":
        continue
    short = e.name.rsplit("\\", 1)[-1]
    if not CARD_MODEL.match(short):
        continue
    b = e.data
    names = M.read_mod_material_names(b)
    seen = {}
    for m in M.read_meshes(b):
        g = MAT_ID.match(names[m["material"]])
        if not g:
            continue
        jid = int(g.group(2))
        seen.setdefault(jid, []).append(m["index"])

    want = {c * ROWS + r for c in range(COLS) for r in range(ROWS)}
    missing = sorted(j for j in want
                     if j not in seen and (j // ROWS, j % ROWS) not in BANNER)
    extra = sorted(j for j in seen if j not in want)
    dupe = sorted(j for j, v in seen.items() if len(v) > 1)

    flag = "OK " if not missing else "*** "
    print("%s%-26s %3d cards, %3d distinct joints" % (flag, short, sum(len(v) for v in seen.values()), len(seen)))
    if missing:
        print("      MISSING cells (col,row) -> joint: %s"
              % ", ".join("(%d,%d)->%d" % (j // ROWS, j % ROWS, j) for j in missing))
    if extra:
        print("      joints past the grid: %s" % extra)
    if dupe:
        print("      joints with more than one mesh: %s"
              % ", ".join("%d x%d" % (j, len(seen[j])) for j in dupe))
