"""MT Framework formats, and the generic whole-archive round-trip.

ARC / MOD / MRL / TEX primitives plus the operators that open an entire archive
in Blender and write it back. The character-select layer on top of this lives in
`scene.py`; this module knows nothing about cards or the grid.

The root `io_umvc3_mod.py` is a shim onto this module, so the headless scripts
that `import io_umvc3_mod as M` keep working unchanged.
"""
import os
import re
import struct
import tempfile
import zlib
import bpy
from bpy.props import StringProperty, FloatProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

# =============================================================== formats =====
# --- ARC ---------------------------------------------------------------------
# 8-byte header (ARC\0, u16 version, u16 count), then 80-byte entries:
#   char name[64]; u32 extHash; u32 compSize; u32 rawSize|flags<<29; u32 offset
# Payloads are zlib streams. Surveying all 6604 shipped archives: version is
# always 7, flags always 2, entries always in ascending offset order, and data
# always starts at the first multiple of 32768 past the entry table.
ARC_ENTRY = 80
ARC_ALIGN = 32768
ARC_FLAGS = 2
ZLIB_LEVEL = 6          # byte-identical to the shipped payloads

EXT_HASHES = {
    "tex": 0x241F5DEB,
    "mod": 0x58A15856,
    "mrl": 0x2749C8A8,
    "lmt": 0x76820D81,
    "gui": 0x22948394,
    # The scheduler resources. They hold the node tree that places every model
    # carrying no world coordinates of its own - see sdl.py.
    "sdl": 0x4C0DB839,
}
HASH_TO_EXT = {v: k for k, v in EXT_HASHES.items()}

# --- MOD (rModel v211, 64-bit offsets) ---------------------------------------
H_VERSION    = 0x04
H_MESHCOUNT  = 0x08
H_MATCOUNT   = 0x0A
H_VBUFSIZE   = 0x18
H_MATOFF     = 0x38
H_MESHOFF    = 0x40
H_VERTOFF    = 0x48
H_INDEXOFF   = 0x50
H_BBMIN      = 0x70
H_BBMAX      = 0x80

MESH_STRIDE = 56
M_FMTID     = 8
M_STRIDE    = 10
M_VBUFOFF   = 16
M_IDXSTART  = 24
M_IDXCOUNT  = 28
M_VTXLO     = 40
M_VTXHI     = 42

POS_SCALE = 32767.0

# Vertex layout is chosen by the format id at mesh+8, NOT by stride alone:
# stride 20 has two different layouts (fmt 1 stores float32 positions, fmt 9
# stores the usual bbox-normalised u16 triple). Surveyed (fmt, stride) pairs in
# mnchscmn.arc: (1,20) (9,12) (9,20) (9,24) (57,28) and 40 for fmt 41/49/57/65.
LAYOUTS = {
    (1, 20):  {"pos": "f32", "normal": 12, "uv0":   16, "color0": None},
    (9, 12):  {"pos": "u16", "normal":  8, "uv0": None, "color0": None},
    (9, 20):  {"pos": "u16", "normal":  8, "uv0":   16, "color0":   12},
    (9, 24):  {"pos": "u16", "normal":  8, "uv0":   16, "color0":   12},
    (57, 28): {"pos": "u16", "normal": 24, "uv0": None, "color0": None},
}

# Fallback by stride, so an unseen format id with a known stride still loads.
STRIDE_DEFAULTS = {
    12: {"pos": "u16", "normal":  8, "uv0": None, "color0": None},
    24: {"pos": "u16", "normal":  8, "uv0":   16, "color0":   12},
    28: {"pos": "u16", "normal": 24, "uv0": None, "color0": None},
    40: {"pos": "u16", "normal":  8, "uv0":   24, "color0":   32},
}


def layout_for(fmt, stride):
    return LAYOUTS.get((fmt, stride)) or STRIDE_DEFAULTS.get(stride)

# --- TEX (rTexture) ----------------------------------------------------------
BC1_CODES = (19, 25)
BC3_CODES = (23, 31, 42)


def _u16(b, o):  return struct.unpack_from("<H", b, o)[0]
def _u32(b, o):  return struct.unpack_from("<I", b, o)[0]
def _u64(b, o):  return struct.unpack_from("<Q", b, o)[0]
def _f32(b, o):  return struct.unpack_from("<f", b, o)[0]
def _half(b, o): return struct.unpack_from("<e", b, o)[0]


# ================================================================== ARC ======
class ArcEntry(object):
    __slots__ = ("name", "hash", "ext", "data", "comp", "dirty")

    def __init__(self, name, hash_, data, comp):
        self.name = name
        self.hash = hash_
        self.ext = HASH_TO_EXT.get(hash_, "%08X" % hash_)
        self.data = data          # decompressed
        self.comp = comp          # original compressed bytes, reused if clean
        self.dirty = False

    @property
    def key(self):
        return (self.name, self.hash)


def read_arc(path):
    with open(path, "rb") as f:
        b = f.read()
    if b[:3] != b"ARC":
        raise RuntimeError("Not an ARC: %s" % path)
    version = _u16(b, 4)
    count = _u16(b, 6)
    entries = []
    for i in range(count):
        o = 8 + i * ARC_ENTRY
        name = b[o:o + 64].split(b"\0", 1)[0].decode("ascii", "replace")
        h = _u32(b, o + 64)
        comp_size = _u32(b, o + 68)
        offset = _u32(b, o + 76)
        comp = b[offset:offset + comp_size]
        try:
            data = zlib.decompress(comp)
        except zlib.error as e:
            raise RuntimeError("Entry %s failed to inflate: %s" % (name, e))
        entries.append(ArcEntry(name, h, data, comp))
    return version, entries


def write_arc(path, version, entries):
    blobs = []
    for e in entries:
        if e.dirty or e.comp is None:
            blobs.append(zlib.compress(e.data, ZLIB_LEVEL))
        else:
            blobs.append(e.comp)

    hdr_end = 8 + len(entries) * ARC_ENTRY
    data_start = ((hdr_end + ARC_ALIGN - 1) // ARC_ALIGN) * ARC_ALIGN
    total = data_start + sum(len(x) for x in blobs)

    out = bytearray(total)
    out[0:4] = b"ARC\0"
    struct.pack_into("<HH", out, 4, version, len(entries))

    cursor = data_start
    for i, e in enumerate(entries):
        o = 8 + i * ARC_ENTRY
        nb = e.name.encode("ascii")
        if len(nb) > 63:
            raise RuntimeError("Entry name too long for the 64-byte field: %s" % e.name)
        out[o:o + len(nb)] = nb
        struct.pack_into("<I", out, o + 64, e.hash)
        struct.pack_into("<I", out, o + 68, len(blobs[i]))
        struct.pack_into("<I", out, o + 72, len(e.data) | (ARC_FLAGS << 29))
        struct.pack_into("<I", out, o + 76, cursor)
        out[cursor:cursor + len(blobs[i])] = blobs[i]
        cursor += len(blobs[i])

    with open(path, "wb") as f:
        f.write(bytes(out))
    return total


# ================================================================== TEX ======
def tex_info(b):
    if len(b) < 24 or b[:4] != b"TEX\0":
        return None
    w2 = _u32(b, 8)
    w3 = _u32(b, 12)
    return {
        "mips": w2 & 0x3F,
        "width": (w2 >> 6) & 0x1FFF,
        "height": (w2 >> 19) & 0x1FFF,
        "fmt": (w3 >> 8) & 0xFF,
        "header": bytes(b[:24]),
        "payload": bytes(b[24:]),
    }


def tex_to_dds_bytes(b):
    info = tex_info(b)
    if not info or info["width"] <= 0 or info["height"] <= 0:
        return None
    data = info["payload"]
    bpp = (len(data) * 8.0) / (info["width"] * info["height"])
    four = b"DXT1" if bpp < 6.0 else b"DXT5"

    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<I", hdr, 4, 124)
    struct.pack_into("<I", hdr, 8, 0x000A1007)
    struct.pack_into("<I", hdr, 12, info["height"])
    struct.pack_into("<I", hdr, 16, info["width"])
    struct.pack_into("<I", hdr, 20, len(data))
    struct.pack_into("<I", hdr, 28, max(1, info["mips"]))
    struct.pack_into("<I", hdr, 76, 32)
    struct.pack_into("<I", hdr, 80, 4)
    hdr[84:88] = four
    struct.pack_into("<I", hdr, 108, 0x1000)
    return bytes(hdr) + data


# --- BC encoding -------------------------------------------------------------
def _pack565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _unpack565(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _fit_endpoints(texels):
    """The 565 pair bounding a set of texels, low first."""
    rmin = gmin = bmin = 255
    rmax = gmax = bmax = 0
    for (r, g, b) in texels:
        if r < rmin: rmin = r
        if g < gmin: gmin = g
        if b < bmin: bmin = b
        if r > rmax: rmax = r
        if g > gmax: gmax = g
        if b > bmax: bmax = b
    return _pack565(rmin, gmin, bmin), _pack565(rmax, gmax, bmax)


def _pick(pal, texel, n):
    best, bestd = 0, -1
    r, g, b = texel
    for j in range(n):
        pr, pg, pb = pal[j]
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if bestd < 0 or d < bestd:
            bestd, best = d, j
    return best


def _encode_color_block(block, opaque=None):
    """One BC1 colour block. `opaque` marks which texels are to be kept.

    With anything masked out the block is written in BC1's **punch-through**
    mode - `c0 <= c1` selects a three-colour palette whose fourth entry is
    transparent black - and the endpoints are fitted to the kept texels ALONE.
    That second half matters as much as the first: the colour under a fully
    transparent pixel is undefined, artists' tools leave anything there, and a
    block whose endpoints span it shades its *visible* texels toward that
    colour. Green and black through the middle of a cut-out is exactly this.
    """
    if opaque is not None and not all(opaque):
        keep = [t for t, o in zip(block, opaque) if o]
        if not keep:
            # nothing visible in this block at all: c0 <= c1, every index 3
            return struct.pack("<HHI", 0, 0, 0xFFFFFFFF)
        c0, c1 = _fit_endpoints(keep)          # low first: c0 <= c1 is the mode
        e0, e1 = _unpack565(c0), _unpack565(c1)
        pal = (e0, e1, tuple((e0[k] + e1[k]) // 2 for k in range(3)))
        bits = 0
        for i, t in enumerate(block):
            bits |= (_pick(pal, t, 3) if opaque[i] else 3) << (2 * i)
        return struct.pack("<HHI", c0, c1, bits)

    c1, c0 = _fit_endpoints(block)             # high first: c0 > c1 is 4-colour
    if c0 == c1:
        # flat block; keep c0 > c1 so the 4-colour mode stays selected
        return struct.pack("<HHI", 1, 0, 0) if c0 == 0 else struct.pack("<HHI", c0, c0 - 1, 0)

    e0 = _unpack565(c0)
    e1 = _unpack565(c1)
    pal = (e0, e1,
           tuple((2 * e0[k] + e1[k]) // 3 for k in range(3)),
           tuple((e0[k] + 2 * e1[k]) // 3 for k in range(3)))

    bits = 0
    for i, t in enumerate(block):
        bits |= _pick(pal, t, 4) << (2 * i)
    return struct.pack("<HHI", c0, c1, bits)


def _encode_alpha_block(alphas):
    a0, a1 = max(alphas), min(alphas)
    if a0 == a1:
        return bytes([a0, a1, 0, 0, 0, 0, 0, 0])
    pal = [a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)]
    idx = 0
    for i, a in enumerate(alphas):
        best, bestd = 0, -1
        for j in range(8):
            d = abs(a - pal[j])
            if bestd < 0 or d < bestd:
                bestd, best = d, j
        idx |= best << (3 * i)
    out = bytearray(8)
    out[0], out[1] = a0, a1
    for k in range(6):
        out[2 + k] = (idx >> (8 * k)) & 0xFF
    return bytes(out)


# BC1 stores one bit of alpha, so a texel is either kept or punched out. Half
# way is the only defensible place to put the line.
BC1_ALPHA_CUTOFF = 128


def encode_bc(pixels, width, height, use_alpha, cutout=False):
    """RGBA bytes -> BC1 (or BC3 with `use_alpha`).

    `cutout` carries the source's transparency into BC1's one bit of alpha,
    rather than dropping it and shipping whatever colour was hiding underneath.
    Off by default: a caller re-encoding a texture it just decoded has no
    transparency to carry, and reading alpha it did not put there would punch
    holes in it.
    """
    data = bytearray()
    for by in range((height + 3) // 4):
        for bx in range((width + 3) // 4):
            rgb, alpha = [], []
            for py in range(4):
                y = min(by * 4 + py, height - 1)
                for px in range(4):
                    x = min(bx * 4 + px, width - 1)
                    o = (y * width + x) * 4
                    rgb.append((pixels[o], pixels[o + 1], pixels[o + 2]))
                    alpha.append(pixels[o + 3])
            if use_alpha:
                data += _encode_alpha_block(alpha)
                data += _encode_color_block(rgb)
            else:
                mask = [a >= BC1_ALPHA_CUTOFF for a in alpha] if cutout else None
                data += _encode_color_block(rgb, mask)
    return bytes(data)


def decode_bc(data, width, height, use_alpha, bottom_up=True):
    """BC1/BC3 -> flat RGBA float list, bottom-up (Blender's pixel order).

    Blender decodes a .dds itself, so this is only needed when the *pixels* are
    wanted rather than an image to look at - which in practice means format 42,
    whose alpha channel carries the whole portrait as luminance.

    `encode_bc` writes rows in FILE order, so it is not the inverse of the
    default: decode-edit-encode mirrors the texture vertically, and does it again
    on every rebuild. Pass bottom_up=False to get file order and make the pair
    round-trip.
    """
    px = [0.0] * (width * height * 4)
    step = 16 if use_alpha else 8
    o = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            if o + step > len(data):
                break
            alpha = [255] * 16
            q = o
            if use_alpha:
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
            e0, e1 = _unpack565(c0), _unpack565(c1)
            punch = c0 <= c1 and not use_alpha
            if not punch:
                cols = [e0, e1,
                        tuple((2 * e0[k] + e1[k]) // 3 for k in range(3)),
                        tuple((e0[k] + 2 * e1[k]) // 3 for k in range(3))]
            else:
                # index 3 is transparent black, not opaque black - reading it as
                # opaque is how a cut-out silently fills in on a re-encode
                cols = [e0, e1,
                        tuple((e0[k] + e1[k]) // 2 for k in range(3)), (0, 0, 0)]
                alpha = [0 if ((idx >> (2 * i)) & 3) == 3 else 255 for i in range(16)]
            for i in range(16):
                x, y = bx + (i & 3), by + (i >> 2)
                if x >= width or y >= height:
                    continue
                c = cols[(idx >> (2 * i)) & 3]
                d = ((height - 1 - y if bottom_up else y) * width + x) * 4
                px[d] = c[0] / 255.0
                px[d + 1] = c[1] / 255.0
                px[d + 2] = c[2] / 255.0
                px[d + 3] = alpha[i] / 255.0
            o += step
    return px


def image_pixels_topdown(img, width, height):
    """Raw stored values as ints, RGBA, top-down (Blender rows are bottom-up).

    Never mutates the caller's image: resizing happens on a throwaway copy.
    """
    # Read the LIVE buffer first. Every archive texture is file-backed, and
    # `img.copy()` on a file-backed image re-reads the file - so copying first
    # threw away whatever the user had just painted, and export silently wrote
    # the original back. Setting the colourspace re-reads it too; that used to be
    # done here, and it turns out to change no values at all (a byte buffer's
    # pixels come through unmanaged either way), so it is simply gone.
    px = list(img.pixels[:])

    if img.size[0] != width or img.size[1] != height:
        # Scale on a GENERATED image seeded from those pixels: nothing backs it
        # with a file, so scaling cannot re-read one, and the caller's image is
        # still never touched.
        #
        # Scale it PREMULTIPLIED. Blender interpolates the four channels
        # independently, and the colour under a transparent pixel is undefined -
        # tools leave anything there - so with straight alpha every edge texel of
        # a cut-out is mixed with a colour that was never meant to be seen. Alpha
        # weights it to nothing here, so a border comes out the colour of the art
        # rather than of the hole, and is then divided back out.
        soft = any(px[i] < 1.0 for i in range(3, len(px), 4))
        if soft:
            for i in range(0, len(px), 4):
                a = px[i + 3]
                px[i] *= a
                px[i + 1] *= a
                px[i + 2] *= a
        tmp = bpy.data.images.new("umvc3_resize", width=img.size[0],
                                  height=img.size[1], alpha=True)
        try:
            tmp.pixels[:] = px
            tmp.scale(width, height)
            px = list(tmp.pixels[:])
        finally:
            bpy.data.images.remove(tmp)
        if soft:
            for i in range(0, len(px), 4):
                a = px[i + 3]
                if a > 1e-6:
                    px[i] /= a
                    px[i + 1] /= a
                    px[i + 2] /= a
                else:
                    px[i] = px[i + 1] = px[i + 2] = 0.0

    want = width * height * 4
    if len(px) < want:
        raise RuntimeError("image gave %d values, expected %d (%dx%d)"
                           % (len(px), want, width, height))

    out = [0] * (width * height * 4)
    for y in range(height):
        src = (height - 1 - y) * width * 4
        dst = y * width * 4
        for i in range(width * 4):
            v = px[src + i]
            v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
            out[dst + i] = int(v * 255.0 + 0.5)
    return out


def encode_image_to_tex(img, reference_tex):
    """Re-encode a Blender image into a .tex shaped like reference_tex."""
    info = tex_info(reference_tex)
    if info is None:
        raise RuntimeError("reference is not a .tex")
    if info["mips"] > 1:
        raise RuntimeError("%d mips; only single-mip (NOMIP) textures are supported" % info["mips"])
    if info["fmt"] in BC1_CODES:
        use_alpha = False
    elif info["fmt"] in BC3_CODES:
        use_alpha = True
    else:
        raise RuntimeError("unknown texture format code %d" % info["fmt"])

    w, h = info["width"], info["height"]
    pixels = image_pixels_topdown(img, w, h)
    # The image is the user's, so its alpha means what it says: carry it into
    # BC1's one bit rather than ship the colour hiding under it.
    payload = encode_bc(pixels, w, h, use_alpha, cutout=not use_alpha)
    if len(payload) != len(info["payload"]):
        raise RuntimeError("encoded %d bytes, expected %d" % (len(payload), len(info["payload"])))
    return info["header"] + payload


# ================================================================== MRL ======
def mt_hash(name):
    """Reflected CRC32 (poly EDB88320, init FFFFFFFF), NO final xor."""
    return (zlib.crc32(name.encode("ascii")) ^ 0xFFFFFFFF) & 0xFFFFFFFF


def parse_mrl_bytes(b):
    if len(b) < 40 or b[:4] != b"MRL\0":
        return [], {}
    mat_count = _u32(b, 8)
    tex_count = _u32(b, 12)
    tex_off = _u64(b, 24)
    mat_off = _u64(b, 32)
    textures = []
    for i in range(tex_count):
        o = tex_off + i * 88 + 24
        textures.append(b[o:o + 64].split(b"\0", 1)[0].decode("ascii", "replace"))
    hash_to_index = {}
    for i in range(mat_count):
        hash_to_index[_u32(b, mat_off + i * 72 + 8)] = i
    return textures, hash_to_index


# Each 72-byte material entry points (+56) at a parameter block of its own,
# whose length is at +12. Diffing the seven same-shader blocks in chs_meku's MRL
# leaves exactly one dword that varies between them - +320 - holding a 1-BASED
# index into the MRL texture table. It reads meku_chs01 for the material the grid
# lines borrow, which the game confirms: the cyan patch painted into meku_chs01
# is what shows on screen, while repainting the meku_chs02 the old guess named
# changed nothing.
#
# The offset is a slot in this shader's parameter layout, not a header field, so
# other shaders put their base map elsewhere and read as out-of-range here. That
# is why this is a hint and not the answer: out of range falls through to the
# heuristics below, which is exactly where every material used to land.
MRL_BASEMAP = 320


def mrl_texture_bindings(b):
    """{material name hash: texture index} for every material whose parameter
    block names a base map at the known slot."""
    if len(b) < 40 or b[:4] != b"MRL\0":
        return {}
    mat_count, tex_count = _u32(b, 8), _u32(b, 12)
    mat_off = _u64(b, 32)
    out = {}
    for i in range(mat_count):
        o = mat_off + i * 72
        blk, size = _u32(b, o + 56), _u32(b, o + 12)
        if size < MRL_BASEMAP + 4 or blk + MRL_BASEMAP + 4 > len(b):
            continue
        v = _u32(b, blk + MRL_BASEMAP)
        if 1 <= v <= tex_count:
            out[_u32(b, o + 8)] = v - 1
    return out


def set_mrl_texture_binding(b, mat_hash, tex_index):
    """Point a material at a different texture in the same MRL. Returns new
    bytes, or None if it could not be done safely.

    Only rewrites the slot when it ALREADY holds a valid index: that is the
    evidence this shader keeps its base map there. For a shader that keeps it
    elsewhere the slot means something else entirely, and writing a texture
    index into it would corrupt an unrelated parameter.
    """
    if len(b) < 40 or b[:4] != b"MRL\0":
        return None
    mat_count, tex_count = _u32(b, 8), _u32(b, 12)
    if not 0 <= tex_index < tex_count:
        return None
    mat_off = _u64(b, 32)
    for i in range(mat_count):
        o = mat_off + i * 72
        if _u32(b, o + 8) != mat_hash:
            continue
        blk, size = _u32(b, o + 56), _u32(b, o + 12)
        if size < MRL_BASEMAP + 4 or blk + MRL_BASEMAP + 4 > len(b):
            return None
        if not 1 <= _u32(b, blk + MRL_BASEMAP) <= tex_count:
            return None
        out = bytearray(b)
        struct.pack_into("<I", out, blk + MRL_BASEMAP, tex_index + 1)
        return bytes(out)
    return None


_NON_ALBEDO = ("_DM", "_SPE", "_NM", "_MM")


def choose_texture(textures, mrl_index, mat_count, bound=None):
    """`bound` is the index `mrl_texture_bindings` recovered, when it found one.
    Everything after it is guesswork: which texture a material samples is
    otherwise not reversed, and every texture is loaded anyway, so a wrong pick
    is a two-click fix in the shader editor."""
    if not textures:
        return None, "no textures"
    if bound is not None and 0 <= bound < len(textures):
        return textures[bound], "mrl binding"
    if len(textures) == 1:
        return textures[0], "only texture (certain)"
    if mrl_index is not None and len(textures) == mat_count:
        return textures[mrl_index], "index match"
    albedo = [t for t in textures if not any(s in t.upper() for s in _NON_ALBEDO)]
    if albedo:
        return albedo[0], "first base map (guess)"
    return textures[0], "first texture (guess)"


# ================================================================== MOD ======
def read_meshes(b):
    count = _u16(b, H_MESHCOUNT)
    mesh_off = _u64(b, H_MESHOFF)
    out = []
    for i in range(count):
        o = mesh_off + i * MESH_STRIDE
        lo, hi = _u16(b, o + M_VTXLO), _u16(b, o + M_VTXHI)
        out.append({
            "index": i,
            "material": (b[o + 5] >> 4) | (b[o + 6] << 4),
            "fmt": b[o + M_FMTID],
            "stride": b[o + M_STRIDE],
            "vbufoff": _u32(b, o + M_VBUFOFF),
            "idxstart": _u32(b, o + M_IDXSTART),
            "idxcount": _u32(b, o + M_IDXCOUNT),
            "vtxlo": lo, "vtxhi": hi, "nverts": hi - lo + 1,
        })
    return out


def read_bbox(b):
    mn = (_f32(b, H_BBMIN), _f32(b, H_BBMIN + 4), _f32(b, H_BBMIN + 8))
    mx = (_f32(b, H_BBMAX), _f32(b, H_BBMAX + 4), _f32(b, H_BBMAX + 8))
    return mn, mx, tuple(mx[i] - mn[i] for i in range(3))


def write_bbox(b, mn, mx):
    for k in range(3):
        struct.pack_into("<f", b, H_BBMIN + 4 * k, float(mn[k]))
        struct.pack_into("<f", b, H_BBMAX + 4 * k, float(mx[k]))


# ------------------------------------------------------------------ skeleton --
# Section at u64 @ 0x28:  descriptors (24 B) | local mats (64) | inverse-bind
# mats (64) | 256-byte remap. Matrices are row-major with the translation in
# row 3, so they compose as row vectors: v' = v . M.
BONE_DESC = 24
H_BONEOFF = 0x28


def _mat_mul(a, c):
    out = [0.0] * 16
    for r in range(4):
        for k in range(4):
            out[r * 4 + k] = sum(a[r * 4 + j] * c[j * 4 + k] for j in range(4))
    return out


def bone_section(b):
    n = _u16(b, 0x06)
    off = _u64(b, H_BONEOFF)
    return n, off, off + n * BONE_DESC, off + n * BONE_DESC + n * 64


def read_bones(b):
    """-> (parents, local mats, inverse-bind mats, remap list)"""
    n, off, loc, inv = bone_section(b)
    parents = [b[off + i * BONE_DESC + 1] for i in range(n)]
    local = [list(struct.unpack_from("<16f", b, loc + i * 64)) for i in range(n)]
    invb = [list(struct.unpack_from("<16f", b, inv + i * 64)) for i in range(n)]
    remap = list(b[inv + n * 64: inv + n * 64 + 256])
    return parents, local, invb, remap


def bone_world(parents, local):
    out = []
    for i in range(len(local)):
        chain, j = [], i
        while j != 255:
            chain.append(j)
            j = parents[j]
        w = local[chain[0]]
        for j in chain[1:]:
            w = _mat_mul(w, local[j])
        out.append(w)
    return out


# ------------------------------------------------------- vertex dequantisation
# Proved in-game: the header bounding box is inert. Positions are decoded with a
# SINGLE uniform scale, and both the scale and the origin live in the
# inverse-bind matrices as  invBind[j] = D . bindWorld[j]^-1  with
# D = scale(S) . translate(origin). Recover D as invBind[0] . bindWorld[0].
#
#     p = origin + raw / 32767 * S
#
# Decoding per axis with the bounding box - which every tool here used to do -
# stretches x, y and z by different factors and is what made the 16-row build
# render huge and splayed.

class Dequant(object):
    __slots__ = ("origin", "scale")

    def __init__(self, origin, scale):
        self.origin = tuple(float(v) for v in origin)
        self.scale = float(scale)

    def decode(self, raw):
        return tuple(self.origin[k] + raw[k] / POS_SCALE * self.scale for k in range(3))

    def encode(self, p):
        out = []
        for k in range(3):
            raw = int(round((p[k] - self.origin[k]) / self.scale * POS_SCALE))
            if raw < 0 or raw > 32767:
                raise ValueError(
                    "position %.3f on axis %d encodes to raw %d, outside 0..32767 for "
                    "origin %.3f scale %.3f - move the origin or grow the scale"
                    % (p[k], k, raw, self.origin[k], self.scale))
            out.append(raw)
        return tuple(out)

    def __repr__(self):
        return "Dequant(origin=(%.3f, %.3f, %.3f), scale=%.3f)" % (self.origin + (self.scale,))


def model_dequant(b):
    """The decode the engine will apply to this model's u16 positions."""
    n, off, loc, inv = bone_section(b)
    if not n:
        mn, mx, ext = read_bbox(b)
        return Dequant(mn, max(ext))          # boneless: nothing better available
    parents, local, invb, _ = read_bones(b)
    D = _mat_mul(invb[0], bone_world(parents, local)[0])
    diag = (D[0], D[5], D[10])
    S = max(abs(v) for v in diag)
    if S <= 0 or any(abs(abs(v) - S) > S * 1e-3 for v in diag):
        raise RuntimeError("inverse-bind matrix is not a uniform scale: diag %r" % (diag,))
    return Dequant((D[12], D[13], D[14]), S)


def set_model_dequant(b, origin, scale):
    """Retarget the decode. Vertex raws are NOT touched - re-encode them yourself.

    We need X with X . invBind[j] = D' . bindWorld[j]^-1, so X = D' . D^-1. In
    row-vector order that is scale(k) then translate(u) with k = S'/S and
    u = (origin' - origin) / S. Prepending the same transform to every bone
    leaves skinning untouched: it factors straight out of the weighted sum.
    """
    b = bytearray(b)
    n, off, loc, inv = bone_section(b)
    if not n:
        raise RuntimeError("model has no bones; nothing carries the decode")
    cur = model_dequant(bytes(b))
    k = float(scale) / cur.scale
    u = [(float(origin[i]) - cur.origin[i]) / cur.scale for i in range(3)]
    for i in range(n):
        m = list(struct.unpack_from("<16f", b, inv + i * 64))
        row3 = [sum(u[j] * m[j * 4 + c] for j in range(3)) + m[12 + c] for c in range(3)]
        for r in range(3):
            for c in range(4):
                m[r * 4 + c] *= k
        m[12], m[13], m[14] = row3
        struct.pack_into("<16f", b, inv + i * 64, *m)
    return bytes(b)


def mod_retarget_dequant(mod, origin, scale):
    """Move the decode AND re-encode every u16 position, so the geometry the
    engine sees is unchanged. This is the only safe way to make room."""
    b = bytearray(mod)
    old = model_dequant(bytes(b))
    new = Dequant(origin, scale)
    vert_off = _u64(b, H_VERTOFF)
    for m in read_meshes(bytes(b)):
        lay = layout_for(m["fmt"], m["stride"])
        if lay is None or lay["pos"] != "u16":
            continue
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            raw = struct.unpack_from("<3H", b, vo)
            struct.pack_into("<3H", b, vo, *new.encode(old.decode(raw)))
    return set_model_dequant(bytes(b), origin, scale)


def mod_geometry_bounds(mod):
    """True min/max of the decoded u16 positions."""
    b = mod
    q = model_dequant(b)
    vert_off = _u64(b, H_VERTOFF)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for m in read_meshes(b):
        lay = layout_for(m["fmt"], m["stride"])
        if lay is None or lay["pos"] != "u16":
            continue
        for k in range(m["nverts"]):
            vo = vert_off + m["vbufoff"] + (m["vtxlo"] + k) * m["stride"]
            p = q.decode(struct.unpack_from("<3H", b, vo))
            for a in range(3):
                lo[a] = min(lo[a], p[a])
                hi[a] = max(hi[a], p[a])
    return tuple(lo), tuple(hi)


# ------------------------------------------------------------- skin weights ---
# fmt 57 / stride 40, the format every card mesh uses:
#   +0  u16 x3  position      +16 u8 x8   bone indices (direct, not via remap)
#   +6  u16     weight0/32767 +24 half x2 uv0
#   +8  u8 x4   normal        +28 half x2 weight5, weight6
#   +12 u8 x4   weight1..4    +32 u8 x4   colour0   +36 u8 x4 colour1
# Weights sum to 1.0 across all 755 stock vertices.
SKIN_STRIDE = 40


def read_skin(b, vo):
    """-> {bone index: weight}, normalised."""
    w = [_u16(b, vo + 6) / 32767.0]
    w += [b[vo + 12 + j] / 255.0 for j in range(4)]
    w += [_half(b, vo + 28), _half(b, vo + 30)]
    idx = [b[vo + 16 + j] for j in range(7)]
    out = {}
    for i, v in zip(idx, w):
        if v > 0.0:
            out[i] = out.get(i, 0.0) + v
    t = sum(out.values())
    return {i: v / t for i, v in out.items()} if t else out


def write_skin(b, vo, weights):
    """weights: {bone index: weight}. Keeps the 7 largest, drops the rest."""
    top = sorted(((v, i) for i, v in weights.items() if v > 0), reverse=True)[:7]
    t = sum(v for v, _ in top)
    if t <= 0:
        raise ValueError("no non-zero weights")
    top = [(v / t, i) for v, i in top]
    while len(top) < 7:
        top.append((0.0, 0))

    # weight0 takes the u16 slot; 1..4 the byte slots; 5..6 the halves. Give the
    # byte slots the remainder after weight0 so the total still lands on 1.0.
    struct.pack_into("<H", b, vo + 6, max(0, min(32767, int(round(top[0][0] * 32767)))))
    w0 = _u16(b, vo + 6) / 32767.0
    tail = [top[j][0] for j in range(1, 7)]
    small = sum(tail[4:])
    struct.pack_into("<e", b, vo + 28, float(tail[4]))
    struct.pack_into("<e", b, vo + 30, float(tail[5]))
    small = _half(b, vo + 28) + _half(b, vo + 30)
    budget = max(0.0, 1.0 - w0 - small)
    mid = tail[:4]
    mt = sum(mid)
    units = [int(round(v / mt * budget * 255.0)) if mt else 0 for v in mid]
    drift = int(round(budget * 255.0)) - sum(units)
    for j in range(4):
        if drift == 0:
            break
        step = 1 if drift > 0 else -1
        if 0 <= units[j] + step <= 255:
            units[j] += step
            drift -= step
    for j in range(4):
        b[vo + 12 + j] = max(0, min(255, units[j]))
    for j in range(7):
        b[vo + 16 + j] = top[j][1] & 0xFF
    b[vo + 23] = 0


def read_mod_material_names(b):
    off = _u64(b, H_MATOFF)
    n = _u16(b, H_MATCOUNT)
    return [b[off + i * 128: off + i * 128 + 128].split(b"\0", 1)[0].decode("ascii", "replace")
            for i in range(n)]


def base_color_input(mat):
    """The Base Color socket of a material's Principled BSDF, or None."""
    if mat is None or mat.node_tree is None:
        return None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None or "Base Color" not in bsdf.inputs:
        return None
    return bsdf.inputs["Base Color"]


def base_color_source(inp):
    """The node actually feeding a socket, looking through reroutes. None if the
    socket is unlinked."""
    seen = 0
    while inp is not None and inp.is_linked and seen < 16:
        node = inp.links[0].from_node
        if node.type != "REROUTE":
            return node
        inp = node.inputs[0]
        seen += 1
    return None


def material_flat_color(mat):
    """(r, g, b) 0..1 when a material shows a flat colour, else None.

    Two ways to say the same thing, and both have to work: unlinking Base Color
    and picking a colour, or wiring an RGB node into it. The engine has no shader
    graph - what a mesh shows comes from its texture - so either way the colour
    has to be painted into the texels the mesh samples.
    """
    inp = base_color_input(mat)
    if inp is None:
        return None
    node = base_color_source(inp)
    try:
        if node is None:
            return tuple(float(v) for v in inp.default_value[:3])
        if node.type == "RGB":
            return tuple(float(v) for v in node.outputs[0].default_value[:3])
    except (AttributeError, TypeError, IndexError):
        return None
    return None


def material_shown_image(mat):
    """The image a material is actually displaying, or None."""
    node = base_color_source(base_color_input(mat))
    return getattr(node, "image", None) if node is not None else None


def linear_to_srgb(v):
    """Base Color is scene-linear; texture bytes are sRGB-encoded, so a colour
    written raw would come out far too dark. This is what makes the swatch in
    Blender and the pixels in game the same colour."""
    v = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
    v = v * 12.92 if v <= 0.0031308 else 1.055 * (v ** (1.0 / 2.4)) - 0.055
    return int(v * 255.0 + 0.5)


def build_material(name, img):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF") or next(
        (n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    # Remember how the material left the importer. A material whose texture
    # could not be loaded also has an unlinked Base Color, and baking its
    # untouched default grey into the archive would be a silent act of vandalism;
    # comparing against this tells a real recolour from one of those.
    mat["umvc3_had_image"] = img is not None
    if bsdf is not None and "Base Color" in bsdf.inputs:
        mat["umvc3_base"] = [float(v) for v in bsdf.inputs["Base Color"].default_value[:3]]
    if img is None or bsdf is None:
        return mat
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = img
    node.location = (-400, 200)
    nt.links.new(bsdf.inputs["Base Color"], node.outputs["Color"])
    if "Alpha" in bsdf.inputs:
        nt.links.new(bsdf.inputs["Alpha"], node.outputs["Alpha"])
    try:
        mat.blend_method = "BLEND"
    except (AttributeError, TypeError):
        pass
    return mat


def import_mod_bytes(context, data, entry_name, scale, tex_lookup, collection):
    """tex_lookup(archive_relative_path) -> bpy.types.Image or None."""
    b = data
    if b[:4] != b"MOD\0":
        raise RuntimeError("%s: not a MOD" % entry_name)
    version = _u16(b, H_VERSION)
    if version != 211:
        raise RuntimeError("%s: MOD version %d unsupported (need 211)" % (entry_name, version))

    q = model_dequant(b)
    vert_off = _u64(b, H_VERTOFF)
    idx_off = _u64(b, H_INDEXOFF)
    meshes = read_meshes(b)

    short = entry_name.replace("\\", "/").split("/")[-1]
    root = bpy.data.objects.new(short, None)
    collection.objects.link(root)
    root["umvc3_entry"] = entry_name
    root["umvc3_scale"] = scale
    root["umvc3_is_model_root"] = True

    mats = []
    if tex_lookup is not None:
        names = read_mod_material_names(b)
        textures, hash_to_index, bindings = tex_lookup.mrl_for(entry_name)
        for nm in names:
            h = mt_hash(nm)
            chosen, why = choose_texture(textures, hash_to_index.get(h), len(names),
                                         bindings.get(h))
            mat = build_material(nm, tex_lookup.image_for(chosen) if chosen else None)
            # so a wrong pick is visible rather than mysterious
            mat["umvc3_texture"] = chosen or ""
            mat["umvc3_texture_why"] = why
            mats.append(mat)

    for m in meshes:
        lay = layout_for(m["fmt"], m["stride"])
        if lay is None:
            print("[umvc3] %s mesh %d: unknown vertex format %d/stride %d, skipped"
                  % (short, m["index"], m["fmt"], m["stride"]))
            continue

        base = vert_off + m["vbufoff"]
        verts, uvs, cols = [], [], []
        for vi in range(m["vtxlo"], m["vtxhi"] + 1):
            vo = base + vi * m["stride"]
            if lay["pos"] == "f32":
                verts.append(tuple(_f32(b, vo + 4 * k) * scale for k in range(3)))
            else:
                raw = (_u16(b, vo), _u16(b, vo + 2), _u16(b, vo + 4))
                verts.append(tuple(v * scale for v in q.decode(raw)))
            if lay["uv0"] is not None:
                uvs.append((_half(b, vo + lay["uv0"]), 1.0 - _half(b, vo + lay["uv0"] + 2)))
            if lay["color0"] is not None:
                c = vo + lay["color0"]
                cols.append((b[c] / 255.0, b[c + 1] / 255.0, b[c + 2] / 255.0, b[c + 3] / 255.0))

        faces = []
        for k in range(0, m["idxcount"], 3):
            io = idx_off + (m["idxstart"] + k) * 2
            a, c2, c3 = _u16(b, io), _u16(b, io + 2), _u16(b, io + 4)
            if a == c2 or c2 == c3 or a == c3:
                continue
            faces.append((a - m["vtxlo"], c2 - m["vtxlo"], c3 - m["vtxlo"]))

        me = bpy.data.meshes.new("%s_m%02d" % (short, m["index"]))
        me.from_pydata(verts, [], faces)
        me.update()

        if mats and 0 <= m["material"] < len(mats):
            me.materials.append(mats[m["material"]])
        if uvs:
            uvl = me.uv_layers.new(name="UVMap")
            for loop in me.loops:
                uvl.data[loop.index].uv = uvs[loop.vertex_index]
        if cols:
            ca = me.color_attributes.new(name="color0", type="FLOAT_COLOR", domain="POINT")
            for i, c in enumerate(cols):
                ca.data[i].color = c

        ob = bpy.data.objects.new(me.name, me)
        ob.parent = root
        collection.objects.link(ob)
        ob["umvc3_entry"] = entry_name
        ob["umvc3_mesh_index"] = m["index"]
        ob["umvc3_material"] = m["material"]
        ob["umvc3_nverts"] = m["nverts"]
        ob["umvc3_scale"] = scale

    return len(meshes)


def patch_mod_bytes(template, objs, scale, write_uvs=True, write_colors=True, expand_bbox=False):
    """Return template with vertex positions / UVs / colours replaced.

    Everything else - header, bones, materials, the ~20 KB block before the
    vertex buffer, the whole index buffer - is copied verbatim, so topology
    must be unchanged and a malformed file is essentially impossible.
    """
    b = bytearray(template)
    q = model_dequant(b)
    vert_off = _u64(b, H_VERTOFF)
    meshes = {m["index"]: m for m in read_meshes(b)}

    if expand_bbox:
        # The decode is uniform and anchored at q.origin, so "making room" means
        # moving that anchor and widening that one scale - not stretching a box
        # per axis. Retarget only if something actually falls outside.
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for ob in objs:
            mtx = ob.matrix_world
            for v in ob.data.vertices:
                w = mtx @ v.co
                for k in range(3):
                    lo[k] = min(lo[k], w[k] / scale)
                    hi[k] = max(hi[k], w[k] / scale)
        need_lo = [min(lo[k], q.origin[k]) for k in range(3)]
        need_hi = [max(hi[k], q.origin[k] + q.scale) for k in range(3)]
        span = max(need_hi[k] - need_lo[k] for k in range(3))
        if span > q.scale or any(need_lo[k] < q.origin[k] - 1e-4 for k in range(3)):
            pad = span * 0.001
            b = bytearray(mod_retarget_dequant(bytes(b),
                                               [v - pad for v in need_lo], span + 2 * pad))
            q = model_dequant(bytes(b))
            write_bbox(b, lo, hi)

    clamped = 0
    for ob in objs:
        mi = ob["umvc3_mesh_index"]
        m = meshes.get(mi)
        if m is None:
            raise RuntimeError("%s references mesh %d, absent from the source" % (ob.name, mi))
        me = ob.data
        if len(me.vertices) != m["nverts"]:
            raise RuntimeError(
                "%s has %d vertices but mesh %d expects %d. Topology is preserved - "
                "do not add or delete vertices." % (ob.name, len(me.vertices), mi, m["nverts"]))

        lay = layout_for(m["fmt"], m["stride"])
        if lay is None:
            continue                      # was skipped on import too
        base = vert_off + m["vbufoff"]
        mtx = ob.matrix_world

        uv_of_vert = {}
        if write_uvs and lay["uv0"] is not None and me.uv_layers.active:
            uvl = me.uv_layers.active
            for loop in me.loops:
                uv_of_vert.setdefault(loop.vertex_index, uvl.data[loop.index].uv)
        ca = me.color_attributes.get("color0") if write_colors else None

        for i, v in enumerate(me.vertices):
            vo = base + (m["vtxlo"] + i) * m["stride"]
            w = mtx @ v.co
            if lay["pos"] == "f32":
                for k in range(3):
                    newv = w[k] / scale
                    oldv = _f32(b, vo + 4 * k)
                    # Blender keeps coordinates as float32, so scaling in and
                    # back out cannot round-trip bit-exactly. Only rewrite when
                    # the vertex genuinely moved, otherwise an untouched model
                    # would come out different from the source.
                    if abs(newv - oldv) > max(1e-4, abs(oldv) * 1e-6):
                        struct.pack_into("<f", b, vo + 4 * k, newv)
            else:
                p = tuple(w[k] / scale for k in range(3))
                try:
                    struct.pack_into("<3H", b, vo, *q.encode(p))
                except ValueError:
                    clamped += 1
                    for k in range(3):
                        t = (p[k] - q.origin[k]) / q.scale
                        struct.pack_into("<H", b, vo + 2 * k,
                                         max(0, min(32767, int(round(t * POS_SCALE)))))
            if i in uv_of_vert:
                u, vv = uv_of_vert[i]
                struct.pack_into("<e", b, vo + lay["uv0"], float(u))
                struct.pack_into("<e", b, vo + lay["uv0"] + 2, float(1.0 - vv))
            if ca is not None and lay["color0"] is not None:
                c = ca.data[i].color
                o = vo + lay["color0"]
                for k in range(4):
                    b[o + k] = max(0, min(255, int(round(c[k] * 255.0))))

    return bytes(b), clamped


# ==================================================== structural edits =======
# Adding a card grows three tables. File order is bones, groups, materials,
# mesh table, bounding records, vertex buffer, index buffer - so an insert
# shifts everything after it. The bounding-record block holds no file offsets
# and already carries more records than meshes, so it only needs moving.

def mod_add_material_slots(mod, names):
    """Append 128-byte material name slots. -> (bytes, first_new_index)"""
    b = bytearray(mod)
    mat_count = _u16(b, H_MATCOUNT)
    mat_off = _u64(b, H_MATOFF)
    end = mat_off + mat_count * 128
    if end != _u64(b, H_MESHOFF):
        raise RuntimeError("material table is not flush against the mesh table")
    blob = bytearray()
    for nm in names:
        enc = nm.encode("ascii")
        if len(enc) > 127:
            raise RuntimeError("material name too long: %s" % nm)
        slot = bytearray(128)
        slot[0:len(enc)] = enc
        blob += slot
    out = bytearray(b[:end]) + blob + bytearray(b[end:])
    struct.pack_into("<H", out, H_MATCOUNT, mat_count + len(names))
    for off in (H_MESHOFF, H_VERTOFF, H_INDEXOFF, 0x58):
        struct.pack_into("<Q", out, off, _u64(out, off) + len(blob))
    return bytes(out), mat_count


# A .mrl is: header(40) | textures(88 each) | materials(72 each) | block data.
# Each material entry owns TWO variable-size blocks, each a (u64 pointer, u32
# size) pair. The second one is empty on most models, which is why sel1/sel2/
# selr1 looked like they carried an undecoded "trailer" - it was simply the
# second block array, unaccounted for.
MRL_ENT = 72
MRL_BLOCKS = ((56, 12), (64, 52))          # (pointer u64, size u32)


def mrl_data_end(mrl):
    """One past the highest byte any material block reaches."""
    n = _u32(mrl, 8)
    off = _u64(mrl, 32)
    end = off + n * MRL_ENT
    for i in range(n):
        o = off + i * MRL_ENT
        for ptr_at, size_at in MRL_BLOCKS:
            p = _u64(mrl, o + ptr_at)
            if p:
                end = max(end, p + _u32(mrl, o + size_at))
    return end


def mrl_trailer_size(mrl):
    """Bytes past the end of all material block data. Should be 0."""
    return len(mrl) - mrl_data_end(mrl)


def mrl_add_materials(mrl, template_idx, names):
    """Clone a material entry and both of its blocks, once per name."""
    b = bytearray(mrl)
    left = mrl_trailer_size(b)
    if left:
        raise RuntimeError("%d bytes of this .mrl are unaccounted for; refusing "
                           "to grow it" % left)
    n = _u32(b, 8)
    off = _u64(b, 32)
    end = off + n * MRL_ENT
    shift = len(names) * MRL_ENT
    tpl = bytes(b[off + template_idx * MRL_ENT: off + (template_idx + 1) * MRL_ENT])

    out = bytearray(b[:end])
    for nm in names:
        ent = bytearray(tpl)
        struct.pack_into("<I", ent, 8, mt_hash(nm))
        out += ent
    out += bytearray(b[end:])

    # Inserting entries pushed every block along; the new entries are clones, so
    # their pointers move with the template's and still resolve to it.
    total = n + len(names)
    for i in range(total):
        o = off + i * MRL_ENT
        for ptr_at, _ in MRL_BLOCKS:
            p = _u64(out, o + ptr_at)
            if p:
                struct.pack_into("<Q", out, o + ptr_at, p + shift)

    # Now give each new material its own copy, appended at the end.
    for k in range(len(names)):
        o = off + (n + k) * MRL_ENT
        for ptr_at, size_at in MRL_BLOCKS:
            p = _u64(out, o + ptr_at)
            size = _u32(out, o + size_at)
            if not p or not size:
                continue
            block = bytes(out[p:p + size])
            if len(block) != size:
                raise RuntimeError("template block at 0x%X truncated" % p)
            struct.pack_into("<Q", out, o + ptr_at, len(out))
            out += block

    struct.pack_into("<I", out, 8, total)
    return bytes(out)


def mod_replace_meshes(mod, specs):
    """specs: [{index, positions[(x,y,z)], uvs?, indices?, bone?}] -> new bytes

    Re-points EXISTING mesh entries at fresh geometry, so a model can be edited
    in Blender and written back without the mesh table growing. Appending
    instead would add an entry per export, and a scene exported twenty times
    would carry twenty dead copies of its own grid.

    Two paths, and the distinction is the whole point:

      * same vertex and index count - overwrite in place. Tuning positions is
        the common case and costs nothing; the file does not change size.
      * anything else - append a new vertex segment and index run, then point
        the entry at it. The old bytes are abandoned in the buffer, which is
        why this is not the default: the file grows by the mesh's size each
        time the topology changes.

    Stride, vertex format and material stay as the model already has them, and
    every new vertex starts as a copy of the mesh's own first vertex, so skin
    weights and colours carry over without this needing to understand them.
    """
    b = bytearray(mod)
    mesh_off = _u64(b, H_MESHOFF)
    vert_off = _u64(b, H_VERTOFF)
    idx_off = _u64(b, H_INDEXOFF)
    vbuf = _u32(b, H_VBUFSIZE)
    idx_count = _u32(b, 0x10)
    vert_count = _u32(b, 0x0C)
    q = model_dequant(bytes(b))
    meshes = {m["index"]: m for m in read_meshes(b)}

    verts = bytearray(b[vert_off:vert_off + vbuf])
    idxs = bytearray(b[idx_off:idx_off + idx_count * 2])
    next_i = idx_count
    added = 0

    for s in specs:
        mi = s["index"]
        if mi not in meshes:
            raise RuntimeError("no mesh %d to replace" % mi)
        m = meshes[mi]
        stride = m["stride"]
        lay = layout_for(m["fmt"], stride)
        if lay is None:
            raise RuntimeError("mesh %d: unknown layout fmt %d stride %d"
                               % (mi, m["fmt"], stride))
        pos = s["positions"]
        nv = len(pos)
        if nv < 1 or nv > 0xFFFF:
            raise RuntimeError("mesh %d: %d vertices is out of range" % (mi, nv))
        tri = list(s.get("indices") or [])
        if not tri:
            raise RuntimeError("mesh %d: replacement needs a triangle list" % mi)

        in_place = (nv == m["nverts"] and len(tri) == m["idxcount"])
        if in_place:
            seg_off, base_i = m["vbufoff"] + m["vtxlo"] * stride, m["idxstart"]
        else:
            while len(verts) % 16:
                verts += b"\0"
            seg_off, base_i = len(verts), next_i

        src = vert_off + m["vbufoff"] + m["vtxlo"] * stride
        first = bytes(b[src:src + stride])
        chunk = bytearray(first * nv) if not in_place else \
            bytearray(verts[seg_off:seg_off + nv * stride])
        bone = s.get("bone")
        if bone is not None and stride != SKIN_STRIDE:
            raise RuntimeError("bone binding needs stride %d, mesh %d is %d"
                               % (SKIN_STRIDE, mi, stride))
        uvs = s.get("uvs")
        # Not every model quantises. `0000` stores plain float32 positions
        # (fmt 1, stride 20), and packing three u16 into that field writes
        # nonsense - which is also why it read back as garbage and looked edited
        # on every export.
        f32_pos = lay.get("pos") == "f32"
        for vi in range(nv):
            o = vi * stride
            if f32_pos:
                struct.pack_into("<3f", chunk, o, *[float(c) for c in pos[vi]])
            else:
                struct.pack_into("<3H", chunk, o, *q.encode(pos[vi]))
            if uvs and lay["uv0"] is not None:
                u, v = uvs[vi]
                struct.pack_into("<e", chunk, o + lay["uv0"], float(u))
                struct.pack_into("<e", chunk, o + lay["uv0"] + 2, float(v))
            if bone is not None:
                write_skin(chunk, o, {bone: 1.0})

        if in_place:
            verts[seg_off:seg_off + nv * stride] = chunk
            for k, t in enumerate(tri):
                struct.pack_into("<H", idxs, (base_i + k) * 2, t)
        else:
            verts += chunk
            for t in tri:
                idxs += struct.pack("<H", t)
            next_i += len(tri)
            added += nv

        e = mesh_off + mi * MESH_STRIDE
        struct.pack_into("<H", b, e + 2, nv)
        struct.pack_into("<I", b, e + M_VBUFOFF, seg_off if not in_place else m["vbufoff"])
        struct.pack_into("<I", b, e + M_IDXSTART, base_i)
        struct.pack_into("<I", b, e + M_IDXCOUNT, len(tri))
        if not in_place:
            struct.pack_into("<H", b, e + M_VTXLO, 0)
            struct.pack_into("<H", b, e + M_VTXHI, nv - 1)

    out = bytearray(b[:vert_off])
    out += verts
    out += idxs
    struct.pack_into("<I", out, 0x0C, vert_count + added)
    struct.pack_into("<I", out, 0x10, next_i)
    struct.pack_into("<I", out, 0x14, next_i // 3)
    struct.pack_into("<I", out, H_VBUFSIZE, len(verts))
    struct.pack_into("<Q", out, H_INDEXOFF, vert_off + len(verts))
    struct.pack_into("<Q", out, 0x58, len(out))
    write_bbox(out, *mod_geometry_bounds(bytes(out)))
    return bytes(out)


def mod_append_meshes(mod, specs):
    """specs: [{template, material, positions[(x,y,z)], uvs?, indices?}]

    `template` supplies the vertex format, the stride, and the mesh-table entry
    to clone. Give `indices` - a flat triangle list, 0-based into `positions` -
    and the new mesh can be any shape; omit it and the template's own topology
    is reused, which is what cloning a card wants.

    `bone` rigid-binds every new vertex to one bone. Without it the new vertices
    inherit the template's skin weights, and that is a trap: a template taken
    from animated geometry drags the new mesh along with it at runtime. It looks
    perfect in Blender, which reads vertex positions and ignores skinning, and
    wrong in game. Bind to the root (usually bone 0) for geometry meant to hold
    still. Only meaningful at stride 40, the one skinned layout that is decoded.

    Positions are in game units and must fit the model's existing decode. Call
    mod_retarget_dequant first if they do not - growing the header box does
    nothing, the box is inert.

    A model may carry SEVERAL vertex segments, each with its own stride and byte
    offset: `chs_meku` has five (strides 12, 24, 28, and 40 twice), and each
    mesh entry names its own via vbufoff, with vtxlo indexing inside it. New
    meshes therefore go into a fresh segment appended after the last one -
    nothing already in the buffer moves, and no existing mesh entry changes.
    That is what lets the book model take new geometry at all.
    """
    b = bytearray(mod)
    mesh_count = _u16(b, H_MESHCOUNT)
    vert_count = _u32(b, 0x0C)
    idx_count = _u32(b, 0x10)
    vbuf = _u32(b, H_VBUFSIZE)
    mesh_off = _u64(b, H_MESHOFF)
    vert_off = _u64(b, H_VERTOFF)
    idx_off = _u64(b, H_INDEXOFF)
    q = model_dequant(bytes(b))
    meshes = {m["index"]: m for m in read_meshes(b)}

    block = bytes(b[mesh_off + mesh_count * 56:vert_off])
    verts = bytearray(b[vert_off:vert_off + vbuf])
    idxs = bytearray(b[idx_off:idx_off + idx_count * 2])

    new_entries = bytearray()
    next_i = idx_count
    added_verts = 0
    for n, s in enumerate(specs):
        tpl = meshes[s["template"]]
        stride = tpl["stride"]
        lay = layout_for(tpl["fmt"], stride)
        if lay is None:
            raise RuntimeError("template mesh %d has an unsupported vertex format"
                               % tpl["index"])
        pos = s["positions"]
        nv = len(pos)
        tri = s.get("indices")
        if tri is None:
            if nv != tpl["nverts"]:
                raise RuntimeError("cloning mesh %d needs %d vertices, got %d"
                                   % (tpl["index"], tpl["nverts"], nv))
            tri = [_u16(b, idx_off + (tpl["idxstart"] + k) * 2) - tpl["vtxlo"]
                   for k in range(tpl["idxcount"])]
        if nv == 0 or len(tri) % 3:
            raise RuntimeError("need a whole number of triangles")
        if min(tri) < 0 or max(tri) >= nv or nv > 0xFFFF:
            raise RuntimeError("triangle index outside the new mesh's %d vertices" % nv)

        # segments in this buffer all start 16-byte aligned; keep that
        while len(verts) % 16:
            verts += b"\0"
        seg_off = len(verts)

        # Every new vertex begins as a copy of the template's first, so they all
        # carry identical skin weights and transform as one - the new mesh keeps
        # the shape authored here instead of being bent by the model's rig, and
        # the skin layout never has to be understood.
        vsrc = vert_off + tpl["vbufoff"] + tpl["vtxlo"] * stride
        first = bytes(b[vsrc:vsrc + stride])
        chunk = bytearray(first * nv)
        bone = s.get("bone")
        if bone is not None and stride != SKIN_STRIDE:
            raise RuntimeError("bone binding needs stride %d, template %d is %d"
                               % (SKIN_STRIDE, tpl["index"], stride))
        for vi in range(nv):
            o = vi * stride
            struct.pack_into("<3H", chunk, o, *q.encode(pos[vi]))
            if s.get("uvs") and lay["uv0"] is not None:
                u, v = s["uvs"][vi]
                struct.pack_into("<e", chunk, o + lay["uv0"], float(u))
                struct.pack_into("<e", chunk, o + lay["uv0"] + 2, float(v))
            if bone is not None:
                write_skin(chunk, o, {bone: 1.0})
        verts += chunk
        for t in tri:
            idxs += struct.pack("<H", t)

        ti = tpl["index"]
        ent = bytearray(b[mesh_off + ti * 56: mesh_off + (ti + 1) * 56])
        struct.pack_into("<H", ent, 2, nv)
        struct.pack_into("<I", ent, M_VBUFOFF, seg_off)
        struct.pack_into("<I", ent, M_IDXSTART, next_i)
        struct.pack_into("<I", ent, M_IDXCOUNT, len(tri))
        struct.pack_into("<H", ent, M_VTXLO, 0)
        struct.pack_into("<H", ent, M_VTXHI, nv - 1)
        mi = s["material"]
        ent[5] = (ent[5] & 0x0F) | ((mi & 0x0F) << 4)
        ent[6] = (mi >> 4) & 0xFF
        ent[38] = (mesh_count + n + 1) & 0xFF
        new_entries += ent
        next_i += len(tri)
        added_verts += nv
    next_v = vert_count + added_verts

    new_vert_off = mesh_off + (mesh_count + len(specs)) * 56 + len(block)
    out = bytearray(b[:mesh_off])
    out += b[mesh_off:mesh_off + mesh_count * 56]
    out += new_entries
    out += block
    out += verts
    out += idxs
    struct.pack_into("<H", out, H_MESHCOUNT, mesh_count + len(specs))
    struct.pack_into("<I", out, 0x0C, next_v)
    struct.pack_into("<I", out, 0x10, next_i)
    struct.pack_into("<I", out, 0x14, next_i // 3)
    struct.pack_into("<I", out, H_VBUFSIZE, len(verts))
    struct.pack_into("<Q", out, H_VERTOFF, new_vert_off)
    struct.pack_into("<Q", out, H_INDEXOFF, new_vert_off + len(verts))
    struct.pack_into("<Q", out, 0x58, len(out))
    write_bbox(out, *mod_geometry_bounds(bytes(out)))
    return bytes(out)


# ========================================================= archive session ===
def cache_dir_for(path):
    near = os.path.join(os.path.dirname(os.path.abspath(path)), "_umvc3_cache")
    try:
        os.makedirs(near, exist_ok=True)
        probe = os.path.join(near, ".probe")
        with open(probe, "wb") as f:
            f.write(b"x")
        os.remove(probe)
        return near
    except OSError:
        fallback = os.path.join(tempfile.gettempdir(), "umvc3_cache")
        os.makedirs(fallback, exist_ok=True)
        return fallback


class ArchiveTextures(object):
    """Resolves .mrl / .tex entries inside the archive being imported."""

    def __init__(self, entries, cache):
        self.by_key = {e.key: e for e in entries}
        self.cache = cache
        self.images = {}

    def mrl_for(self, mod_entry_name):
        """(textures, material hash -> mrl index, material hash -> texture index)"""
        e = self.by_key.get((mod_entry_name, EXT_HASHES["mrl"]))
        if e is None:
            return [], {}, {}
        textures, hash_to_index = parse_mrl_bytes(e.data)
        return textures, hash_to_index, mrl_texture_bindings(e.data)

    def image_for(self, tex_rel):
        if tex_rel in self.images:
            return self.images[tex_rel]
        e = self.by_key.get((tex_rel, EXT_HASHES["tex"]))
        img = None
        if e is not None:
            dds = tex_to_dds_bytes(e.data)
            if dds:
                safe = tex_rel.replace("\\", "_").replace("/", "_") + ".dds"
                p = os.path.join(self.cache, safe)
                if not os.path.isfile(p) or os.path.getsize(p) != len(dds):
                    with open(p, "wb") as f:
                        f.write(dds)
                try:
                    img = bpy.data.images.load(p, check_existing=True)
                    img["umvc3_entry"] = tex_rel
                    img["umvc3_cache"] = p
                    # name it after the resource, not the mangled cache file,
                    # so it is findable in the Image dropdowns
                    nice = tex_rel.replace("\\", "/").split("/")[-1]
                    if img.name != nice and nice not in bpy.data.images:
                        img.name = nice
                except RuntimeError:
                    img = None
        self.images[tex_rel] = img
        return img

    def preload_all(self):
        n = 0
        for e in self.by_key.values():
            if e.hash == EXT_HASHES["tex"] and self.image_for(e.name) is not None:
                n += 1
        return n


def texture_is_modified(img):
    """Did the user change this imported texture?"""
    if img.is_dirty:
        return True
    cached = img.get("umvc3_cache")
    if not cached:
        return False
    try:
        return os.path.normcase(bpy.path.abspath(img.filepath)) != os.path.normcase(cached)
    except Exception:
        return False


def import_archive(context, filepath, scale, do_models, do_textures, name_filter):
    version, entries = read_arc(filepath)
    cache = cache_dir_for(filepath)
    tex = ArchiveTextures(entries, cache) if do_textures else None

    nf = name_filter.strip().lower()
    n_tex = tex.preload_all() if tex else 0

    top = bpy.data.collections.new(os.path.basename(filepath))
    context.scene.collection.children.link(top)

    n_models = 0
    n_meshes = 0
    for e in entries:
        if e.hash != EXT_HASHES["mod"] or not do_models:
            continue
        if nf and nf not in e.name.lower():
            continue
        col = bpy.data.collections.new(e.name.replace("\\", "/").split("/")[-1])
        top.children.link(col)
        try:
            n_meshes += import_mod_bytes(context, e.data, e.name, scale, tex, col)
            n_models += 1
        except RuntimeError as err:
            print("[umvc3] skipped %s: %s" % (e.name, err))
            bpy.data.collections.remove(col)

    context.scene["umvc3_arc"] = os.path.abspath(filepath)
    context.scene["umvc3_arc_version"] = version
    context.scene["umvc3_scale"] = scale
    print("[umvc3] %s: %d entries, %d models (%d meshes), %d textures"
          % (os.path.basename(filepath), len(entries), n_models, n_meshes, n_tex))
    return len(entries), n_models, n_meshes, n_tex


def export_archive(context, filepath, source_arc, scale, expand_bbox):
    version, entries = read_arc(source_arc)
    by_key = {e.key: e for e in entries}

    # group imported objects by their source entry
    groups = {}
    for ob in context.scene.objects:
        if ob.type == "MESH" and "umvc3_entry" in ob.keys() and "umvc3_mesh_index" in ob.keys():
            groups.setdefault(ob["umvc3_entry"], []).append(ob)

    models_written = 0
    total_clamped = 0
    for name, objs in groups.items():
        e = by_key.get((name, EXT_HASHES["mod"]))
        if e is None:
            print("[umvc3] %s not in %s, skipped" % (name, os.path.basename(source_arc)))
            continue
        sc = objs[0].get("umvc3_scale", scale)
        data, clamped = patch_mod_bytes(e.data, objs, sc, expand_bbox=expand_bbox)
        if data != e.data:
            e.data = data
            e.dirty = True
            models_written += 1
        total_clamped += clamped

    # ---- structural additions: cards created with Add Card -----------------
    new_groups = {}
    for ob in context.scene.objects:
        if ob.type == "MESH" and "umvc3_entry" in ob.keys() and "umvc3_new_from" in ob.keys():
            new_groups.setdefault(ob["umvc3_entry"], []).append(ob)

    cards_added = 0
    for name, objs in sorted(new_groups.items()):
        mod_e = by_key.get((name, EXT_HASHES["mod"]))
        if mod_e is None:
            print("[umvc3] %s not in archive, new cards skipped" % name)
            continue
        mrl_e = by_key.get((name, EXT_HASHES["mrl"]))
        sc = objs[0].get("umvc3_scale", scale)
        existing = read_mod_material_names(mod_e.data)
        meshes = {m["index"]: m for m in read_meshes(mod_e.data)}

        tpl_mats, new_names = [], []
        for k, ob in enumerate(objs):
            tpl = ob["umvc3_new_from"]
            if tpl not in meshes:
                raise RuntimeError("%s clones mesh %d, absent from %s" % (ob.name, tpl, name))
            tpl_mats.append(meshes[tpl]["material"])
            base = existing[tpl_mats[k]].rstrip("_")
            cand = "%s_n%d" % (base, k)
            while cand in existing or cand in new_names:
                cand += "x"
            new_names.append(cand)

        # Only give the new meshes their own materials when the .mrl can take
        # them. Overlay models carry an undecoded trailer, so they reuse the
        # template's material - which is correct anyway: a highlight is generic,
        # it is the portrait cards that need distinct slots.
        can_add = mrl_e is not None and mrl_trailer_size(mrl_e.data) == 0
        if can_add:
            mod_data, first_new = mod_add_material_slots(mod_e.data, new_names)
            mrl_e.data = mrl_add_materials(mrl_e.data, tpl_mats[0], new_names)
            mrl_e.dirty = True
        else:
            mod_data, first_new = mod_e.data, None
            if mrl_e is not None:
                print("[umvc3] %s: .mrl has a trailer, new meshes reuse existing materials"
                      % _leaf(name))

        specs = []
        for k, ob in enumerate(objs):
            me = ob.data
            mtx = ob.matrix_world
            pos = [tuple((mtx @ v.co)[j] / sc for j in range(3)) for v in me.vertices]
            uvs = None
            if me.uv_layers.active:
                uvl = me.uv_layers.active
                per_vert = {}
                for loop in me.loops:
                    per_vert.setdefault(loop.vertex_index, uvl.data[loop.index].uv)
                uvs = [(per_vert[i][0], 1.0 - per_vert[i][1]) if i in per_vert else (0.0, 0.0)
                       for i in range(len(me.vertices))]
            mat = (first_new + k) if first_new is not None else tpl_mats[k]
            specs.append({"template": ob["umvc3_new_from"], "material": mat,
                          "positions": pos, "uvs": uvs})

        mod_e.data = mod_append_meshes(mod_data, specs)
        mod_e.dirty = True
        cards_added += len(objs)

    tex_written = 0
    tex_failed = []
    for img in bpy.data.images:
        name = img.get("umvc3_entry")
        if not name or not texture_is_modified(img):
            continue
        e = by_key.get((name, EXT_HASHES["tex"]))
        if e is None:
            continue
        try:
            e.data = encode_image_to_tex(img, e.data)
            e.dirty = True
            tex_written += 1
        except RuntimeError as err:
            tex_failed.append("%s (%s)" % (name, err))

    size = write_arc(filepath, version, entries)
    return {
        "entries": len(entries), "models": models_written, "textures": tex_written,
        "clamped": total_clamped, "failed": tex_failed, "size": size,
        "cards": cards_added,
    }


def import_mod(context, filepath, scale, collection=None):
    """Load one loose .mod. -> mesh count. No textures; those need the archive."""
    with open(filepath, "rb") as f:
        data = f.read()
    return import_mod_bytes(context, data, os.path.abspath(filepath), scale,
                            None, collection or context.collection)


def export_mod(context, filepath, template_path, scale, write_uvs=True,
               write_colors=True, expand_bbox=False):
    """Patch one loose .mod from the imported meshes. -> (meshes, clamped)."""
    objs = [o for o in context.scene.objects
            if o.type == "MESH" and "umvc3_mesh_index" in o.keys()]
    if not objs:
        raise RuntimeError("no imported UMVC3 meshes in the scene")
    with open(template_path, "rb") as f:
        template = f.read()
    data, clamped = patch_mod_bytes(template, objs, scale, write_uvs,
                                    write_colors, expand_bbox)
    with open(filepath, "wb") as f:
        f.write(data)
    return len(objs), clamped


# ============================================================== operators ====
class IMPORT_OT_umvc3_arc(bpy.types.Operator, ImportHelper):
    """Open an entire MT Framework archive: every model, material and texture"""
    bl_idname = "import_scene.umvc3_arc"
    bl_label = "Import UMVC3 Archive"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".arc"
    filter_glob: StringProperty(default="*.arc", options={"HIDDEN"})
    scale: FloatProperty(
        name="Scale", default=0.01, min=0.0001, max=10.0,
        description="Game units are large (~1500 across); 0.01 keeps models inside Blender's default clipping")
    do_models: BoolProperty(name="Import Models", default=True)
    do_textures: BoolProperty(name="Import Textures", default=True)
    name_filter: StringProperty(
        name="Name Filter", default="",
        description="Only import models whose entry path contains this text. Leave blank for all")

    def execute(self, context):
        try:
            n, models, meshes, tex = import_archive(
                context, self.filepath, self.scale,
                self.do_models, self.do_textures, self.name_filter)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, "%d entries: %d models / %d meshes / %d textures"
                    % (n, models, meshes, tex))
        return {"FINISHED"}


class EXPORT_OT_umvc3_arc(bpy.types.Operator, ExportHelper):
    """Write the archive back, re-encoding edited models and textures"""
    bl_idname = "export_scene.umvc3_arc"
    bl_label = "Save UMVC3 Archive"
    filename_ext = ".arc"
    filter_glob: StringProperty(default="*.arc", options={"HIDDEN"})
    source: StringProperty(
        name="Source .arc", subtype="FILE_PATH",
        description="Archive to use as the baseline. Blank = the one this scene was imported from")
    scale: FloatProperty(name="Scale", default=0.01, min=0.0001, max=10.0)
    expand_bbox: BoolProperty(
        name="Expand Bounding Box", default=False,
        description="Grow each model's bbox to cover moved vertices. Only grows, never shrinks")

    def invoke(self, context, event):
        src = context.scene.get("umvc3_arc")
        if src and not self.filepath:
            self.filepath = os.path.basename(src)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        src = bpy.path.abspath(self.source) if self.source else context.scene.get("umvc3_arc")
        if not src or not os.path.isfile(src):
            self.report({"ERROR"}, "No source .arc - import one first or set it explicitly")
            return {"CANCELLED"}
        try:
            r = export_archive(context, self.filepath, src, self.scale, self.expand_bbox)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        msg = "%d entries, %d models + %d textures re-encoded (%d KB)" % (
            r["entries"], r["models"], r["textures"], r["size"] // 1024)
        if r.get("cards"):
            msg += "; %d new card mesh(es) added" % r["cards"]
        level = "INFO"
        if r["clamped"]:
            msg += "; %d coords clamped - enable Expand Bounding Box" % r["clamped"]
            level = "WARNING"
        if r["failed"]:
            msg += "; FAILED: " + ", ".join(r["failed"])
            level = "WARNING"
        self.report({level}, msg)
        return {"FINISHED"}


class IMPORT_OT_umvc3_mod(bpy.types.Operator, ImportHelper):
    """Import a single loose .mod file"""
    bl_idname = "import_scene.umvc3_mod"
    bl_label = "Import UMVC3 Model"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".mod"
    filter_glob: StringProperty(default="*.mod", options={"HIDDEN"})
    scale: FloatProperty(name="Scale", default=0.01, min=0.0001, max=10.0)

    def execute(self, context):
        try:
            n = import_mod(context, self.filepath, self.scale)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, "Imported %d meshes (no textures - use archive import for those)" % n)
        return {"FINISHED"}


class EXPORT_OT_umvc3_mod(bpy.types.Operator, ExportHelper):
    """Export the active model back to a loose .mod file"""
    bl_idname = "export_scene.umvc3_mod"
    bl_label = "Export UMVC3 Model"
    filename_ext = ".mod"
    filter_glob: StringProperty(default="*.mod", options={"HIDDEN"})
    template: StringProperty(
        name="Template .mod", subtype="FILE_PATH",
        description="Original .mod to patch. Blank = the file this model was imported from")
    scale: FloatProperty(name="Scale", default=0.01, min=0.0001, max=10.0)
    expand_bbox: BoolProperty(name="Expand Bounding Box", default=False)

    def execute(self, context):
        objs = [o for o in context.scene.objects
                if o.type == "MESH" and "umvc3_mesh_index" in o.keys()]
        if not objs:
            self.report({"ERROR"}, "No imported UMVC3 meshes in the scene")
            return {"CANCELLED"}
        tpl = bpy.path.abspath(self.template) if self.template else objs[0].get("umvc3_entry")
        if not tpl or not os.path.isfile(tpl):
            self.report({"ERROR"}, "No template .mod - set one explicitly "
                                   "(models opened from an archive save via File > Export > UMVC3 Archive)")
            return {"CANCELLED"}
        try:
            sc = objs[0].get("umvc3_scale", self.scale)
            _, clamped = export_mod(context, self.filepath, tpl, sc,
                                    expand_bbox=self.expand_bbox)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        msg = "Exported %d meshes" % len(objs)
        if clamped:
            self.report({"WARNING"}, msg + " (%d coords clamped)" % clamped)
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class UMVC3_OT_replace_texture(bpy.types.Operator, ImportHelper):
    """Point the selected archive texture at an image file of your own"""
    bl_idname = "umvc3.replace_texture"
    bl_label = "Replace Texture"
    bl_options = {"REGISTER", "UNDO"}
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif;*.tiff;*.dds;*.exr",
        options={"HIDDEN"})

    def execute(self, context):
        img = context.scene.umvc3_texture
        if img is None:
            self.report({"ERROR"}, "Pick a texture first")
            return {"CANCELLED"}
        if not os.path.isfile(self.filepath):
            self.report({"ERROR"}, "No such file")
            return {"CANCELLED"}
        try:
            img.filepath = self.filepath
            img.source = "FILE"
            img.reload()
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, "%s -> %s (re-encoded on save)"
                    % (img.get("umvc3_entry", img.name), os.path.basename(self.filepath)))
        return {"FINISHED"}


class UMVC3_OT_revert_texture(bpy.types.Operator):
    """Restore the selected texture to the version in the archive"""
    bl_idname = "umvc3.revert_texture"
    bl_label = "Revert Texture"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        img = context.scene.umvc3_texture
        if img is None:
            self.report({"ERROR"}, "Pick a texture first")
            return {"CANCELLED"}
        cache = img.get("umvc3_cache")
        if not cache or not os.path.isfile(cache):
            self.report({"ERROR"}, "No cached original for this texture")
            return {"CANCELLED"}
        img.filepath = cache
        img.source = "FILE"
        img.reload()
        self.report({"INFO"}, "Reverted %s" % img.get("umvc3_entry", img.name))
        return {"FINISHED"}


# Card grids come in matched sets per side: the portrait model plus the hover
# and selected-state overlays, which sit at identical positions (mesh i in
# sel1_a matches mesh i in face_a). A new card needs a clone in every one of
# them or it cannot be highlighted or selected in game.
CARD_MODEL_RE = re.compile(r"^chs_meku_(face|sel\d+|seld\d+|selr\d+)_([ab])(_typeC)?$")


def _leaf(entry):
    return entry.replace("\\", "/").split("/")[-1]


class UMVC3_OT_add_card(bpy.types.Operator):
    """Clone the selected card - and its hover/selected-state overlays - into a
    new slot. The copies are written as new meshes when you save the archive"""
    bl_idname = "umvc3.add_card"
    bl_label = "Add Card"
    bl_options = {"REGISTER", "UNDO"}

    dx: FloatProperty(name="Offset X", default=0.0,
                      description="Game units. Grid columns are ~64 apart")
    dy: FloatProperty(name="Offset Y", default=-68.0,
                      description="Game units. Grid rows are ~68 apart, negative is down")
    include_states: BoolProperty(
        name="Include Hover / Select States", default=True,
        description="Also clone the matching mesh from every sel/seld/selr model on this "
                    "side, so the new card can be highlighted and selected")

    def execute(self, context):
        ob = context.active_object
        if ob is None or ob.type != "MESH" or "umvc3_mesh_index" not in ob.keys():
            self.report({"ERROR"}, "Select a card imported from an archive")
            return {"CANCELLED"}

        idx = ob["umvc3_mesh_index"]
        side = None
        m = CARD_MODEL_RE.match(_leaf(ob.get("umvc3_entry", "")))
        if m:
            side = m.group(2)

        targets = [ob]
        if self.include_states and side:
            for other in context.scene.objects:
                if other is ob or other.type != "MESH":
                    continue
                if other.get("umvc3_mesh_index") != idx:
                    continue
                mm = CARD_MODEL_RE.match(_leaf(other.get("umvc3_entry", "")))
                if mm and mm.group(2) == side:
                    targets.append(other)

        sc = ob.get("umvc3_scale", 0.01)
        created = []
        for t in targets:
            new = t.copy()
            new.data = t.data.copy()
            new.name = "%s_new" % t.name
            for col in t.users_collection:
                col.objects.link(new)
            new["umvc3_new_from"] = t["umvc3_mesh_index"]
            del new["umvc3_mesh_index"]          # it is not an existing mesh any more
            new.location = t.location.copy()
            new.location.x += self.dx * sc
            new.location.y += self.dy * sc
            created.append(new)

        for o in context.selected_objects:
            o.select_set(False)
        for o in created:
            o.select_set(True)
        context.view_layer.objects.active = created[0]

        self.report({"INFO"}, "Cloned %d mesh(es): %s"
                    % (len(created), ", ".join(sorted(_leaf(o["umvc3_entry"]) for o in created))))
        return {"FINISHED"}


def _umvc3_tex_poll(self, img):
    return img.get("umvc3_entry") is not None


class UMVC3_PT_archive(bpy.types.Panel):
    """Properties > Scene, alongside the character-select panels rather than in
    a viewport tab of its own."""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_label = "UMVC3 Archive"

    def draw(self, context):
        layout = self.layout
        arc = context.scene.get("umvc3_arc")
        if not arc:
            layout.label(text="No archive loaded", icon="INFO")
            layout.operator(IMPORT_OT_umvc3_arc.bl_idname, text="Open Archive…", icon="FILE_FOLDER")
            return

        box = layout.box()
        box.label(text=os.path.basename(arc), icon="PACKAGE")

        roots = [o for o in context.scene.objects if o.get("umvc3_is_model_root")]
        imgs = [i for i in bpy.data.images if i.get("umvc3_entry")]
        changed = [i for i in imgs if texture_is_modified(i)]
        box.label(text="%d models, %d textures" % (len(roots), len(imgs)))
        if changed:
            box.label(text="%d texture(s) edited" % len(changed), icon="BRUSH_DATA")

        pending = [o for o in context.scene.objects if o.get("umvc3_new_from") is not None]
        if pending:
            box.label(text="%d new card mesh(es) pending" % len(pending), icon="ADD")

        col = layout.column(align=True)
        col.label(text="Cards:")
        col.operator(UMVC3_OT_add_card.bl_idname, text="Add Card", icon="DUPLICATE")

        col = layout.column(align=True)
        col.label(text="Texture:")
        col.prop(context.scene, "umvc3_texture", text="")
        img = context.scene.umvc3_texture
        if img is not None:
            info = col.box()
            info.label(text=img.get("umvc3_entry", img.name))
            info.label(text="%d x %d" % (img.size[0], img.size[1]))
            if texture_is_modified(img):
                info.label(text="edited - will be re-encoded", icon="BRUSH_DATA")
            row = col.row(align=True)
            row.operator(UMVC3_OT_replace_texture.bl_idname, text="Replace…", icon="FILEBROWSER")
            row.operator(UMVC3_OT_revert_texture.bl_idname, text="Revert", icon="LOOP_BACK")

        layout.separator()
        layout.operator(EXPORT_OT_umvc3_arc.bl_idname, text="Save Archive As…", icon="FILE_TICK")
        layout.operator(IMPORT_OT_umvc3_arc.bl_idname, text="Open Another…", icon="FILE_FOLDER")


def menu_import(self, context):
    self.layout.operator(IMPORT_OT_umvc3_arc.bl_idname, text="UMVC3 Archive (.arc)")
    self.layout.operator(IMPORT_OT_umvc3_mod.bl_idname, text="UMVC3 Model (.mod)")


def menu_export(self, context):
    self.layout.operator(EXPORT_OT_umvc3_arc.bl_idname, text="UMVC3 Archive (.arc)")
    self.layout.operator(EXPORT_OT_umvc3_mod.bl_idname, text="UMVC3 Model (.mod)")


CLASSES = (IMPORT_OT_umvc3_arc, EXPORT_OT_umvc3_arc,
           IMPORT_OT_umvc3_mod, EXPORT_OT_umvc3_mod,
           UMVC3_OT_add_card,
           UMVC3_OT_replace_texture, UMVC3_OT_revert_texture, UMVC3_PT_archive)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.umvc3_texture = bpy.props.PointerProperty(
        type=bpy.types.Image, poll=_umvc3_tex_poll,
        name="Texture", description="Archive texture to replace or revert")
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    del bpy.types.Scene.umvc3_texture
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
