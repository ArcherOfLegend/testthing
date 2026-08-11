"""Headless test of the character-select animation round-trip.

Imports the screen with the schedulers' keyframes, checks every node's pose
against the file at nine frames, exports untouched (which must change nothing),
then moves a key and adds one and checks both land in the `.sdl`.

  UMVC3_GAME   game folder (default: the Steam install)
  UMVC3_ARC    archive to import (default: the game's mnchscmn_en.arc)

    blender --background --factory-startup --python test_css_anim.py
"""
import os
import sys
import tempfile

import bpy

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)

import io_umvc3_css
from io_umvc3_css import anim as A
from io_umvc3_css import mod as M
from io_umvc3_css import scene as S
from io_umvc3_css import sdl as SDL

GAME = os.environ.get(
    "UMVC3_GAME",
    r"C:\Program Files (x86)\Steam\steamapps\common\ULTIMATE MARVEL VS. CAPCOM 3")
ARC = os.environ.get("UMVC3_ARC") or S.arc_in(GAME)
OUT = os.path.join(tempfile.gettempdir(), "umvc3_anim_test")
os.makedirs(OUT, exist_ok=True)

fails = []


def check(cond, msg):
    print("  %s %s" % ("ok  " if cond else "FAIL", msg))
    if not cond:
        fails.append(msg)


def sdl_entry(path, leaf):
    _v, entries = M.read_arc(path)
    for e in entries:
        if e.hash == M.EXT_HASHES["sdl"] and e.name.endswith(leaf):
            return e
    return None


print("\n=== register + import (animated) ===")
io_umvc3_css.register()
bpy.ops.wm.read_factory_settings(use_empty=True)
r = S.import_css(bpy.context, game_dir=GAME, arc_path=ARC, scale=0.01,
                 load_portraits=False, load_screen=False, animate=True)
sc = bpy.context.scene
print("   %d placed, frames %d..%d at %d, %d clip actions"
      % (r["placed"], sc.frame_start, sc.frame_end, sc.frame_current,
         len([a for a in bpy.data.actions if a.get("umvc3_sdl_clip")])))

cen = bpy.data.objects.get("sdl_card1p_cen")
no1 = bpy.data.objects.get("sdl_chs_card1p_no1")
check(cen is not None and no1 is not None, "the card stack's empties exist")
check(sc.frame_end >= 605, "scene frame range covers the last key (%d)" % sc.frame_end)
check(sc.frame_current == 61, "scene opens at the settle frame (%d)" % sc.frame_current)
check(not sc.timeline_markers,
      "no timeline markers: the clips are actions, not labels on one timeline")

ad = cen.animation_data
check(ad is not None and len(ad.nla_tracks) == 1,
      "the anchor's clips are laid out as NLA strips")
strips = list(ad.nla_tracks[0].strips)
check([s.name for s in strips][:3] == ["start", "sel1", "sel1_decide"],
      "one strip per clip, named after it: %s" % [s.name for s in strips][:4])
check(all(s.frame_start < s.frame_end for s in strips)
      and all(a.frame_end <= b.frame_start for a, b in zip(strips, strips[1:])),
      "each at the frames the clip table gives it, in order")
check(ad.action is None, "and no whole-timeline action to keep in sync with them")

clip_acts = [a for a in bpy.data.actions if a.get("umvc3_sdl_clip")]
check(len(clip_acts) >= 19, "one action per clip, for every layout (%d)" % len(clip_acts))
start = bpy.data.actions.get("chs_card1p | start")
check(start is not None and list(start["umvc3_sdl_range"]) == [0, 61],
      "named <layout> | <clip>, tagged with its range")
bag = A.bag_for(start, cen)
paths = sorted({fc.data_path for fc in bag.fcurves})
check("location" in paths and "scale" in paths,
      "holding this node's curves in its own slot: %s" % paths)
check(A.bag_for(start, no1) is not None,
      "and every other node of the layout in the same action")

# the values the file holds, at the frames it holds them
e = sdl_entry(ARC, "chs_card1p")
doc = SDL.parse(e.data)
node = doc.by_name("card1p_cen")


def evaluated(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    return ob.evaluated_get(dg)


want = [(k.frame, tuple(round(c, 3) for c in k.value[:3])) for k in node.props["mPos"].keys]
got = []
for f, _v in want:
    sc.frame_set(f)
    got.append((f, tuple(round(c / 0.01, 3)
                         for c in evaluated(cen).matrix_local.translation)))
check(all(abs(a[1][i] - b[1][i]) < 0.05 for a, b in zip(want, got) for i in range(3)),
      "every mPos key reproduces in Blender")
if want[:3] != got[:3]:
    print("      want %s\n      got  %s" % (want[:3], got[:3]))

# A child's world transform must be the whole node chain composed, on EVERY
# frame - not just the one the pose used to be baked at. Composed here straight
# from the file, independently of how the importer built the scene.
from mathutils import Euler, Matrix, Vector


def sample(node, track, frame, default):
    """The track at a frame, the way the keys say to read it: a code-0 key
    holds until the next one, anything else interpolates to it."""
    p = node.props.get(track)
    if p is None or not p.keys:
        return default
    if frame <= p.keys[0].frame:
        return p.keys[0].value[:3]
    for a, b in zip(p.keys, p.keys[1:]):
        if a.frame <= frame < b.frame:
            if a.code == 0:
                return a.value[:3]
            t = (frame - a.frame) / float(b.frame - a.frame)
            return tuple(x + (y - x) * t for x, y in zip(a.value[:3], b.value[:3]))
    return p.keys[-1].value[:3]


def engine_local(node, frame):
    return Matrix.LocRotScale(
        Vector(sample(node, "mPos", frame, (0.0, 0.0, 0.0))) * 0.01,
        Euler(sample(node, "mAngle", frame, (0.0, 0.0, 0.0)), "XYZ"),
        Vector(sample(node, "mScale", frame, (1.0, 1.0, 1.0))))


def engine_world(doc, name, frame):
    m = Matrix.Identity(4)
    for n in reversed(SDL.chain(doc.by_name(name))):
        m = m @ engine_local(n, frame)
    return m


FRAMES = (0, 27, 41, 61, 121, 300, 465, 560, 605)
worst, where = 0.0, None
wworst, wwhere = 0.0, None
for f in FRAMES:
    sc.frame_set(f)
    for nm, ob in (("card1p_cen", cen), ("chs_card1p_no1", no1)):
        ev = evaluated(ob)
        d = max(abs(a - b) for ra, rb in zip(engine_local(doc.by_name(nm), f), ev.matrix_basis)
                for a, b in zip(ra, rb))
        if d > worst:
            worst, where = d, (nm, f)
        # matrix_world is only evaluated while something in the subtree is
        # drawn; at 605 the whole stack is hidden, which is the animation
        # doing its job rather than a pose going wrong.
        if not ev.hide_viewport:
            dw = max(abs(a - b) for ra, rb in zip(engine_world(doc, nm, f), ev.matrix_world)
                     for a, b in zip(ra, rb))
            if dw > wworst:
                wworst, wwhere = dw, (nm, f)
check(worst < 1e-5, "every node's own transform matches the file at nine frames "
                    "(worst %.2e at %s)" % (worst, where))
check(wworst < 1e-5, "and the chain composes to the same world matrix the engine "
                     "builds (worst %.2e at %s)" % (wworst, wwhere))

sc.frame_set(0)
w0 = evaluated(no1).matrix_world.translation.copy()
sc.frame_set(61)
w61 = evaluated(no1).matrix_world.translation.copy()
check(w0.x < -8.0, "at frame 0 the card is off-screen left (x=%.2f)" % w0.x)
check(-4.5 < w61.x < -4.0, "at the settle frame it has flown in (x=%.2f)" % w61.x)

# constant-interpolation keys came across as holds
codes = {k.frame: k.code for k in node.props["mPos"].keys}
mism = []
for fc in A.bag_for(start, cen).fcurves:
    if fc.data_path != "location":
        continue
    for kp in fc.keyframe_points:
        f = round(kp.co[0])
        if f not in codes:
            continue                      # a boundary sample, not a key of the file
        want_c = "CONSTANT" if codes[f] == 0 else "LINEAR"
        if kp.interpolation != want_c:
            mism.append((f, kp.interpolation, want_c))
check(not mism, "interpolation matches the file's codes%s" % (" %s" % mism[:3] if mism else ""))

print("\n=== export with nothing touched ===")
out1 = os.path.join(OUT, "untouched.arc")
S.export_css(bpy.context, out1, follow_page=False, refit_weights=False)
a = sdl_entry(ARC, "chs_card1p").data
b = sdl_entry(out1, "chs_card1p").data
check(a == b, "an untouched layout is byte-identical (%d vs %d bytes)" % (len(a), len(b)))
for leaf in ("chs_card2p", "chs_meku", "chs_hnd_a"):
    check(sdl_entry(ARC, leaf).data == sdl_entry(out1, leaf).data,
          "%s untouched too" % leaf)

print("\n=== move a key in a clip, then export ===")


def curve(action, ob, path, index):
    return next(fc for fc in A.bag_for(action, ob).fcurves
                if fc.data_path == path and fc.array_index == index)


def set_key(action, ob, path, index, frame, value):
    fc = curve(action, ob, path, index)
    for kp in fc.keyframe_points:
        if round(kp.co[0]) == frame:
            kp.co = (float(frame), float(value))
            kp.handle_left.y = kp.handle_right.y = float(value)
            fc.update()
            return True
    kp = fc.keyframe_points.insert(float(frame), float(value))
    kp.interpolation = "LINEAR"
    fc.update()
    return False


# the fly-in's first pose, edited in the `start` clip and nowhere else
set_key(start, cen, "location", 0, 0, -9.0)
set_key(start, cen, "location", 1, 0, 0.5)
out2 = os.path.join(OUT, "moved.arc")
S.export_css(bpy.context, out2, follow_page=False, refit_weights=False)
doc2 = SDL.parse(sdl_entry(out2, "chs_card1p").data)
k0 = doc2.by_name("card1p_cen").props["mPos"].keys[0]
check(abs(k0.value[0] - (-900.0)) < 0.01 and abs(k0.value[1] - 50.0) < 0.01,
      "the moved key is in the file: %s" % (tuple(round(c, 2) for c in k0.value[:3]),))
old = SDL.parse(a).by_name("card1p_cen").props["mPos"].keys
check(len(doc2.by_name("card1p_cen").props["mPos"].keys) == len(old),
      "no keys were gained or lost")
check(all(abs(x.value[0] - y.value[0]) < 0.01
          for x, y in list(zip(doc2.by_name("card1p_cen").props["mPos"].keys, old))[1:]),
      "every other key is untouched")
check(all(x.code == y.code
          for x, y in zip(doc2.by_name("card1p_cen").props["mPos"].keys, old)),
      "interpolation codes are preserved (including the two 5s)")
check(sdl_entry(out2, "chs_card2p").data == sdl_entry(ARC, "chs_card2p").data,
      "the other player's layout was not rewritten")

print("\n=== add a key inside a clip ===")
# frame 300 is inside `rollup3` (291..301), which is where it has to land
rollup3 = bpy.data.actions["chs_card1p | rollup3"]
set_key(rollup3, cen, "location", 0, 300, -3.0)
out3 = os.path.join(OUT, "added.arc")
S.export_css(bpy.context, out3, follow_page=False, refit_weights=False)
doc3 = SDL.parse(sdl_entry(out3, "chs_card1p").data)
keys3 = doc3.by_name("card1p_cen").props["mPos"].keys
check(len(keys3) == len(old) + 1, "the new key is in the file (%d -> %d)"
      % (len(old), len(keys3)))
check(any(k.frame == 300 and abs(k.value[0] + 300.0) < 0.01 for k in keys3),
      "at the right frame with the right value")
check(doc3.by_name("chs_card1p_no1").model == "ui\\chs\\chs_meku\\chs_card",
      "the rest of the layout still parses")
check(len(doc3.clips) == 19, "the clip table survived (%d clips)" % len(doc3.clips))

print("\n=== drag an un-keyed node ===")
# A node whose track holds one key is a pose, and dragging the empty is how you
# edit it. The cursor is the case that matters: it has no mAngle track at all,
# so rotating it has to add the property record.
plate = next(o for o in sc.objects
             if o.get("umvc3_sdl_node") == "chs_card1p_no1_un")
before_pos = SDL.parse(a).by_name("chs_card1p_no1_un").props["mPos"].keys[0].value[0]
check(not any((("location", 0) in curves) for _l, _lo, _hi, curves
                  in A.clip_sources(plate, e.name)),
      "a node whose position never moves has no location curve in any clip")
plate.location = (plate.location.x + 0.5, plate.location.y, plate.location.z)

hnd = next(o for o in sc.objects if o.get("umvc3_sdl_node") == "p_chs_hnd1_1P")
hnd_doc = SDL.parse(sdl_entry(ARC, "chs_hnd_a").data)
check("mAngle" not in hnd_doc.by_name("p_chs_hnd1_1P").props,
      "the cursor has no mAngle track to start with")
hnd.rotation_euler = (0.0, 0.0, 0.25)

out4 = os.path.join(OUT, "dragged.arc")
S.export_css(bpy.context, out4, follow_page=False, refit_weights=False)
got_pos = SDL.parse(sdl_entry(out4, "chs_card1p").data) \
    .by_name("chs_card1p_no1_un").props["mPos"].keys[0].value[0]
check(abs(got_pos - (before_pos + 50.0)) < 0.01,
      "dragging a node that holds a single key writes it (%.1f -> %.1f)"
      % (before_pos, got_pos))
doc4 = SDL.parse(sdl_entry(out4, "chs_hnd_a").data)
n4 = doc4.by_name("p_chs_hnd1_1P")
check("mAngle" in n4.props and abs(n4.props["mAngle"].keys[0].value[2] - 0.25) < 1e-4,
      "and rotating one writes a track that had to be created")
check(len(doc4.nodes) == len(hnd_doc.nodes)
      and all(doc4.by_name(n.name) is not None for n in hnd_doc.nodes.values()),
      "every node survived the record insertion")
check(all((doc4.by_name(n.name).parent is None) == (n.parent is None)
          and (n.parent is None
               or doc4.by_name(n.name).parent.name == n.parent.name)
          for n in hnd_doc.nodes.values()),
      "and so did every mpParent, which is a record index")

print("\n=== re-import what we exported ===")
bpy.ops.wm.read_factory_settings(use_empty=True)
S.import_css(bpy.context, game_dir=GAME, arc_path=out3, scale=0.01,
             load_portraits=False, load_screen=False, animate=True)
cen2 = bpy.data.objects.get("sdl_card1p_cen")
act2 = bpy.data.actions.get("chs_card1p | rollup3")
fc = next(f for f in A.bag_for(act2, cen2).fcurves
          if f.data_path == "location" and f.array_index == 0)
check(any(abs(kp.co[0] - 300) < 0.5 and abs(kp.co[1] + 3.0) < 0.01
          for kp in fc.keyframe_points),
      "the added key comes back on re-import, in the clip it belongs to")
sc2 = bpy.context.scene
sc2.frame_set(300)
dg = bpy.context.evaluated_depsgraph_get()
check(abs(cen2.evaluated_get(dg).matrix_basis.translation.x + 3.0) < 0.01,
      "and the strips play it back")

print("\n=== import with animation off still works ===")
bpy.ops.wm.read_factory_settings(use_empty=True)
S.import_css(bpy.context, game_dir=GAME, arc_path=ARC, scale=0.01,
             load_portraits=False, load_screen=False, animate=False)
cen3 = bpy.data.objects.get("sdl_card1p_cen")
check(cen3 is not None and cen3.animation_data is None,
      "no animation data when it is off")
check(abs(cen3.matrix_world.translation.x - (-4.25)) < 0.01,
      "and the settle pose is where it always was (x=%.3f)"
      % cen3.matrix_world.translation.x)

print("\n%s  (%d checks failed)" % ("FAILED" if fails else "ALL PASSED", len(fails)))
for f in fails:
    print("   -", f)
sys.exit(1 if fails else 0)
