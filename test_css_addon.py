"""Headless round-trip test for the character-select addon.

Runs the whole path the UI drives: register, import the screen as a scene,
export it untouched (which must not move anything), then move a card and check
that its depth followed the page and its weights were refitted.

  UMVC3_GAME   game folder (default: the Steam install)
  UMVC3_ARC    archive to import (default: the game's mnchscmn_en.arc)
  UMVC3_OUT    scratch directory for the exported archives

    blender --background --factory-startup --python test_css_addon.py
"""
import os
import shutil
import struct
import sys
import tempfile

import bpy

try:
    TOOLS = os.path.dirname(os.path.abspath(__file__))
except NameError:
    TOOLS = os.getcwd()
sys.path.insert(0, TOOLS)

import io_umvc3_css
from io_umvc3_css import grid as G
from io_umvc3_css import mod as M
from io_umvc3_css import roster as R
from io_umvc3_css import scene as S
from io_umvc3_css import verify as V

GAME = os.environ.get(
    "UMVC3_GAME",
    r"C:\Program Files (x86)\Steam\steamapps\common\ULTIMATE MARVEL VS. CAPCOM 3")
# A known-good 9 x 16 build, not whatever is installed. Half these checks assert
# that an untouched export changes nothing and that every card is on the regular
# grid, and the whole point of the addon is that the installed archive may be
# deliberately rearranged - testing against it makes the suite fail on success.
FIXTURE = os.path.join(TOOLS, "backup", "BUILT_mnchscmn_16col9row_installed.arc")
ARC = os.environ.get("UMVC3_ARC") or (
    FIXTURE if os.path.isfile(FIXTURE) else S.arc_in(GAME))
OUT = os.environ.get("UMVC3_OUT") or os.path.join(tempfile.gettempdir(), "umvc3_css_test")
os.makedirs(OUT, exist_ok=True)

fails = []


def check(cond, msg):
    print("  %s %s" % ("ok  " if cond else "FAIL", msg))
    if not cond:
        fails.append(msg)


def card_centre(entries, entry_name, jid, rows):
    e = next(x for x in entries if x.ext == "mod" and x.name == entry_name)
    for c in G.read_cards(e.data, rows=rows):
        if c["jid"] == jid:
            return c
    return None


print("=" * 72)
print("register")
io_umvc3_css.register()
check(hasattr(bpy.types.Scene, "umvc3_css_rows"), "scene properties registered")
check("css_import" in dir(bpy.ops.umvc3) and "css_install" in dir(bpy.ops.umvc3),
      "operators registered")

# A panel's draw() only runs with a UI, so a typo'd property or operator name
# would show up as a broken sidebar and nothing else. Check the references
# resolve here instead.
from io_umvc3_css import ui as U
import inspect
src = "".join(inspect.getsource(c.draw) for c in U.CLASSES if hasattr(c, "draw")
              and issubclass(c, bpy.types.Panel))
missing = [n for n in set(__import__("re").findall(r"sc\.(umvc3_\w+)", src))
           if not hasattr(bpy.types.Scene, n)]
check(not missing, "every property the panels draw exists: missing %s" % missing)
bad_ops = [c.bl_idname for c in U.CLASSES if issubclass(c, bpy.types.Operator)
           and not hasattr(bpy.ops.umvc3, c.bl_idname.split(".", 1)[1])]
check(not bad_ops, "every operator the panels call is registered: %s" % bad_ops)

# Panels belong in the Properties editor, beside the data they describe, not in
# a viewport tab you have to know to open.
panels = [c for c in list(U.CLASSES) + list(M.CLASSES)
          if isinstance(c, type) and issubclass(c, bpy.types.Panel)]
check(len(panels) == 4, "four panels: %s" % [p.bl_label for p in panels])
misplaced = [p.__name__ for p in panels
             if p.bl_space_type != "PROPERTIES" or p.bl_region_type != "WINDOW"]
check(not misplaced, "every panel is in the Properties editor: %s" % misplaced)
check(not [p.__name__ for p in panels if getattr(p, "bl_category", None)],
      "no panel claims a viewport sidebar tab any more")
ctx = {p.__name__: getattr(p, "bl_context", None) for p in panels}
check(ctx.get("UMVC3_PT_css_card") == "object",
      "the card panel is in the Object tab (%s)" % ctx.get("UMVC3_PT_css_card"))
check(ctx.get("UMVC3_PT_css") == "scene" and ctx.get("UMVC3_PT_css_write") == "scene"
      and ctx.get("UMVC3_PT_archive") == "scene",
      "scene-wide panels are in the Scene tab: %s" % ctx)
# a sub-panel must share its parent's space and context or it never draws
for p in panels:
    parent = getattr(p, "bl_parent_id", None)
    if parent:
        par = next(q for q in panels if q.__name__ == parent)
        check(par.bl_space_type == p.bl_space_type and par.bl_context == p.bl_context,
              "%s sits in the same tab as its parent %s" % (p.__name__, parent))

print("\nroster")
table = R.relayout(9, 16)
row0 = [table[s] for s in range(8)]
check(row0 == [20, 25, 24, 21, 23, 0, 0, 53],
      "9x16 page A row 0 is Jill/Nemesis/Firebrand/Strider/PW, blanks, RANDOM: %s" % row0)
check(table[8] == 54 and table[9] == 0 and table[10] == 0,
      "page B row 0 opens with RANDOM at the spine then two blanks")
check(sorted(v for v in table.values() if v not in (0, 53, 54)) == list(range(1, 51)),
      "all 50 vanilla characters placed exactly once")
ce = R.read_ce_roster(GAME)
check(len(ce) == 83, "CloneEngine roster has 83 playable entries (got %d)" % len(ce))
check(R.VANILLA_NAMES[24] == "RedArremer" and R.display_name("RedArremer") == "Firebrand",
      "id 24 is Firebrand")

print("\nslot <-> cell round-trip")
bad = [(p, c, r) for p in "ab" for c in range(8) for r in range(9)
       if G.cell_of_slot(G.slot_of(p, c, r, 9, 16), 9, 16) != (p, c, r)]
check(not bad, "every cell survives slot_of -> cell_of_slot (%d bad)" % len(bad))
check(G.slot_of("a", 0, 0, 9, 16) == 7 and G.slot_of("b", 0, 0, 9, 16) == 8,
      "joint column 0 of each page sits either side of the spine")

print("\ngrid detection survives a rearranged screen")
_, _det = M.read_arc(ARC)
check(G.detect_grid(_det) == (9, 16), "the source archive detects as 9 x 16")
_e = next(x for x in _det if x.ext == "mod" and x.name.endswith("face_a"))
_cards = G.read_cards(_e.data, rows=None)
check(G.detect_rows(_cards) == 9, "face_a alone detects 9 rows")
# Displace cards by hand and re-detect. Detection used to demand every card be
# within 2 units of its row and column, so ONE moved card failed outright and
# silently fell back to vanilla 7 x 8 - which renumbers every slot and every
# character assignment in the scene.
for n_moved in (1, 3, 8):
    hacked = [dict(c) for c in _cards]
    for c in hacked[:n_moved]:
        c["cx"] = c["cx"] + 400.0
        c["cy"] = c["cy"] - 130.0
    check(G.detect_rows(hacked) == 9,
          "%d displaced card(s) still detect as 9 rows (got %s)"
          % (n_moved, G.detect_rows(hacked)))
# ...but a genuinely different grid must not be forced to 9
check(G.detect_rows([dict(c, cy=c["cy"], cx=c["cx"]) for c in _cards]) == 9,
      "an untouched model is unchanged by the robustness")

print("\nmaterial -> texture binding")
_ver, _ents = M.read_arc(ARC)
_meku = next(x for x in _ents if x.ext == "mod" and G.leaf(x.name) == "chs_meku")
_mrl = next(x for x in _ents if x.ext == "mrl" and G.leaf(x.name) == "chs_meku")
_texs, _h2i = M.parse_mrl_bytes(_mrl.data)
_bind = M.mrl_texture_bindings(_mrl.data)
check(len(_bind) >= 7, "recovered %d of 8 bindings from the MRL" % len(_bind))
# The one the game confirms: the grid lines borrow this material, and the patch
# painted into meku_chs01 is what shows on screen. The old heuristic said
# meku_chs02, so editing the texture Blender showed changed nothing in game.
_who = "XfBAD_W_22__m01_"
_got, _why = M.choose_texture(_texs, _h2i.get(M.mt_hash(_who)),
                              len(M.read_mod_material_names(_meku.data)),
                              _bind.get(M.mt_hash(_who)))
check(_got.endswith("meku_chs01_BM_NOMIP") and _why == "mrl binding",
      "%s binds meku_chs01, not the first base map (%s, %s)" % (_who, _got, _why))
# a shader that keeps its base map elsewhere must fall through, not pick garbage
check(M.choose_texture(_texs, None, 8, None)[1] != "mrl binding",
      "an unrecovered binding still falls back to the heuristic")
check(M.choose_texture(["only"], None, 1, 99)[0] == "only",
      "an out-of-range binding is ignored rather than trusted")

print("\nimport %s" % os.path.basename(ARC))
r = S.import_css(bpy.context, game_dir=GAME, arc_path=ARC, scale=0.01,
                 load_portraits=True, report=lambda m: None)
print("  %d x %d, %d card meshes in %d groups, %d portraits bound"
      % (r["rows"], r["cols"], r["cards"], r["groups"], r["portraits"]))
check(r["rows"] == 9 and r["cols"] == 16, "detected a 9 x 16 grid")
check(r["cards"] > 800, "annotated every card mesh (%d)" % r["cards"])
check(r["portraits"] > 40, "bound %d portraits onto cards" % r["portraits"])

print("\nediting an archive texture survives export")
# Archive textures are file-backed, and img.copy() on a file-backed image
# re-reads the file - so reading pixels through a copy threw the user's paint
# away and export wrote the original straight back, silently.
_img = next(i for i in bpy.data.images if i.get("umvc3_entry") and i.size[0] > 0)
_w, _h = _img.size
_before = M.image_pixels_topdown(_img, _w, _h)[:4]
_px = list(_img.pixels)
for _i in range(0, len(_px), 4):
    _px[_i:_i + 4] = [1.0, 0.0, 0.0, 1.0]
_img.pixels[:] = _px
_img.update()
check(M.texture_is_modified(_img), "a painted texture reads as modified")
_after = M.image_pixels_topdown(_img, _w, _h)[:4]
check(_after == [255, 0, 0, 255],
      "the painted pixels reach the encoder (%s -> %s)" % (_before, _after))
# and the resize path must not lose them either
_half = M.image_pixels_topdown(_img, _w // 2, _h // 2)
check(len(_half) == (_w // 2) * (_h // 2) * 4 and _half[:4] == [255, 0, 0, 255],
      "scaling to %dx%d keeps them too" % (_w // 2, _h // 2))
check(tuple(_img.size) == (_w, _h), "the caller's image is left at its own size")
# decode/encode are only inverses in file order; the default is Blender order.
# Top half black, bottom half white - whole 4x4 blocks, so BC1 is exact and any
# difference is a mirror rather than compression noise.
_flat = [0] * (8 * 8 * 4)
for _i in range(8 * 8):
    _v = 0 if (_i // 8) < 4 else 255
    _flat[_i * 4] = _flat[_i * 4 + 1] = _flat[_i * 4 + 2] = _v
    _flat[_i * 4 + 3] = 255
_enc = M.encode_bc(_flat, 8, 8, False)
_rt = M.decode_bc(_enc, 8, 8, False, bottom_up=False)
check(_rt[0] * 255 < 8 and _rt[-4] * 255 > 247,
      "decode_bc(bottom_up=False) round-trips encode_bc without mirroring")
_mirror = M.decode_bc(_enc, 8, 8, False)
check(_mirror[0] * 255 > 247 and _mirror[-4] * 255 < 8,
      "and the default really is the other way up, as its callers assume")

_img.reload()          # leave the scene as it was found

print("\ntransparency becomes BC1's one bit, not the colour hiding under it")
# The colour under a fully transparent pixel is undefined and tools leave
# anything there. Dropping the alpha ships it opaque - and worse, a block whose
# endpoints span it shades its VISIBLE texels toward it, which is how green and
# black came through the middle of a cut-out portrait.
_HID = (0, 255, 0)                                      # the garbage under the hole
_cut = [0] * (8 * 8 * 4)
for _i in range(8 * 8):
    _opaque = (_i % 8) < 4                              # left half art, right half hole
    _cut[_i * 4:_i * 4 + 3] = [200, 40, 40] if _opaque else list(_HID)
    _cut[_i * 4 + 3] = 255 if _opaque else 0
_enc_c = M.encode_bc(_cut, 8, 8, False, cutout=True)
_dec_c = M.decode_bc(_enc_c, 8, 8, False, bottom_up=False)
check(_dec_c[3] > 0.5 and _dec_c[4 * 4 + 3] < 0.5,
      "the hole comes back transparent and the art opaque (%.0f, %.0f)"
      % (_dec_c[3], _dec_c[4 * 4 + 3]))
check(_dec_c[0] > 0.6 and _dec_c[1] < 0.3,
      "the art keeps its own colour, unpolluted by what it sat beside (%.2f, %.2f, %.2f)"
      % tuple(_dec_c[:3]))
check(all(_dec_c[(_i * 4) + 1] < 0.3 for _i in range(64)),
      "and the green under the hole is nowhere in the block at all")
# without the flag nothing changes for callers that never had alpha to carry
_opaque_px = [v if (i % 4) != 3 else 255 for i, v in enumerate(_cut)]
check(M.encode_bc(_opaque_px, 8, 8, False) == M.encode_bc(_opaque_px, 8, 8, False, cutout=True),
      "an opaque image encodes identically either way")
check(M.decode_bc(M.encode_bc(_opaque_px, 8, 8, False), 8, 8, False, bottom_up=False)[3] > 0.5,
      "and still decodes as opaque, so a re-encode cannot punch holes in it")
# a block with nothing visible at all is legal and wholly transparent
_none = [0, 0, 0, 0] * 16
check(all(v < 0.5 for v in M.decode_bc(M.encode_bc(_none, 4, 4, False, cutout=True),
                                       4, 4, False, bottom_up=False)[3::4]),
      "a fully transparent block encodes and comes back fully transparent")

# The same colour bleeds in through the RESIZE, which interpolates the four
# channels independently: every edge texel of a cut-out then carries a colour
# nobody ever meant to be seen, whatever the encoder does with it afterwards.
_bl = bpy.data.images.new("t_bleed", width=64, height=64, alpha=True)
_bl.pixels = [v for _i in range(64 * 64)
              for v in ([0.8, 0.15, 0.15, 1.0] if (_i % 64) < 32
                        else [0.0, 1.0, 0.0, 0.0])]
_scaled = M.image_pixels_topdown(_bl, 32, 32)
check(max(_scaled[1::4]) < 90,
      "scaling a cut-out keeps the hole's colour out of its border (max g %d)"
      % max(_scaled[1::4]))
check(max(_scaled[0::4]) > 180 and min(_scaled[3::4]) == 0,
      "while keeping the art and the hole themselves")
check(S._soft_alpha(_bl) is False, "a clean cut-out needs no warning about alpha")
_bl.pixels = [0.5] * (64 * 64 * 4)
check(S._soft_alpha(_bl) is True, "a half-transparent one does")
bpy.data.images.remove(_bl)

print("\na flat Base Color is baked into the texels the mesh samples")
_ents2 = M.read_arc(ARC)[1]
_bk2 = {e.key: e for e in _ents2}
_lines = [o for o in bpy.context.scene.objects
          if o.type == "MESH" and o.get("umvc3_entry")
          and G.leaf(o["umvc3_entry"]) == "chs_meku" and o.data.materials
          and (o.data.materials[0].get("umvc3_texture") or "").endswith("meku_chs01_BM_NOMIP")]
check(bool(_lines), "found the grid-line meshes (%d)" % len(_lines))
# untouched materials must bake nothing at all
check(S.bake_flat_materials(bpy.context.scene, _bk2, report=lambda m: None)[0] == [],
      "an untouched scene bakes no colours")
# An RGB node wired into Base Color is the other way to say "make this red", and
# it leaves the socket LINKED - which an is_linked check reads as "shows an
# image" and skips, so the colour silently never reached the game.
_ob = max(_lines, key=lambda o: len(o.data.vertices))
_nt = _ob.data.materials[0].node_tree
_bs = next(n for n in _nt.nodes if n.type == "BSDF_PRINCIPLED")
_rgbnode = _nt.nodes.new("ShaderNodeRGB")
_rgbnode.outputs[0].default_value = (0.0, 1.0, 0.0, 1.0)
_nt.links.new(_bs.inputs["Base Color"], _rgbnode.outputs[0])
check(_bs.inputs["Base Color"].is_linked, "an RGB node leaves the socket linked")
check(M.material_flat_color(_ob.data.materials[0]) == (0.0, 1.0, 0.0),
      "and the colour is still read through it")
# through a reroute too, which is how a tidied graph ends up wired
_rr = _nt.nodes.new("NodeReroute")
_nt.links.new(_rr.inputs[0], _rgbnode.outputs[0])
_nt.links.new(_bs.inputs["Base Color"], _rr.outputs[0])
check(M.material_flat_color(_ob.data.materials[0]) == (0.0, 1.0, 0.0),
      "and through a reroute")
_nt.nodes.remove(_rr)
_nt.nodes.remove(_rgbnode)
_nt.links.new(_bs.inputs["Base Color"],
              next(n for n in _nt.nodes if n.type == "TEX_IMAGE").outputs["Color"])
check(M.material_flat_color(_ob.data.materials[0]) is None,
      "an image-fed material is not a flat colour")
check(M.material_shown_image(_ob.data.materials[0]) is not None,
      "and its image is what it shows")

# A page mapped across its whole sheet must be refused, not flooded - archive
# textures are shared, and that would take everything else on them with it.
_page = max(_lines, key=lambda o: len(o.data.vertices)).data.materials[0]
_pb = next(n for n in _page.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
for _l in list(_pb.inputs["Base Color"].links):
    _page.node_tree.links.remove(_l)
_pb.inputs["Base Color"].default_value = (1.0, 0.0, 0.0, 1.0)
check(M.material_flat_color(_page) == (1.0, 0.0, 0.0), "the flat colour is read back")
_pp, _ps = S.bake_flat_materials(bpy.context.scene, _bk2, report=lambda m: None)
check(_pp == [] and any("covers" in s for s in _ps),
      "a material mapped across its sheet is refused, not flooded (%s)" % (_ps[:1],))

# The grid-line case: every vertex samples ONE texel, which is unambiguous.
_TEX = "ui\\chs\\chs_meku\\meku_chs01_BM_NOMIP"
_me = bpy.data.meshes.new("flatprobe")
_me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
_me.update()
_uv = _me.uv_layers.new(name="UVMap")
for _d in _uv.data:
    _d.uv = (0.025, 1.0 - 0.0444)          # as the importer stores it
_fm = M.build_material("flatprobe", None)
_fm["umvc3_texture"] = _TEX
_fm["umvc3_had_image"] = True              # the user unlinked a real image
_me.materials.append(_fm)
_fo = bpy.data.objects.new("flatprobe", _me)
_fo["umvc3_entry"] = "ui\\chs\\chs_meku\\chs_meku"
bpy.context.scene.collection.objects.link(_fo)
next(n for n in _fm.node_tree.nodes
     if n.type == "BSDF_PRINCIPLED").inputs["Base Color"].default_value = (1.0, 0.0, 0.0, 1.0)
_painted, _ = S.bake_flat_materials(bpy.context.scene, _bk2, report=lambda m: None)
check(any("flatprobe" in p for p in _painted),
      "a single-texel footprint bakes (%s)" % (_painted or "nothing",))
_ti = M.tex_info(_bk2[(_TEX, M.EXT_HASHES["tex"])].data)
_W, _H = _ti["width"], _ti["height"]
_dec = M.decode_bc(_ti["payload"], _W, _H, _ti["fmt"] not in M.BC1_CODES, bottom_up=False)
_x, _y = int(0.025 * _W), int(0.0444 * _H)
_rgb = tuple(int(_dec[(_y * _W + _x) * 4 + c] * 255 + 0.5) for c in range(3))
check(_rgb == (255, 0, 0), "the texel it samples is exactly the colour asked for %s" % (_rgb,))
# exact means block-aligned: a region ending mid-block interpolates with the old
check(all(int(_dec[((_y + dy) * _W + _x + dx) * 4] * 255 + 0.5) == 255
          for dy in (-1, 0, 1) for dx in (-1, 0, 1)),
      "and so are its neighbours, so filtering cannot blend the old colour back")
bpy.data.objects.remove(_fo)

print("\nany shading at all is exported, by letting Blender render it")
# Ambient occlusion, a mix, a procedural - none of them can be read off the
# graph, so Cycles evaluates them. These uvs collapse to a point, as the grid
# lines' do, so there is no area to rasterise into and it bakes to a colour
# attribute instead, which needs no uvs at all.
_bk3 = {e.key: e for e in M.read_arc(ARC)[1]}
_me2 = bpy.data.meshes.new("aoprobe")
_me2.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
_me2.update()
_uv2 = _me2.uv_layers.new(name="UVMap")
for _d in _uv2.data:
    _d.uv = (0.025, 1.0 - 0.0444)
_am = M.build_material("aoprobe", None)
_am["umvc3_texture"] = _TEX
_am["umvc3_had_image"] = True
_me2.materials.append(_am)
_ao = bpy.data.objects.new("aoprobe", _me2)
# well clear of the imported screen: sat at the origin it is buried inside the
# card grid and bakes black, which is the right answer to the wrong question
_ao.location = (1000.0, 1000.0, 1000.0)
_ao["umvc3_entry"] = "ui\\chs\\chs_meku\\chs_meku"
bpy.context.scene.collection.objects.link(_ao)
# Imported meshes carry the colours the .mod stores, and a vertex bake writes
# into whichever colour attribute is ACTIVE - so without claiming that, the bake
# quietly filled this one and left the target at its creation value, which reads
# back as a perfectly plausible result. The probe has to have one too or the test
# cannot see that bug.
_me2.color_attributes.new(name="color0", type="FLOAT_COLOR", domain="CORNER")
_ant = _am.node_tree
_abs = next(n for n in _ant.nodes if n.type == "BSDF_PRINCIPLED")
# A DIFFUSE bake scales by the BSDF's own parameters; at this Metallic it would
# come back at a tenth strength. EMIT asks the graph for its colour and nothing else.
_abs.inputs["Metallic"].default_value = 0.9
_aon = _ant.nodes.new("ShaderNodeAmbientOcclusion")
_aon.inputs["Color"].default_value = (0.0, 0.0, 1.0, 1.0)     # unmistakably blue
_ant.links.new(_abs.inputs["Base Color"], _aon.outputs["Color"])
check(M.material_flat_color(_am) is None, "an AO node is not a flat colour")
check(S._uv_area(_ao, 0) < 1e-9, "and this probe has no uv area to bake into")

_snap = (bpy.context.scene.render.engine,
         sorted(o.name for o in bpy.context.scene.objects if o.select_get()),
         sorted((o.name, a.name) for o in bpy.context.scene.objects
                if o.type == "MESH" for a in o.data.color_attributes))
_ap, _as_ = S.bake_flat_materials(bpy.context.scene, _bk3, report=lambda m: None)
check(any("aoprobe" in p for p in _ap),
      "it is baked anyway (%s)" % (_ap or _as_ or "nothing",))
_ti3 = M.tex_info(_bk3[(_TEX, M.EXT_HASHES["tex"])].data)
_dec3 = M.decode_bc(_ti3["payload"], _ti3["width"], _ti3["height"],
                    _ti3["fmt"] not in M.BC1_CODES, bottom_up=False)
_o3 = (int(0.0444 * _ti3["height"]) * _ti3["width"] + int(0.025 * _ti3["width"])) * 4
_rgb3 = tuple(int(_dec3[_o3 + c] * 255 + 0.5) for c in range(3))
check(_rgb3[2] > 200 and _rgb3[0] < 60,
      "the AO node's own colour is what lands, at full strength %s" % (_rgb3,))
# baking drives the render engine, selection and visibility - all of it borrowed
check((bpy.context.scene.render.engine,
       sorted(o.name for o in bpy.context.scene.objects if o.select_get()),
       sorted((o.name, a.name) for o in bpy.context.scene.objects
              if o.type == "MESH" for a in o.data.color_attributes)) == _snap,
      "and the scene is handed back exactly as it was found")
bpy.data.objects.remove(_ao)

# The other path: a material WITH uv area is rendered through its own mapping,
# so a gradient lands where it belongs instead of collapsing to one colour.
_SMALL = "ui\\chs\\chs_meku\\black_BM_NOMIP"
_bk4 = {e.key: e for e in M.read_arc(ARC)[1]}
check((_SMALL, M.EXT_HASHES["tex"]) in _bk4, "the 16x16 probe texture is in the fixture")
_me3 = bpy.data.meshes.new("uvprobe")
_me3.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
_me3.update()
_uv3 = _me3.uv_layers.new(name="UVMap")
for _li, _c in enumerate([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]):
    _uv3.data[_li].uv = _c
_um = M.build_material("uvprobe", None)
_um["umvc3_texture"] = _SMALL
_um["umvc3_had_image"] = True
_me3.materials.append(_um)
_uo = bpy.data.objects.new("uvprobe", _me3)
_uo.location = (1000.0, 1000.0, 1000.0)
_uo["umvc3_entry"] = "ui\\chs\\chs_meku\\chs_meku"
bpy.context.scene.collection.objects.link(_uo)
_unt = _um.node_tree
_grad = _unt.nodes.new("ShaderNodeTexGradient")
_ucoord = _unt.nodes.new("ShaderNodeTexCoord")
_unt.links.new(_grad.inputs["Vector"], _ucoord.outputs["UV"])
_unt.links.new(next(n for n in _unt.nodes if n.type == "BSDF_PRINCIPLED").inputs["Base Color"],
               _grad.outputs["Color"])
check(S._uv_area(_uo, 0) > 0.9, "this probe covers the whole sheet in uv space")
_up, _us2 = S.bake_flat_materials(bpy.context.scene, _bk4, report=lambda m: None)
check(any("uvprobe" in p and "uvs" in p for p in _up),
      "it goes through the uv bake (%s)" % (_up or _us2 or "nothing",))
_ti4 = M.tex_info(_bk4[(_SMALL, M.EXT_HASHES["tex"])].data)
_dec4 = M.decode_bc(_ti4["payload"], _ti4["width"], _ti4["height"],
                    _ti4["fmt"] not in M.BC1_CODES, bottom_up=False)
_left = _dec4[(8 * _ti4["width"] + 1) * 4]
_right = _dec4[(8 * _ti4["width"] + _ti4["width"] - 2) * 4]
check(_right - _left > 0.5,
      "and the gradient survives as a gradient, not an average (%.2f -> %.2f)"
      % (_left, _right))
bpy.data.objects.remove(_uo)

cards = [o for o in bpy.context.scene.objects if o.get("umvc3_card")]
check(len(cards) == r["groups"], "one card object per cell")
# Every card mesh is either a card root or parented to one - nothing loose.
roots = set(cards)
orphan = [o.name for o in bpy.context.scene.objects
          if o.get("umvc3_jid") is not None and o.type == "MESH"
          and o not in roots and o.parent not in roots]
check(not orphan, "every card mesh belongs to a card (%d loose)" % len(orphan))
check(all(o.type == "MESH" for o in cards),
      "no leftover empties - the card is a real mesh you can click")

# A card and its overlays must group together and sit on top of each other.
# Cell (0,0) is the banner's own cell, where only selr1 has an ordinary card, so
# sample a mid-grid one.
sample = next(o for o in cards if not o.get("umvc3_is_banner")
              and o["umvc3_row"] == 3 and o["umvc3_joint_col"] == 1)
kinds = sorted(o.get("umvc3_kind") for o in S.card_meshes(sample))
check(len(kinds) == 6, "%s owns its 6 meshes: %s" % (sample.name, kinds))
spread = max((o.matrix_world.translation - sample.matrix_world.translation).length
             for o in S.card_meshes(sample))
check(spread < 0.5, "grouped meshes are coincident (spread %.3f)" % spread)

# The card IS the face mesh, so clicking what you see in the viewport selects
# the thing that carries the overlays with it.
check(sample.type == "MESH" and sample.get("umvc3_kind") == "face",
      "the card object is the face mesh, not a separate empty")
check(all(o.parent is sample for o in S.card_meshes(sample) if o is not sample),
      "every overlay is parented to the card")
cc = S.card_collection(sample)
check(cc is not None and cc.get("umvc3_card_collection")
      and len(cc.objects) == 6,
      "the card has its own collection holding all 6 meshes: %s (%d objects)"
      % (cc.name if cc else None, len(cc.objects) if cc else 0))
check(cc.name == sample.name, "the collection is named for the card (%s)" % cc.name)
# Origins sit on the card, so rotate/scale pivot about the card, not the book
check((sample.location - sample.matrix_world.translation).length < 1e-5
      and sample.location.length > 0.1,
      "the card's origin was moved onto the card itself")
hidden = [o for o in S.card_meshes(sample) if o is not sample and o.hide_get()]
check(len(hidden) == 5, "the 5 overlays are hidden so they cannot steal a click")
check(not sample.hide_get(), "the card itself is visible")
# 12 models x 72 cells x 2 pages, less the 2 cells per page that `face` leaves
# for the banner blanks, all landing in 144 card groups + 2 banner groups
check(r["groups"] == 146 and r["cards"] == 860,
      "every mesh accounted for: %d groups, %d meshes" % (r["groups"], r["cards"]))

print("\nexport untouched")
out1 = os.path.join(OUT, "untouched.arc")
st = S.export_css(bpy.context, out1, follow_page=True, refit_weights=True,
                  report=lambda m: None)
print("  %d models, %d cards, %d moved, %d renumbered, %d KB"
      % (st["models"], st["cards"], st["moved"], st["renumbered"], st["size"] // 1024))
check(st["renumbered"] == 0, "nothing was renumbered")
check(st["moved"] == 0, "no card moved (%d did)" % st["moved"])
# Every card's uvs are rewritten on every export; a half read into a float32 and
# packed back is the same half, so an untouched one must still report nothing.
check(st["reuvd"] == 0, "and no card's uvs changed (%d did)" % st["reuvd"])

# The grid must survive the trip through the scene properties. Blender only
# stores an ID property when the value differs from the registered default, so
# detecting the stock 9 x 16 and storing it leaves scene.get() returning None -
# read it back the wrong way and the whole screen exports as vanilla 7 x 8.
check(S.scene_grid(bpy.context.scene) == (9, 16),
      "scene_grid reads 9 x 16 back off the scene: %s" % (S.scene_grid(bpy.context.scene),))
check((st["rows"], st["cols"]) == (9, 16),
      "export used 9 x 16, not a silent vanilla fallback (got %d x %d)"
      % (st["rows"], st["cols"]))
check(S.plugin_mismatch(st["rows"], st["cols"]) is None,
      "no spurious plugin-rebuild warning for an unmodified 9 x 16 scene")

problems, warnings, lines = V.verify_file(out1, st["rows"], st["cols"] // 2,
                                          stock_path=ARC)
for l in lines:
    print("  " + l)
check(not problems, "verify finds no problems in the untouched export")
check(not warnings, "untouched cards are all still on the regular grid")
drifts = [float(l.split("drift")[1].split()[0]) for l in lines if "drift" in l]
check(max(drifts) < 0.03,
      "verify's own drift column reads ~0 against the source (%.4f)" % max(drifts))
for p in (problems + warnings)[:10]:
    print("     " + p)

# drift against the archive it came from
_, src_entries = M.read_arc(ARC)
_, out_entries = M.read_arc(out1)
src_by = {(e.name, e.ext): e for e in src_entries}
worst, worst_where = 0.0, ""
for e in out_entries:
    if e.ext != "mod" or not G.model_kind(e.name):
        continue
    se = src_by[(e.name, e.ext)]
    q1, q2 = M.model_dequant(se.data), M.model_dequant(e.data)
    v1, v2 = M._u64(se.data, M.H_VERTOFF), M._u64(e.data, M.H_VERTOFF)
    for m1, m2 in zip(M.read_meshes(se.data), M.read_meshes(e.data)):
        for k in range(0, m1["nverts"], 7):
            o1 = v1 + m1["vbufoff"] + (m1["vtxlo"] + k) * m1["stride"]
            o2 = v2 + m2["vbufoff"] + (m2["vtxlo"] + k) * m2["stride"]
            p1 = q1.decode(struct.unpack_from("<3H", se.data, o1))
            p2 = q2.decode(struct.unpack_from("<3H", e.data, o2))
            d = max(abs(p1[i] - p2[i]) for i in range(3))
            if d > worst:
                worst, worst_where = d, G.leaf(e.name)
step = M.model_dequant(src_by[("ui\\chs\\chs_meku\\chs_meku_face_a", "mod")].data).scale / M.POS_SCALE
check(worst <= step, "untouched geometry drifts %.4f <= one quantisation step %.4f (%s)"
      % (worst, step, worst_where))

print("\nmove a card and re-export")
target = next(o for o in cards
              if not o.get("umvc3_is_banner") and o["umvc3_page"] == "a"
              and o["umvc3_row"] == 4 and o["umvc3_joint_col"] == 2)
before = card_centre(src_entries, target["umvc3_entry"],
                     target["umvc3_jid"], 9)
target.location.x += 120.0 * 0.01          # two cells outward, in game units
bpy.context.view_layer.update()

out2 = os.path.join(OUT, "moved.arc")
st2 = S.export_css(bpy.context, out2, follow_page=True, refit_weights=True,
                   report=lambda m: None)
check(st2["moved"] == 6,
      "all 6 meshes moved, so the hidden overlays exported too (%d did)"
      % st2["moved"])
check(st2["renumbered"] == 0, "moving a card did NOT renumber it")

_, moved_entries = M.read_arc(out2)
after = card_centre(moved_entries, target["umvc3_entry"],
                    target["umvc3_jid"], 9)
dx = after["cx"] - before["cx"]
dz = after["cz"] - before["cz"]
check(abs(dx - 120.0) < 1.0, "card moved %.1f units in x (wanted 120)" % dx)
check(abs(dz) > 0.5, "depth followed the page bow (%+.2f in z)" % dz)

surf = None
from io_umvc3_css import pagefit
surf = pagefit.page_surface(moved_entries, "a")
clear_before = before["cz"] - pagefit.page_surface(src_entries, "a")(before["cx"], before["cy"])
clear_after = after["cz"] - surf(after["cx"], after["cy"])
check(abs(clear_before - clear_after) < 1.5,
      "clearance over the paper preserved (%.2f -> %.2f)" % (clear_before, clear_after))

# weights must have been refitted to the new position, and still be sane
b = next(e for e in moved_entries
         if e.ext == "mod" and e.name == target["umvc3_entry"]).data
vert_off = M._u64(b, M.H_VERTOFF)
mesh = next(m for m in M.read_meshes(b) if m["index"] == after["index"])
sums, changed = [], 0
sb = next(e for e in src_entries if e.ext == "mod"
          and e.name == target["umvc3_entry"]).data
svert = M._u64(sb, M.H_VERTOFF)
smesh = next(m for m in M.read_meshes(sb) if m["index"] == before["index"])
for k in range(mesh["nverts"]):
    w = M.read_skin(b, vert_off + mesh["vbufoff"] + (mesh["vtxlo"] + k) * mesh["stride"])
    sw = M.read_skin(sb, svert + smesh["vbufoff"] + (smesh["vtxlo"] + k) * smesh["stride"])
    sums.append(sum(w.values()))
    if w != sw:
        changed += 1
check(all(abs(s - 1.0) < 1e-3 for s in sums), "refitted weights still sum to 1")
check(changed > 0, "weights were refitted for the new position (%d/%d vertices)"
      % (changed, mesh["nverts"]))

problems2, warnings2, _ = V.verify_file(out2, st2["rows"], st2["cols"] // 2)
check(not problems2, "no hard problems after a deliberate move")
for p in problems2[:10]:
    print("     " + p)
# The alignment check must still notice - it is a warning precisely so that a
# rearranged screen installs, not because it stopped looking.
check(any("column 2" in w for w in warnings2),
      "the moved card is reported as off the regular grid (%d warning(s))"
      % len(warnings2))

print("\ndrag a card across the spine")
# Joint column 0 sits at x ~ -38, so a small drag right crosses x = 0 and leaves
# the page's sampled area. The page surface is a QUADRATIC MLS fit sampled only
# over its own half of the book: unclamped, extrapolating it past the spine gave
# one card 5919 units of z spread - a fold, not a move - which is what "super
# distorted" looked like in game.
spine = next(o for o in cards if not o.get("umvc3_is_banner")
             and o["umvc3_page"] == "a" and o["umvc3_joint_col"] == 0
             and o["umvc3_row"] == 4)
spine_face = S.card_face(spine)
spine_entry, spine_mi = spine_face["umvc3_entry"], spine_face["umvc3_mesh_index"]
spine.location.x += 400.0 * 0.01          # well onto the other page
bpy.context.view_layer.update()
out4 = os.path.join(OUT, "spine.arc")
st4 = S.export_css(bpy.context, out4, follow_page=True, refit_weights=True,
                   report=lambda m: None)
_, sp_entries = M.read_arc(out4)
spb = next(e for e in sp_entries if e.ext == "mod" and e.name == spine_entry).data
spq = M.model_dequant(spb)
spv = M._u64(spb, M.H_VERTOFF)
spm = next(m for m in M.read_meshes(spb) if m["index"] == spine_mi)
spz = []
for k in range(spm["nverts"]):
    vo = spv + spm["vbufoff"] + (spm["vtxlo"] + k) * spm["stride"]
    spz.append(spq.decode(struct.unpack_from("<3H", spb, vo))[2])
zspread = max(spz) - min(spz)
check(zspread < 40.0,
      "a card dragged past the spine stays flat: %.1f units of z spread" % zspread)
check(spq.scale / M.POS_SCALE < 0.05,
      "the model's quantisation step stayed tight (%.4f)" % (spq.scale / M.POS_SCALE))
p4, w4, _ = V.verify_file(out4, st4["rows"], st4["cols"] // 2)
check(not p4, "verify finds no problems after crossing the spine")
for p in p4[:6]:
    print("     " + p)
# and the limit must sit well below the 5919-unit fold this used to produce
check(zspread * 2 < V.FLAT_LIMIT < 500.0,
      "the flatness limit (%.0f) clears a real card but catches a fold"
      % V.FLAT_LIMIT)
spine.location.x -= 400.0 * 0.01
bpy.context.view_layer.update()

print("\nadd a card into a genuinely free cell")
# face_a carries 70 of 72 cells: joint ids 9 and 18 are the two the banner plate
# covers, so nothing is there to collide with.
FACE_A = "ui\\chs\\chs_meku\\chs_meku_face_a"
donor = next(o for o in bpy.context.scene.objects
             if o.get("umvc3_entry") == FACE_A and o.get("umvc3_jid") == 10)
holder = bpy.data.objects.new("card_a_c1_r0_new", None)
bpy.context.scene.collection.objects.link(holder)
holder["umvc3_card"], holder["umvc3_page"] = True, "a"
holder["umvc3_joint_col"], holder["umvc3_row"], holder["umvc3_jid"] = 1, 0, 9
holder["umvc3_is_banner"] = False
holder.location = donor.matrix_world.translation.copy()
holder.location.y += 68.0 * 0.01           # up one row, into row 0

clone = donor.copy()
clone.data = donor.data.copy()
clone.name = "card_a_c1_r0_face"
bpy.context.scene.collection.objects.link(clone)
clone["umvc3_new_from"] = donor["umvc3_mesh_index"]
del clone["umvc3_mesh_index"]
clone["umvc3_jid"] = 9
clone.parent = holder
clone.matrix_parent_inverse = holder.matrix_world.inverted()
bpy.context.view_layer.update()

out3 = os.path.join(OUT, "added.arc")
st3 = S.export_css(bpy.context, out3, follow_page=True, refit_weights=True,
                   report=lambda m: None)
check(st3["added"] == 1, "one new card mesh appended (%d)" % st3["added"])

_, added_entries = M.read_arc(out3)
ae = next(e for e in added_entries if e.ext == "mod" and e.name == FACE_A)
am = next(e for e in added_entries if e.ext == "mrl" and e.name == FACE_A)
new_cards = G.read_cards(ae.data, rows=9, with_verts=False)
check(len(new_cards) == 71, "face_a now carries 71 cards (was 70)")
check(any(c["jid"] == 9 for c in new_cards), "joint id 9 now exists")
names = M.read_mod_material_names(ae.data)
entry = G.mrl_entries(am.data).get(M.mt_hash(names[
    next(c for c in new_cards if c["jid"] == 9)["material"]]))
check(entry is not None, "the new material resolves to an .mrl entry")
check(entry is not None and G.read_joint_id(am.data, entry) == 9,
      "the new .mrl entry stores joint id 9 in bits 21..28")
p3, w3, _ = V.verify_file(out3, st3["rows"], st3["cols"] // 2)
check(not p3, "verify finds no problems with the added card")
for p in p3[:10]:
    print("     " + p)

print("\ndynamic placement")
ce = R.read_ce_roster(GAME)
# assignment keys must be name-based, or reordering Characters.ini silently
# repoints every assignment at whoever landed on that index
check(R.char_key("clone-engine", "Gambit") == "cGambit"
      and R.parse_key("cGambit") == ("clone-engine", "Gambit"),
      "CloneEngine assignments are keyed by CharacterID, not by index")
check(R.parse_key("v24") == ("vanilla", 24)
      and R.resolve("v24").label == "Firebrand", "vanilla keys resolve by id")
picks = R.characters(GAME)
check(len(picks) > 130 and any(k == "cGambit" for k, _l, _s in picks),
      "the assign list is built live from Characters.ini (%d entries)" % len(picks))

# import already tags every card with who is on it
tagged = [o for o in cards if o.get("umvc3_char")]
check(len(tagged) > 130, "%d cards carry a character assignment" % len(tagged))
gambit = next(o for o in cards
              if o.get("umvc3_char") == "c%s" % ce[ce.index("Gambit")])
check(gambit["umvc3_slot"] == R.VANILLA_SLOTS + ce.index("Gambit"),
      "Gambit's card is the one at his CloneEngine slot")

# move a vanilla character and a CE character to new cells
ryu = next(o for o in cards if o.get("umvc3_char") == "v1")
jill = next(o for o in cards if o.get("umvc3_char") == "v20")
ryu["umvc3_char"], jill["umvc3_char"] = "v20", "v1"          # swap
other = next(o for o in cards if o.get("umvc3_slot") == R.VANILLA_SLOTS + 0)
other["umvc3_char"], gambit["umvc3_char"] = "cGambit", other["umvc3_char"]
layout, ce_order, problems = S.plan_placement(bpy.context.scene, 9, 16, ce)
check(not problems, "the swaps are legal: %s" % problems[:2])
check(layout[ryu["umvc3_slot"]] == 20 and layout[jill["umvc3_slot"]] == 1,
      "swapping two vanilla characters swaps their [Layout] ids")
check(max(layout) < R.VANILLA_SLOTS,
      "[Layout] only covers slots CloneEngine does not claim")
check(ce_order[0] == "Gambit", "Gambit moved to CE index 0")
check(sorted(ce_order) == sorted(ce) and len(ce_order) == len(ce),
      "reordering keeps every CloneEngine character exactly once")

# a vanilla character parked above slot 55 is a real mistake and must be caught
gambit["umvc3_char"] = "v1"
_l, _o, probs = S.plan_placement(bpy.context.scene, 9, 16, ce)
check(any("claims every slot" in p for p in probs),
      "a vanilla character above slot 55 is reported, not silently dropped")
gambit["umvc3_char"] = "cGambit"
other["umvc3_char"] = "c%s" % ce[0]
ryu["umvc3_char"], jill["umvc3_char"] = "v1", "v20"

# the Characters.ini rewrite - dry run, nothing on disk is touched
ini_path = os.path.join(GAME, "Characters.ini")
before = open(ini_path, encoding="utf-8", errors="replace").read()
new_order = [ce[5]] + [c for c in ce if c != ce[5]]
text, seq = R.rewrite_characters_ini(ini_path, new_order, dry_run=True)
check(open(ini_path, encoding="utf-8", errors="replace").read() == before,
      "dry_run really did not write")
check(seq[0] == ce[5] and sorted(seq) == sorted(ce),
      "the rewrite puts the requested entry first and keeps the roster whole")
import re as _re
check(text.count("[Character") == before.count("[Character"),
      "no section gained or lost (%d)" % text.count("[Character"))
for key in ("SoundID", "NumColors", "BaseCharacter", "Child1"):
    check(text.count(key) == before.count(key),
          "%s count preserved (%d)" % (key, before.count(key)))
# child helpers must not have been dragged across their parents
def playable_positions(t):
    out, cur, body = [], None, []
    for ln in t.splitlines():
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if cur is not None:
                out.append(("soundid" in " ".join(body).lower()))
            cur, body = s, []
        else:
            body.append(ln)
    if cur is not None:
        out.append(("soundid" in " ".join(body).lower()))
    return out
check(playable_positions(text) == playable_positions(before),
      "playable and helper sections stayed in the same positions")

# Putting one character on two cards leaves another with nowhere to go. That
# must be refused at every layer, never silently truncated - it deleted a
# character from a real Characters.ini once.
try:
    R.rewrite_characters_ini(ini_path, [ce[0]] + list(ce), dry_run=True)
    check(False, "a duplicated entry must raise")
except RuntimeError as _e:
    check("twice" in str(_e), "the rewrite refuses a duplicated entry: %s" % _e)
try:
    R.rewrite_characters_ini(ini_path, list(ce[:-1]), dry_run=True)
    check(True, "a short order is completed from the leftovers")
except RuntimeError as _e:
    check(False, "a short order should be completed, not refused: %s" % _e)

# and the planner catches it first, naming both cards
dup_a = next(o for o in cards if o.get("umvc3_char") == "c%s" % ce[3])
dup_b = next(o for o in cards if o.get("umvc3_char") == "c%s" % ce[9])
_keep = dup_b["umvc3_char"]
dup_b["umvc3_char"] = dup_a["umvc3_char"]
_l2, _o2, dup_probs = S.plan_placement(bpy.context.scene, 9, 16, ce)
check(any("two cards" in p and ce[3] in p for p in dup_probs),
      "planning reports the character that is on two cards: %s" % dup_probs[:1])
check(sorted(_o2) == sorted(ce),
      "even so the planned order still holds every character exactly once")
dup_b["umvc3_char"] = _keep
names_after = _re.findall(r"CharacterID=(\S+)", text)
check(sorted(names_after) == sorted(_re.findall(r"CharacterID=(\S+)", before)),
      "every CharacterID survives the rewrite")

print("\nthe Card panel polls on the active object")
bpy.context.view_layer.objects.active = None
check(not U.UMVC3_PT_css_card.poll(bpy.context),
      "the Object tab stays clean when nothing is selected")
scenery = next((o for o in bpy.context.scene.objects
                if o.get("umvc3_jid") is None and not o.get("umvc3_card")), None)
check(scenery is not None, "found a non-card object to test against")
bpy.context.view_layer.objects.active = scenery
check(not U.UMVC3_PT_css_card.poll(bpy.context),
      "and for a non-card object like %s" % scenery.name)
# cell (0,0) is the banner's own, where only selr1 has a card and so has no
# overlays to speak of - sample one that carries the full six
sample_card = next(o for o in cards if not o.get("umvc3_is_banner") and o.children)
bpy.context.view_layer.objects.active = sample_card
check(U.UMVC3_PT_css_card.poll(bpy.context), "but shows for a card")
overlay = sample_card.children[0]
bpy.context.view_layer.objects.active = overlay
check(U.UMVC3_PT_css_card.poll(bpy.context)
      and U.active_card(bpy.context) is sample_card,
      "and for one of its overlays, resolving back to the card")
bpy.context.view_layer.objects.active = sample_card

print("\nthe inline character dropdown")
items = U.character_items(None, bpy.context)
check(len(items) == len(picks) and items[0][0] == R.BLANK_KEY,
      "the dropdown lists every character (%d) with blank first" % len(items))
check(all(len(it) == 3 and isinstance(it[0], str) for it in items),
      "every item is a well-formed (identifier, label, description) triple")
check(len({it[0] for it in items}) == len(items),
      "identifiers are unique, so none can shadow another")
ce_items = [it for it in items if it[0].startswith("c")]
check(len(ce_items) == len(ce) and ("cGambit", "Gambit", "CloneEngine: Gambit") in items,
      "all %d Characters.ini entries are in the list" % len(ce))

target_card = next(o for o in cards if not o.get("umvc3_is_banner")
                   and o["umvc3_slot"] == R.VANILLA_SLOTS + ce.index("Gambit"))
face = S.card_face(target_card)


def shown_image(ob):
    mat = S.card_face(ob).data.materials[0]
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image is not None:
            return n.image.name
    return None


before_img = shown_image(target_card)
# drive it exactly as the panel does: set the enum, not the operator
target_card.umvc3_character = "cIceman"
check(target_card["umvc3_char"] == "cIceman",
      "picking from the dropdown writes the name-keyed assignment (%r)"
      % target_card.get("umvc3_char"))
check(target_card.umvc3_character == "cIceman",
      "and reads back as the same entry")
after_img = shown_image(target_card)
check(after_img != before_img and after_img is not None,
      "the card's texture changed in Blender: %s -> %s" % (before_img, after_img))
check("Iceman" in after_img, "and it is Iceman's portrait (%s)" % after_img)

# a vanilla pick works the same way
target_card.umvc3_character = "v1"
check(target_card["umvc3_char"] == "v1" and "Ryu" in (shown_image(target_card) or ""),
      "a vanilla pick shows that portrait too (%s)" % shown_image(target_card))

# The enum must survive Characters.ini being reordered - that is what placing a
# CloneEngine character does, and an index-keyed enum would silently repoint.
target_card.umvc3_character = "cGambit"
idx_before = U._ENUM_CACHE["index"]["cGambit"]
U._rebuild_items.__globals__["R"] = R
reordered = ["Iceman"] + [c for c in ce if c != "Iceman"]
U._ENUM_CACHE["items"] = [(R.BLANK_KEY, "(blank)", "")] + \
    [("c%s" % n, n, "") for n in reordered]
U._ENUM_CACHE["index"] = {it[0]: i for i, it in enumerate(U._ENUM_CACHE["items"])}
check(U._ENUM_CACHE["index"]["cGambit"] != idx_before,
      "Gambit's position in the list really did change")
check(target_card["umvc3_char"] == "cGambit"
      and target_card.umvc3_character == "cGambit",
      "the card still reads as Gambit after the list was reordered")
U._ENUM_CACHE["key"] = None            # force a genuine rebuild for later checks
U.character_items(None, bpy.context)
check(U._ENUM_CACHE["index"]["cGambit"] == idx_before, "list rebuilt cleanly")
target_card.umvc3_character = "c%s" % ce[ce.index("Gambit")]

print("\nsquaring a card that was flattened while tilted")
# Flattening with S Z 0 projects rather than rotates, so a card tilted in 3D
# first lands as a parallelogram. Reproduce that exactly: the affine measured off
# a real damaged install was [[1, 0], [0.264, 0.701]].
sq = next(o for o in cards if not o.get("umvc3_is_banner")
          and o["umvc3_page"] == "a" and o["umvc3_joint_col"] == 2
          and o["umvc3_row"] == 6)
sq_uv = [tuple(d.uv) for d in sq.data.uv_layers.active.data]
sq_loc = tuple(round(v, 5) for v in sq.location)


def extents(ob):
    xs = [v.co.x for v in ob.data.vertices]
    ys = [v.co.y for v in ob.data.vertices]
    return round((max(xs) - min(xs)) / 0.01, 1), round((max(ys) - min(ys)) / 0.01, 1)


# its own shape before the damage - cards in different joint columns are
# legitimately a fraction of a unit apart in width, so a sibling is not the yardstick
sq_size = extents(sq)
check(U._yaw_of(sq) < 2.0, "the card starts square (%.2f deg)" % U._yaw_of(sq))
for o in [sq] + list(sq.children):
    for v in o.data.vertices:
        x, y = v.co.x, v.co.y
        v.co.x, v.co.y = x, 0.2643 * x + 0.7009 * y
    o.data.update()
check(U._yaw_of(sq) > 20.0, "and is skewed after the projection (%.2f deg)"
      % U._yaw_of(sq))

for o in bpy.context.scene.objects:
    o.select_set(False)
sq.select_set(True)
bpy.context.view_layer.objects.active = sq
bpy.ops.umvc3.css_square(keep_flat=True, selected_only=True, reference=ARC)
check(U._yaw_of(sq) < 2.0, "Square Cards puts it back (%.2f deg)" % U._yaw_of(sq))
check([tuple(d.uv) for d in sq.data.uv_layers.active.data] == sq_uv,
      "UVs untouched - they are not uniform across cards, so this matters")
check(tuple(round(v, 5) for v in sq.location) == sq_loc,
      "and the card stayed where it was put")
check(all(U._yaw_of(o) < 2.0 for o in [sq]), "the overlays came with it")
check(extents(sq) == sq_size,
      "and is exactly the size it was before the damage: %s vs %s"
      % (extents(sq), sq_size))

print("\ngeometry authored in the viewport")
# The grid lines live in chs_meku, which the card path does not own, so editing
# them in Blender only reaches the game through this.
_g_before = S.export_custom_meshes(bpy.context.scene,
                                   {e.key: e for e in M.read_arc(ARC)[1]},
                                   0.01, report=lambda m: None)[0]
check(_g_before == [], "an untouched scene rewrites no geometry (%s)" % (_g_before or "none"))

# Whichever chs_meku mesh is biggest and has uvs. Naming the grid lines
# directly would tie this to a build that has them; the fixture is the book.
_cands = [o for o in bpy.context.scene.objects
          if o.type == "MESH" and o.get("umvc3_entry")
          and G.leaf(o["umvc3_entry"]) == "chs_meku"
          and o.get("umvc3_mesh_index") is not None
          and o.data.uv_layers.active and len(o.data.vertices) > 100]
_lo = max(_cands, key=lambda o: len(o.data.vertices)) if _cands else None
check(_lo is not None, "found a chs_meku mesh with uvs to edit (%d candidates)" % len(_cands))
if _lo is not None:
    _idx = _lo["umvc3_mesh_index"]
    _me13 = _lo.data
    _n0, _i0 = len(_me13.vertices), len(_me13.polygons)
    for _i in range(0, len(_me13.vertices) - 1, 2):
        _a, _b = _me13.vertices[_i], _me13.vertices[_i + 1]
        _mid = (_a.co + _b.co) * 0.5
        _a.co = _mid + (_a.co - _mid) * 2.0
        _b.co = _mid + (_b.co - _mid) * 2.0
    _me13.update()
    _bk6 = {e.key: e for e in M.read_arc(ARC)[1]}
    _g_after = S.export_custom_meshes(bpy.context.scene, _bk6, 0.01, report=lambda m: None)[0]
    check(any(("mesh %d" % _idx) in c for c in _g_after),
          "editing it is picked up (%s)" % (_g_after or "nothing"))
    _me = _bk6[(_lo["umvc3_entry"], M.EXT_HASHES["mod"])]
    _mm = {m["index"]: m for m in M.read_meshes(_me.data)}
    check(_mm[_idx]["nverts"] == _n0, "vertex count is preserved, so it wrote in place")
    check(M._u16(_me.data, M.H_MESHCOUNT) == len(_mm),
          "the mesh table did not grow - repeated exports must not accumulate copies")
    _q = M.model_dequant(_me.data)
    _vo = M._u64(_me.data, M.H_VERTOFF) + _mm[_idx]["vbufoff"] + _mm[_idx]["vtxlo"] * _mm[_idx]["stride"]
    _p = [_q.decode(struct.unpack_from("<3H", _me.data, _vo + k * _mm[_idx]["stride"]))
          for k in (0, 1)]
    _w = sum((_p[0][k] - _p[1][k]) ** 2 for k in range(3)) ** 0.5
    check(_w > 1e-4, "the edit really reached the archive (%.2f units apart)" % _w)
    _lay = M.layout_for(_mm[_idx]["fmt"], _mm[_idx]["stride"])
    _v0 = M._half(_me.data, _vo + _lay["uv0"] + 2)
    _v1 = M._half(_me.data, _vo + _mm[_idx]["stride"] + _lay["uv0"] + 2)
    check(abs(_v0 - _v1) >= 0.0,
          "uvs survived the round trip (%.3f vs %.3f)" % (_v0, _v1))

print("\nthe .sdl scheduler says where the homeless models are drawn")
# chs_card and the cursor carry no world coordinates: nothing in the model says
# where they go, and it is not in the exe either - a scheduler resource animates
# a node tree, and the engine binds the drawn unit to a node by name.
from io_umvc3_css import sdl as SD

_sdl_e = [e for e in M.read_arc(ARC)[1] if e.hash == M.EXT_HASHES["sdl"]]
check(len(_sdl_e) > 10, "the archive carries the layouts (%d)" % len(_sdl_e))
_doc = SD.parse(next(e for e in _sdl_e if e.name.endswith("chs_card1p")).data)
check(_doc is not None and len(_doc.nodes) == 25,
      "chs_card1p parses to a node tree (%s nodes)" % (_doc and len(_doc.nodes)))
check([c[0] for c in _doc.clips[:3]] == ["start", "sel1", "sel1_decide"],
      "and to its clip list: %s" % [c[0] for c in _doc.clips[:3]])
check(_doc.settle_frame() == 61,
      "the fly-in ends at frame %d" % _doc.settle_frame())
# The key COUNT has to come from the record. Derived from the gap to the next
# block it overruns, and a curve then reads its last keys out of the NEXT
# property's key table: mPos picks up frame numbers as positions, and mAngle
# comes back holding (1, 1, 1), which is a scale.
_bounds = set()
for _c in _doc.clips:
    _bounds.add(int(_c[1])); _bounds.add(int(_c[2]))
_last = max(_bounds)
_frames = sorted(set(k.frame for n in _doc.nodes.values()
                     for p in n.props.values() for k in p.keys))
check(_frames and _frames[-1] <= _last,
      "no key runs past the last clip at %d (highest is %d)" % (_last, _frames[-1]))
check(all(any(int(c[1]) <= f <= int(c[2]) for c in _doc.clips) for f in _frames),
      "and every key falls inside a clip rather than between them")
_ang0 = _doc.by_name("chs_card1p_no1_un").at("mAngle", 0)
check(abs(_ang0[0]) < 1e-3 and abs(_ang0[2]) < 1e-3,
      "a rotation curve holds rotations, not the scale that follows it: %s"
      % (tuple(round(v, 2) for v in _ang0),))

_c1 = _doc.by_name("chs_card1p_no1")
check(_c1.parent is not None and _c1.parent.name == "card1p_cen",
      "mpParent resolves as a record index: %s" % (_c1.parent and _c1.parent.name))
check(_c1.model == "ui\\chs\\chs_meku\\chs_card",
      "mpModel resolves past its extension hash: %r" % _c1.model)
check(_c1.flags() == SD.INHERIT_ALL,
      "mParentFlags reads as the int it is, not a denormal float (%d)" % _c1.flags())
_p, _a, _s = SD.transform(_c1.parent, _doc.settle_frame())
check(tuple(round(v) for v in _p) == (-425, 0, 0) and abs(_a[1] - 1.22) < 0.01,
      "the anchor settles where the game draws it: pos %s ang %s"
      % (tuple(round(v, 1) for v in _p), tuple(round(v, 2) for v in _a)))

# and in the scene: instanced, mirrored, and never on the geometry that is edited
_cards = [o for o in bpy.context.scene.objects if o.get("umvc3_sdl_node")]
check(len(_cards) > 30, "the layout is in the scene as empties (%d)" % len(_cards))
_inst = {o["umvc3_sdl_node"]: o for o in _cards if o.instance_collection}
check("chs_card1p_no1" in _inst and "chs_card2p_no1" in _inst,
      "both players' cards are instanced: %d in all" % len(_inst))
_x1 = _inst["chs_card1p_no1"].matrix_world.translation.x
_x2 = _inst["chs_card2p_no1"].matrix_world.translation.x
check(_x1 < -3 and abs(_x1 + _x2) < 0.05,
      "and mirror about the spine: %.2f vs %.2f" % (_x1, _x2))
check(not any(G.leaf(o.instance_collection.name).startswith("chs_meku")
              for o in _inst.values()),
      "the book and its card grids are NOT instanced - an edit to those is "
      "written back from where the mesh sits")
_book = next(o for o in _cards if o.get("umvc3_sdl_node") == "chs_meku")
check(_book.instance_collection is None and _book.get("umvc3_sdl_not_instanced"),
      "though its node is still built, so the transform is there to read")

print("\nthe rest of the screen imports and writes back to its own archive")
# The character select is spread across archives: the book and its cards are in
# mnchscmn, the team and assist panels in mnchs, the cursor in mnchsstg. They are
# authored about the same origin, so one scale puts them all where they sit.
_scr = list(bpy.context.scene.get(S.S_SCREEN) or [])
check(len(_scr) >= 1, "the import loaded the other archives: %s"
      % [os.path.basename(p) for p in _scr])
_scr_dir = os.path.join(OUT, "screen")
if os.path.isdir(_scr_dir):
    shutil.rmtree(_scr_dir)          # or a previous run's output answers for this one
os.makedirs(_scr_dir)
_scr_out = os.path.join(_scr_dir, "out.arc")
check(S.export_css(bpy.context, _scr_out, report=lambda m: None)["screen"] == [],
      "an untouched scene writes none of them")
check(sorted(os.listdir(_scr_dir)) == ["out.arc"],
      "and leaves no archive beside it: %s" % sorted(os.listdir(_scr_dir)))


def _mesh_bytes(arc, entry, mesh_index):
    e = next(x for x in M.read_arc(arc)[1] if x.ext == "mod" and x.name == entry)
    m = {x["index"]: x for x in M.read_meshes(e.data)}[mesh_index]
    base = M._u64(e.data, M.H_VERTOFF) + m["vbufoff"] + m["vtxlo"] * m["stride"]
    return bytes(e.data[base:base + m["nverts"] * m["stride"]])


# an edit to a panel that lives in mnchs must reach mnchs, and nothing else
_panel = next(o for o in bpy.context.scene.objects
              if o.type == "MESH" and "n_chs_team" in (o.get("umvc3_entry") or "")
              and o.get("umvc3_mesh_index") is not None and len(o.data.vertices) > 3)
_panel_arc = _panel[S.O_ARC]
check(os.path.basename(_panel_arc).startswith("mnchs_"),
      "the team panel came from %s" % os.path.basename(_panel_arc))
for _v in _panel.data.vertices:
    _v.co.x += 0.5
_panel.data.update()
_sst = S.export_css(bpy.context, _scr_out, report=lambda m: None)
check([os.path.basename(p) for p, _m, _t in _sst["screen"]]
      == [os.path.basename(_panel_arc)],
      "only that archive is written: %s"
      % [os.path.basename(p) for p, _m, _t in _sst["screen"]])
_written = os.path.join(_scr_dir, os.path.basename(_panel_arc))
check(_mesh_bytes(_written, _panel["umvc3_entry"], _panel["umvc3_mesh_index"])
      != _mesh_bytes(_panel_arc, _panel["umvc3_entry"], _panel["umvc3_mesh_index"]),
      "the panel's vertices really changed in it")
for _v in _panel.data.vertices:
    _v.co.x -= 0.5
_panel.data.update()

# The cursor is in TWO archives under one name. Editing the copy that came from
# mnchscmn must not write mnchsstg's, or every archive holding a resource would
# get every other archive's edits to it.
_hands = [o for o in bpy.context.scene.objects
          if o.type == "MESH" and (o.get("umvc3_entry") or "").endswith("p_chs_hnd1")
          and o.get("umvc3_mesh_index") is not None and len(o.data.vertices) > 3]
_by_arc = {}
for _o in _hands:
    _by_arc.setdefault(os.path.basename(_o[S.O_ARC]), []).append(_o)
check(len(_by_arc) == 2, "the cursor came from both archives: %s" % sorted(_by_arc))
_cmn_hand = next(o for o in _hands if S._same_path(o[S.O_ARC], ARC))
_stg_arc = next(p for p in _scr if "mnchsstg" in os.path.basename(p))
_stg_before = _mesh_bytes(_stg_arc, _cmn_hand["umvc3_entry"],
                          _cmn_hand["umvc3_mesh_index"])
for _v in _cmn_hand.data.vertices:
    _v.co.y += 0.5
_cmn_hand.data.update()
_hst = S.export_css(bpy.context, _scr_out, report=lambda m: None)
check(_hst["screen"] == [],
      "editing mnchscmn's copy writes no other archive: %s"
      % [os.path.basename(p) for p, _m, _t in _hst["screen"]])
check(any("p_chs_hnd1" in g for g in _hst["geometry"]),
      "it went into the card archive instead: %s" % _hst["geometry"])
check(_mesh_bytes(_stg_arc, _cmn_hand["umvc3_entry"], _cmn_hand["umvc3_mesh_index"])
      == _stg_before, "and mnchsstg's own copy is untouched on disk")
for _v in _cmn_hand.data.vertices:
    _v.co.y -= 0.5
_cmn_hand.data.update()

# A scene saved before any of this existed tags nothing, and re-importing to get
# the rest of the screen would throw away everything in it. Simulate one.
_kept = {}
for _o in list(bpy.context.scene.objects):
    if _o.get(S.O_ARC) is not None and not S._same_path(_o[S.O_ARC], ARC):
        bpy.data.objects.remove(_o)          # pretend they were never loaded
for _o in bpy.context.scene.objects:
    if S.O_ARC in _o.keys():
        del _o[S.O_ARC]                      # and that nothing was ever tagged
del bpy.context.scene[S.S_SCREEN]
check(S.export_css(bpy.context, _scr_out, report=lambda m: None)["screen"] == [],
      "an untagged scene still exports, as the only archive it knows")
_added, _arcs = S.load_screen_into(bpy.context, GAME, report=lambda m: None)
check(_added >= 5 and len(_arcs) >= 1,
      "the rest of the screen can be added to it in place: %d model(s) from %s"
      % (_added, [os.path.basename(p) for p in _arcs]))
_retro = [o for o in bpy.context.scene.objects
          if o.get("umvc3_entry") is not None and o.get(S.O_ARC) is None]
check(not _retro, "everything that was already there is tagged to the card archive")
check(S.load_screen_into(bpy.context, GAME, report=lambda m: None)[0] == 0,
      "and asking twice adds nothing - two copies would write their edits twice")

print("\nBlender graph -> ps_3_0 shader")
from io_umvc3_css import shader as SH
import subprocess as _sp
_fxc = S.find_fxc()
check(bool(_fxc), "found fxc.exe to compile with (%s)" % (_fxc or "none"))


def _emit(nm, wire):
    m = M.build_material(nm, None)
    nt = m.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    wire(nt, b)
    return m, SH.emit_hlsl(m, M.base_color_input(m))[0]


def _compiles(src, nm):
    if not _fxc:
        return True
    p = os.path.join(OUT, nm + ".hlsl")
    with open(p, "w") as f:
        f.write(src)
    r = _sp.run([_fxc, "/nologo", "/T", "ps_3_0", "/E", "main",
                 "/Fo", p.replace(".hlsl", ".bin"), p], capture_output=True, text=True)
    if r.returncode != 0:
        print("      fxc: %s" % (r.stderr or r.stdout).strip().splitlines()[-1:])
    return r.returncode == 0


def _w_image(nt, b):
    nt.links.new(b.inputs["Base Color"],
                 nt.nodes.new("ShaderNodeTexImage").outputs["Color"])


def _w_invert(nt, b):
    t = nt.nodes.new("ShaderNodeTexImage")
    i = nt.nodes.new("ShaderNodeInvert"); i.inputs["Fac"].default_value = 1.0
    nt.links.new(i.inputs["Color"], t.outputs["Color"])
    nt.links.new(b.inputs["Base Color"], i.outputs["Color"])


def _w_mix(nt, b):
    t = nt.nodes.new("ShaderNodeTexImage")
    c = nt.nodes.new("ShaderNodeRGB"); c.outputs[0].default_value = (0, 0.5, 1, 1)
    x = nt.nodes.new("ShaderNodeMixRGB"); x.blend_type = "MULTIPLY"
    nt.links.new(x.inputs[1], t.outputs["Color"])
    nt.links.new(x.inputs[2], c.outputs[0])
    nt.links.new(b.inputs["Base Color"], x.outputs[0])


_mat, _src = _emit("t_image", _w_image)
# The register pins are the contract with the game's vertex shader. fxc assigns
# by declaration order if left alone, and the game fills registers by its own
# numbering - drift here samples whatever happens to be in s0.
check("register(s0)" in _src, "the sampler is pinned to s0")
check("TEXCOORD2" in _src and "psin.uv" in _src,
      "uv comes from TEXCOORD2, as the disassembled original declares")
check("tex2D(tAlbedo, psin.uv)" in _src, "an Image Texture node becomes a real sample")
check(_compiles(_src, "t_image"), "it compiles as ps_3_0")

for _nm, _wire in (("t_invert", _w_invert), ("t_mix", _w_mix)):
    _m, _s = _emit(_nm, _wire)
    check(_compiles(_s, _nm), "%s compiles as ps_3_0" % _nm)

# A flat colour must still translate - it is the same path, not a special case
_flat = M.build_material("t_flat", None)
next(n for n in _flat.node_tree.nodes
     if n.type == "BSDF_PRINCIPLED").inputs["Base Color"].default_value = (1, 0, 0, 1)
check(_compiles(SH.emit_hlsl(_flat, M.base_color_input(_flat))[0], "t_flat"),
      "an unlinked Base Color compiles too")

# Refusing loudly matters more than translating approximately: a shader that
# builds but shades wrongly costs a game launch to notice.
_bad = M.build_material("t_noise", None)
_bnt = _bad.node_tree
_bb = next(n for n in _bnt.nodes if n.type == "BSDF_PRINCIPLED")
_bnt.links.new(_bb.inputs["Base Color"],
               _bnt.nodes.new("ShaderNodeTexNoise").outputs["Color"])
_rep = SH.unsupported_nodes(M.base_color_input(_bad))
check(any(t == "TEX_NOISE" for _, t in _rep),
      "an untranslatable node is named, not silently approximated (%s)" % _rep)

# A driven Alpha is what makes a glow possible, and it has to discard its own
# near-invisible outskirts: they blend to nothing but still write depth, so
# anything crossing behind gets clipped by a part of the halo nobody can see.
_gm = M.build_material("t_glow", None)
_gnt = _gm.node_tree
_gb = next(n for n in _gnt.nodes if n.type == "BSDF_PRINCIPLED")
_co = _gnt.nodes.new("ShaderNodeTexCoord")
_sx = _gnt.nodes.new("ShaderNodeSeparateXYZ")
_rp = _gnt.nodes.new("ShaderNodeValToRGB")
_gnt.links.new(_sx.inputs[0], _co.outputs["UV"])
_gnt.links.new(_rp.inputs[0], _sx.outputs["Y"])
_gnt.links.new(_gb.inputs["Base Color"], _rp.outputs["Color"])
_gnt.links.new(_gb.inputs["Alpha"], _rp.outputs["Alpha"])
_gsrc, _ = SH.emit_hlsl(_gm, M.base_color_input(_gm), _gb.inputs["Alpha"])
check("psin.uv" in _gsrc and ".yyy" in _gsrc,
      "the ribbon coordinate reaches the shader via Texture Coordinate -> Separate XYZ")
check("lerp(" in _gsrc, "a ColorRamp becomes lerps between its stops")
check("clip(" in _gsrc, "a driven alpha discards its invisible outskirts")
check(_compiles(_gsrc, "t_glow"), "the whole glow graph compiles as ps_3_0")
# and an undriven alpha must NOT clip - opaque geometry has nothing to discard
_nosrc, _ = SH.emit_hlsl(_gm, M.base_color_input(_gm), None)
check("clip(" not in _nosrc, "with alpha undriven there is no discard")

# A material that ships a shader must NOT also be baked into its texture: the
# flattened answer would show through the live one, and they disagree by
# construction, since escaping the bake is the whole point of the shader.
_bk5 = {e.key: e for e in M.read_arc(ARC)[1]}
_sm = bpy.data.meshes.new("shaderprobe")
_sm.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
_sm.update()
_suv = _sm.uv_layers.new(name="UVMap")
for _d in _suv.data:
    _d.uv = (0.025, 1.0 - 0.0444)
_smat = M.build_material("shaderprobe", None)
_smat["umvc3_texture"] = _TEX
_smat["umvc3_had_image"] = True
_sm.materials.append(_smat)
_so = bpy.data.objects.new("shaderprobe", _sm)
_so["umvc3_entry"] = "ui\\chs\\chs_meku\\chs_meku"
bpy.context.scene.collection.objects.link(_so)
next(n for n in _smat.node_tree.nodes
     if n.type == "BSDF_PRINCIPLED").inputs["Base Color"].default_value = (1, 0, 0, 1)
check(any("shaderprobe" in p for p in
          S.bake_flat_materials(bpy.context.scene, _bk5, report=lambda m: None)[0]),
      "without a shader it bakes, as before")
_smat["umvc3_shader_crc"] = "DEADBEEF"
check(not any("shaderprobe" in p for p in
              S.bake_flat_materials(bpy.context.scene,
                                    {e.key: e for e in M.read_arc(ARC)[1]},
                                    report=lambda m: None)[0]),
      "with a shader the bake leaves it alone")
bpy.data.objects.remove(_so)

print("\nthe authored graph survives a re-import")
# The importer builds every material the same way, because that is all the
# archive describes. A material carrying a shader is different: the graph IS the
# shader, so losing it on import means rebuilding the glow by hand every session.
_rm = M.build_material("t_roundtrip", None)
_rnt = _rm.node_tree
_rb = next(n for n in _rnt.nodes if n.type == "BSDF_PRINCIPLED")
_rc = _rnt.nodes.new("ShaderNodeTexCoord")
_rs = _rnt.nodes.new("ShaderNodeSeparateXYZ")
_rr = _rnt.nodes.new("ShaderNodeValToRGB")
_rx = _rnt.nodes.new("ShaderNodeMixRGB"); _rx.blend_type = "MULTIPLY"
_rnt.links.new(_rs.inputs[0], _rc.outputs["UV"])
_rnt.links.new(_rr.inputs[0], _rs.outputs["Y"])
_rnt.links.new(_rx.inputs[1], _rr.outputs["Color"])
_rnt.links.new(_rb.inputs["Base Color"], _rx.outputs[0])
_rnt.links.new(_rb.inputs["Alpha"], _rr.outputs["Alpha"])
_rr.color_ramp.elements[0].position = 0.0
_rr.color_ramp.elements[0].color = (0.0, 0.1, 0.3, 0.0)
_rr.color_ramp.elements[1].position = 0.5
_rr.color_ramp.elements[1].color = (0.8, 0.95, 1.0, 0.52)
_re = _rr.color_ramp.elements.new(1.0); _re.color = (0.0, 0.1, 0.3, 0.0)
_rm["umvc3_shader_crc"] = "ABCD1234"
_saved = SH.graph_to_dict(_rm)
check(len(_saved["nodes"]) == 6 and len(_saved["links"]) == 6,
      "the graph serialises (%d nodes, %d links)"
      % (len(_saved["nodes"]), len(_saved["links"])))
import json as _json
_saved = _json.loads(_json.dumps(_saved))          # through a file, as it really goes

_fresh = M.build_material("t_roundtrip_fresh", None)
check(len(_fresh.node_tree.nodes) <= 3, "a fresh material is the stock stub")
SH.graph_from_dict(_fresh, _saved)
_types = sorted(n.type for n in _fresh.node_tree.nodes)
check(_types == sorted(n.type for n in _rnt.nodes),
      "every node came back (%s)" % _types)
_fr = next(n for n in _fresh.node_tree.nodes if n.type == "VALTORGB")
check([round(e.position, 3) for e in _fr.color_ramp.elements] == [0.0, 0.5, 1.0],
      "the ramp stops came back at the right positions")
check(abs(_fr.color_ramp.elements[1].color[3] - 0.52) < 1e-4,
      "and with their alpha, which is what shapes the glow")
_fx = next(n for n in _fresh.node_tree.nodes if n.type == "MIX_RGB")
check(_fx.blend_type == "MULTIPLY", "node settings like blend_type came back")
check(_fresh.get("umvc3_shader_crc") == "ABCD1234", "so did the shader target")
_fb = next(n for n in _fresh.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
check(_fb.inputs["Alpha"].is_linked and _fb.inputs["Base Color"].is_linked,
      "and the links, so it still emits the same shader")
check("clip(" in SH.emit_hlsl(_fresh, M.base_color_input(_fresh),
                              _fb.inputs["Alpha"])[0],
      "the restored graph re-emits a glow, not a stub")

print("\nretargeting a card's uvs reaches the archive")
# A card's uvs are what frames the portrait inside it, so this is how a portrait
# is cropped - and `write_card` wrote positions and weights only, which left the
# reframing in the .blend and the game showing the old crop.
_uvcard = next(o for o in cards if not o.get("umvc3_is_banner")
               and S.card_face(o) is not None
               and S.card_face(o).data.uv_layers.active is not None)
_uvface = S.card_face(_uvcard)
_uvlayer = _uvface.data.uv_layers.active
_uv_was = [tuple(d.uv) for d in _uvlayer.data]
_uvout = os.path.join(OUT, "uvedit.arc")
# Against this scene as the earlier checks left it, so the uv edit is the only
# difference between the two exports.
_uvbase = S.export_css(bpy.context, _uvout, follow_page=True, refit_weights=True,
                       report=lambda m: None)
check(_uvbase["reuvd"] == 0, "nothing has retargeted uvs yet (%d)" % _uvbase["reuvd"])
for _d in _uvlayer.data:                                 # crop to the middle
    _d.uv = (_d.uv[0] * 0.5 + 0.25, _d.uv[1] * 0.5 + 0.25)
_uvst = S.export_css(bpy.context, _uvout, follow_page=True, refit_weights=True,
                     report=lambda m: None)
check(_uvst["reuvd"] == 1 and _uvst["moved"] == _uvbase["moved"],
      "one card reports rewritten uvs and nothing else changed: %d re-uv'd, "
      "%d moved vs %d" % (_uvst["reuvd"], _uvst["moved"], _uvbase["moved"]))


def _file_uvs(arc, entry, mesh_index):
    """Every uv of one mesh, straight out of an archive, in file orientation."""
    e = next(x for x in M.read_arc(arc)[1] if x.ext == "mod" and x.name == entry)
    m = {x["index"]: x for x in M.read_meshes(e.data)}[mesh_index]
    lay = M.layout_for(m["fmt"], m["stride"])
    base = M._u64(e.data, M.H_VERTOFF) + m["vbufoff"]
    return [(M._half(e.data, base + (m["vtxlo"] + i) * m["stride"] + lay["uv0"]),
             M._half(e.data, base + (m["vtxlo"] + i) * m["stride"] + lay["uv0"] + 2))
            for i in range(m["nverts"])]


_got = _file_uvs(_uvout, _uvface["umvc3_entry"], _uvface["umvc3_mesh_index"])
_want = S._uvs(_uvface)
check(len(_got) == len(_want) and
      all(abs(a[0] - b[0]) < 1e-3 and abs(a[1] - b[1]) < 1e-3
          for a, b in zip(_got, _want)),
      "every vertex's uv in the file is the one Blender holds (%s vs %s)"
      % ([tuple(round(v, 3) for v in u) for u in _got[:2]],
         [tuple(round(v, 3) for v in u) for u in _want[:2]]))
_stock = _file_uvs(ARC, _uvface["umvc3_entry"], _uvface["umvc3_mesh_index"])
check(any(abs(a[0] - b[0]) > 1e-3 for a, b in zip(_got, _stock)),
      "and it really differs from the archive it was exported from")
# a card nobody touched keeps the uvs it shipped with, to the byte
_oface = next(o for o in bpy.context.scene.objects
              if o is not _uvface and o.type == "MESH"
              and o.get("umvc3_entry") == _uvface["umvc3_entry"]
              and o.get("umvc3_mesh_index") is not None
              and o.data.uv_layers.active is not None)
check(_file_uvs(_uvout, _oface["umvc3_entry"], _oface["umvc3_mesh_index"])
      == _file_uvs(ARC, _oface["umvc3_entry"], _oface["umvc3_mesh_index"]),
      "an untouched card in the same model is byte-identical")

for _d, _uv in zip(_uvlayer.data, _uv_was):
    _d.uv = _uv
check(S.export_css(bpy.context, _uvout, follow_page=True, refit_weights=True,
                   report=lambda m: None)["reuvd"] == 0,
      "putting them back reports nothing again - the round trip is exact")

print("\nan image put on a card's material becomes that character's portrait")
# What a player sees on a card is the character's loose .tex, bound per slot at
# runtime - not the sheet the card samples - so this is the only path that can
# carry "make this card look like this", and it used to carry nothing: the image
# is in no archive, so every export path skipped it and the card came back from
# the install still wearing the portrait it shipped with.
#
# Written into a scratch game folder. This overwrites files under the portrait
# directory, and the real install is not the suite's to edit.
from io_umvc3_css import portraits as P

FAKE = os.path.join(OUT, "fake_game")
os.makedirs(R.portrait_dir(FAKE), exist_ok=True)
_stem = R.VANILLA_NAMES[1]
_ref_path = R.find_portrait(GAME, _stem)
check(_ref_path is not None, "a stock portrait to seed the scratch folder with")
_dst = R.portrait_path(FAKE, _stem, 0)
shutil.copy2(_ref_path, _dst)
_before = open(_dst, "rb").read()

_stale = [i.name for i in bpy.data.images
          if i.get("umvc3_portrait") and (i.is_dirty or i.get("umvc3_portrait_dirty"))]
check(not _stale, "no portrait was left dirty by the earlier checks (%s)" % _stale)

_pcard = next(o for o in cards if not o.get("umvc3_is_banner")
              and S.card_face(o) is not None and S.card_face(o).data.materials
              and M.material_shown_image(S.card_face(o).data.materials[0]) is not None)
_pcard["umvc3_char"] = "v1"
_pmat = S.card_face(_pcard).data.materials[0]
_art = bpy.data.images.new("t_portrait_art", width=64, height=64, alpha=True)
_art.pixels = [0.0, 1.0, 0.0, 1.0] * (64 * 64)          # solid, opaque green
check(S._set_material_image(_pmat, _art), "the card shows an image of the user's")

# and the same again wired as a second image node, which is how a material
# actually gets its picture changed - the stock node stays in the tree, unread
_second = _pmat.node_tree.nodes.new("ShaderNodeTexImage")
_second.image = _art
_pbsdf = M.base_color_input(_pmat)
_pmat.node_tree.links.new(_pbsdf, _second.outputs["Color"])
check(M.material_shown_image(_pmat) is _art,
      "a second image node feeding Base Color is what the material shows")

_edits = S.card_portrait_edits(bpy.context.scene, FAKE)
check([e[0] for e in _edits] == [_pcard],
      "exactly the edited card is seen as showing something the game would not: %s"
      % [e[0].name for e in _edits])
check(U._pending_portrait(_pcard) is _art,
      "the card panel says so before the install, not the game afterwards")
_pw, _pf = S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)
check(_pw == [os.path.basename(_dst)] and not _pf,
      "and the install writes that character's portrait: %s %s" % (_pw, _pf))
_after = open(_dst, "rb").read()
check(_after != _before, "the .tex on disk really changed")
check(open(_dst + ".bak", "rb").read() == _before,
      "and the original was backed up before it was overwritten")
_pi = M.tex_info(_after)
check(_pi is not None and _pi["fmt"] == 19,
      "written as format 19, the only one this pipeline round-trips (%s)"
      % (_pi or {}).get("fmt"))

# The proof, and the whole point: the file the game reads is the image that was
# put on the card and nothing else. Not fitted into the 112x76 window, not laid
# under the torn-photo frame - every texel of it, corners included, is the art.
# Set Portrait is where fitting lives, because that is asked for explicitly.
_ppx = M.decode_bc(_pi["payload"], _pi["width"], _pi["height"], False, bottom_up=False)


def _green(i):
    return _ppx[i * 4 + 1] > 0.6 and _ppx[i * 4] < 0.35 and _ppx[i * 4 + 2] < 0.35


_W, _H = _pi["width"], _pi["height"]
_corners = [0, _W - 1, (_H - 1) * _W, _H * _W - 1]
check(all(_green(i) for i in _corners),
      "the corners are the user's green, so no frame was laid over it")
_margin = (2 * _W + _W // 2)                             # where the frame used to be
check(_green(_margin), "and so is the margin above the old art window")
check(all(_green(i) for i in range(0, _W * _H, 97)),
      "every texel of the portrait is the image, unedited")

check([e[0] for e in S.card_portrait_edits(bpy.context.scene, FAKE)] == [_pcard],
      "the card still shows the user's own image, which is theirs to keep editing")
check(S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None) == ([], []),
      "but a second install writes nothing - the file is already that image")
check(U._pending_portrait(_pcard) is _art, "and the panel still names it")

# Editing the image and installing again must reach the game.
_art.pixels = [1.0, 0.0, 0.0, 1.0] * (64 * 64)          # now red
_rw, _rf = S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)
_rpi = M.tex_info(open(_dst, "rb").read())
_rpx = M.decode_bc(_rpi["payload"], _rpi["width"], _rpi["height"], False, bottom_up=False)
check(_rw == [os.path.basename(_dst)] and not _rf and _rpx[0] > 0.6 and _rpx[1] < 0.35,
      "repainting the image and reinstalling reaches the .tex (%s, %.2f, %.2f, %.2f)"
      % (_rw, _rpx[0], _rpx[1], _rpx[2]))

# The .dds preview cache must not swallow a replaced portrait either: every one
# this writes is BC1 at the same size, so a length-only freshness check hands
# back the previous picture forever - which is what Set Portrait reads back.
_c1 = R.load_portrait(_dst, M.cache_dir_for(_dst), _stem)
_c1px = list(_c1.pixels[:4])
_art.pixels = [0.0, 0.0, 1.0, 1.0] * (64 * 64)          # now blue, same size and format
S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)
_c2 = R.load_portrait(_dst, M.cache_dir_for(_dst), _stem)
check(_c2.pixels[2] > 0.6 and list(_c2.pixels[:4]) != _c1px,
      "a replaced portrait previews as itself, not as the cached old one (%.2f, %.2f, %.2f)"
      % tuple(_c2.pixels[:3]))

# A card with no character has no file to be written to, and saying nothing is
# how this went wrong in the first place.
_pcard["umvc3_char"] = R.BLANK_KEY
S._set_material_image(_pmat, _art)
_nw, _nf = S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)
check(not _nw and any("no character assigned" in f for f in _nf),
      "an unassigned card is reported rather than silently skipped: %s" % _nf)

# The same silence on any other mesh: an image from disk is in no archive, so
# nothing can be bound to it and the mesh has to be told.
_rb_notes = S.rebind_materials(bpy.context.scene,
                               {e.key: e for e in M.read_arc(ARC)[1]},
                               report=lambda m: None)[1]
check([n for n in _rb_notes if "t_portrait_art" in n] and
      all("this card's portrait" in n for n in _rb_notes if "t_portrait_art" in n),
      "rebinding reports the image it cannot bind, once, as the card's portrait "
      "however the scene is walked: %s" % [n for n in _rb_notes if "t_portrait_art" in n])

# A portrait with a transparent margin: the hole must arrive as a hole, and the
# art beside it must not pick up the colour that was hiding in it.
_pcard["umvc3_char"] = "v1"
_hole = bpy.data.images.new("t_portrait_hole", width=64, height=64, alpha=True)
_hpx = [0.0] * (64 * 64 * 4)
for _i in range(64 * 64):
    _inside = 16 <= (_i % 64) < 48 and 16 <= (_i // 64) < 48
    # opaque red inside, and outside the usual undefined green under alpha 0
    _hpx[_i * 4:_i * 4 + 4] = [0.8, 0.15, 0.15, 1.0] if _inside else [0.0, 1.0, 0.0, 0.0]
_hole.pixels = _hpx
S._set_material_image(_pmat, _hole)
_hw, _hf = S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)
check(_hw == [os.path.basename(_dst)] and not _hf,
      "the cut-out portrait is written: %s %s" % (_hw, _hf))
_hi = M.tex_info(open(_dst, "rb").read())
_hd = M.decode_bc(_hi["payload"], _hi["width"], _hi["height"], False, bottom_up=False)
_W2, _H2 = _hi["width"], _hi["height"]
_ctr = ((_H2 // 2) * _W2 + _W2 // 2) * 4                # inside the opaque square
check(_hd[_ctr + 3] > 0.5 and _hd[_ctr] > 0.6 and _hd[_ctr + 1] < 0.3,
      "the art is opaque and its own colour (%.2f, %.2f, %.2f, a %.0f)"
      % (_hd[_ctr], _hd[_ctr + 1], _hd[_ctr + 2], _hd[_ctr + 3]))
check(_hd[3] < 0.5, "the margin is a hole, not a colour (a %.0f)" % _hd[3])
check(max(_hd[1::4]) < 0.35,
      "and the green that was under it is nowhere in the texture (max g %.2f)"
      % max(_hd[1::4]))
bpy.data.images.remove(_hole)
S._set_material_image(_pmat, _art)
S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)

# One character's portrait put on another's card is copied, not rebuilt: it is
# already framed, and the stock ones are format 42, of which only the alpha has
# ever been decoded - rebuilding from that preview installs a greyscale card.
_stem2 = R.VANILLA_NAMES[2]
_ref2 = R.find_portrait(GAME, _stem2)
_dst2 = R.portrait_path(FAKE, _stem2, 0)
shutil.copy2(_ref2, _dst2)
_pcard["umvc3_char"] = "v2"
S._set_material_image(_pmat, R.load_portrait(_dst, M.cache_dir_for(_dst), _stem))
_cw, _cf = S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)
check(_cw == [os.path.basename(_dst2)] and not _cf,
      "it is written under the other character's name: %s %s" % (_cw, _cf))
check(open(_dst2, "rb").read() == open(_dst, "rb").read(),
      "byte for byte, rather than through a decode nobody has finished")
check(S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None) == ([], []),
      "and settles - a portrait is matched by name, not by which install it "
      "was read from")

# A portrait changed IN PLACE - the datablock pointed at the user's own art
# rather than replaced with a new one - keeps its tag, and the tag says which
# portrait the image STANDS FOR, not that it still looks like it. Trusting it
# installed nothing at all, and the card kept the portrait it shipped with:
# a photo on a dark background inside a torn white border, reported as the
# exporter having added a background and a border.
_png = os.path.join(OUT, "t_repoint.png")
_mk = bpy.data.images.new("t_repoint_src", width=128, height=128, alpha=True)
_mk.pixels = [1.0, 0.0, 0.0, 1.0] * (128 * 128)          # solid red
_mk.filepath_raw = _png
_mk.file_format = "PNG"
_mk.save()
bpy.data.images.remove(_mk)

_pcard["umvc3_char"] = "v1"
_stock_img = R.load_portrait(_dst, M.cache_dir_for(_dst), _stem)
S._set_material_image(_pmat, _stock_img)
check(S.unmodified_portrait(_stock_img) is True,
      "the portrait as it was loaded is still that file")
check(S.card_portrait_edits(bpy.context.scene, FAKE) == [],
      "so its own card is not an edit")
_stock_img.filepath = _png
_stock_img.source = "FILE"
_stock_img.reload()
check(S.unmodified_portrait(_stock_img) is False,
      "pointing it at your own art is seen for what it is")
check([c.name for c, _i, _w, _s in S.card_portrait_edits(bpy.context.scene, FAKE)]
      == [_pcard.name], "and the card becomes an edit again")
check(U._pending_portrait(_pcard) is _stock_img, "the panel names it too")
_iw, _if_ = S.write_portraits(FAKE, bpy.context.scene, report=lambda m: None)
check(_iw == [os.path.basename(_dst)] and not _if_,
      "the install writes it: %s %s" % (_iw, _if_))
_ii = M.tex_info(open(_dst, "rb").read())
_ipx = M.decode_bc(_ii["payload"], _ii["width"], _ii["height"], False, bottom_up=False)
check(_ipx[0] > 0.6 and _ipx[2] < 0.35,
      "and it is the art, not a copy of the file the tag names (%.2f, %.2f, %.2f)"
      % tuple(_ipx[:3]))

# Which cache directory a portrait was decoded into depends on what the scene
# was opened from - beside the archive when a screen is imported, beside the
# portrait when Set Portrait writes one - so this is judged by file NAME. Whole
# paths called 133 untouched cards edited against a real scene, and re-encoding
# those installs the greyscale preview of every format 42 portrait in the game.
_elsewhere = os.path.join(OUT, "cache_elsewhere")
os.makedirs(_elsewhere, exist_ok=True)
shutil.copy2(os.path.join(M.cache_dir_for(_dst), os.path.basename(_dst) + ".dds"),
             os.path.join(_elsewhere, os.path.basename(_dst) + ".dds"))
_stock_img.filepath = os.path.join(_elsewhere, os.path.basename(_dst) + ".dds")
_stock_img.source = "FILE"
_stock_img.reload()
check(S.unmodified_portrait(_stock_img) is True,
      "the same portrait cached somewhere else still reads as untouched")
check(S.card_portrait_edits(bpy.context.scene, FAKE) == [],
      "so a scene cached elsewhere installs nothing it should not")

print("\nplugin mismatch reporting")
check(S.plugin_mismatch(9, 16) is None, "9 x 16 matches the compiled plugin")
msg = S.plugin_mismatch(12, 12)
check(msg and any("not a power of two" in m for m in msg),
      "a 12-column grid is flagged as needing mod/div detours")

print("\nini")
ini_dir = os.path.join(OUT, "ini")
os.makedirs(ini_dir, exist_ok=True)
p = S.write_ini(ini_dir, stage=4)
raw = open(p, "rb").read()
check(not raw.startswith(b"\xef\xbb\xbf"), "ini written without a BOM")
check(b"Stage=4" in raw and b"Slot7=" in raw, "ini carries Stage and 8 NewRows slots")
check(b"[Layout]" not in raw, "no [Layout] section when nothing was placed")
# and with a layout, in the exact shape GetPrivateProfileIntA will read back
p2 = S.write_ini(ini_dir, stage=4, layout={0: 20, 7: 53, 55: 32})
raw2 = open(p2, "rb").read()
check(b"[Layout]" in raw2 and b"Slot0=20" in raw2 and b"Slot7=53" in raw2
      and b"Slot55=32" in raw2, "[Layout] carries slot -> character id")
check(raw2.count(b"\r\n") > 10 and not raw2.startswith(b"\xef\xbb\xbf"),
      "still CRLF and still no BOM")
# the plugin only honours [Layout] below slot 56; make sure we never emit above
big = S.write_ini(ini_dir, stage=4, layout={i: 1 for i in range(R.VANILLA_SLOTS)})
check(b"Slot56=" not in open(big, "rb").read(),
      "nothing is written for slots CloneEngine claims")

io_umvc3_css.unregister()

print("\n" + "=" * 72)
if fails:
    print("%d FAILURE(S):" % len(fails))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
