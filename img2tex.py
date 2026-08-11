"""Encode an image into an MT Framework .tex, matching an existing one.

Run through Blender (it supplies image loading; there is no Python on PATH here):

  blender --background --factory-startup --python img2tex.py -- \
      --image custom.png --like original.tex --out custom.tex

--like copies the reference's width, height, mip count and format code, and the
image is rescaled to match, so the result is a drop-in replacement the game
already knows how to read.
"""
import bpy
import os
import struct
import sys

# format code -> block codec, from surveying every .tex in the game
BC1_CODES = (19, 25)
BC3_CODES = (23, 31, 42)


def parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    out = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            key = argv[i][2:]
            val = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "1"
            out[key] = val
            i += 2
        else:
            i += 1
    return out


def read_tex_header(path):
    with open(path, "rb") as f:
        b = f.read(24)
    if len(b) < 24 or b[:4] != b"TEX\0":
        raise RuntimeError("not a .tex: %s" % path)
    head = struct.unpack_from("<I", b, 4)[0]
    w2 = struct.unpack_from("<I", b, 8)[0]
    w3 = struct.unpack_from("<I", b, 12)[0]
    return {
        "raw": b,
        "head": head,
        "mips": w2 & 0x3F,
        "width": (w2 >> 6) & 0x1FFF,
        "height": (w2 >> 19) & 0x1FFF,
        "fmt": (w3 >> 8) & 0xFF,
    }


def load_pixels(path, width, height):
    """-> flat list of ints, RGBA per pixel, top-down."""
    img = bpy.data.images.load(path, check_existing=False)
    # Read stored values, not a colour-managed version of them: BC blocks hold
    # exactly the bytes the game samples.
    try:
        img.colorspace_settings.name = "Non-Color"
    except (AttributeError, TypeError):
        pass
    if img.size[0] != width or img.size[1] != height:
        print("[img2tex] scaling %dx%d -> %dx%d" % (img.size[0], img.size[1], width, height))
        img.scale(width, height)

    px = list(img.pixels[:])
    out = [0] * (width * height * 4)
    for y in range(height):
        src = (height - 1 - y) * width * 4          # Blender rows are bottom-up
        dst = y * width * 4
        for i in range(width * 4):
            v = px[src + i]
            v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
            out[dst + i] = int(v * 255.0 + 0.5)
    bpy.data.images.remove(img)
    return out


def pack565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def unpack565(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def encode_color_block(block):
    """block: 16 x (r,g,b). Returns 8 bytes, always 4-colour mode."""
    rmin = gmin = bmin = 255
    rmax = gmax = bmax = 0
    for (r, g, b) in block:
        if r < rmin: rmin = r
        if g < gmin: gmin = g
        if b < bmin: bmin = b
        if r > rmax: rmax = r
        if g > gmax: gmax = g
        if b > bmax: bmax = b

    c0 = pack565(rmax, gmax, bmax)
    c1 = pack565(rmin, gmin, bmin)
    if c0 == c1:
        # flat block; c0 > c1 keeps 4-colour mode, indices all reference c0
        if c0 == 0:
            return struct.pack("<HHI", 1, 0, 0)
        return struct.pack("<HHI", c0, c0 - 1, 0)
    if c0 < c1:
        c0, c1 = c1, c0

    e0 = unpack565(c0)
    e1 = unpack565(c1)
    pal = (
        e0,
        e1,
        tuple((2 * e0[k] + e1[k]) // 3 for k in range(3)),
        tuple((e0[k] + 2 * e1[k]) // 3 for k in range(3)),
    )

    bits = 0
    for i, (r, g, b) in enumerate(block):
        best = 0
        bestd = -1
        for j in range(4):
            pr, pg, pb = pal[j]
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if bestd < 0 or d < bestd:
                bestd = d
                best = j
        bits |= best << (2 * i)
    return struct.pack("<HHI", c0, c1, bits)


def encode_alpha_block(alphas):
    """alphas: 16 ints. Returns 8 bytes, 8-value mode."""
    a0 = max(alphas)
    a1 = min(alphas)
    if a0 == a1:
        return bytes([a0, a1, 0, 0, 0, 0, 0, 0])
    pal = [a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)]

    idx = 0
    for i, a in enumerate(alphas):
        best = 0
        bestd = -1
        for j in range(8):
            d = abs(a - pal[j])
            if bestd < 0 or d < bestd:
                bestd = d
                best = j
        idx |= best << (3 * i)
    out = bytearray(8)
    out[0] = a0
    out[1] = a1
    for k in range(6):
        out[2 + k] = (idx >> (8 * k)) & 0xFF
    return bytes(out)


def encode(pixels, width, height, use_alpha):
    data = bytearray()
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    for by in range(bh):
        for bx in range(bw):
            rgb = []
            alpha = []
            for py in range(4):
                y = min(by * 4 + py, height - 1)
                for px_ in range(4):
                    x = min(bx * 4 + px_, width - 1)
                    o = (y * width + x) * 4
                    rgb.append((pixels[o], pixels[o + 1], pixels[o + 2]))
                    alpha.append(pixels[o + 3])
            if use_alpha:
                data += encode_alpha_block(alpha)
            data += encode_color_block(rgb)
    return bytes(data)


def main():
    a = parse_args(sys.argv)
    for req in ("image", "like", "out"):
        if req not in a:
            print("usage: --image <src> --like <reference.tex> --out <dest.tex>")
            sys.exit(2)

    ref = read_tex_header(a["like"])
    if ref["mips"] > 1:
        print("[img2tex] ERROR: reference has %d mips; only single-mip (NOMIP) "
              "textures are supported." % ref["mips"])
        sys.exit(3)
    if ref["fmt"] in BC1_CODES:
        use_alpha = False
        codec = "BC1"
    elif ref["fmt"] in BC3_CODES:
        use_alpha = True
        codec = "BC3"
    else:
        print("[img2tex] ERROR: unknown format code %d in %s" % (ref["fmt"], a["like"]))
        sys.exit(4)

    w, h = ref["width"], ref["height"]
    print("[img2tex] target %dx%d %s (fmt=%d)" % (w, h, codec, ref["fmt"]))

    pixels = load_pixels(os.path.abspath(a["image"]), w, h)
    data = encode(pixels, w, h, use_alpha)

    expect = os.path.getsize(a["like"]) - 24
    if len(data) != expect:
        print("[img2tex] ERROR: produced %d bytes, reference payload is %d" % (len(data), expect))
        sys.exit(5)

    with open(a["out"], "wb") as f:
        f.write(ref["raw"])       # reuse the reference header verbatim
        f.write(data)
    print("[img2tex] wrote %s (%d bytes)" % (a["out"], 24 + len(data)))


main()
