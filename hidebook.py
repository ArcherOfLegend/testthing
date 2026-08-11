"""Collapse chosen meshes of a model so they stop drawing.

Used to retire the comic book once the cards have been moved onto the dome:
`chs_meku`'s six page meshes and two covers are what make the screen read as an
open book, and nothing else depends on them.

**How it hides them matters.** Setting every vertex to one *position* is not
enough - these meshes are skinned to a 69-bone rig, so vertices sharing a
position but not their weights get pulled apart again the moment the book
animates, and the mesh reappears as a folded blob. Setting every vertex to a
copy of vertex 0's **whole record** avoids that: byte-identical vertices carry
identical weights, so they transform identically no matter what the rig does,
and every triangle stays zero-area.

It also means this needs no knowledge of the vertex layout, which is worth
having here - `chs_meku` mixes strides 12, 24, 28 and 40 across formats 9, 57
and 65, and only fmt 57 stride 40 has ever been decoded properly.

Reversible: nothing is removed, no table changes size, no offsets move. Rebuild
from the source archive to get the book back.

  UMVC3_ARC     archive to read
  UMVC3_OUT     archive to write
  UMVC3_MODEL   model to edit (default chs_meku)
  UMVC3_HIDE    comma-separated mesh indices (default the pages and covers)
"""
import sys, os, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
from io_umvc3_css import grid as G

ARC = os.environ["UMVC3_ARC"]
OUT = os.environ["UMVC3_OUT"]
MODEL = os.environ.get("UMVC3_MODEL", "chs_meku")
# 2, 7, 8, 9, 10, 11 are the six pages; 5 and 6 the two covers. 0, 1, 3 and 4
# are the backdrop panel and two slivers, which are all that is left holding the
# screen together until a galaxy replaces them.
HIDE = [int(v) for v in os.environ.get("UMVC3_HIDE", "2,5,6,7,8,9,10,11").split(",")]

ver, entries = M.read_arc(ARC)
e = next((x for x in entries if x.ext == "mod" and G.leaf(x.name) == MODEL), None)
if e is None:
    raise SystemExit("no model %r in %s" % (MODEL, ARC))

b = bytearray(e.data)
q = M.model_dequant(bytes(b))
vert_off = M._u64(b, M.H_VERTOFF)
meshes = {m["index"]: m for m in M.read_meshes(bytes(b))}

print("%s: %d meshes, hiding %s\n" % (MODEL, len(meshes), HIDE))
for mi in HIDE:
    m = meshes.get(mi)
    if m is None:
        print("  mesh %d does not exist, skipped" % mi)
        continue
    base = vert_off + m["vbufoff"] + m["vtxlo"] * m["stride"]
    first = bytes(b[base:base + m["stride"]])
    before = []
    for k in range(m["nverts"]):
        vo = base + k * m["stride"]
        before.append(q.decode(struct.unpack_from("<3H", b, vo)))
    for k in range(1, m["nverts"]):
        b[base + k * m["stride"]: base + (k + 1) * m["stride"]] = first
    span = max(max(p[i] for p in before) - min(p[i] for p in before) for i in range(3))
    print("  mesh %2d  stride %2d fmt %2d  %4d verts  was %6.0f units across -> a point"
          % (mi, m["stride"], m["fmt"], m["nverts"], span))

M.write_bbox(b, *M.mod_geometry_bounds(bytes(b)))
e.data = bytes(b)
e.dirty = True
M.write_arc(OUT, ver, entries)
print("\nwrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
