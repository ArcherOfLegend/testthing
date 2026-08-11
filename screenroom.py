"""Measure how much vertical room the comic book actually has on screen.

Finds the rows the book occupies (saturated blue/red page colour) and the rows
covered by the 2D overlays (near-black full-width bands: the CHARACTER SELECT
banner and the bottom control bar), so a stretch factor can be chosen from
numbers rather than eyeballing.

  UMVC3_IN
"""
import bpy, os

IN = os.environ["UMVC3_IN"]
img = bpy.data.images.load(IN)
w, h = img.size
px = list(img.pixels[:])


def row(y):
    o = (h - 1 - y) * w * 4
    return [(px[o + x * 4], px[o + x * 4 + 1], px[o + x * 4 + 2]) for x in range(w)]


# The left page is the only large blue-dominant area in this x band; the
# background comic art outside the book is what fooled a wider window.
PX0, PX1 = int(w * 0.30), int(w * 0.45)
BX0, BX1 = int(w * 0.36), int(w * 0.64)

page_rows, dark_rows = [], []
for y in range(h):
    r = row(y)
    page = sum(1 for x in range(PX0, PX1)
               if r[x][2] > r[x][0] * 1.35 and r[x][2] > 0.18 and r[x][2] < 0.85)
    dark = sum(1 for x in range(BX0, BX1) if max(r[x]) < 0.12)
    if page > (PX1 - PX0) * 0.30:
        page_rows.append(y)
    if dark > (BX1 - BX0) * 0.85:
        dark_rows.append(y)


def runs(v):
    out = []
    for y in v:
        if out and y == out[-1][1] + 1:
            out[-1][1] = y
        else:
            out.append([y, y])
    return [(a, b) for a, b in out if b - a > 3]


print("image %dx%d" % (w, h))
print("book (page colour) rows: %s" % runs(page_rows))
print("full-width dark bands  : %s" % runs(dark_rows))
if page_rows:
    top, bot = min(page_rows), max(page_rows)
    print()
    print("book spans y %d..%d  (%d px)" % (top, bot, bot - top))
    bands = runs(dark_rows)
    above = max([b for a, b in bands if b < top] or [0])
    below = min([a for a, b in bands if a > bot] or [h])
    print("clear band between overlays: y %d..%d  (%d px)" % (above, below, below - above))
    print("headroom if the book fills it: x%.3f" % ((below - above) / float(bot - top)))
