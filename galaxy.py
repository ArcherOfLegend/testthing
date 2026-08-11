"""Paint a galaxy over the character-select backdrop.

`meku_menu_co00_BM_NOMIP` is the full-screen panel behind the whole screen -
identified by flooding each 1280x720 candidate with a different flat colour and
seeing which one the screen turned. It is 1280x720 and format 19 (BC1), which
maps 1:1 to the display and is the one format this pipeline writes correctly.

The art is built to sit *behind a grid of portraits*, so it deliberately keeps
the middle calm: nebula detail and star density rise toward the edges, and the
centre stays dark so the cards read against it. A planet limb sits low enough to
clear the bottom row.

Nebula is generated at low resolution and bilinearly upsampled - clouds are
smooth, and 921,600 pixels of multi-octave noise in Python is not.

  UMVC3_ARC   archive to read
  UMVC3_OUT   archive to write
  UMVC3_SEED  vary the sky (default 7)
  UMVC3_PNG   optional: also dump the image for inspection
"""
import sys, os, math, random

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
from io_umvc3_css import grid as G
from mathutils import Vector, noise

ARC = os.environ["UMVC3_ARC"]
OUT = os.environ["UMVC3_OUT"]
SEED = int(os.environ.get("UMVC3_SEED", "7"))
PNG = os.environ.get("UMVC3_PNG")
TARGET = "meku_menu_co00_BM_NOMIP"

W, H = 1280, 720
NW, NH = 160, 90                      # nebula lattice, upsampled to full size
random.seed(SEED)


def fbm(x, y, z, octaves=5, lac=2.0, gain=0.5):
    amp, freq, total, norm = 1.0, 1.0, 0.0, 0.0
    for _ in range(octaves):
        total += amp * noise.noise(Vector((x * freq, y * freq, z * freq)))
        norm += amp
        amp *= gain
        freq *= lac
    return total / norm                # -1..1


def build_nebula(z, scale):
    """Low-res fBm field in 0..1."""
    f = []
    for j in range(NH):
        row = []
        for i in range(NW):
            v = fbm(i / float(NW) * scale, j / float(NH) * scale * (NH / float(NW)), z)
            row.append(max(0.0, min(1.0, v * 0.5 + 0.5)))
        f.append(row)
    return f


def sample(f, u, v):
    """Bilinear lookup into a low-res field, u/v in 0..1."""
    x = max(0.0, min(NW - 1.001, u * (NW - 1)))
    y = max(0.0, min(NH - 1.001, v * (NH - 1)))
    x0, y0 = int(x), int(y)
    tx, ty = x - x0, y - y0
    a = f[y0][x0] * (1 - tx) + f[y0][x0 + 1] * tx
    b = f[y0 + 1][x0] * (1 - tx) + f[y0 + 1][x0 + 1] * tx
    return a * (1 - ty) + b * ty


print("generating nebula fields...")
violet = build_nebula(0.0, 3.2)
teal = build_nebula(11.3, 4.7)
dust = build_nebula(23.7, 9.0)

# The grid of cards occupies roughly the middle 670 x 436 px. Keep that area
# quiet so the portraits have something plain to sit on.
CX, CY = W / 2.0, H / 2.0
GRID_RX, GRID_RY = 400.0, 280.0

# A planet limb, centred well below the frame so its edge clears the bottom row.
PL_X, PL_Y, PL_R = 640.0, 1250.0, 640.0

print("painting %dx%d..." % (W, H))
px = [0] * (W * H * 4)
for y in range(H):
    v = y / float(H - 1)
    for x in range(W):
        u = x / float(W - 1)
        # how far outside the card grid this pixel is, 0 in the middle -> 1 out
        dx = (x - CX) / GRID_RX
        dy = (y - CY) / GRID_RY
        out = max(0.0, min(1.0, (math.sqrt(dx * dx + dy * dy) - 0.75) / 0.9))

        base = 0.030 + 0.020 * v                      # deep space, faint gradient
        r, g, b = base * 0.55, base * 0.60, base * 1.25

        n1 = sample(violet, u, v)
        n1 = max(0.0, n1 - 0.45) / 0.55
        amt = n1 * n1 * (0.22 + 0.85 * out)
        r += amt * 0.70; g += amt * 0.18; b += amt * 0.95      # violet / magenta

        n2 = sample(teal, u, v)
        n2 = max(0.0, n2 - 0.55) / 0.45
        amt = n2 * n2 * (0.14 + 0.60 * out)
        r += amt * 0.05; g += amt * 0.45; b += amt * 0.55      # teal

        n3 = sample(dust, u, v)
        amt = max(0.0, n3 - 0.62) * (0.30 + 0.70 * out) * 0.55
        r += amt * 0.55; g += amt * 0.42; b += amt * 0.75      # fine dust

        # planet limb across the bottom
        pd = math.hypot(x - PL_X, y - PL_Y)
        if pd < PL_R:
            k = 1.0 - pd / PL_R
            r *= 0.20; g *= 0.22; b *= 0.30                     # dark body
            rim = max(0.0, 1.0 - (PL_R - pd) / 26.0)
            r += rim * 0.35; g += rim * 0.60; b += rim * 1.00   # lit atmosphere
        elif pd < PL_R + 60.0:
            k = 1.0 - (pd - PL_R) / 60.0
            r += k * k * 0.10; g += k * k * 0.18; b += k * k * 0.30

        o = (y * W + x) * 4
        px[o] = r; px[o + 1] = g; px[o + 2] = b; px[o + 3] = 1.0

print("scattering stars...")
for _ in range(2600):
    x, y = random.randrange(W), random.randrange(H)
    dx = (x - CX) / GRID_RX
    dy = (y - CY) / GRID_RY
    out = max(0.0, min(1.0, (math.sqrt(dx * dx + dy * dy) - 0.6) / 0.9))
    if random.random() > 0.25 + 0.75 * out:        # thinner over the grid
        continue
    if math.hypot(x - PL_X, y - PL_Y) < PL_R:      # not through the planet
        continue
    b = random.random() ** 2.2
    o = (y * W + x) * 4
    for c, k in ((0, 0.85), (1, 0.90), (2, 1.0)):
        px[o + c] = min(1.0, px[o + c] + b * k)

for _ in range(90):                                # a few with a soft halo
    x, y = random.randrange(W), random.randrange(H)
    if math.hypot(x - PL_X, y - PL_Y) < PL_R:
        continue
    tint = random.choice(((1.0, 0.85, 0.75), (0.75, 0.85, 1.0), (1.0, 1.0, 1.0)))
    for jy in range(-3, 4):
        for jx in range(-3, 4):
            xx, yy = x + jx, y + jy
            if not (0 <= xx < W and 0 <= yy < H):
                continue
            d = math.hypot(jx, jy)
            k = max(0.0, 1.0 - d / 3.2) ** 2.5
            o = (yy * W + xx) * 4
            for c in range(3):
                px[o + c] = min(1.0, px[o + c] + k * tint[c])

# --- the MvC3 grid ---------------------------------------------------------
# Lines on the same sphere the cards sit on, drawn at cell BOUNDARIES so they
# fall between characters, and continued outward at the same angular pitch until
# they leave the frame - which is what makes the grid read as infinite.
#
# The projection is orthographic. Measured off a screenshot by autocorrelating
# the column profile: 15 column gaps span 660 px for 900 game units, i.e. 1.364
# units per pixel, with no scale change between the dome's apex (z 200) and its
# rim (z 135). Under orthographic projection a line of constant latitude has a
# constant screen y, so the horizontals come out straight and only the verticals
# curve - exactly the vanilla look.
if os.environ.get("UMVC3_GRID", "1") != "0":
    UPP = float(os.environ.get("UMVC3_UPP", "1.364"))
    GW = float(os.environ.get("UMVC3_WIDTH", "900"))
    GH = float(os.environ.get("UMVC3_HEIGHT", "560"))
    GB = float(os.environ.get("UMVC3_BULGE", "65"))
    GROWS, GCOLS = 9, 16
    _t = 2.0 * math.atan2(GB, GW / 2.0)
    GR = (GW / 2.0) / math.sin(_t)
    GYAW, GPITCH = _t, math.asin(min(1.0, (GH / 2.0) / GR))
    DTH = 2.0 * GYAW / (GCOLS - 1)
    DPH = 2.0 * GPITCH / (GROWS - 1)

    def proj(th, ph):
        return (CX + (GR * math.sin(th) * math.cos(ph)) / UPP,
                CY - (GR * math.sin(ph)) / UPP)

    def stamp(fx, fy, k):
        """Additive blue line with a soft halo."""
        xi, yi = int(fx), int(fy)
        for jy in range(-2, 3):
            for jx in range(-2, 3):
                x, y = xi + jx, yi + jy
                if not (0 <= x < W and 0 <= y < H):
                    continue
                d = math.hypot(fx - x, fy - y)
                a = k * max(0.0, 1.0 - d / 2.3) ** 2
                if a <= 0.0:
                    continue
                o = (y * W + x) * 4
                px[o] = min(1.0, px[o] + a * 0.16)
                px[o + 1] = min(1.0, px[o + 1] + a * 0.55)
                px[o + 2] = min(1.0, px[o + 2] + a * 1.00)

    # how far out the lines have to go to leave a 1280x720 frame
    def ang_for(half_px, radius):
        s = min(0.999, half_px * UPP / radius)
        return math.asin(s)

    n_col = int(ang_for(W / 2.0 + 40, GR) / DTH) + 1
    n_row = int(ang_for(H / 2.0 + 40, GR) / DPH) + 1
    print("grid: +-%d columns, +-%d rows of lines (cards use %d x %d)"
          % (n_col, n_row, GCOLS, GROWS))

    TH_MAX = ang_for(W / 2.0 + 60, GR)
    PH_MAX = ang_for(H / 2.0 + 60, GR)

    # verticals: constant longitude, sampled along latitude
    for i in range(-n_col, n_col + 1):
        th = (i + 0.5) * DTH
        if abs(th) > TH_MAX:
            continue
        fade = max(0.25, 1.0 - (abs(th) / TH_MAX) ** 2 * 0.6)
        steps = 900
        for s in range(steps + 1):
            ph = -PH_MAX + (2 * PH_MAX) * s / steps
            x, y = proj(th, ph)
            if -4 <= x < W + 4 and -4 <= y < H + 4:
                stamp(x, y, 0.55 * fade)
    # horizontals: constant latitude
    for j in range(-n_row, n_row + 1):
        ph = (j + 0.5) * DPH
        if abs(ph) > PH_MAX:
            continue
        fade = max(0.25, 1.0 - (abs(ph) / PH_MAX) ** 2 * 0.6)
        steps = 1400
        for s in range(steps + 1):
            th = -TH_MAX + (2 * TH_MAX) * s / steps
            x, y = proj(th, ph)
            if -4 <= x < W + 4 and -4 <= y < H + 4:
                stamp(x, y, 0.55 * fade)

# to bytes, top-down, which is what encode_bc wants
flat = [0] * (W * H * 4)
for i in range(W * H):
    for c in range(3):
        flat[i * 4 + c] = int(max(0.0, min(1.0, px[i * 4 + c])) * 255 + 0.5)
    flat[i * 4 + 3] = 255

if PNG:
    import bpy
    img = bpy.data.images.new("galaxy", width=W, height=H, alpha=True)
    # flat is top-down; Blender's pixel buffer is bottom-up
    buf = []
    for y in range(H - 1, -1, -1):
        o = y * W * 4
        buf.extend(v / 255.0 for v in flat[o:o + W * 4])
    img.pixels = buf
    img.file_format = "PNG"
    img.filepath_raw = PNG
    img.save()
    print("dumped", PNG)

print("encoding BC1...")
payload = M.encode_bc(flat, W, H, False)

ver, entries = M.read_arc(ARC)
hit = 0
for e in entries:
    if e.ext == "tex" and G.leaf(e.name) == TARGET:
        info = M.tex_info(e.data)
        if len(payload) != len(info["payload"]):
            raise SystemExit("payload %d != %d" % (len(payload), len(info["payload"])))
        e.data = info["header"] + payload
        e.dirty = True
        hit += 1
        print("repainted %s (%dx%d fmt %d)" % (TARGET, info["width"], info["height"],
                                               info["fmt"]))
if not hit:
    raise SystemExit("%s not found in %s" % (TARGET, ARC))
M.write_arc(OUT, ver, entries)
print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
