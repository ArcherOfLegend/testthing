"""Header-bbox probe: change only the bounding box, touch no vertex.

  face_a (left page)  bbmin.y and bbmax.y both -100  -> pure translation
  face_b (right page) bbmax.y +200 only              -> pure extent change

The selection overlays (sel*/selr*/seld*) are left alone, so they stay as a
fixed reference grid over both pages.

  left page moves down, right page stretches  -> engine reads the header box per axis
  left page moves down, right page unchanged  -> header offset, uniform scale from elsewhere
  neither moves                               -> the inverse-bind matrices carry both

  UMVC3_ARC, UMVC3_OUT
"""
import sys, os, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

ARC, OUT = os.environ["UMVC3_ARC"], os.environ["UMVC3_OUT"]
ver, entries = M.read_arc(ARC)

for e in entries:
    if e.ext != "mod":
        continue
    short = e.name.rsplit("\\", 1)[-1]
    if short not in ("chs_meku_face_a", "chs_meku_face_b"):
        continue
    b = bytearray(e.data)
    mn, mx, ext = M.read_bbox(bytes(b))
    if short == "chs_meku_face_a":
        struct.pack_into("<f", b, M.H_BBMIN + 4, mn[1] - 100.0)
        struct.pack_into("<f", b, M.H_BBMAX + 4, mx[1] - 100.0)
        what = "translate y by -100"
    else:
        struct.pack_into("<f", b, M.H_BBMAX + 4, mx[1] + 200.0)
        what = "grow ext.y by +200"
    e.data = bytes(b)
    e.dirty = True
    nmn, nmx, next_ = M.read_bbox(e.data)
    print("%-18s %-22s  min.y %8.3f -> %8.3f   max.y %8.3f -> %8.3f   ext.y %8.3f -> %8.3f"
          % (short, what, mn[1], nmn[1], mx[1], nmx[1], ext[1], next_[1]))

M.write_arc(OUT, ver, entries)
print("\nwrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
