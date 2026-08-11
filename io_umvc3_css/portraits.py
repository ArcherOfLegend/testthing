"""Turn an ordinary image into a character-select portrait `.tex`.

This is `import_portraits.py`'s pipeline as a function, so the addon can build a
portrait for a card the moment you assign a character to it.

Two things it has to get right:

  * **The white torn photo border is part of the portrait image, not the card.**
    It is identical in every stock portrait, so `frame_template.py` recovered it
    by comparing a spread of them - pixels that do not vary are frame, pixels
    that do are the photo. Art goes inside that window, the frame goes back over
    the margin.
  * **Write format 19 (BC1), never 42.** Stock portraits are 42, whose packing
    has never been worked out; a textbook DXT5 chart came back from the game as
    two flat bands. 19 round-trips correctly. It costs alpha, which does not
    matter - the cards are opaque.
"""
import struct

from . import frame_data
from . import mod as M

BC1_FMT = 19
BG_TOP = (0.15, 0.16, 0.20)
BG_BOT = (0.05, 0.05, 0.08)

# The art window is 112x76 texels (1.47:1). A card of a different shape squashes
# whatever is in it, so cropping the source to the CARD's aspect first and then
# stretching it to fill the window cancels that out. Defaults to the window's own
# aspect, which is a plain cover-fit and matches every portrait already
# installed - correcting some and not others looks worse than a uniform squash.
X0, Y0, X1, Y1 = frame_data.WINDOW
WINDOW_ASPECT = float(X1 - X0) / float(Y1 - Y0)


def image_rgba(img):
    """(pixels bottom-up RGBA floats, width, height) for a Blender image."""
    return list(img.pixels[:]), img.size[0], img.size[1]


def build(pixels, sw, sh, reference, card_aspect=None):
    """Fit an image into the art window and lay the frame back over it.

    `pixels` is Blender's bottom-up RGBA float list. `reference` is any stock
    portrait `.tex`, used for its header. -> .tex bytes at format 19.
    """
    info = M.tex_info(reference)
    if info is None:
        raise RuntimeError("reference is not a .tex")
    tw, th = info["width"], info["height"]
    if tw != frame_data.SIZE:
        raise RuntimeError("frame template is %d px, reference is %d"
                           % (frame_data.SIZE, tw))
    aspect = card_aspect or WINDOW_ASPECT
    rw, rh = X1 - X0, Y1 - Y0
    frame = frame_data.LUM

    def at(x, y):                      # y top-down into a bottom-up buffer
        return ((sh - 1 - y) * sw + x) * 4

    # trim fully transparent margin so the subject fills the window
    xs0, ys0, xs1, ys1 = sw, sh, -1, -1
    for y in range(sh):
        row = (sh - 1 - y) * sw * 4
        for x in range(sw):
            if pixels[row + x * 4 + 3] > 0.02:
                if x < xs0: xs0 = x
                if x > xs1: xs1 = x
                if y < ys0: ys0 = y
                if y > ys1: ys1 = y
    if xs1 < xs0:
        raise RuntimeError("the image is fully transparent")
    bw, bh = xs1 - xs0 + 1, ys1 - ys0 + 1

    # Stock portraits are close crops that fill the frame, so crop rather than
    # letterbox, anchored at the top - these are busts and the head is the part
    # worth keeping.
    if bw / float(bh) > aspect:
        cw, ch = max(1, int(round(bh * aspect))), bh
    else:
        cw, ch = bw, max(1, int(round(bw / aspect)))
    cw, ch = min(cw, bw), min(ch, bh)
    cx0, cy0 = xs0 + (bw - cw) // 2, ys0

    out = [0] * (tw * th * 4)
    for i in range(tw * th):
        v = frame[i]
        out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = v
        out[i * 4 + 3] = 255
    for ty in range(Y0, Y1):
        t = (ty - Y0) / float(max(1, rh - 1))
        rgb = [int((BG_TOP[c] + (BG_BOT[c] - BG_TOP[c]) * t) * 255 + 0.5)
               for c in range(3)]
        for tx in range(X0, X1):
            o = (ty * tw + tx) * 4
            out[o], out[o + 1], out[o + 2] = rgb

    for ty in range(rh):
        sy0 = cy0 + int(ty * ch / float(rh))
        sy1 = max(sy0 + 1, cy0 + int((ty + 1) * ch / float(rh)))
        for tx in range(rw):
            sx0 = cx0 + int(tx * cw / float(rw))
            sx1 = max(sx0 + 1, cx0 + int((tx + 1) * cw / float(rw)))
            ar = ag = ab = aa = 0.0
            n = 0
            for sy in range(sy0, min(sy1, sh)):
                for sx in range(sx0, min(sx1, sw)):
                    s = at(sx, sy)
                    a = pixels[s + 3]
                    ar += pixels[s] * a
                    ag += pixels[s + 1] * a
                    ab += pixels[s + 2] * a
                    aa += a
                    n += 1
            if not n or aa <= 0.0:
                continue
            a = aa / n
            o = ((Y0 + ty) * tw + (X0 + tx)) * 4
            for c, v in enumerate((ar / aa, ag / aa, ab / aa)):
                base = out[o + c] / 255.0
                out[o + c] = int(min(1.0, max(0.0, v * a + base * (1.0 - a))) * 255 + 0.5)

    hdr = bytearray(info["header"])
    w3 = M._u32(hdr, 12)
    struct.pack_into("<I", hdr, 12, (w3 & ~(0xFF << 8)) | (BC1_FMT << 8))
    payload = M.encode_bc(out, tw, th, False)
    want = tw * th // 2
    if len(payload) != want:
        raise RuntimeError("encoded %d bytes, expected %d" % (len(payload), want))
    return bytes(hdr) + payload


def build_from_image(img, reference, card_aspect=None):
    px, w, h = image_rgba(img)
    return build(px, w, h, reference, card_aspect)
