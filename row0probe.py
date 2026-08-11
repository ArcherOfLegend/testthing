"""Where every row-0 card actually sits, stock vs rebuilt.

Row 0 is the row the CAPCOM/MARVEL banner plate shares with real characters, so
it is the one place where a card can be geometrically correct and still invisible
- covered by the plate - or where the plate can drift off the cells it is meant
to cover. Print the x extent of every mesh in joint row 0 next to the column
pitch taken from row 1, for both archives.

  UMVC3_STOCK, UMVC3_BUILT, UMVC3_MODEL (default chs_meku_face_a)
"""
import sys, os, re, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

MODEL = os.environ.get("UMVC3_MODEL", "chs_meku_face_a")
MAT_ID = re.compile(r"^(.*_m)(\d\d)(_.*)$")


def survey(arc, rows):
    ver, entries = M.read_arc(arc)
    for e in entries:
        if e.ext != "mod" or e.name.rsplit("\\", 1)[-1] != MODEL:
            continue
        b = e.data
        q = M.model_dequant(b)
        names = M.read_mod_material_names(b)
        vert_off = M._u64(b, 0x48)
        out = []
        for m in M.read_meshes(b):
            g = MAT_ID.match(names[m["material"]])
            if not g:
                continue
            jid = int(g.group(2))
            xs = []
            for k in range(m["nverts"]):
                vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
                xs.append(q.decode(struct.unpack_from("<3H", b, vo))[0])
            out.append({"jid": jid, "col": jid // rows, "row": jid % rows,
                        "lo": min(xs), "hi": max(xs), "mat": names[m["material"]]})
        return out
    return []


for label, arc, rows in (("STOCK", os.environ["UMVC3_STOCK"], 7),
                         ("BUILT", os.environ["UMVC3_BUILT"], 9)):
    cards = survey(arc, rows)
    print("=" * 74)
    print("%s  %s   (%d rows per column, %d cards)" % (label, arc, rows, len(cards)))

    r1 = sorted([c for c in cards if c["row"] == 1], key=lambda c: c["col"])
    if r1:
        print("  row 1 columns (the reference pitch):")
        for c in r1:
            print("    col %d  x %8.1f .. %8.1f   width %6.1f" % (c["col"], c["lo"], c["hi"], c["hi"] - c["lo"]))

    r0 = sorted([c for c in cards if c["row"] == 0], key=lambda c: c["col"])
    print("  row 0:")
    have = {c["col"] for c in r0}
    for col in range(max(have) + 1 if have else 0):
        c = next((x for x in r0 if x["col"] == col), None)
        if c is None:
            print("    col %d  -- no card --" % col)
            continue
        w = c["hi"] - c["lo"]
        ref = next((x for x in r1 if x["col"] == col), None)
        note = ""
        if ref:
            rw = ref["hi"] - ref["lo"]
            if w > rw * 1.5:
                note = "  <- WIDE (%.1fx a normal card)" % (w / rw)
            dx = ((c["lo"] + c["hi"]) - (ref["lo"] + ref["hi"])) / 2
            if abs(dx) > 5:
                note += "  offset %+.1f from its column" % dx
        print("    col %d  x %8.1f .. %8.1f   width %6.1f%s" % (col, c["lo"], c["hi"], w, note))

    # which row-1 columns does the row-0 plate physically cover?
    wide = [c for c in r0 if r1 and (c["hi"] - c["lo"]) > 1.5 * (r1[0]["hi"] - r1[0]["lo"])]
    for c in wide:
        covered = [x["col"] for x in r1 if x["lo"] < c["hi"] and x["hi"] > c["lo"]]
        print("  the wide plate at col %d spans x %.1f..%.1f -> covers columns %s"
              % (c["col"], c["lo"], c["hi"], covered))
    print()
