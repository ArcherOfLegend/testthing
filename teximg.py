"""Helper for testing texture round-trips.

  --mode topng   --in <img> --out <png>      full-resolution dump
  --mode compare --a <img> --b <img>         mean/max abs error per channel
"""
import bpy, sys, os


def parse_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    out, i = {}, 0
    while i < len(argv):
        if argv[i].startswith("--"):
            k = argv[i][2:]
            v = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else "1"
            out[k] = v
            i += 2
        else:
            i += 1
    return out


def load_raw(path):
    img = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    try:
        img.colorspace_settings.name = "Non-Color"
    except (AttributeError, TypeError):
        pass
    return img


a = parse_args(sys.argv)
mode = a.get("mode", "")

if mode == "topng":
    img = load_raw(a["in"])
    print("size", img.size[0], img.size[1])
    img.file_format = "PNG"
    img.save_render(os.path.abspath(a["out"]))
    print("wrote", a["out"])

elif mode == "compare":
    ia, ib = load_raw(a["a"]), load_raw(a["b"])
    if tuple(ia.size) != tuple(ib.size):
        print("SIZE MISMATCH", tuple(ia.size), tuple(ib.size)); sys.exit(1)
    pa, pb = list(ia.pixels[:]), list(ib.pixels[:])
    n = len(pa)
    names = "RGBA"
    tot = [0.0] * 4
    mx = [0.0] * 4
    for i in range(0, n, 4):
        for c in range(4):
            d = abs(pa[i + c] - pb[i + c])
            tot[c] += d
            if d > mx[c]:
                mx[c] = d
    px = n // 4
    print("pixels: %d  (%dx%d)" % (px, ia.size[0], ia.size[1]))
    for c in range(4):
        print("  %s  mean=%6.2f/255   max=%6.2f/255" % (names[c], tot[c] / px * 255.0, mx[c] * 255.0))
else:
    print("bad --mode"); sys.exit(2)
