"""The character select's animation, as Blender keyframes.

The `.sdl` schedulers do not only say where a model is drawn - they say where it
is drawn *at every frame*. The card stack flies in from off-screen left, the
cards roll through their three slots as you pick a character, the cursor hops,
the book opens. All of it is keys in an archive file (see `sdl.py`), and this
module is what carries those keys into Blender and back.

What maps to what
=================

| `.sdl` track | in Blender |
|---|---|
| `mPos`, `mAngle`, `mScale` | the empty's location / rotation / scale |
| `Draw` | *Disable in Viewports* and *in Renders*, keyed |
| every other keyed track | a keyed custom property, `sdl_<name>` |

The transforms are the ones worth having in the viewport, so they are the
object's own channels; everything else - colour, transparency, draw depth,
`Move` - becomes a custom property so it still shows up in the Graph Editor,
still animates, and still writes back. Tracks whose value is a string-table
offset (`Texture`, `mpModel`) are left alone: their keys are file offsets, not
numbers to be edited, and they round-trip untouched.

Parenting
=========

Placing one pose can compose the node chain by hand and hand Blender a world
matrix. An *animated* chain cannot: the parent moves too, so the child has to
be a real child, with its basis holding exactly the node's own local transform
and `matrix_parent_inverse` left at identity. Blender then composes
`parent_world @ local` on every frame, which is what the engine does for
`mParentFlags == 3` - the value every node in these layouts uses.

Clips are actions
=================

A layout's keys are one long track per property, and its clip table names ranges
over them: `start` 0-61, `sel1` 61-71, `sel1_decide` 71-91, … `start_vs`. Those
are the units an edit is actually about - "the fly-in is too slow", "the card
lands too far left" - so each clip becomes **its own Action**, named
`<layout> | <clip>`, holding the keys in its range for every node in the layout
at once (one slot per node - which is what slotted Actions are for).

The whole timeline still plays: the clip actions are laid out as **NLA strips**
at the frames they belong to, so nothing is lost by splitting them up, and a
clip edited in place is a clip the timeline immediately plays differently.
There is no separate whole-timeline action to keep in sync with them - the
strips *are* the timeline.

A key exactly on a boundary belongs to both neighbours: 61 ends `start` and
begins `sel1`, and a clip that did not carry its own first key would play from
whatever came before it. On the way out the copies are merged, and where two
clips disagree the one that differs from the shipped file wins, because that is
the edit; if both were edited apart, that is reported rather than guessed.

Frames
======

Frame numbers are the file's own, so a key at 300 in Blender is the key at 300
in the archive. The scene's frame range covers them and opens at the settle
frame - the end of the first clip, after the fly-in - so a freshly imported
screen looks exactly as it did before any of this existed.
"""
import bpy

from . import sdl as SDL

O_NODE = "umvc3_sdl_node"
O_SDL = "umvc3_sdl"
O_TRACKS = "umvc3_sdl_tracks"        # which .sdl tracks this object carries
O_INTERP = "umvc3_sdl_interp"        # {track: [frame, code, frame, code, ...]}
A_CLIP = "umvc3_sdl_clip"            # on an action: which clip it holds
A_RANGE = "umvc3_sdl_range"          # on an action: [start, end]
PREFIX = "sdl_"                      # custom property per non-transform track
WHOLE = "(all)"                      # the pseudo-clip a layout with no clip table gets

# The three that become object channels, and what a value has to be multiplied
# by on the way in. Only position is in game units; angles are radians and
# scale is a ratio, both of which Blender takes as they are.
XFORM = (("mPos", "location"), ("mAngle", "rotation_euler"), ("mScale", "scale"))

# Tracks whose values are string-table offsets rather than numbers.
OPAQUE_KINDS = (0x0D, 0x0E)
# Kinds stored as whole numbers. The file holds them as 32 raw bits and the
# type says how to read them; Blender only has signed ints, so anything past
# 2^31 comes in negative and is masked back on the way out. `mAnmNoReq` opens
# on 0xFFFFFFFF, which is -1 and not four billion.
INT_KINDS = (6, 0x0B, 0x0C, 0x0F)


def _signed(v):
    v = int(v)
    return v - (1 << 32) if v >= (1 << 31) else v


def _codes_of(ob, track):
    """{frame: interpolation code} as imported, for the keys still at those
    frames on export."""
    got = ob.get(O_INTERP) or {}
    flat = got.get(track) or []
    return {int(flat[i]): int(flat[i + 1]) for i in range(0, len(flat) - 1, 2)}


def _remember_codes(ob, track, keys):
    got = dict(ob.get(O_INTERP) or {})
    got[track] = [v for k in keys for v in (k.frame, k.code)]
    ob[O_INTERP] = got


def all_fcurves(ob):
    """Every F-curve on an object, on 4.4+ slotted actions and older ones.

    A slotted action keeps its curves in a channelbag per slot rather than on
    the action, and `Action.fcurves` is gone in 5.x - so ask the strip for the
    bag belonging to the slot this object is bound to.
    """
    ad = ob.animation_data
    if ad is None or ad.action is None:
        return []
    act = ad.action
    if hasattr(act, "fcurves"):                     # Blender 4.3 and earlier
        return list(act.fcurves)
    out, slot = [], getattr(ad, "action_slot", None)
    for layer in act.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            bag = strip.channelbag(slot) if slot is not None else None
            if bag is None:
                bags = list(getattr(strip, "channelbags", ()))
                bag = bags[0] if bags else None
            if bag is not None:
                out += list(bag.fcurves)
    return out


def _fcurves(ob, path, index=None):
    return [fc for fc in all_fcurves(ob)
            if fc.data_path == path and (index is None or fc.array_index == index)]


def collect_tracks(ob, node, scale):
    """Every animated channel of `node`, ready to be keyed on `ob`.

    -> [(data_path, [(frame, code, value tuple - one entry per array index)])]

    Also sets the custom properties the non-transform tracks animate: a curve
    can only exist for a property the object actually has.
    """
    out, names = [], []
    for track, path in XFORM:
        p = node.props.get(track)
        if p is None or len(p.keys) < 2:
            continue
        mul = scale if track == "mPos" else 1.0
        out.append((path, [(k.frame, k.code, tuple(c * mul for c in k.value[:3]))
                           for k in p.keys]))
        _remember_codes(ob, track, p.keys)
        names.append(track)

    draw = node.props.get("Draw")
    if draw is not None and len(draw.keys) > 1 and any(not k.value[0] for k in draw.keys):
        keys = [(k.frame, k.code, (0.0 if k.value[0] else 1.0,)) for k in draw.keys]
        out.append(("hide_viewport", keys))
        out.append(("hide_render", keys))
        _remember_codes(ob, "Draw", draw.keys)
        names.append("Draw")

    for name, p in sorted(node.props.items()):
        if name in ("mPos", "mAngle", "mScale", "Draw", "mpParent", "mpModel"):
            continue
        if len(p.keys) < 2 or not p.editable or p.kind in OPAQUE_KINDS:
            continue
        conv = _signed if p.kind in INT_KINDS else float
        n = len(p.keys[0].value)
        first = p.keys[0].value
        ob[PREFIX + name] = [conv(c) for c in first] if n > 1 else conv(first[0])
        out.append(('["%s%s"]' % (PREFIX, name),
                    [(k.frame, k.code, tuple(conv(c) for c in k.value))
                     for k in p.keys]))
        _remember_codes(ob, name, p.keys)
        names.append(name)

    if names:
        ob[O_TRACKS] = names
    return out


def slot_of(act, ob, make=False):
    """This object's slot in a shared action, by the name we gave it."""
    for s in act.slots:
        if s.name_display == ob.name:
            return s
    return act.slots.new("OBJECT", ob.name) if make else None


def _channelbag(act, slot, make=False):
    layer = act.layers[0] if act.layers else (act.layers.new("Layer") if make else None)
    if layer is None:
        return None
    strip = layer.strips[0] if layer.strips else (
        layer.strips.new(type="KEYFRAME") if make else None)
    if strip is None:
        return None
    return strip.channelbag(slot, ensure=True) if make else strip.channelbag(slot)


def bag_for(act, ob):
    """The channelbag holding `ob`'s curves in `act`, or None."""
    slot = slot_of(act, ob)
    return _channelbag(act, slot) if slot is not None else None


def value_at(keys, frame):
    """(code, value) of a track at a frame, read the way the file means it.

    A code-0 key holds until the next one; anything else interpolates to it.
    Before the first key and after the last, the end value stands.
    """
    if frame <= keys[0][0]:
        return keys[0][1], keys[0][2]
    for a, b in zip(keys, keys[1:]):
        if a[0] <= frame <= b[0]:
            if a[1] == SDL.HOLD or b[0] == a[0]:
                return a[1], a[2]
            t = (frame - a[0]) / float(b[0] - a[0])
            return a[1], tuple(x + (y - x) * t for x, y in zip(a[2], b[2]))
    return keys[-1][1], keys[-1][2]


def slice_track(keys, lo, hi):
    """A clip's share of a track: its own keys, plus its two boundaries.

    **Every clip carries every animated channel.** A strip that has nothing to
    say about a channel does not leave the previous strip holding it - the
    channel falls back to the object's own value and the pose jumps - so a clip
    with no key of its own in range still gets the value sampled at each end.
    Those samples are what the track already says, so they are dropped again on
    the way out unless they were edited: see `redundant`.
    """
    inside = [k for k in keys if lo <= k[0] <= hi]
    out = []
    if not any(k[0] == lo for k in inside):
        code, value = value_at(keys, lo)
        out.append((lo, code, value))
    out += inside
    if hi > lo and not any(k[0] == hi for k in inside):
        code, value = value_at(keys, hi)
        out.append((hi, code, value))
    return out


def write_clip(act, ob, tracks, lo, hi):
    """Put every key in [lo, hi] into this action, under `ob`'s own slot."""
    inside = [(path, slice_track(keys, lo, hi)) for path, keys in tracks]
    inside = [(path, keys) for path, keys in inside if keys]
    if not inside:
        return 0
    slot = slot_of(act, ob, make=True)
    bag = _channelbag(act, slot, make=True)
    wrote = 0
    for path, keys in inside:
        for index in range(len(keys[0][2])):
            fc = bag.fcurves.new(path, index=index)
            for frame, code, value in keys:
                kp = fc.keyframe_points.insert(float(frame), float(value[index]))
                kp.interpolation = "CONSTANT" if code == SDL.HOLD else "LINEAR"
            fc.update()
            wrote += 1
    return wrote


def clip_labels(clips):
    """Clip names made unique. `chs_card1p` ships two called `sel_team_end`."""
    out, seen = [], {}
    for name, start, end in clips:
        seen[name] = seen.get(name, 0) + 1
        out.append((name if seen[name] == 1 else "%s.%d" % (name, seen[name]),
                    int(start), int(end)))
    return out


def make_clip_actions(doc, entry_name, leaf):
    """One Action per clip, tagged with the layout and range it belongs to.

    A layout with no clip table at all - the cursor's - gets a single action
    over everything, so there is always exactly one place its keys live.
    """
    clips = clip_labels(doc.clips) or [(WHOLE, 0, doc.last_frame())]
    made = []
    for label, lo, hi in clips:
        act = bpy.data.actions.new("%s | %s" % (leaf, label))
        act.use_fake_user = True          # it is the animation; nothing else uses it
        act[O_SDL] = entry_name
        act[A_CLIP] = label
        act[A_RANGE] = [lo, hi]
        made.append((label, lo, hi, act))
    return made


def lay_out_nla(ob, actions, leaf):
    """The clips back on the timeline, as strips at the frames they cover.

    This is what keeps the whole screen playable once the animation is split
    up: the strips *are* the timeline, so a clip edited in place is a clip the
    timeline plays differently, with nothing to keep in sync. Ranges are the
    file's own, and `HOLD_FORWARD` reproduces what the engine does between
    clips - a value holds from its last key.
    """
    ad = ob.animation_data or ob.animation_data_create()
    track = ad.nla_tracks.new()
    track.name = leaf
    made = 0
    for label, lo, hi, act in sorted(actions, key=lambda a: a[1]):
        if hi <= lo:
            continue          # `start_wait` is 61..61: a real clip, but not a strip
        slot = slot_of(act, ob)
        bag = bag_for(act, ob)
        if slot is None or bag is None or not len(bag.fcurves):
            continue          # this node has nothing to do in this clip
        strip = track.strips.new(label, int(lo), act)
        strip.action_slot = slot
        strip.frame_start, strip.frame_end = float(lo), float(hi)
        strip.action_frame_start, strip.action_frame_end = float(lo), float(hi)
        strip.extrapolation = "HOLD_FORWARD" if made else "HOLD"
        strip.blend_type = "REPLACE"
        made += 1
    if not made:
        ad.nla_tracks.remove(track)
    ob.update_tag()
    return made


def apply_node(ob, node, scale, actions):
    """Key `ob` from every animated track on `node`, one action per clip.

    -> the track names that came across
    """
    tracks = collect_tracks(ob, node, scale)
    if not tracks:
        return []
    for label, lo, hi, act in actions:
        write_clip(act, ob, tracks, lo, hi)
    return list(ob.get(O_TRACKS) or ())


def set_range(scene, first, last, settle):
    """Cover the animation, and open at the frame the screen is at rest."""
    scene.frame_start = min(scene.frame_start, int(first))
    scene.frame_end = max(scene.frame_end, int(last))
    scene.frame_current = int(settle)


# ----------------------------------------------------------------- export ---

def clip_sources(ob, entry_name):
    """Every clip action holding this object's curves, earliest range first.

    -> [(label, lo, hi, {(data_path, index): fcurve})]
    """
    out = []
    for act in bpy.data.actions:
        if act.get(O_SDL) != entry_name:
            continue
        bag = bag_for(act, ob)
        if bag is None or not len(bag.fcurves):
            continue
        lo, hi = (list(act.get(A_RANGE)) or [0, 0])[:2]
        out.append((str(act.get(A_CLIP) or act.name), int(lo), int(hi),
                    {(fc.data_path, fc.array_index): fc for fc in bag.fcurves}))
    out.sort(key=lambda s: (s[1], s[2]))
    return out


def _sampled(ob, path, indices, codes, default_code, curves=None):
    """One channel's keys, as [(frame, code, tuple)].

    Blender keys each component on its own curve, and a user who moved only x
    leaves y and z without a key at that frame. The `.sdl` stores one key per
    frame holding the whole vector, so the frames are unioned and every
    component is *evaluated* there - which is what the curve is showing anyway.
    """
    if curves is None:
        curves = {}
        for i in indices:
            for fc in _fcurves(ob, path, i):
                curves[i] = fc
    if not curves:
        return None
    frames = sorted({int(round(kp.co[0]))
                     for fc in curves.values() for kp in fc.keyframe_points})
    if not frames:
        return None
    out = []
    for f in frames:
        value = tuple(curves[i].evaluate(f) if i in curves else 0.0 for i in indices)
        code = codes.get(f)
        if code is None:
            # A key the file has no code for - one the user added, or a clip
            # boundary. Hold if they made it constant; otherwise take the code
            # the track already carries across that frame, so a key keeps the
            # kind of the segment it lands in.
            const = all(kp.interpolation == "CONSTANT"
                        for fc in curves.values() for kp in fc.keyframe_points
                        if int(round(kp.co[0])) == f)
            code = SDL.HOLD if const else (
                default_code(f) if callable(default_code) else default_code)
        out.append((f, code, value))
    return out


def _default_code(prop):
    for k in prop.keys:
        if k.code:
            return k.code
    return SDL.SMOOTH


def _same(a, b):
    """Two keys, compared at the precision the file actually stores."""
    if a is None or b is None:
        return False
    if a[0] != b[0]:
        return False
    return all(abs(float(x) - float(y)) <= 1e-6 * max(1.0, abs(float(x)))
               for x, y in zip(a[1], b[1]))


def merge_clips(sources, path, indices, codes, default_code, prop, ob, report,
                what="", conv=None):
    """One track's keys, in the file's own units, out of the per-clip actions.

    Each clip owns its own range, so a key inside a clip's range that the clip
    no longer has was **deleted**, and a key outside every clip's range - the
    cursor's, whose layout ships no clip table at all - is left alone. A key on
    a boundary exists in both neighbours: if they disagree, the one that differs
    from the shipped file is the edit and wins. Both edited apart is the only
    genuinely ambiguous case, and it is reported rather than guessed.
    """
    orig = {k.frame: (k.code, tuple(k.value[:len(indices)])) for k in prop.keys} \
        if prop is not None else {}
    was = [(f, c, v) for f, (c, v) in sorted(orig.items())]
    # The code for a frame the file has no key at is the one the track already
    # carries across it - which is what a clip boundary was sampled with, and
    # the segment a newly added key lands in.
    if was:
        default_code = lambda f: value_at(was, f)[0]
    merged, from_clip, clashes = {}, {}, []
    covered = []
    for label, lo, hi, curves in sources:
        got = _sampled(ob, path, indices, codes, default_code,
                       curves={i: curves[(path, i)] for i in indices
                               if (path, i) in curves})
        if got is None:
            continue
        covered.append((lo, hi))
        for f, code, value in got:
            # Into the file's own units and sense before anything is compared:
            # a merge that weighed Blender's metres against the archive's game
            # units would call every key an edit.
            new = (code, conv(value) if conv else value)
            old = merged.get(f)
            if old is None or _same(old, new):
                merged[f], from_clip[f] = new, label
                continue
            if _same(old, orig.get(f)):          # the other clip just carried it
                merged[f], from_clip[f] = new, label
            elif not _same(new, orig.get(f)):
                clashes.append((f, from_clip.get(f), label))
    if not covered:
        return None      # no clip says anything about this channel at all
    for f, kv in orig.items():
        if f in merged:
            continue
        if not any(lo <= f <= hi for lo, hi in covered):
            merged[f] = kv                        # no clip owns it; not a deletion
    for f, a, b in clashes:
        report("[umvc3] %s frame %d: %s and %s were both edited; kept %s's"
               % (what, f, a, b, a))
    out = [(f, merged[f][0], merged[f][1]) for f in sorted(merged)]
    return [k for k in out if not redundant(k, orig)]


def redundant(key, orig):
    """Is this key one of the boundary samples, saying nothing new?

    Every clip carries the value of every channel at each of its ends so that it
    plays on its own (see `slice_track`), and those samples are not keys the
    file has. One is dropped again when it lands on a frame the file has no key
    at *and* holds exactly what the track already said there - so an untouched
    layout writes back byte for byte, and a boundary someone actually moved
    survives, because then it no longer matches.
    """
    frame, code, value = key
    if not orig or frame in orig:
        return False
    keys = [(f, c, v) for f, (c, v) in sorted(orig.items())]
    was_code, was_value = value_at(keys, frame)
    return code == was_code and all(
        abs(float(a) - float(b)) <= 1e-5 * max(1.0, abs(float(a)))
        for a, b in zip(was_value, value))


DEFAULT = {"mPos": (0.0, 0.0, 0.0), "mAngle": (0.0, 0.0, 0.0),
           "mScale": (1.0, 1.0, 1.0)}


def read_node(ob, node, doc, scale, report=print, sources=None):
    """Write `ob`'s curves back into `node`. -> [tracks written], [skipped]

    `sources` are the layout's clip actions holding this object's curves. A
    scene imported before clips were actions has none, and then the object's own
    action is read directly - so an older `.blend` still exports.
    """
    written, skipped = [], []
    where = "%s %s" % (doc_leaf(doc), node.name)

    def sample(path, indices, codes, default_code, prop, conv):
        """A track's keys in the file's units, from the clips or from the
        object's own action if this scene predates them."""
        if sources:
            return merge_clips(sources, path, indices, codes, default_code,
                               prop, ob, report, where, conv)
        got = _sampled(ob, path, indices, codes, default_code)
        return None if got is None else [(f, c, conv(v)) for f, c, v in got]

    for track, path in XFORM:
        if track == "mAngle" and ob.rotation_mode != "XYZ":
            # The file stores an XYZ euler and nothing else; a quaternion or a
            # different order would have to be converted, and rotation_euler is
            # stale while the object is in another mode, so writing it would
            # write whatever it last held.
            skipped.append("mAngle (object is in %s mode)" % ob.rotation_mode)
            continue
        mul = 1.0 / scale if track == "mPos" else 1.0
        p = node.props.get(track)
        got = sample(path, (0, 1, 2), _codes_of(ob, track),
                     _default_code(p) if p is not None else SDL.SMOOTH, p,
                     lambda v: tuple(x * mul for x in v))
        if got is None:
            # Not animated - but it can still have been dragged. A node that
            # holds one key is a pose, and moving the empty is how you edit it;
            # without this, nudging the cursor would export as nothing.
            if not ob.get("umvc3_sdl_local"):
                continue           # an older scene: the basis is a world matrix
            here = tuple(v * mul for v in getattr(ob, path))
            if p is not None and len(p.keys) > 1:
                continue                       # keys the user deleted; leave them
            if p is not None and not p.keys:
                keys = [(0, SDL.SMOOTH, here)]
            elif p is None:
                if max(abs(a - b) for a, b in zip(here, DEFAULT[track])) < 1e-6:
                    continue
                p = doc.add_prop(node, track, 8, 20)
                report("[umvc3] %s: %s had no %s track; one was added"
                       % (doc_leaf(doc), node.name, track))
                keys = [(0, SDL.SMOOTH, here)]
            else:
                k = p.keys[0]
                keys = [(k.frame, k.code, here)]
            if _changed(p, keys):
                p.set_keys(keys)
                written.append(track)
            continue
        keys = got
        if p is None:
            # The node never had this channel. Adding the record is safe - it
            # goes in with the node's other properties and every index after it
            # is moved along - but say so, because it is a real change of shape.
            p = doc.add_prop(node, track, 8, 20)
            report("[umvc3] %s: %s had no %s track; one was added"
                   % (doc_leaf(doc), node.name, track))
        if _changed(p, keys):
            p.set_keys(keys)
            written.append(track)

    p = node.props.get("Draw")
    # `Draw` is 1 where the engine draws the node, which is the opposite sense
    # to Blender's "hide", so it is turned back over before anything compares it.
    got = sample("hide_viewport", (0,), _codes_of(ob, "Draw"), SDL.HOLD, p,
                 lambda v: (0 if v[0] else 1,))
    if got is not None:
        if p is None:
            skipped.append("Draw")
        elif _changed(p, got):
            p.set_keys(got)
            written.append("Draw")

    for name in (ob.get(O_TRACKS) or ()):
        if name in ("mPos", "mAngle", "mScale", "Draw"):
            continue
        p = node.props.get(name)
        if p is None or not p.editable:
            skipped.append(name)
            continue
        n = 4 if p.kind == 8 else 1        # kind 8 is the only multi-component one
        whole = p.kind in INT_KINDS
        got = sample('["%s%s"]' % (PREFIX, name), tuple(range(n)),
                     _codes_of(ob, name), _default_code(p), p,
                     (lambda v: tuple(int(round(x)) & 0xFFFFFFFF for x in v))
                     if whole else (lambda v: tuple(v)))
        if got is None:
            continue
        if _changed(p, got):
            p.set_keys(got)
            written.append(name)
    return written, skipped


def _changed(prop, keys):
    """Is this actually different from what the file already holds?

    Compared at float32, because that is what the file stores and what Blender
    handed back: a value that survived a round trip unchanged must not count as
    an edit, or every export would rewrite every layout.
    """
    if len(prop.keys) != len(keys):
        return True
    for old, (f, c, v) in zip(prop.keys, keys):
        if old.frame != f or old.code != c:
            return True
        for a, b in zip(old.value, v):
            if abs(float(a) - float(b)) > 1e-6 * max(1.0, abs(float(a))):
                return True
    return False


def doc_leaf(doc):
    return getattr(doc, "_leaf", "layout")


def objects_by_layout(scene):
    """{entry name: {node name: object}} for everything the layouts placed."""
    out = {}
    for ob in scene.objects:
        name, node = ob.get(O_SDL), ob.get(O_NODE)
        if name and node:
            out.setdefault(name, {})[node] = ob
    return out


def export_layouts(scene, by_key, scale, owns=None, report=print):
    """Write every edited layout back into its archive entries.

    -> [(entry leaf, [tracks])] for the layouts that changed.
    """
    from . import mod as M
    done = []
    for entry_name, obs in sorted(objects_by_layout(scene).items()):
        e = by_key.get((entry_name, M.EXT_HASHES["sdl"]))
        if e is None:
            continue
        if owns is not None and not any(owns(ob) for ob in obs.values()):
            continue
        doc = SDL.parse(e.data)
        if doc is None:
            continue
        doc._leaf = entry_name.split("\\")[-1]
        touched = []
        for node_name, ob in sorted(obs.items()):
            node = doc.by_name(node_name)
            if node is None:
                report("[umvc3] %s: no node called %s any more" % (doc._leaf, node_name))
                continue
            written, skipped = read_node(ob, node, doc, scale, report,
                                         sources=clip_sources(ob, entry_name))
            touched += ["%s.%s" % (node_name, t) for t in written]
            for s in skipped:
                report("[umvc3] %s: %s.%s cannot be written back" %
                       (doc._leaf, node_name, s))
        if not touched:
            continue
        e.data, e.dirty = doc.build(), True
        done.append((doc._leaf, touched))
        report("[umvc3] %s: %d animation track(s) written" % (doc._leaf, len(touched)))
    return done
