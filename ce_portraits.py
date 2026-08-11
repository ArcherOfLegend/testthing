"""CloneEngine's own portraits are tagged format 42, which the engine does not
decode as BC3 - hence the magenta cards. Decode them the way an ordinary DXT5
reader would and dump PNGs, to see whether CE simply mislabelled plain DXT5.

  UMVC3_DIR   loose .tex directory
  UMVC3_IDS   one CE id per line
  UMVC3_OUT   directory for PNGs
  UMVC3_ONLY  optional comma-separated subset
"""
import bpy, sys, os, struct

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M

DIR = os.environ["UMVC3_DIR"]
IDS = os.environ["UMVC3_IDS"]
OUT = os.environ["UMVC3_OUT"]
ONLY = [s for s in os.environ.get("UMVC3_ONLY", "").split(",") if s]
os.makedirs(OUT, exist_ok=True)


def unpack565(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return ((r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31)


def decode_bc(data, w, h, has_alpha):
    """-> flat RGBA float list, bottom-up (Blender's pixel order)."""
    px = [0.0] * (w * h * 4)
    step = 16 if has_alpha else 8
    o = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            if o + step > len(data):
                break
            alpha = [255] * 16
            q = o
            if has_alpha:
                a0, a1 = data[q], data[q + 1]
                bits = int.from_bytes(data[q + 2:q + 8], "little")
                tbl = [a0, a1]
                if a0 > a1:
                    tbl += [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
                else:
                    tbl += [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
                alpha = [tbl[(bits >> (3 * i)) & 7] for i in range(16)]
                q += 8
            c0, c1 = struct.unpack_from("<HH", data, q)
            idx = struct.unpack_from("<I", data, q + 4)[0]
            e0, e1 = unpack565(c0), unpack565(c1)
            if c0 > c1 or has_alpha:
                cols = [e0, e1,
                        tuple((2 * e0[k] + e1[k]) // 3 for k in range(3)),
                        tuple((e0[k] + 2 * e1[k]) // 3 for k in range(3))]
            else:
                cols = [e0, e1,
                        tuple((e0[k] + e1[k]) // 2 for k in range(3)), (0, 0, 0)]
            for i in range(16):
                x, y = bx + (i & 3), by + (i >> 2)
                if x >= w or y >= h:
                    continue
                c = cols[(idx >> (2 * i)) & 3]
                d = ((h - 1 - y) * w + x) * 4
                px[d] = c[0] / 255.0
                px[d + 1] = c[1] / 255.0
                px[d + 2] = c[2] / 255.0
                px[d + 3] = alpha[i] / 255.0
            o += step
    return px


ids = ONLY or [l.strip() for l in open(IDS) if l.strip()]
made = []
for cid in ids:
    path = os.path.join(DIR, "f_%s00_BM_HQ_NOMIP.tex" % cid)
    if not os.path.exists(path):
        continue
    b = open(path, "rb").read()
    v = M._u32(b, 8)
    w, h = (v >> 6) & 0x1FFF, (v >> 19) & 0x1FFF
    fmt = (M._u32(b, 12) >> 8) & 0xFF
    if not ONLY and fmt != 42:
        continue
    px = decode_bc(b[24:], w, h, fmt not in M.BC1_CODES)
    img = bpy.data.images.new(cid, width=w, height=h, alpha=True)
    img.pixels = px
    img.file_format = "PNG"
    img.filepath_raw = os.path.join(OUT, "%s.png" % cid)
    img.save()
    bpy.data.images.remove(img)
    made.append(cid)

print("decoded %d portraits (fmt %s) to %s" % (len(made), "any" if ONLY else "42", OUT))
print(" ".join(made))
