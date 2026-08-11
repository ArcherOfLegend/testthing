"""Repair the CE character portraits the engine cannot decode.

CloneEngine ships its own f_<id>00 portraits tagged format 42. Format 42 is not
BC3 - stock portraits use it, but its colour block holds chroma in a packing
nobody has worked out - so the engine renders CE's files as magenta noise.
Format 19 (BC1) round-trips correctly, which is what every portrait this project
generated already uses.

So: read CE's file the way an ordinary DXT5 reader would, lay the recovered
image into the standard card frame, and write it back at format 19. Where CE's
own art is just a placeholder silhouette that is still what shows, but as a
clean silhouette in a proper frame instead of noise.

  UMVC3_DIR    loose .tex directory (read and written in place)
  UMVC3_IDS    one CE id per line
  UMVC3_REF    a stock .tex to take the header from
  UMVC3_BACKUP directory to copy originals into
  UMVC3_REPORT set to 1 to only report, writing nothing
"""
import bpy, sys, os, struct, shutil

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
import frame_data

DIR = os.environ["UMVC3_DIR"]
IDS = os.environ["UMVC3_IDS"]
REF = os.environ["UMVC3_REF"]
BACKUP = os.environ.get("UMVC3_BACKUP")
REPORT = os.environ.get("UMVC3_REPORT") == "1"
PNG = os.environ.get("UMVC3_PNG")
BC1_FMT = 19
BG_TOP = (0.15, 0.16, 0.20)
BG_BOT = (0.05, 0.05, 0.08)

with open(REF, "rb") as f:
    ref = M.tex_info(f.read())
TW, TH = ref["width"], ref["height"]
hdr = bytearray(ref["header"])
w3 = M._u32(hdr, 12)
struct.pack_into("<I", hdr, 12, (w3 & ~(0xFF << 8)) | (BC1_FMT << 8))
HEADER = bytes(hdr)
X0, Y0, X1, Y1 = frame_data.WINDOW
RW, RH = X1 - X0, Y1 - Y0
FRAME = frame_data.LUM


def unpack565(c):
    return (((c >> 11) & 0x1F) * 255 // 31, ((c >> 5) & 0x3F) * 255 // 63,
            (c & 0x1F) * 255 // 31)


def decode_bc3(data, w, h):
    """-> (rgb top-down bytes, alpha top-down bytes)"""
    rgb = [0] * (w * h * 3)
    al = [255] * (w * h)
    o = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            if o + 16 > len(data):
                break
            a0, a1 = data[o], data[o + 1]
            bits = int.from_bytes(data[o + 2:o + 8], "little")
            tbl = [a0, a1]
            tbl += ([((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)] if a0 > a1
                    else [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255])
            c0, c1 = struct.unpack_from("<HH", data, o + 8)
            idx = struct.unpack_from("<I", data, o + 12)[0]
            e0, e1 = unpack565(c0), unpack565(c1)
            cols = [e0, e1, tuple((2 * e0[k] + e1[k]) // 3 for k in range(3)),
                    tuple((e0[k] + 2 * e1[k]) // 3 for k in range(3))]
            for i in range(16):
                x, y = bx + (i & 3), by + (i >> 2)
                if x >= w or y >= h:
                    continue
                c = cols[(idx >> (2 * i)) & 3]
                p = y * w + x
                rgb[p * 3], rgb[p * 3 + 1], rgb[p * 3 + 2] = c
                al[p] = tbl[(bits >> (3 * i)) & 7]
            o += 16
    return rgb, al


def stats(vals):
    n = len(vals)
    m = sum(vals) / n
    return m, (sum((v - m) ** 2 for v in vals) / n) ** 0.5


ids = [l.strip() for l in open(IDS) if l.strip()]
print("%-14s %-6s %13s %13s  %s" % ("id", "fmt", "rgb mean/sd", "alpha mean/sd", "action"))
fixed, skipped = 0, 0
for cid in ids:
    path = os.path.join(DIR, "f_%s00_BM_HQ_NOMIP.tex" % cid)
    if not os.path.exists(path):
        continue
    b = open(path, "rb").read()
    v = M._u32(b, 8)
    w, h = (v >> 6) & 0x1FFF, (v >> 19) & 0x1FFF
    fmt = (M._u32(b, 12) >> 8) & 0xFF
    if fmt != 42:
        skipped += 1
        continue
    rgb, al = decode_bc3(b[24:], w, h)
    lum = [(rgb[i * 3] * 30 + rgb[i * 3 + 1] * 59 + rgb[i * 3 + 2] * 11) // 100
           for i in range(w * h)]
    lm, ls = stats(lum)
    am, asd = stats(al)

    # The colour block holds a flat-shaded figure and the alpha holds its
    # silhouette mask, so composite the two over the same backing the generated
    # portraits use. That reads as a deliberate "no art yet" placeholder rather
    # than the noise format 42 currently produces.
    xs0, ys0, xs1, ys1 = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if al[y * w + x] > 8:
                xs0, xs1 = min(xs0, x), max(xs1, x)
                ys0, ys1 = min(ys0, y), max(ys1, y)
    if xs1 < xs0:
        xs0, ys0, xs1, ys1 = 0, 0, w - 1, h - 1
    bw, bh = xs1 - xs0 + 1, ys1 - ys0 + 1

    out = [0] * (TW * TH * 4)
    for i in range(TW * TH):
        g = FRAME[i]
        out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = g
        out[i * 4 + 3] = 255
    for ty in range(Y0, Y1):
        t = (ty - Y0) / float(max(1, RH - 1))
        bg = [int((BG_TOP[c] + (BG_BOT[c] - BG_TOP[c]) * t) * 255 + 0.5) for c in range(3)]
        # contain-fit, so the silhouette keeps its proportions in a wide card
        scale = min(RW / float(bw), RH / float(bh))
        dw, dh = max(1, int(bw * scale)), max(1, int(bh * scale))
        ox, oy = X0 + (RW - dw) // 2, Y0 + (RH - dh) // 2
        for tx in range(X0, X1):
            o = (ty * TW + tx) * 4
            out[o], out[o + 1], out[o + 2] = bg
            if not (ox <= tx < ox + dw and oy <= ty < oy + dh):
                continue
            sx = min(w - 1, xs0 + (tx - ox) * bw // dw)
            sy = min(h - 1, ys0 + (ty - oy) * bh // dh)
            a = al[sy * w + sx] / 255.0
            if a <= 0.0:
                continue
            s = (sy * w + sx) * 3
            for c in range(3):
                out[o + c] = int(rgb[s + c] * a + bg[c] * (1.0 - a) + 0.5)
    print("%-14s %-6d %6.1f/%5.1f %6.1f/%5.1f  %s"
          % (cid, fmt, lm, ls, am, asd, "silhouette placeholder -> fmt 19"))
    if PNG:
        os.makedirs(PNG, exist_ok=True)
        img = bpy.data.images.new(cid, width=TW, height=TH, alpha=True)
        img.pixels = [out[((TH - 1 - y) * TW + x) * 4 + c] / 255.0
                      for y in range(TH) for x in range(TW) for c in range(4)]
        img.file_format = "PNG"
        img.filepath_raw = os.path.join(PNG, "%s.png" % cid)
        img.save()
        bpy.data.images.remove(img)
    if REPORT:
        continue
    payload = M.encode_bc(out, TW, TH, False)
    if len(payload) != TW * TH // 2:
        print("   !! payload %d != %d, skipped" % (len(payload), TW * TH // 2))
        continue
    if BACKUP:
        os.makedirs(BACKUP, exist_ok=True)
        dst = os.path.join(BACKUP, os.path.basename(path))
        if not os.path.exists(dst):
            shutil.copy2(path, dst)
    with open(path, "wb") as f:
        f.write(HEADER)
        f.write(payload)
    fixed += 1

print()
print("%d already format 19, %d rewritten%s" % (skipped, fixed, " (report only)" if REPORT else ""))
