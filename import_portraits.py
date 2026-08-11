"""Turn supplied roster-icon PNGs into CSS portrait .tex files.

Format 42 (what stock portraits use) keeps a full greyscale portrait in its
alpha channel and chroma in the colour block, in a packing that has not been
worked out - a red/green/blue/white test chart written as plain BC3 came back
from the game as two flat bands. Format 19 (BC1) does round-trip correctly, so
these are written at 19. That costs alpha, which is fine: the cards are opaque.

The white torn photo border is part of the portrait image, not the card. It is
identical in every stock portrait, so frame_template.py recovers it by comparing
a spread of them - pixels that do not vary are frame, pixels that do are the
photo. Art goes inside that window, the frame is laid back over the margin.

  UMVC3_SRC   root of the supplied icon folders
  UMVC3_REF   a stock .tex to copy the header from
  UMVC3_OUT   where to write the .tex files
  UMVC3_ONLY  optional comma-separated list of ids, for quick iteration
"""
import bpy, sys, os

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)
import io_umvc3_mod as M
import frame_data

SRC = os.environ["UMVC3_SRC"]
REF = os.environ["UMVC3_REF"]
OUT = os.environ["UMVC3_OUT"]
ONLY = [s for s in os.environ.get("UMVC3_ONLY", "").split(",") if s]

BC1_FMT = 19
BG_TOP = (0.15, 0.16, 0.20)
BG_BOT = (0.05, 0.05, 0.08)

# Width/height of the card the art window is drawn onto, in game units. The
# window is 112x76 texels (1.47:1), so a card of a different shape squashes
# whatever is in it; cropping the source to the CARD's aspect first and then
# stretching it to fill the window cancels that out.
#
# Defaults to the window's own aspect, which is a plain cover-fit and matches
# every portrait currently installed. Set it to the real card aspect (0.85 at
# 9 rows x 16 columns) ONLY when regenerating the whole set - the 50 vanilla
# portraits are stock art this pipeline does not produce, so correcting some
# and not others looks worse than the uniform squash.
CARD_ASPECT = float(os.environ.get("UMVC3_CARD_ASPECT", "%.6f" % (112.0 / 76.0)))

# CE resource id -> supplied icon. Only confident matches; anything absent keeps
# whatever portrait it already has. The row-8 eight were confirmed against the
# in-game name plate; the rest are matched by name.
MAP = {
    # --- the eight on row 8 ---
    "Rash":       "Tabs/Rashid.png",
    "KennFist":   "Tabs/Ken.png",
    "Gui":        "Tabs/Guile.png",
    "Chl":        "Tabs/Charlie.png",
    "Jeannix":    "Tabs/Jean Grey.png",
    "WL3":        "Tabs/Laura.png",
    "Psylock":    "Tabs/Psylocke V1.png",
    "Cyclop":     "Tabs/Cyclops.png",
    # --- CE characters whose only shipped portrait is a placeholder silhouette,
    #     but for which real art does exist in the supplied folders ---
    "Dan":        "other/r_Dan00_BM_NOMIP.png",
    "WrMach":     "other/b_WrMach00_BM_HQ_NOMIP.png",
    "Neroe":      "other/b_Neroe00_BM_HQ_NOMIP.png",
    "Hunksher":   "Tabs/Hunk.png",
    "Hunkpool":   "Tabs/Hunk.png",
    # --- everyone else with a clearly named icon ---
    "Asuraan":    "Tabs/Asura.png",
    "BHeart":     "CaliKing/Blackheart V2.png",
    "Batsu":      "CaliKing/Batsu V1.png",
    "Bishop":     "CaliKing/Bishop.png",
    "BisonSkrull": "other/M. Bison.png",
    "Cable":      "CaliKing/Cable V1.png",
    "Cammyremer": "Tabs/Cammy.png",
    "CapCom":     "CaliKing/Captain Commando V1.png",
    "Carnage":    "CaliKing/Carnage.png",
    "Carter":     "Shumariachi/carter.png",
    "Cmar":       "Tabs/Captain Marvel.png",
    "DStranger":  "EMC/Stranger.png",
    "Dm5gil":     "other/DMCV Vergil.png",
    "Dmc1e":      "Tabs/DMC1 Dante.png",
    "Eyu":        "Tabs/Evil Ryu.png",
    "Gambit":     "CaliKing/Gambit.png",
    "GeneGH":     "other/Gene.png",
    "Glori":      "other/Gloria.png",
    "Hnt":        "Tabs/Hunk.png",
    "Iceman":     "CaliKing/Ice Man.png",
    "Jihad":      "Shumariachi/Jihad.png",
    "Jugs":       "other/jugg.png",
    "Juri":       "other/Juri V2.png",
    "KTho":       "EMC/King Thor.png",
    "Krauser":    "Tabs/krauser.png",
    "Kyosk":      "Shumariachi/kyosuke.png",
    "Leons":      "Tabs/leon.png",
    "Lilithan":   "Tabs/Lilith V1.png",
    "Mayahodo":   "Tabs/PW and Maya.png",
    "MonsterHun": "Tabs/Monster Hunter.png",
    "Mooneto":    "Tabs/Moonstone.png",
    "Mvc2inel":   "Tabs/MVC2 Sentinal.png",
    "Orlk":       "Tabs/Orange Hulk.png",
    "Redshlk":    "Tabs/Red She-Hulk V1.png",
    "RobbiReyes": "Shumariachi/robbie1.png",
    "STR29":      "other/strider 2099.png",
    "Saki":       "Shumariachi/saki.png",
    "Sakura":     "CaliKing/Sakura V1.png",
    "ServbotA":   "other/Servbot crop.png",
    "Shadli":     "Tabs/Shadow Lady.png",
    "Shini":      "Tabs/Shin Akuma V1.png",
    "Shocker":    "CaliKing/Shocker V1.png",
    "SorcClea":   "EMC/Clea.png",
    "SpiderGwe":  "Tabs/Spider-Gwen.png",
    "StaJ":       "EMC/stars Jill.png",
    "Stris":      "Tabs/Stars Chris v1.png",
    "Talbain":    "CaliKing/Talbain V1.png",
    "Thanos":     "Tabs/Thanos V1.png",
    "USAGENTica": "EMC/US Agent.png",
    "Ultro":      "Tabs/Ultron.png",
    "Venom":      "CaliKing/Venom.png",
    "Westar":     "Tabs/Stars Wesker.png",
    "Xero":       "EMC/x.png",
}

with open(REF, "rb") as f:
    ref = M.tex_info(f.read())
TW, TH = ref["width"], ref["height"]
if TW != frame_data.SIZE:
    raise RuntimeError("frame template is %d px, reference is %d" % (frame_data.SIZE, TW))

import struct as _struct
hdr = bytearray(ref["header"])
w3 = M._u32(hdr, 12)
_struct.pack_into("<I", hdr, 12, (w3 & ~(0xFF << 8)) | (BC1_FMT << 8))
HEADER = bytes(hdr)

X0, Y0, X1, Y1 = frame_data.WINDOW
RW, RH = X1 - X0, Y1 - Y0
FRAME = frame_data.LUM                      # top-down greyscale, 0..255
print("target %dx%d fmt %d, art window %d,%d..%d,%d (%dx%d)"
      % (TW, TH, BC1_FMT, X0, Y0, X1, Y1, RW, RH))

os.makedirs(OUT, exist_ok=True)
written, failed = 0, []

for stem in sorted(MAP):
    if ONLY and stem not in ONLY:
        continue
    path = os.path.join(SRC, MAP[stem])
    if not os.path.exists(path):
        failed.append("%s (%s missing)" % (stem, MAP[stem]))
        continue
    try:
        img = bpy.data.images.load(path, check_existing=False)
        sw, sh = img.size
        px = list(img.pixels[:])            # bottom-up RGBA floats
        bpy.data.images.remove(img)

        def at(x, y):                       # y top-down
            return ((sh - 1 - y) * sw + x) * 4

        xs0, ys0, xs1, ys1 = sw, sh, -1, -1
        for y in range(sh):
            row = (sh - 1 - y) * sw * 4
            for x in range(sw):
                if px[row + x * 4 + 3] > 0.02:
                    if x < xs0: xs0 = x
                    if x > xs1: xs1 = x
                    if y < ys0: ys0 = y
                    if y > ys1: ys1 = y
        if xs1 < xs0:
            failed.append("%s (fully transparent)" % stem)
            continue
        bw, bh = xs1 - xs0 + 1, ys1 - ys0 + 1

        # Stock portraits are close crops that fill the frame, so crop rather
        # than letterbox, anchored at the top - these icons are busts and the
        # head is the part worth keeping. The crop takes the CARD's aspect, then
        # fills the whole window, which cancels the window-to-card distortion.
        if bw / float(bh) > CARD_ASPECT:
            cw, ch = max(1, int(round(bh * CARD_ASPECT))), bh
        else:
            cw, ch = bw, max(1, int(round(bw / CARD_ASPECT)))
        cw, ch = min(cw, bw), min(ch, bh)
        cx0, cy0 = xs0 + (bw - cw) // 2, ys0

        # frame and margins straight from the template, greyscale
        out = [0] * (TW * TH * 4)
        for i in range(TW * TH):
            v = FRAME[i]
            out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = v
            out[i * 4 + 3] = 255
        # backing inside the window
        for ty in range(Y0, Y1):
            t = (ty - Y0) / float(max(1, RH - 1))
            rgb = [int((BG_TOP[c] + (BG_BOT[c] - BG_TOP[c]) * t) * 255 + 0.5) for c in range(3)]
            for tx in range(X0, X1):
                o = (ty * TW + tx) * 4
                out[o], out[o + 1], out[o + 2] = rgb
        # the icon, box-averaged down and composited over the backing
        for ty in range(RH):
            sy0 = cy0 + int(ty * ch / float(RH))
            sy1 = max(sy0 + 1, cy0 + int((ty + 1) * ch / float(RH)))
            for tx in range(RW):
                sx0 = cx0 + int(tx * cw / float(RW))
                sx1 = max(sx0 + 1, cx0 + int((tx + 1) * cw / float(RW)))
                ar = ag = ab = aa = 0.0
                n = 0
                for sy in range(sy0, min(sy1, sh)):
                    for sx in range(sx0, min(sx1, sw)):
                        s = at(sx, sy)
                        a = px[s + 3]
                        ar += px[s] * a; ag += px[s + 1] * a; ab += px[s + 2] * a
                        aa += a; n += 1
                if not n or aa <= 0.0:
                    continue
                a = aa / n
                o = ((Y0 + ty) * TW + (X0 + tx)) * 4
                for c, v in enumerate((ar / aa, ag / aa, ab / aa)):
                    base = out[o + c] / 255.0
                    out[o + c] = int(min(1.0, max(0.0, v * a + base * (1.0 - a))) * 255 + 0.5)

        payload = M.encode_bc(out, TW, TH, False)
        want = TW * TH // 2
        if len(payload) != want:
            failed.append("%s (payload %d != %d)" % (stem, len(payload), want))
            continue
        with open(os.path.join(OUT, "f_%s00_BM_HQ_NOMIP.tex" % stem), "wb") as f:
            f.write(HEADER)
            f.write(payload)
        written += 1
    except Exception as e:
        failed.append("%s (%s)" % (stem, e))

print("wrote %d portraits to %s" % (written, OUT))
if failed:
    print("FAILED (%d): %s" % (len(failed), "; ".join(failed)))
