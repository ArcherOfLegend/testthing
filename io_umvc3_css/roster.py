"""Who is on the character select, and what their card shows.

Three separate things decide what a cell displays, and they live in three
different places:

  * the **grid table** maps slot -> character id. Vanilla's is 7 rows x 8 in the
    exe at rva 0xB3E580; the plugin re-lays it for a wider grid, and CloneEngine
    claims every slot from 56 up by index regardless of what the table says.
  * the **id -> internal name** table sits in the exe at rva 0xC553A0, with three
    unrelated strings in front of it, so **character id = table index - 2**.
    That table is static, so it is baked in here rather than re-scanned - see
    `idnames.py` for the recovery.
  * the **portrait** is a loose `f_<Name><colour>_BM_HQ_NOMIP.tex` under
    `nativePCx64/ui/chs/chs_face_a/chs_cs_f/`, not in any archive.

Format 42 (what the 50 vanilla portraits still use) is not BC3 and its packing
has never been worked out - written back as plain DXT5 it returns from the game
as two flat bands. Its **alpha channel is the whole portrait as luminance**
though, so previews decode that; the RGB block carries only about one chroma
degree of freedom (r + b is near constant and g is all but binary), which is not
enough to reconstruct colour. Anything this writes goes out as format 19 (BC1),
which round-trips correctly.
"""
import os
import re

from . import mod as M

# --- the grid table ---------------------------------------------------------
VANILLA_ROWS, VANILLA_COLS = 7, 8
VANILLA_SLOTS = VANILLA_ROWS * VANILLA_COLS      # 56, and CE owns everything above
BANNER_BLANKS = 2                 # cells the banner plate covers besides RANDOM

ID_RANDOM_A, ID_RANDOM_B = 53, 54
# `vfn17` draws the UNKNOWN plate for these before the id -> name -> portrait
# path ever runs, so their table names are never seen.
UNKNOWN_IDS = (0, 52, 55)

# rva 0xB3E580, read out by readgrid.py. Column 0 of each page is the one
# furthest from the spine; the RANDOM plates sit at columns 3 and 4.
VANILLA_TABLE = (
    20,  0,  0, 53, 54,  0,  0, 37,
    25, 24, 21, 23, 45, 47, 50, 49,
     4, 11,  9, 22, 48, 46, 27, 39,
     5, 13,  1,  7, 40, 28, 33, 35,
    15, 14,  2,  8, 44, 41, 34, 38,
    17, 10,  3,  6, 26, 43, 30, 42,
    16, 19, 18, 12, 36, 29, 31, 32,
)

# --- id -> internal name (exe table index - 2) ------------------------------
VANILLA_NAMES = {
    0: "cmn",
    1: "Ryu", 2: "Chunli", 3: "Gouki", 4: "Chris", 5: "Wesker", 6: "VJoe",
    7: "Dante", 8: "Trish", 9: "Frank", 10: "Spencer", 11: "Arthur",
    12: "Amaterasu", 13: "Zero", 14: "Tron", 15: "Morrigan", 16: "Leilei",
    17: "Felicia", 18: "CViper", 19: "Haggar", 20: "Jill", 21: "Hiryu",
    22: "Vergil", 23: "Naruhodo", 24: "RedArremer", 25: "Nemesis",
    26: "SpiderMan", 27: "CapAmerica", 28: "Wolverine", 29: "Magneto",
    30: "Hulk", 31: "SheHulk", 32: "TaskMaster", 33: "IronMan", 34: "Thor",
    35: "DrDoom", 36: "Phoenix", 37: "Shuma", 38: "Modok", 39: "Dormammu",
    40: "DeadPool", 41: "Storm", 42: "SuperSkrull", 43: "Sentinel", 44: "X23",
    45: "Nova", 46: "RRaccoon", 47: "GhostRider", 48: "IronFist",
    49: "DrStrange", 50: "HawkEye", 51: "Galactus", 52: "ZeroSh",
    53: "MorriganSh", 54: "FeliciaF", 55: "FeliciaC", 56: "Zombie",
    57: "Mayoi", 58: "RedArremerSh", 59: "DrStrangeSh",
}

# The internal names are not what anyone calls these characters.
DISPLAY_NAMES = {
    "Chunli": "Chun-Li", "Gouki": "Akuma", "Chris": "Chris Redfield",
    "Wesker": "Albert Wesker", "VJoe": "Viewtiful Joe", "Frank": "Frank West",
    "Spencer": "Nathan Spencer", "Tron": "Tron Bonne", "Leilei": "Hsien-Ko",
    "CViper": "C. Viper", "Haggar": "Mike Haggar", "Jill": "Jill Valentine",
    "Hiryu": "Strider Hiryu", "Naruhodo": "Phoenix Wright",
    "RedArremer": "Firebrand", "Nemesis": "Nemesis T-Type",
    "SpiderMan": "Spider-Man", "CapAmerica": "Captain America",
    "SheHulk": "She-Hulk", "TaskMaster": "Taskmaster", "IronMan": "Iron Man",
    "DrDoom": "Doctor Doom", "Shuma": "Shuma-Gorath", "Modok": "M.O.D.O.K.",
    "DeadPool": "Deadpool", "SuperSkrull": "Super-Skrull", "X23": "X-23",
    "RRaccoon": "Rocket Raccoon", "GhostRider": "Ghost Rider",
    "IronFist": "Iron Fist", "DrStrange": "Doctor Strange", "HawkEye": "Hawkeye",
}

PORTRAIT_DIR = os.path.join("nativePCx64", "ui", "chs", "chs_face_a", "chs_cs_f")
PORTRAIT_RE = re.compile(r"^[bf]_(.+?)(\d{2,3})_BM")     # lazy: Rash255 -> Rash2 + 55
BC1_FMT = 19


def display_name(internal):
    return DISPLAY_NAMES.get(internal, internal)


# ============================================================== CloneEngine ===
def read_ce_roster(game_dir):
    """The playable CloneEngine characters, in the order CE assigns slots.

    CE maps slot 56+n to the nth playable entry of `Characters.ini`. Sections
    without SoundID/NumColors are child helpers and get no slot - of the 99
    sections, 83 are playable, which is why the grid needs 9 rows.
    """
    path = os.path.join(game_dir, "Characters.ini")
    if not os.path.isfile(path):
        return []
    out, cur, playable = [], None, False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                if cur and playable:
                    out.append(cur)
                cur, playable = None, False
            elif "=" in line:
                k, v = line.split("=", 1)
                k, v = k.strip().lower(), v.strip()
                if k == "characterid":
                    cur = v
                elif k in ("soundid", "numcolors") and v:
                    playable = True
    if cur and playable:
        out.append(cur)
    return out


# ================================================================ the table ===
def relayout(rows, cols, table=VANILLA_TABLE, banner_blanks=BANNER_BLANKS):
    """Re-lay the vanilla 56 across a `rows` x `cols` grid -> {slot: id}.

    This mirrors `BuildLayout` in the plugin, and has to: a page is chosen by
    column while the source is linear in slot, so widening re-divides slots
    0-55 between the pages. At 16 columns they split 32/24 while each page needs
    26, so the last four Marvel characters move to the Capcom page.

    Getting the row-0 reservation wrong is not cosmetic - joint columns 1 and 2
    of row 0 have no card mesh at all, so a character landing there renders
    nothing while staying hoverable and selectable.
    """
    half = cols // 2
    a, b = [], []
    for r in range(VANILLA_ROWS):
        for c in range(VANILLA_COLS):
            v = table[r * VANILLA_COLS + c]
            if v == 0:
                continue
            if c < VANILLA_COLS // 2:
                if v != ID_RANDOM_A:
                    a.append(v)
            elif v != ID_RANDOM_B:
                b.append(v)

    cells_a = [s for s in range(VANILLA_SLOTS) if s % cols < half]
    cells_b = [s for s in range(VANILLA_SLOTS) if s % cols >= half]
    need_a = len(cells_a) - 1 - banner_blanks
    need_b = len(cells_b) - 1 - banner_blanks
    spill = len(b) - need_b
    if spill < 0 or len(a) + spill != need_a:
        raise RuntimeError(
            "a %d x %d grid cannot hold the vanilla roster below slot %d "
            "(%d Capcom + %d Marvel into %d + %d cells)"
            % (rows, cols, VANILLA_SLOTS, len(a), len(b), need_a, need_b))

    out = {}
    # Page A is slot columns 0..half-1 with joint column 0 at the spine, so the
    # banner sits at the END of row 0; page B is the mirror, so it sits at the
    # start. RANDOM is the banner's own cell, the blanks are beside it.
    feed_a = list(a) + (b[len(b) - spill:] if spill else [])
    ia = 0
    for s in cells_a:
        c = s % cols
        if s < cols and c == half - 1:
            out[s] = ID_RANDOM_A
        elif s < cols and c >= half - 1 - banner_blanks:
            out[s] = 0
        else:
            out[s] = feed_a[ia]
            ia += 1
    feed_b = b[:len(b) - spill] if spill else list(b)
    ib = 0
    for s in cells_b:
        c = s % cols
        if s < cols and c == half:
            out[s] = ID_RANDOM_B
        elif s < cols and c <= half + banner_blanks:
            out[s] = 0
        else:
            out[s] = feed_b[ib]
            ib += 1
    return out


class Slot(object):
    """What one cell of the grid holds."""

    __slots__ = ("slot", "source", "cid", "name", "label")

    def __init__(self, slot, source, cid, name, label):
        self.slot = slot
        self.source = source          # 'vanilla' | 'clone-engine' | 'special' | 'empty'
        self.cid = cid                # character id, or None above slot 55
        self.name = name              # internal name / CE CharacterID, or None
        self.label = label            # what to show a human

    def __repr__(self):
        return "<slot %d %s %s>" % (self.slot, self.source, self.label)


def effective_table(rows, cols, game_dir=None, ce_roster=None, new_rows=None):
    """{slot: Slot} for the whole grid, as the game will actually read it.

    Below slot 56 that is the re-laid vanilla roster. From 56 up CloneEngine
    substitutes its own roster by index and ignores the table entirely, so the
    plugin's [NewRows] ids only ever show when CE is absent - `new_rows` supplies
    those for the preview.
    """
    if ce_roster is None:
        ce_roster = read_ce_roster(game_dir) if game_dir else []
    table = relayout(rows, cols)
    out = {}
    for slot in range(rows * cols):
        if slot < VANILLA_SLOTS:
            cid = table.get(slot, 0)
            out[slot] = _vanilla_slot(slot, cid)
        elif slot - VANILLA_SLOTS < len(ce_roster):
            nm = ce_roster[slot - VANILLA_SLOTS]
            out[slot] = Slot(slot, "clone-engine", None, nm, display_name(nm))
        elif new_rows and (slot - VANILLA_SLOTS) < len(new_rows):
            out[slot] = _vanilla_slot(slot, new_rows[slot - VANILLA_SLOTS])
        else:
            out[slot] = Slot(slot, "empty", None, None, "UNKNOWN")
    return out


def _vanilla_slot(slot, cid):
    if cid == ID_RANDOM_A:
        return Slot(slot, "special", cid, None, "RANDOM (Capcom)")
    if cid == ID_RANDOM_B:
        return Slot(slot, "special", cid, None, "RANDOM (Marvel)")
    if cid in UNKNOWN_IDS:
        return Slot(slot, "empty", cid, None, "blank (behind the banner)"
                    if cid == 0 else "UNKNOWN")
    nm = VANILLA_NAMES.get(cid)
    if nm is None:
        return Slot(slot, "empty", cid, None, "id %d" % cid)
    return Slot(slot, "vanilla", cid, nm, display_name(nm))


# --- assignment keys --------------------------------------------------------
# A card stores who is on it as a key, not a slot number, so an assignment
# survives the character moving. Vanilla is "v<id>"; CloneEngine is "c<name>",
# keyed by CharacterID rather than by index, because placing CE characters
# rewrites the order of Characters.ini and an index would then mean someone else.
BLANK_KEY = "v0"


def char_key(source, ident):
    return ("c%s" % ident) if source == "clone-engine" else ("v%d" % int(ident))


def parse_key(key):
    """-> ('vanilla'|'clone-engine', id or CharacterID), or (None, None)."""
    if not key:
        return None, None
    if key.startswith("c"):
        return "clone-engine", key[1:]
    try:
        return "vanilla", int(key[1:])
    except ValueError:
        return None, None


def resolve(key, ce_roster=()):
    """-> Slot describing whoever `key` names (slot index left as -1)."""
    source, ident = parse_key(key)
    if source == "clone-engine":
        label = display_name(ident)
        return Slot(-1, "clone-engine", None, ident,
                    label if ident in ce_roster else "%s (not in Characters.ini)" % label)
    if source == "vanilla":
        return _vanilla_slot(-1, ident)
    return Slot(-1, "empty", None, None, "UNKNOWN")


def key_of_slot(slot):
    """The assignment key for a Slot produced by `effective_table`."""
    if slot is None:
        return BLANK_KEY
    if slot.source == "clone-engine":
        return "c%s" % slot.name
    if slot.cid is not None:
        return "v%d" % slot.cid
    return BLANK_KEY


def characters(game_dir=None, ce_roster=None):
    """Everything that can be put on a card, for the assign dropdown.

    Read live, so a character added to Characters.ini shows up without touching
    any code here."""
    if ce_roster is None:
        ce_roster = read_ce_roster(game_dir) if game_dir else []
    out = [(BLANK_KEY, "(blank)", "special")]
    out.append(("v%d" % ID_RANDOM_A, "RANDOM (Capcom)", "special"))
    out.append(("v%d" % ID_RANDOM_B, "RANDOM (Marvel)", "special"))
    for cid in sorted(VANILLA_NAMES):
        if cid in UNKNOWN_IDS or cid in (ID_RANDOM_A, ID_RANDOM_B) or cid > 51:
            continue
        out.append(("v%d" % cid, display_name(VANILLA_NAMES[cid]), "vanilla"))
    for nm in ce_roster:
        out.append(("c%s" % nm, display_name(nm), "clone-engine"))
    return out


# ==================================================== Characters.ini rewrite ===
def _parse_ini_sections(text):
    """[(header, [lines]), ...] preserving everything, including the preamble."""
    out, cur, body = [], None, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if cur is not None or body:
                out.append((cur, body))
            cur, body = s, []
        else:
            body.append(line)
    if cur is not None or body:
        out.append((cur, body))
    return out


def _is_playable(body):
    keys = {l.split("=", 1)[0].strip().lower() for l in body if "=" in l}
    return "soundid" in keys and "numcolors" in keys


def _character_id(body):
    for l in body:
        if "=" in l:
            k, v = l.split("=", 1)
            if k.strip().lower() == "characterid":
                return v.strip()
    return None


def rewrite_characters_ini(path, order, dry_run=False):
    """Reorder the playable sections so CE deals them out in `order`.

    CloneEngine maps slot 56+n to the nth **playable** entry, and ignores the
    grid table there, so this is the only way to move a CE character. Sections
    are renumbered `[CharacterN]` in the new order as well as physically moved,
    so it does not matter whether CE walks the file or the numbering.

    Safe because CE's cross-references are **by name** - `BaseCharacter=VJoe`,
    `Child1=PsylockF` - never by index or section number. Child helper sections
    are not playable, get no slot, and are kept exactly as they are.

    -> (new text, [CharacterIDs in their new order]).
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    sections = _parse_ini_sections(text)

    playable, others = [], []
    for header, body in sections:
        if header is None:
            others.append((header, body))
        elif _is_playable(body):
            playable.append((_character_id(body), body))
        else:
            others.append((header, body))

    known = {cid for cid, _ in playable}
    missing = [c for c in order if c not in known]
    if missing:
        raise RuntimeError("not in Characters.ini: %s" % ", ".join(missing[:6]))

    # A character asked for twice means one of the others has nowhere to go, and
    # the loop below would simply never reach it - which deletes it from the
    # roster. Refuse instead: there are only as many slots as entries.
    dupes = sorted({c for c in order if order.count(c) > 1})
    if dupes:
        raise RuntimeError("asked for twice, so something else would be dropped: %s"
                           % ", ".join(dupes[:6]))

    by_id = {cid: body for cid, body in playable}
    seq = list(order) + [cid for cid, _ in playable if cid not in set(order)]
    if len(seq) != len(playable):
        raise RuntimeError("%d entries for %d playable sections - refusing to "
                           "write a roster that is not one-to-one"
                           % (len(seq), len(playable)))

    # Permute the playable entries **in place**: each playable slot in the file
    # takes the next id from `seq`, and every non-playable section stays exactly
    # where it was. Hoisting all the playable ones to the front would also give
    # CE the right order, but it would move child helpers across their parents,
    # and nothing here knows whether CE resolves those as it parses.
    lines, n, i = [], 0, 0
    for header, body in sections:
        if header is None:
            lines.extend(body)
            continue
        n += 1
        lines.append("[Character%d]" % n)
        if _is_playable(body):
            lines.extend(by_id[seq[i]])
            i += 1
        else:
            lines.extend(body)

    out = "\n".join(l.rstrip("\r") for l in lines).rstrip("\n") + "\n"

    # Post-condition: a reorder moves entries, it never adds or removes one.
    # Checked on the text actually about to be written, so no rearrangement of
    # this function can quietly lose a character.
    was = sorted(re.findall(r"(?mi)^\s*CharacterID\s*=\s*(\S+)", text))
    now = sorted(re.findall(r"(?mi)^\s*CharacterID\s*=\s*(\S+)", out))
    if was != now:
        lost = sorted(set(was) - set(now))
        gained = sorted(set(now) - set(was))
        raise RuntimeError("the rewrite would change the roster - lost %s, "
                           "gained %s" % (lost[:4] or "nothing", gained[:4] or "nothing"))
    if not dry_run:
        with open(path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(out)
    return out, seq


# ================================================================ portraits ===
def portrait_dir(game_dir):
    return os.path.join(game_dir, PORTRAIT_DIR)


def portrait_path(game_dir, stem, colour=0):
    return os.path.join(portrait_dir(game_dir),
                        "f_%s%02d_BM_HQ_NOMIP.tex" % (stem, colour))


def is_portrait_of(path, stem):
    """Is this `.tex` the portrait of `stem`, in any colour?

    Not via PORTRAIT_RE: where the name ends in a digit the split is genuinely
    ambiguous - f_X2300 is X23 colour 00 and also parses as X2 colour 300 - and
    the pattern takes the wrong one, which reads as every such character wearing
    somebody else's portrait. Given the stem, only the colour is left to check.
    """
    if not path or not stem:
        return False
    name = os.path.basename(path)
    for pre in ("f_", "b_"):
        if name.startswith(pre + stem):
            return name[len(pre) + len(stem):].split("_", 1)[0].isdigit()
    return False


def find_portrait(game_dir, stem):
    """The lowest-numbered colour that exists for `stem`, or None."""
    d = portrait_dir(game_dir)
    if not os.path.isdir(d):
        return None
    for colour in (0, 1):
        p = portrait_path(game_dir, stem, colour)
        if os.path.isfile(p):
            return p
    pre = "f_%s" % stem
    for fn in sorted(os.listdir(d)):
        m = PORTRAIT_RE.match(fn)
        if m and m.group(1) == stem:
            return os.path.join(d, fn)
    return None


def portrait_stem(slot):
    """The portrait filename stem for a Slot, or None if it has no art."""
    return slot.name if slot and slot.name else None


def file_differs(path, data):
    """Would writing `data` to `path` change it? Missing counts as different."""
    try:
        if os.path.getsize(path) != len(data):
            return True
        with open(path, "rb") as f:
            return f.read() != data
    except OSError:
        return True


def load_portrait(path, cache, name=None):
    """A .tex on disk -> a Blender image.

    Format 19 goes through .dds so Blender decodes it; format 42 is decoded here
    from its alpha channel, which is the only part of it anyone has read
    successfully. The image is tagged so the exporter can find it again.
    """
    import bpy
    with open(path, "rb") as f:
        raw = f.read()
    info = M.tex_info(raw)
    if info is None:
        return None
    nice = name or os.path.basename(path)
    img = None
    if info["fmt"] == BC1_FMT or info["fmt"] in M.BC1_CODES:
        dds = M.tex_to_dds_bytes(raw)
        if dds:
            p = os.path.join(cache, os.path.basename(path) + ".dds")
            # Compare the bytes, not the length. Every portrait this pipeline
            # writes is BC1 at the same size as the last one, so a length check
            # calls a replaced portrait unchanged and hands back the previous
            # picture - the card then shows the old art however many times you
            # rewrite it.
            stale = file_differs(p, dds)
            if stale:
                with open(p, "wb") as f:
                    f.write(dds)
            try:
                img = bpy.data.images.load(p, check_existing=True)
                if stale:
                    # check_existing hands back a datablock that is still
                    # holding the pixels of the file as it was
                    img.reload()
            except RuntimeError:
                img = None
    if img is None:
        w, h = info["width"], info["height"]
        px = M.decode_bc(info["payload"], w, h, info["fmt"] not in M.BC1_CODES)
        img = bpy.data.images.new(nice, width=w, height=h, alpha=True)
        if info["fmt"] not in M.BC1_CODES:
            # alpha is the portrait; the colour block is chroma nobody has decoded
            out = [0.0] * len(px)
            for i in range(w * h):
                v = px[i * 4 + 3]
                out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = v
                out[i * 4 + 3] = 1.0
            px = out
        img.pixels = px
    if img.name != nice and nice not in bpy.data.images:
        img.name = nice
    # Which portrait this image STANDS FOR. It survives the user pointing the
    # datablock at their own art - one of the obvious ways to change a portrait -
    # so it is not on its own evidence that the image still looks like the file;
    # see `scene.unmodified_portrait`, which is what decides that.
    img["umvc3_portrait"] = os.path.abspath(path)
    img["umvc3_portrait_fmt"] = info["fmt"]
    return img


def portrait_bytes(img, reference):
    """A Blender image -> portrait .tex bytes, forced to format 19.

    Stock portraits are format 42 and `encode_image_to_tex` would faithfully
    keep that header, which is exactly the trap: the game cannot decode what
    this pipeline writes at 42. Rewrite the format field first.

    That leaves the one bit of alpha BC1 carries, which is a cut-out and not a
    fade: above the cutoff a texel is kept, below it the texel is punched out
    and its colour is not stored at all. The colour under a transparent pixel is
    undefined - tools leave anything there - so dropping the alpha and shipping
    that colour is what turns a transparent margin into garbage on the card.
    """
    import struct
    info = M.tex_info(reference)
    if info is None:
        raise RuntimeError("reference is not a .tex")
    hdr = bytearray(info["header"])
    w3 = M._u32(hdr, 12)
    struct.pack_into("<I", hdr, 12, (w3 & ~(0xFF << 8)) | (BC1_FMT << 8))
    w, h = info["width"], info["height"]
    payload = M.encode_bc(M.image_pixels_topdown(img, w, h), w, h, False, cutout=True)
    want = w * h // 2
    if len(payload) != want:
        raise RuntimeError("encoded %d bytes, expected %d" % (len(payload), want))
    return bytes(hdr) + payload
