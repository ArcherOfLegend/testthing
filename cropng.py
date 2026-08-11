"""Crop and magnify a region of a saved screenshot, so old shots can be compared
against new ones without relaunching the game.

  UMVC3_IN, UMVC3_OUT, UMVC3_RECT = x,y,w,h  , UMVC3_ZOOM (default 4)
"""
import bpy, os

IN = os.environ["UMVC3_IN"]
OUT = os.environ["UMVC3_OUT"]
X, Y, W, H = [int(v) for v in os.environ["UMVC3_RECT"].split(",")]
Z = int(os.environ.get("UMVC3_ZOOM", "4"))

img = bpy.data.images.load(IN)
sw, sh = img.size
px = list(img.pixels[:])
out = bpy.data.images.new("crop", width=W * Z, height=H * Z, alpha=True)
dst = [0.0] * (W * Z * H * Z * 4)
for ty in range(H * Z):
    sy = Y + ty // Z
    if not (0 <= sy < sh):
        continue
    srow = (sh - 1 - sy) * sw
    drow = (H * Z - 1 - ty) * W * Z
    for tx in range(W * Z):
        sx = X + tx // Z
        if not (0 <= sx < sw):
            continue
        s, d = (srow + sx) * 4, (drow + tx) * 4
        dst[d:d + 4] = px[s:s + 4]
out.pixels = dst
out.file_format = "PNG"
out.filepath_raw = OUT
out.save()
print("wrote %s (%dx%d from %s at %d,%d)" % (OUT, W * Z, H * Z, IN, X, Y))
