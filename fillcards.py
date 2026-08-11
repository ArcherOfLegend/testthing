"""Make each portrait fill its whole grid cell.

A card's UVs span the entire 128x128 portrait texture, but only texels
(8,44)..(120,120) are the photograph - the rest is the torn-photo frame and its
margin. So the visible portrait sits inset inside its cell and cannot reach the
grid lines. Retargeting each card's UVs to the art window crops the frame away
and the photo fills the cell edge to edge.

The window is 112 x 76 texels (1.47:1) and a cell is 0.90:1, so filling it
directly would squash every face by 0.61. Cropping the window to the cell's
aspect first - taking the middle 69 of its 112 texels - fills the cell with no
distortion at all, which also fixes the ~0.58 horizontal squash the portraits
have carried since they were first generated.

Only the `face` models are touched: the overlays carry highlight frames, not
photographs, and the banner plate carries the RANDOM/CAPCOM logo, which cropping
would ruin.

  UMVC3_ARC / UMVC3_OUT
  UMVC3_WIDTH / UMVC3_HEIGHT   the dome, to derive the cell aspect
"""
import sys, os, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
from io_umvc3_css import grid as G
from io_umvc3_css import frame_data

ARC = os.environ["UMVC3_ARC"]
OUT = os.environ["UMVC3_OUT"]
GW = float(os.environ.get("UMVC3_WIDTH", "900"))
GH = float(os.environ.get("UMVC3_HEIGHT", "560"))
ROWS, COLS = 9, 16

S = float(frame_data.SIZE)
X0, Y0, X1, Y1 = frame_data.WINDOW
win_w, win_h = float(X1 - X0), float(Y1 - Y0)

# Take the aspect from the cards themselves rather than recomputing it from the
# dome settings - it stays right whatever those are, and it cannot drift out of
# step with buildplanet.py the way a second copy of the formula can.
_ver, _entries = M.read_arc(ARC)
_face = next(x for x in _entries if x.ext == "mod" and (G.model_kind(x.name) or ("",))[0] == "face")
_cards = G.read_cards(_face.data, rows=ROWS)
_normal, _ = G.split_banners(_cards)
CELL_ASPECT = (sum(c["w"] for c in _normal) / len(_normal)) / \
              (sum(c["h"] for c in _normal) / len(_normal))

# crop the window to the cell's aspect, centred, so nothing is stretched
want_w = win_h * CELL_ASPECT
if want_w <= win_w:
    cx = (X0 + X1) / 2.0
    ax0, ax1 = cx - want_w / 2.0, cx + want_w / 2.0
    ay0, ay1 = float(Y0), float(Y1)
else:                                   # cell is wider than the window
    want_h = win_w / CELL_ASPECT
    cy = (Y0 + Y1) / 2.0
    ax0, ax1 = float(X0), float(X1)
    ay0, ay1 = cy - want_h / 2.0, cy + want_h / 2.0
U0, U1 = ax0 / S, ax1 / S
V0, V1 = ay0 / S, ay1 / S
print("cell aspect %.3f; art window %dx%d texels -> crop %.0fx%.0f" %
      (CELL_ASPECT, X1 - X0, Y1 - Y0, ax1 - ax0, ay1 - ay0))
print("uv target: u %.4f..%.4f  v %.4f..%.4f\n" % (U0, U1, V0, V1))

ver, entries = _ver, _entries
total = 0
for e in entries:
    kind = G.model_kind(e.name) if e.ext == "mod" else None
    if not kind or kind[0] != "face":
        continue
    b = bytearray(e.data)
    vert_off = M._u64(b, M.H_VERTOFF)
    cards = G.read_cards(bytes(b), rows=ROWS, with_verts=True)
    _normal, banners = G.split_banners(cards)
    banner_ix = {c["index"] for c in banners}
    n = 0
    for c in cards:
        if c["index"] in banner_ix:            # the RANDOM / CAPCOM plate
            continue
        lay = M.layout_for(c["fmt"], c["stride"])
        if lay is None or lay["uv0"] is None:
            continue
        base = vert_off + c["vbufoff"] + c["vtxlo"] * c["stride"]
        uv = []
        for k in range(c["nverts"]):
            vo = base + k * c["stride"]
            uv.append((M._half(b, vo + lay["uv0"]), M._half(b, vo + lay["uv0"] + 2)))
        umin = min(u for u, _ in uv); umax = max(u for u, _ in uv)
        vmin = min(v for _, v in uv); vmax = max(v for _, v in uv)
        if umax - umin < 1e-6 or vmax - vmin < 1e-6:
            continue
        # normalise the card's own uv rectangle onto the art window, so whatever
        # internal structure the quad has is preserved
        for k in range(c["nverts"]):
            vo = base + k * c["stride"]
            u = (uv[k][0] - umin) / (umax - umin)
            v = (uv[k][1] - vmin) / (vmax - vmin)
            struct.pack_into("<e", b, vo + lay["uv0"], float(U0 + u * (U1 - U0)))
            struct.pack_into("<e", b, vo + lay["uv0"] + 2, float(V0 + v * (V1 - V0)))
        n += 1
    e.data = bytes(b)
    e.dirty = True
    total += n
    print("%-26s %3d cards re-mapped" % (G.leaf(e.name), n))

M.write_arc(OUT, ver, entries)
print("\n%d cards total; wrote %s (%d bytes)" % (total, OUT, os.path.getsize(OUT)))
