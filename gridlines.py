"""Build the MvC3 grid as real geometry on the card sphere.

The textured-sheet approach needed a depth offset to sit behind the cards, and
that offset shrank it under perspective - so it needed a scale compensation, and
that fought with the depth separation the cards needed to stay visible. All of
that goes away here: the lines are thin ribbons ON the card sphere, at the cell
boundaries, a few units IN FRONT of the cards. Being in front means they can
never be occluded and never z-fight, and being at the boundaries means the tiny
residual scale error is hidden under the line itself.

They are generated from the same dome formula as `buildplanet.py`, so alignment
is exact by construction - the engine projects lines and cards identically, and
there is no camera model anywhere in this file.

The lines are appended to `chs_meku` as two new meshes (all the verticals, all
the horizontals). That model carries five vertex segments of four different
strides, which `mod_append_meshes` used to refuse; it now appends a new segment
instead of assuming a single one.

They borrow the collapsed page mesh's material, whose texture is `meku_chs01` -
unused once the book is gone - and every vertex points at one small solid patch
painted into it, so the whole grid is one flat colour with no UV mapping to get
wrong.

  UMVC3_ARC / UMVC3_OUT
  UMVC3_WIDTH/HEIGHT/BULGE/APEX   the dome, must match buildplanet.py
  UMVC3_LINE                      line width in game units (default 2.6)
  UMVC3_LINE_STANDOFF             how far in front of the cards (default 3)
  UMVC3_LINE_YAW / _PITCH         how far past the cards lines run, degrees
  UMVC3_LINE_COLOR                "r,g,b" 0..255 (default 60,210,255)
"""
import sys, os, math, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
from io_umvc3_css import grid as G

ARC = os.environ["UMVC3_ARC"]
OUT = os.environ["UMVC3_OUT"]
GW = float(os.environ.get("UMVC3_WIDTH", "900"))
GH = float(os.environ.get("UMVC3_HEIGHT", "560"))
GB = float(os.environ.get("UMVC3_BULGE", "65"))
APEX = float(os.environ.get("UMVC3_APEX", "200"))
WIDTH = float(os.environ.get("UMVC3_LINE", "2.6"))
STANDOFF = float(os.environ.get("UMVC3_LINE_STANDOFF", "3"))
THEXT = math.radians(float(os.environ.get("UMVC3_LINE_YAW", "34")))
PHEXT = math.radians(float(os.environ.get("UMVC3_LINE_PITCH", "26")))
# Which mesh to copy the vertex format and material from. chs_meku carries two
# shaders: mesh 2 is a book page, opaque; mesh 1 is the glow that used to ring
# the book, and shares its shader with every hover and select frame in the
# archive - the translucent one. Lasers want that, and it comes with a different
# vertex format (fmt 9, stride 24, unskinned), which is why this is a template
# rather than a material setting.
TEMPLATE = int(os.environ.get("UMVC3_LINE_TEMPLATE", "2"))
# Textures to paint the lines' colour into, whichever one that shader samples.
TEXTURES = [t.strip() for t in os.environ.get(
    "UMVC3_LINE_TEXTURE", "meku_chs01_BM_NOMIP").split(",") if t.strip()]
# Flood the whole sheet rather than a patch. The translucent shader's sheets are
# tiny accent strips the collapsed book no longer draws, and flooding removes the
# question of which texel a uv lands on.
FLOOD = os.environ.get("UMVC3_LINE_FLOOD", "0") not in ("0", "", "no")
ALPHA = int(os.environ.get("UMVC3_LINE_ALPHA", "255"))
# Run the uv ACROSS the ribbon - 0 at one edge, 1 at the other - so a pixel
# shader has something to fade along. Without it every vertex samples the same
# texel and the line can only ever be one flat colour, however wide it is: there
# is no coordinate to tell the core from the edge.
#
# This costs the constant sample, so it only makes sense with FLOOD: the whole
# sheet is one colour, sampling anywhere returns it, and the uv is free to mean
# something else entirely.
CROSS_UV = os.environ.get("UMVC3_LINE_CROSS_UV", "0") not in ("0", "", "no")
# Push the two families apart in depth. Built at one radius they are exactly
# coplanar wherever they cross, which is z-fighting by construction - and the
# wide halo makes it worse, because the whole ribbon competes for depth, not
# just the visible core. A gap of about a pixel settles every tie the same way
# without being visible as an offset.
SPLIT = float(os.environ.get("UMVC3_LINE_SPLIT", "1.5"))
# Rigid to the root. Inheriting the template page vertex's weights binds the
# lines to the book's page bones, which the engine curls at runtime - correct in
# Blender, which ignores skinning, and visibly adrift in game. Only meaningful on
# the skinned layout; the translucent shader's format carries no weights at all.
LINE_BONE = int(os.environ.get("UMVC3_LINE_BONE", "0"))
ROWS, COLS = 9, 16

_t = 2.0 * math.atan2(GB, GW / 2.0)
R = (GW / 2.0) / math.sin(_t)
YAW, PITCH = _t, math.asin(min(1.0, (GH / 2.0) / R))
DTH = 2.0 * YAW / (COLS - 1)
DPH = 2.0 * PITCH / (ROWS - 1)
CZ = APEX - R
RR = R + STANDOFF                      # the lines' own radius: in front of the cards
HALF = WIDTH / 2.0

# A small solid patch painted into the texture; every vertex samples its middle.
# It sits in the top-left corner, which the collapsed book no longer draws and no
# card maps to, so repainting it cannot disturb anything else sharing the sheet.
PATCH = (16, 48)                       # texels, square
COLOR = tuple(max(0, min(255, int(float(v))))
              for v in os.environ.get("UMVC3_LINE_COLOR", "60,210,255").split(","))


def at(th, ph, r=None):
    r = RR if r is None else r
    return (r * math.sin(th) * math.cos(ph),
            r * math.sin(ph),
            CZ + r * math.cos(th) * math.cos(ph))


def tan_th(th, ph):
    """Unit tangent along increasing longitude."""
    return (math.cos(th), 0.0, -math.sin(th))


def tan_ph(th, ph):
    """Unit tangent along increasing latitude."""
    return (-math.sin(th) * math.sin(ph), math.cos(ph), -math.cos(th) * math.sin(ph))


def ribbon(points):
    """points: [(centre, perpendicular)] -> (positions, triangles).

    Emitted double-sided. The verticals and horizontals are built with the same
    vertex order but perpendiculars that point different ways round, so one of
    the two families comes out back-facing and is culled - the horizontals
    vanished entirely the first time. Winding both ways costs a few thousand
    indices and removes the question."""
    pos, tri = [], []
    for c, p in points:
        pos.append(tuple(c[i] - HALF * p[i] for i in range(3)))
        pos.append(tuple(c[i] + HALF * p[i] for i in range(3)))
    for i in range(len(points) - 1):
        a = 2 * i
        tri += [a, a + 1, a + 3, a, a + 3, a + 2]        # front
        tri += [a, a + 3, a + 1, a, a + 2, a + 3]        # back
    return pos, tri


verticals, vtris = [], []
horizontals, htris = [], []
nv = nh = 0

STEPS_V, STEPS_H = 26, 34
for k in range(-40, 60):
    th = (k - COLS / 2.0) * DTH
    if abs(th) > THEXT:
        continue
    pts = []
    for s in range(STEPS_V + 1):
        ph = -PHEXT + 2 * PHEXT * s / STEPS_V
        pts.append((at(th, ph), tan_th(th, ph)))
    p, t = ribbon(pts)
    base = len(verticals)
    verticals += p
    vtris += [x + base for x in t]
    nv += 1

for m in range(-40, 60):
    ph = (ROWS / 2.0 - m) * DPH
    if abs(ph) > PHEXT:
        continue
    pts = []
    for s in range(STEPS_H + 1):
        th = -THEXT + 2 * THEXT * s / STEPS_H
        pts.append((at(th, ph, RR + SPLIT), tan_ph(th, ph)))
    p, t = ribbon(pts)
    base = len(horizontals)
    horizontals += p
    htris += [x + base for x in t]
    nh += 1

print("grid: %d vertical lines (%d verts), %d horizontal (%d verts)"
      % (nv, len(verticals), nh, len(horizontals)))
print("radius %.0f verticals / %.0f horizontals (cards %.0f), width %.1f units"
      % (RR, RR + SPLIT, R, WIDTH))

ver, entries = M.read_arc(ARC)
e = next(x for x in entries if x.ext == "mod" and G.leaf(x.name) == "chs_meku")
b = e.data
tpl = {m["index"]: m for m in M.read_meshes(b)}[TEMPLATE]
print("template mesh %d: stride %d fmt %d, material %d"
      % (TEMPLATE, tpl["stride"], tpl["fmt"], tpl["material"]))

allp = verticals + horizontals
b, q = G.fit_decode(b, allp)
print("decode step %.4f" % (q.scale / M.POS_SCALE))

# The uv has to be worked out against the sheet actually being painted - these
# range from 1280x720 down to 64x16, and a fraction that lands mid-patch on one
# lands off the edge of another.
targets = [te for te in entries if te.ext == "tex" and G.leaf(te.name) in TEXTURES]
if not targets:
    raise SystemExit("none of %s is in %s" % (TEXTURES, ARC))
if FLOOD:
    UV = (0.5, 0.5)
else:
    _i = M.tex_info(targets[0].data)
    UV = ((PATCH[0] + PATCH[1]) / 2.0 / _i["width"],
          (PATCH[0] + PATCH[1]) / 2.0 / _i["height"])
print("lines sample uv %.4f,%.4f of %s"
      % (UV[0], UV[1], ", ".join(G.leaf(t.name) for t in targets)))

spec = {"template": TEMPLATE, "material": tpl["material"]}
if tpl["stride"] == M.SKIN_STRIDE:
    spec["bone"] = LINE_BONE          # unskinned formats carry no weights to fix


def uvs_for(points):
    """One uv per vertex. ribbon() emits the two edges of each rib in order, so
    the odd/even index IS the side of the line - no extra bookkeeping needed."""
    if not CROSS_UV:
        return [UV] * len(points)
    if not FLOOD:
        raise SystemExit("UMVC3_LINE_CROSS_UV needs UMVC3_LINE_FLOOD: the uv "
                         "stops selecting a colour and starts measuring width")
    return [(UV[0], float(i & 1)) for i in range(len(points))]


specs = [
    dict(spec, positions=verticals, uvs=uvs_for(verticals), indices=vtris),
    dict(spec, positions=horizontals, uvs=uvs_for(horizontals), indices=htris),
]
if CROSS_UV:
    print("uv runs across the ribbon (0 at one edge, 1 at the other)")
before = M._u16(b, M.H_MESHCOUNT)
b = M.mod_append_meshes(b, specs)
print("meshes %d -> %d" % (before, M._u16(b, M.H_MESHCOUNT)))
e.data = b
e.dirty = True

# paint the colour the lines sample
for te in targets:
    info = M.tex_info(te.data)
    W, H = info["width"], info["height"]
    use_alpha = info["fmt"] not in M.BC1_CODES
    # file order, so decode/paint/encode round-trips: the default is bottom-up
    # for Blender and would mirror the rest of the sheet, once per rebuild,
    # while landing the patch in the same place either way
    px = M.decode_bc(info["payload"], W, H, use_alpha, bottom_up=False)
    flat = [0] * (W * H * 4)
    for i in range(W * H * 4):
        flat[i] = int(max(0.0, min(1.0, px[i])) * 255 + 0.5)
    if FLOOD:
        x0, x1, y0, y1 = 0, W, 0, H
    else:
        x0, x1 = min(PATCH[0], W), min(PATCH[1], W)
        y0, y1 = min(PATCH[0], H), min(PATCH[1], H)
    for y in range(y0, y1):
        for x in range(x0, x1):
            o = (y * W + x) * 4
            flat[o], flat[o + 1], flat[o + 2] = COLOR
            flat[o + 3] = ALPHA if use_alpha else 255
    te.data = info["header"] + M.encode_bc(flat, W, H, use_alpha)
    te.dirty = True
    print("  %-28s %4dx%-4d fmt %-3d painted %dx%d rgb%s alpha %s"
          % (G.leaf(te.name), W, H, info["fmt"], x1 - x0, y1 - y0, COLOR,
             ALPHA if use_alpha else "n/a"))

M.write_arc(OUT, ver, entries)
print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
