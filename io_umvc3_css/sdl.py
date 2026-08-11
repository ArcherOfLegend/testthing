"""The `.sdl` scheduler resources: where the engine draws what, and when.

Several models in the character-select archives sit at their own local origin -
`chs_card`, its name plate and type panel, the cursor - because nothing in the
model places them. **The `.sdl` does.** It is a node tree with animated
transforms, and the engine binds a drawn unit to a node by name:

    uMenuChrSelCardPlayer__setup   loads ui\\chs\\chs_meku\\chs_card%dp
    uMenuChrSelCardPlayer_vfn28    formats chs_card%dp_no%d[_tf|_tw]
    MtAnim__helper_E580(anim, name)  ->  the node
    sMvc3Manager__beginPhase_19A0(unit, node, ...)  binds the two

So a card's position is a keyframe in an archive file, not a constant in the
exe, and it is editable like anything else here.

The format
==========

    +0x00  "SDL\\0"
    +0x04  u16 version (0x16)   +0x06  u16 record count
    +0x08  u32 DTI hash of rScheduler   +0x0C u32 (unidentified, preserved)
    +0x18  u64 offset of the string table
    0x20   record[count], 0x30 bytes each

    record +0x00  u8  storage kind    +0x01 u8 property type    +0x02 u16 keys
           +0x04  u32  object: unused. property: OWNER RECORD INDEX
           +0x08  u64  name, as an offset into the string table
           +0x10  u32  object: the DTI hash of its class
           +0x20  u64  key table, one u32 per key
           +0x28  u64  values, `kind` bytes each

    key word:  frame in the low 16 bits, interpolation code in bits 24..31

An object owns every following record whose `+0x04` is its own index. Record 0
is always `Root`, which is why owner indices used to look one-based.

`mpParent` holds a record index. `mpModel` holds a string-table offset to a
*typed* reference: the four bytes there are the extension hash (`0x58A15856`,
`.mod`) and the path follows. Object 0 is `UiSdlAnimeFrame`, and its properties
are the clip table - `FrameName<i>`, `FrameStart<i>`, `FrameEnd<i>`, the last
two being **floats**, not ints. The key frames land exactly on those clip
boundaries, which is what says the parse is right rather than merely plausible.

How this was pinned down
========================

`rScheduler__convert` @ `0x140522670` is the load-time fixup, and it settles
what a record is: it walks records from **0x20** (not 0x50 - the table starts
right after the header, and record 0 is `Root`), reads the kind at `+0x00` and
the key count at `+0x02`, relocates the name at `+0x08` against the string
table, resolves `+0x10` through `MtDTI__findByHash` for objects, and relocates
the key table and values at `+0x20`/`+0x28` for kinds 6..16 only. Kind 13's
values are string offsets it loads as resources - that is `mpModel`.

**A value is `kind` bytes wide, not 16.** Vectors and colours are 16, a float
or an int 4, a bool 1, a string or resource reference 8. Reading everything as
16 silently misreads any multi-key scalar track - `mTransparency`, `mFrame`,
`mDepth` - as neighbouring keys' bytes. The old `.sdl` reader here did that;
it only ever looked at `mPos`/`mAngle`/`mScale`, which are genuinely 16.

**The key count is in the record**, at `+0x02`. Deriving it from the gap
between the key table and the values overruns, because the table is padded to
16 while one property's values run right up to the next property's key table.

Both are verified by rebuilding: `build()` reproduces **1657 of the 1664 `.sdl`
files the game ships byte for byte**, and all 29 in the character-select
archives. The 7 that differ are main-menu files whose blocks are laid out in a
different order; they still rebuild to a valid, equivalent file, and nothing
rewrites a resource it did not edit.

Interpolation
=============

Bits 24..31 of a key word are an interpolation code. Across every `.sdl` in the
game it is one of 0, 2, 3 and 5. Integer, bool and string tracks are always 0;
float and vector tracks are 3, sometimes 5, and **sometimes 0 on individual
keys of an otherwise moving track** - which is what a hold looks like. So:

    0  -> the value is held until the next key (Blender's CONSTANT)
    3  -> interpolated; the ordinary case
    5  -> interpolated; a second mode, seen on 118 keys, all of them on
          vector tracks, clustered where a card eases into a zoom

What separates 3 from 5 has not been decoded, and neither has the exact curve
either of them draws between two keys, so both import as linear - a straight
reading of the keys that are actually in the file rather than an invented
spline. **The code is preserved per key on export**, so a round trip does not
quietly retype a track, and an edited key keeps the code of the key it
replaces.

Rotation
========

`uCoord__setEulerRotation` @ `0x140547b50` switches on the rotation order at
`uCoord+0x4c`; order 0 builds

    [ cz cy,            cy sz,             -sy   ]
    [ sx sy cz - cx sz, cx cz + sx sy sz,  cy sx ]
    [ cx sy cz + sx sz, cx sy sz - sx cz,  cy cx ]

which is `Rz . Ry . Rx` transposed for MT's row-vector convention - exactly
Blender's `Euler(..., "XYZ")`. No `.sdl` in the character-select archives sets
a rotation order at all, so order 0 is what they get, and XYZ is right rather
than merely convenient.
"""
import struct

MAGIC = b"SDL\0"
REC = 0x30
FIRST = 0x20                     # the record table starts here; record 0 is Root
OBJECT = 2                       # storage kind 2 marks an object

# uCoord's mParentFlags, from the transform compose at 0x14013cf34: an enum, not
# a bitfield. 0 resets the child's basis to identity, 1 normalises it (parent
# rotation without its scale), 2 keeps the lengths only, 3 falls through and
# inherits the parent's matrix whole. Every node in the card layout uses 3.
INHERIT_NONE, INHERIT_ROT, INHERIT_SCALE, INHERIT_ALL = 0, 1, 2, 3

# Bytes per key value, by storage kind - the low byte of the record's first
# word. Kinds outside this table keep their bytes verbatim and are not editable.
# Measured over every key of every `.sdl` the game ships: kind 6 is 4 bytes,
# 8 is 16, 9 is 4, 11 is 1, 12 is 4, 13 and 14 are 8, 15 is 4, and 16 is a
# 64-byte matrix (six keys in the whole game, none in this screen).
KIND_SIZE = {5: 4, 6: 4, 8: 16, 9: 4, 0x0B: 1, 0x0C: 4, 0x0D: 8, 0x0E: 8,
             0x0F: 4, 0x10: 64}
# ... and how to read them. A kind with no format keeps its bytes verbatim.
KIND_FMT = {5: "<I", 6: "<I", 8: "<4f", 9: "<f", 0x0B: "<B", 0x0C: "<I",
            0x0D: "<Q", 0x0E: "<Q", 0x0F: "<I"}

HOLD = 0                         # interpolation codes
SMOOTH = 3

# The transform properties, and how many components of a kind-8 value each uses.
TRANSFORM = {"mPos": 3, "mAngle": 3, "mScale": 3}


def align(n, a):
    return (n + a - 1) // a * a


class Key(object):
    """One key: a frame, an interpolation code, and a value tuple."""
    __slots__ = ("frame", "code", "value")

    def __init__(self, frame, code, value):
        self.frame = int(frame)
        self.code = int(code)
        self.value = value

    def __repr__(self):
        return "<key %d %s>" % (self.frame, self.value)


class Prop(object):
    """One property of one node: a name, a storage kind, and its keys."""
    __slots__ = ("index", "name", "kind", "type", "keys", "raw", "dirty")

    def __init__(self, index, name, kind, type_, keys, raw):
        self.index = index
        self.name = name
        self.kind = kind            # storage kind: what a value looks like
        self.type = type_           # MT property type: what it means
        self.keys = keys            # [Key], empty when the kind is not decoded
        self.raw = raw              # the value block verbatim
        self.dirty = False

    @property
    def editable(self):
        return self.kind in KIND_FMT

    def scalar(self, default=0.0):
        """The first component of the first key - for the single-key case."""
        if not self.keys or self.keys[0].value is None:
            return default
        v = self.keys[0].value
        return v[0] if isinstance(v, tuple) else v

    def set_keys(self, keys):
        """Replace every key. `keys` is [(frame, code, value tuple)]."""
        if not self.editable:
            raise RuntimeError("%s is stored as kind %d, which is not decoded"
                               % (self.name, self.kind))
        fmt = KIND_FMT[self.kind]
        n = len(struct.unpack(fmt, b"\0" * struct.calcsize(fmt)))
        out = []
        for frame, code, value in keys:
            if not isinstance(value, (tuple, list)):
                value = (value,)
            value = tuple(value)[:n]
            value = value + (0,) * (n - len(value))
            out.append(Key(frame, code, value))
        out.sort(key=lambda k: k.frame)
        self.keys = out
        self.raw = b"".join(struct.pack(fmt, *k.value) for k in out)
        self.dirty = True


class Node(object):
    __slots__ = ("index", "name", "cls", "props", "parent", "model")

    def __init__(self, index, name, cls):
        self.index = index
        self.name = name
        self.cls = cls              # the DTI hash of the node's class
        self.props = {}             # name -> Prop
        self.parent = None          # another Node, from mpParent
        self.model = None           # resource path from mpModel

    def __repr__(self):
        return "<sdl %s>" % self.name

    def at(self, prop, frame, default=(0.0, 0.0, 0.0)):
        """The property's value at `frame`, held from the last key at or before.

        Stepped, not interpolated: this places a scene at a moment. Where the
        keys themselves are wanted - to carry the animation across rather than
        one pose out of it - read `props[name].keys`.
        """
        p = self.props.get(prop)
        if p is None or not p.keys:
            return default
        val = p.keys[0].value
        for k in p.keys:
            if k.frame > frame:
                break
            val = k.value
        return val[:3]

    def int_at(self, prop, default=0):
        p = self.props.get(prop)
        return int(p.scalar(default)) if p is not None and p.keys else default

    def flags(self):
        return self.int_at("mParentFlags", INHERIT_ALL)

    def animated(self):
        """Which of this node's properties actually move. -> [name]"""
        return [n for n, p in sorted(self.props.items()) if len(p.keys) > 1]


class Sdl(object):
    def __init__(self, data, version, header, records, nodes, clips, strings):
        self.data = data                        # what it was parsed from
        self.version = version
        self.header = header                    # bytes 0x08..0x18, preserved
        self.records = records                  # every record, in file order
        self.nodes = nodes                      # {record index: Node}
        self.clips = clips                      # [(name, start, end)]
        self.strings = strings                  # the string table, verbatim

    def by_name(self, name):
        for n in self.nodes.values():
            if n.name == name:
                return n
        return None

    def settle_frame(self):
        """A frame at which the screen is at rest.

        The end of the first clip: `start` is the fly-in, everything has arrived
        by the time it ends, and the later clips are the carousel rolling - a
        card is mid-move through most of them.
        """
        return int(self.clips[0][2]) if self.clips else 0

    def last_frame(self):
        """The last frame any key in the file lands on."""
        return max([k.frame for r in self.records for k in r["prop"].keys] or [0])

    def dirty(self):
        return any(r["prop"].dirty for r in self.records)

    def string_offset(self, s):
        """The offset of `s` in the string table, appending it if it is new.

        The table is the last thing in the file and everything addresses it by
        an offset from its start, so appending never moves an existing string.
        """
        want = s.encode("ascii")
        off = 0
        while off < len(self.strings):
            end = self.strings.find(b"\0", off)
            if end < 0:
                break
            if self.strings[off:end] == want:
                return off
            off = end + 1
        off = len(self.strings)
        self.strings = self.strings + want + b"\0"
        return off

    def add_prop(self, node, name, kind, type_):
        """Give a node a property it does not have, and return it.

        The record goes in with the node's other properties rather than at the
        end of the table, because that is how every shipped file is laid out.
        That renumbers every record after it, so the owner of each later
        property and every `mpParent` - which holds a record index - are moved
        along with it.
        """
        if name in node.props:
            return node.props[name]
        if kind not in KIND_FMT:
            raise RuntimeError("cannot author a kind-%d property" % kind)
        pos = node.index + 1
        for i, r in enumerate(self.records):
            if r["prop"].kind != OBJECT and r["owner"] == node.index:
                pos = max(pos, i + 1)

        for r in self.records:
            if r["prop"].kind != OBJECT and r["owner"] >= pos:
                r["owner"] += 1
        for n in self.nodes.values():
            p = n.props.get("mpParent")
            if p is not None and p.keys and int(p.keys[0].value[0]) >= pos:
                p.set_keys([(k.frame, k.code, (int(k.value[0]) + 1,)) for k in p.keys])

        prop = Prop(pos, name, kind, type_, [], b"")
        self.records.insert(pos, {
            "owner": node.index, "vals": 1 << 62,
            "mid": struct.pack("<Q", self.string_offset(name)) + b"\0" * 16,
            "prop": prop})
        prop.dirty = True
        for i, r in enumerate(self.records):
            r["prop"].index = i
        moved = {}
        for idx, n in self.nodes.items():
            if idx >= pos:
                n.index = idx + 1
            moved[n.index] = n
        self.nodes = moved
        node.props[name] = prop
        return prop

    def build(self):
        """Serialise back to `.sdl` bytes.

        Blocks are emitted in the order the source had them, so a file nothing
        edited comes back byte for byte; a key added or removed just moves the
        blocks after it along. The string table is copied verbatim - editing
        keys never needs a new string, and the property and node names are
        already in it.
        """
        recs = self.records
        off = FIRST + len(recs) * REC
        order = sorted(range(len(recs)),
                       key=lambda i: (recs[i]["vals"] if recs[i]["prop"].keys
                                      else 1 << 62, i))
        place = {}
        for i in order:
            p = recs[i]["prop"]
            if not p.keys:
                place[i] = (0, 0)
                continue
            off = align(off, 4)
            ktab = off
            off += len(p.keys) * 4
            off = align(off, 16)
            place[i] = (ktab, off)
            off += len(p.raw)
        stroff = align(off, 4)
        out = bytearray(max(stroff + len(self.strings), off))
        struct.pack_into("<4sHH", out, 0, MAGIC, self.version, len(recs))
        out[0x08:0x18] = self.header
        struct.pack_into("<Q", out, 0x18, stroff)
        for i, r in enumerate(recs):
            p = r["prop"]
            o = FIRST + i * REC
            struct.pack_into("<BBH", out, o, p.kind, p.type, len(p.keys))
            struct.pack_into("<I", out, o + 4, r["owner"])
            out[o + 0x08:o + 0x20] = r["mid"]
            ktab, vals = place[i]
            struct.pack_into("<2Q", out, o + 0x20, ktab, vals)
            if p.keys:
                struct.pack_into("<%dI" % len(p.keys), out, ktab,
                                 *[(k.frame & 0xFFFF) | (k.code << 24) for k in p.keys])
                out[vals:vals + len(p.raw)] = p.raw
        out[stroff:] = self.strings
        return bytes(out)


def _cstring(b, off):
    end = b.find(b"\0", off)
    return b[off:end if end >= 0 else len(b)].decode("ascii", "replace")


def parse(data):
    """A `.sdl` resource -> Sdl, or None if it is not one."""
    if len(data) < FIRST + REC or data[:4] != MAGIC:
        return None
    version, count = struct.unpack_from("<HH", data, 4)
    strtab = struct.unpack_from("<Q", data, 0x18)[0]
    if strtab >= len(data) or FIRST + count * REC > len(data):
        return None

    def name_at(rel):
        return _cstring(data, strtab + rel) if rel else ""

    def resource_at(rel):
        """A typed resource reference: extension hash, then the path."""
        return _cstring(data, strtab + rel + 4) if rel else ""

    # Where every block starts, so an undecoded kind's values can be measured
    # rather than guessed - the file is then reproduced whatever it holds.
    heads = [strtab]
    for i in range(count):
        o = FIRST + i * REC
        nk = struct.unpack_from("<H", data, o + 2)[0]
        if nk:
            ktab, vals = struct.unpack_from("<2Q", data, o + 0x20)
            heads += [ktab, vals]
    heads.sort()

    records, nodes = [], {}
    for i in range(count):
        o = FIRST + i * REC
        kind, ptype, nk = struct.unpack_from("<BBH", data, o)
        owner = struct.unpack_from("<I", data, o + 4)[0]
        nof = struct.unpack_from("<Q", data, o + 8)[0]
        ktab, vals = struct.unpack_from("<2Q", data, o + 0x20)
        name = name_at(nof)
        size = KIND_SIZE.get(kind)
        if nk and (ktab + nk * 4 > len(data) or vals > len(data)):
            nk = 0                                  # truncated; keep the record
        # The value block is kept as the file has it, padding and all, so an
        # untouched property is written back exactly - a block that runs up to
        # the string table carries the alignment slack with it. An edited one is
        # repacked to `nk * size` in `set_keys`.
        span = 0
        if nk:
            nxt = next((h for h in heads if h > vals), len(data))
            span = max(nxt - vals, nk * size) if size is not None else nxt - vals
        raw = data[vals:vals + span] if nk else b""
        # Every key gets a frame and an interpolation code even where its value
        # is a kind this does not decode - so the key table is still written
        # back, and a record is never dropped for being unreadable.
        keys, fmt = [], KIND_FMT.get(kind)
        for k in range(nk):
            word = struct.unpack_from("<I", data, ktab + k * 4)[0]
            v = struct.unpack_from(fmt, raw, k * size) if fmt else None
            keys.append(Key(word & 0xFFFF, word >> 24, v))
        prop = Prop(i, name, kind, ptype, keys, raw)
        records.append({"owner": owner, "mid": data[o + 8:o + 0x20],
                        "vals": vals, "prop": prop})
        if kind == OBJECT:
            nodes[i] = Node(i, name, struct.unpack_from("<I", data, o + 0x10)[0])

    clip_props = {}
    for i, r in enumerate(records):
        p = r["prop"]
        if p.kind == OBJECT:
            continue
        owner = nodes.get(r["owner"])
        if owner is not None:
            owner.props[p.name] = p
        if r["owner"] in nodes and nodes[r["owner"]].name == "UiSdlAnimeFrame":
            clip_props[p.name] = p

    for n in nodes.values():
        idx = n.int_at("mpParent", 0)
        n.parent = nodes.get(idx) if idx else None
        rel = n.int_at("mpModel", 0)
        n.model = resource_at(rel) if rel else None

    clips = []
    for i in range(len(clip_props)):
        nm, st, en = (clip_props.get("FrameName%d" % i),
                      clip_props.get("FrameStart%d" % i),
                      clip_props.get("FrameEnd%d" % i))
        if not (nm and st and en and nm.keys):
            break
        clips.append((name_at(int(nm.keys[0].value[0])), st.scalar(), en.scalar()))

    return Sdl(data, version, data[0x08:0x18], records, nodes, clips, data[strtab:])


def transform(node, frame):
    """(position, euler xyz, scale) for one node at a frame, in game units."""
    return (node.at("mPos", frame, (0.0, 0.0, 0.0)),
            node.at("mAngle", frame, (0.0, 0.0, 0.0)),
            node.at("mScale", frame, (1.0, 1.0, 1.0)))


def chain(node):
    """A node and every parent above it, innermost first. Cycle-safe."""
    out, seen = [], set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        out.append(node)
        node = node.parent
    return out
