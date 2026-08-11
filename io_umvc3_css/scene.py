"""The character select as a Blender scene: import it, edit it, put it back.

A card is not one object. Each cell of the grid is a card mesh in `face_a`/
`face_b` plus a matching mesh in every hover/select overlay (`sel1`, `sel2`,
`seld1`, `seld2`, `selr1`), all carrying the same joint id. Move the card and
leave the overlays behind and the highlight frames the wrong cell, so import
parents the whole set to one empty and you drag that.

**A card's cell is its joint id, not its position.** The engine finds a card
with `cChrTrace__findByJointId`, so where a card is drawn and which slot it
answers to are independent. Dragging a card therefore does not renumber it -
that would silently rewire the grid under a cosmetic edit. Use "Renumber From
Position" when you actually mean to move a card between cells.

Export re-encodes positions, and does the two things that a moved card cannot
do without:

  * **carries depth along the page.** The open book bows in both axes; a card
    moved in x or y without its z sinks behind the opaque page, which then shows
    through as a large soft blob swallowing several cards.
  * **refits skin weights.** The page is curled at runtime by a 4x4 bone
    lattice, so a card needs the weights belonging to where it now sits.
"""
import math
import os
import shutil
import struct

import bpy
from mathutils import Matrix, Vector

from . import anim as ANIM
from . import mod as M
from . import grid as G
from . import pagefit
from . import roster as R
from . import sdl as SDL

ARC_NAME = "mnchscmn_en.arc"          # the one the game actually loads
ARC_ALT = "mnchscmn.arc"              # write both or you will test nothing
UI_DIR = os.path.join("nativePCx64", "ui")

# The screen is not one archive. mnchscmn holds the book and its cards; the team
# and assist panels are in mnchs, the cursor in mnchsstg, and mnchsea carries no
# geometry at all. They are authored in the same units about the same origin, so
# importing them at one scale puts each where it sits on screen.
SCREEN_STEMS = ("mnchs", "mnchsstg", "mnchsea")

S_ARC = "umvc3_css_arc"
S_GAME = "umvc3_css_game_dir"
S_ROWS = "umvc3_css_rows"
S_COLS = "umvc3_css_cols"
S_SCREEN = "umvc3_css_screen_arcs"    # the other archives this scene holds

# Which archive an object or an image came from. Several archives carry the same
# resource - `p_chs_hnd1` is in both mnchscmn and mnchsstg, under one name - so
# without this an edit to one would be written into both. Absent means the
# archive the scene was opened from, which is what every scene held before there
# was more than one.
O_ARC = "umvc3_source_arc"

# How far past the spine a card must sit before it is treated as being on the
# other page. Roughly half a card, which also spans the gutter neither page
# samples (page A ends at x=0, page B starts at x=27).
SPINE_MARGIN = 30.0


def arc_in(game_dir, name=ARC_NAME):
    return os.path.join(game_dir, UI_DIR, name)


def screen_arcs(game_dir):
    """The other character-select archives present, as paths.

    Localised first: the game loads `<stem>_en.arc` where it exists, and that is
    the copy an edit has to reach.
    """
    out = []
    for stem in SCREEN_STEMS:
        for name in ("%s_en.arc" % stem, "%s.arc" % stem):
            p = arc_in(game_dir, name)
            if os.path.isfile(p):
                out.append(p)
                break
    return out


def _same_path(a, b):
    return bool(a) and bool(b) and \
        os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def owner_of(arc_path, is_main):
    """A test for "this object or image belongs to `arc_path`".

    Scenes imported before the screen was more than one archive tag nothing, so
    an untagged datablock belongs to whichever archive the scene was opened
    from - not to every archive, which would write one model's edits into all of
    them.
    """
    def owns(db):
        got = db.get(O_ARC)
        if not got:
            return is_main
        return _same_path(got, arc_path)
    return owns


def scene_grid(scene):
    """(rows, cols) off the scene.

    Read through RNA, never through `scene.get()`: these are registered
    properties, and Blender only materialises an ID property when the value
    written differs from the registered default. Detecting the stock 9 x 16 and
    storing it therefore leaves `get()` returning None, and a `get()` with a
    vanilla fallback silently exports the whole screen as 7 x 8."""
    return (int(getattr(scene, S_ROWS, G.SRC_ROWS)),
            int(getattr(scene, S_COLS, G.SRC_COLS * 2)))


def find_source(game_dir=None, arc_path=None):
    if arc_path:
        return arc_path
    if game_dir:
        p = arc_in(game_dir)
        if os.path.isfile(p):
            return p
    raise RuntimeError("no %s found - set the game folder or pick an .arc" % ARC_NAME)


# ==================================================================== import ==
def _set_material_image(mat, img):
    if mat is None or not mat.use_nodes:
        return False
    # The node Base Color actually reads, before any other image node in the
    # tree: adding a second one is how a material gets its picture changed, and
    # writing to a node the graph no longer follows changes nothing visible.
    node = M.base_color_source(M.base_color_input(mat))
    if node is not None and node.type == "TEX_IMAGE":
        node.image = img
        return True
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE":
            n.image = img
            return True
    return False


def card_meshes(card):
    """Every mesh one cell owns: the card itself plus its hover/select overlays."""
    out = [card] if card.type == "MESH" else []
    out.extend(o for o in card.children if o.type == "MESH")
    return out


def card_face(card):
    """The portrait-bearing mesh of a card, which is usually the card itself."""
    for ob in card_meshes(card):
        if ob.get("umvc3_kind") == "face":
            return ob
    return card if card.type == "MESH" else None


def portrait_materials(scene):
    """The names of the materials a character's portrait is shown on.

    Whatever `card_face` picks, which for the two cells the banner plate covers
    is an overlay rather than a `face` mesh - and never a banner, since no
    character owns one.
    """
    out = set()
    for ob in scene.objects:
        if not ob.get("umvc3_card") or ob.get("umvc3_is_banner"):
            continue
        face = card_face(ob)
        if face is None:
            continue
        out.update(m.name for m in face.data.materials if m is not None)
    return out


def card_collection(card):
    for c in card.users_collection:
        if c.get("umvc3_card_collection"):
            return c
    return next(iter(card.users_collection), None)


def place_sdl_layout(entries, by_entry, parent_col, scale, report=print,
                     animate=True, scene=None, arc_path=None):
    """Put every model the `.sdl` places where the engine draws it.

    A model that carries no world coordinates of its own - the big card, its
    plates, the cursor - is positioned by a scheduler resource, not by code, so
    this is the only thing that knows where it goes. Each node becomes an empty
    holding its transform, parented as the file parents it, and the model is
    INSTANCED onto that empty rather than moved: one model can be placed three
    times over (the three cards are one `chs_card`), and the source meshes have
    to keep the coordinates they are written back with.

    With `animate`, the node's keys come across as keyframes and the empty is a
    real child - basis holding the node's own local transform, parent inverse
    left at identity - so Blender composes the chain the way the engine does on
    every frame, not just on the one the pose was baked at. Without it, each
    empty is baked at the settle frame, which is what this did before.

    -> [(sdl leaf, nodes placed)]
    """
    from mathutils import Euler, Matrix, Vector
    done = []
    span = [None, 0, 0]              # first frame, last frame, settle
    for e in entries:
        if e.hash != M.EXT_HASHES["sdl"]:
            continue
        try:
            doc = SDL.parse(e.data)
        except Exception as err:
            report("[umvc3] %s: not read as a layout (%s)" % (G.leaf(e.name), err))
            continue
        if doc is None or not any(n.model for n in doc.nodes.values()):
            continue
        frame = doc.settle_frame()
        col = bpy.data.collections.new("%s (layout)" % G.leaf(e.name))
        col["umvc3_sdl"] = e.name
        col["umvc3_sdl_frame"] = frame
        col["umvc3_sdl_clips"] = ["%s %g %g" % c for c in doc.clips]
        parent_col.children.link(col)

        made, world = {}, {}

        def place(node):
            """-> the empty for this node, building its parents first."""
            if node.index in made:
                return made[node.index]
            pos, ang, scl = SDL.transform(node, frame)
            # Rotation order is the one uCoord's compose uses for order 0, which
            # is Rz.Ry.Rx - Blender's XYZ - and no .sdl here sets another.
            local = Matrix.LocRotScale(Vector(pos) * scale,
                                       Euler(ang, "XYZ"), Vector(scl))
            par = place(node.parent) if node.parent is not None else None
            made[node.index] = None                  # guard against a cycle
            mtx = (world[node.parent.index] @ local) if par is not None else local
            ob = bpy.data.objects.new("sdl_%s" % node.name, None)
            ob.empty_display_size = 0.2
            ob.rotation_mode = "XYZ"        # what uCoord's order 0 composes
            ob.matrix_world = mtx
            ob["umvc3_sdl_node"] = node.name
            ob["umvc3_sdl"] = e.name
            # Says the transform below is the NODE'S OWN, not its world matrix.
            # A scene imported before this existed baked the world matrix into
            # the basis and left the parent inverse to undo it, so a nudge to an
            # empty there means something else entirely and is not written back.
            ob["umvc3_sdl_local"] = True
            if arc_path:
                # Which archive this layout goes home to. `p_chs_hnd1` lives in
                # two of them under one name, so an untagged empty would write
                # its animation into every archive that carries the resource.
                ob[O_ARC] = os.path.abspath(arc_path)
            col.objects.link(ob)
            if par is not None:
                # The child holds its own local transform and nothing else, so
                # Blender composes the chain the way the engine does. Baking the
                # world matrix into the basis and cancelling it with the parent
                # inverse lands in the same place only while nothing moves.
                ob.parent = par
                ob.matrix_basis = local
            made[node.index] = ob
            world[node.index] = mtx
            return ob

        n_placed, n_known = 0, 0
        for node in sorted(doc.nodes.values(), key=lambda n: n.index):
            src = by_entry.get(node.model) if node.model else None
            ob = place(node)
            if src is None or ob is None:
                continue
            n_known += 1
            # The book and its card grids are what this addon exists to edit,
            # and an edit is written back from where the mesh SITS - so drawing
            # them under the layout transform would write that transform into
            # the geometry on the next export. Their node is still built, so the
            # transform is in the scene to read; only the geometry stays put.
            if G.leaf(node.model).startswith("chs_meku"):
                ob["umvc3_sdl_not_instanced"] = "edited in place; see the empty's transform"
                continue
            ob.instance_type = "COLLECTION"
            ob.instance_collection = src
            n_placed += 1
            for o in src.objects:
                o.hide_set(True)         # the copy at the origin is not the one
        n_anim, n_clips = 0, 0
        if animate:
            # One action per clip, shared by every node in the layout, then the
            # clips laid back out as NLA strips so the whole thing still plays.
            clips = ANIM.make_clip_actions(doc, e.name, G.leaf(e.name))
            for node in sorted(doc.nodes.values(), key=lambda n: n.index):
                ob = made.get(node.index)
                if ob is None or not ANIM.apply_node(ob, node, scale, clips):
                    continue
                ANIM.lay_out_nla(ob, clips, G.leaf(e.name))
                n_anim += 1
            for _label, _lo, _hi, act in clips:
                if act.users or act.use_fake_user:
                    n_clips += 1
            last = doc.last_frame()
            span[0] = 0 if span[0] is None else min(span[0], 0)
            span[1] = max(span[1], last)
            span[2] = max(span[2], frame)
            col["umvc3_sdl_last_frame"] = last
            col["umvc3_sdl_clip_actions"] = [a.name for _l, _lo, _hi, a in clips]

        if n_known:
            # Kept even when nothing was instanced. A layout whose models are
            # all edited in place - chs_meku's is entirely that - is still the
            # only record of where the game draws them, and dropping the
            # collection would take the empties holding it with it.
            done.append((G.leaf(e.name), n_placed))
            report("[umvc3] %s: %d of %d model(s) placed%s"
                   % (G.leaf(e.name), n_placed, n_known,
                      ", %d node(s) animated over %d frames in %d clip action(s)"
                      % (n_anim, doc.last_frame(), n_clips)
                      if n_anim else " at frame %d" % frame))
        else:
            bpy.data.collections.remove(col)
    if animate and scene is not None and span[0] is not None:
        ANIM.set_range(scene, span[0], span[1], span[2])
    return done


def import_screen_arc(context, path, scale, parent, report=print, place_layout=True,
                      animate=True):
    """Every model in one of the other character-select archives.

    Its textures are resolved lazily rather than preloaded: mnchs alone carries
    294 of them, nearly all for 2D layers no model samples, and decoding the lot
    to look at four panels is most of the import.

    -> how many models came in.
    """
    version, entries = M.read_arc(path)
    tex = M.ArchiveTextures(entries, M.cache_dir_for(path))
    col = bpy.data.collections.new(os.path.basename(path))
    made, by_entry = 0, {}
    for e in entries:
        if e.hash != M.EXT_HASHES["mod"]:
            continue
        sub = bpy.data.collections.new(G.leaf(e.name))
        col.children.link(sub)
        try:
            M.import_mod_bytes(context, e.data, e.name, scale, tex, sub)
        except RuntimeError as err:
            report("[umvc3] skipped %s: %s" % (e.name, err))
            bpy.data.collections.remove(sub)
            continue
        if not sub.objects:
            # a model with no drawable mesh - `g_chs_set` and the effect models
            # are joints and nothing else
            bpy.data.collections.remove(sub)
            continue
        for ob in sub.objects:
            ob[O_ARC] = os.path.abspath(path)
        by_entry[e.name] = sub
        made += 1
    if not made:
        bpy.data.collections.remove(col)
        return 0
    parent.children.link(col)
    if place_layout:
        place_sdl_layout(entries, by_entry, col, scale, report,
                         animate=animate, scene=context.scene, arc_path=path)
    for img in tex.images.values():
        if img is not None:
            img[O_ARC] = os.path.abspath(path)
    return made


def load_screen_into(context, game_dir, report=print):
    """Add the other archives' models to a scene that was opened without them.

    Re-importing would bring them in too, and throw away everything the scene
    has been edited into on the way - which is the whole reason this exists.

    -> (models added, every screen archive the scene now holds)
    """
    sc = context.scene
    src = sc.get(S_ARC)
    if not src:
        raise RuntimeError("no character select in this scene - import one first")
    top = next((c for c in sc.collection.children_recursive
                if c.name.startswith("character select")), sc.collection)
    # Whatever is already here came from the archive the scene was opened from.
    # Tag it before anything else arrives, or the two become indistinguishable.
    for ob in sc.objects:
        if ob.get("umvc3_entry") is not None and ob.get(O_ARC) is None:
            ob[O_ARC] = src
    have = {os.path.normcase(os.path.abspath(p)) for p in (sc.get(S_SCREEN) or ())}
    arcs = list(sc.get(S_SCREEN) or ())
    scale = sc.get("umvc3_scale", 0.01)
    added = 0
    for p in screen_arcs(game_dir):
        if os.path.normcase(os.path.abspath(p)) in have:
            # a second copy in the scene would write its edits twice, and the
            # two copies would disagree about which is the archive's
            report("[umvc3] %s is already in this scene" % os.path.basename(p))
            continue
        n = import_screen_arc(context, p, scale, top, report)
        if n:
            arcs.append(os.path.abspath(p))
            added += n
            report("[umvc3] %s: %d model(s)" % (os.path.basename(p), n))
    sc[S_SCREEN] = arcs
    context.view_layer.update()
    return added, arcs


def import_css(context, game_dir=None, arc_path=None, scale=0.01,
               load_portraits=True, hide_overlays=True, load_screen=True,
               place_layout=True, animate=True, report=print):
    """Open the whole character-select screen, annotated and grouped."""
    src = find_source(game_dir, arc_path)
    version, entries = M.read_arc(src)
    cache = M.cache_dir_for(src)
    tex = M.ArchiveTextures(entries, cache)
    tex.preload_all()

    rows, cols = G.detect_grid(entries, report=report)
    report("[umvc3] %s: %d x %d grid" % (os.path.basename(src), rows, cols))

    top = bpy.data.collections.new("character select")
    context.scene.collection.children.link(top)

    # --- every model, annotated -------------------------------------------
    per_entry = {}
    for e in entries:
        if e.hash != M.EXT_HASHES["mod"]:
            continue
        col = bpy.data.collections.new(G.leaf(e.name))
        top.children.link(col)
        try:
            M.import_mod_bytes(context, e.data, e.name, scale, tex, col)
        except RuntimeError as err:
            report("[umvc3] skipped %s: %s" % (e.name, err))
            bpy.data.collections.remove(col)
            continue
        per_entry[e.name] = col

    by_entry_mesh = {}
    for ob in context.scene.objects:
        if ob.type == "MESH" and "umvc3_mesh_index" in ob.keys():
            by_entry_mesh[(ob["umvc3_entry"], ob["umvc3_mesh_index"])] = ob

    # --- cards, and the overlays that belong to them -----------------------
    cards_col = bpy.data.collections.new("cards")
    top.children.link(cards_col)
    table = R.effective_table(rows, cols, game_dir) if game_dir else {}
    groups = {}
    n_cards = 0
    for e in entries:
        kind = G.model_kind(e.name) if e.ext == "mod" else None
        if not kind:
            continue
        what, page = kind
        cards = G.read_cards(e.data, rows=rows)
        _, banners = G.split_banners(cards)
        banner_ix = {c["index"] for c in banners}
        for c in cards:
            ob = by_entry_mesh.get((e.name, c["index"]))
            if ob is None:
                continue
            ob["umvc3_kind"] = what
            ob["umvc3_page"] = page
            ob["umvc3_jid"] = c["jid"]
            ob["umvc3_joint_col"] = c["col"]
            ob["umvc3_row"] = c["row"]
            ob["umvc3_is_banner"] = c["index"] in banner_ix
            # The seld overlays carry three coincident copies of the banner
            # plate, one per joint column it covers, so that hovering any of the
            # three lights the whole banner. They group as one card.
            key = (page, "banner") if c["index"] in banner_ix else (page, c["jid"])
            groups.setdefault(key, []).append((ob, c))
            n_cards += 1

    empties = {}
    for key in sorted(groups, key=lambda k: (k[0], 0 if k[1] == "banner" else k[1])):
        members = groups[key]
        page, which = key
        banner = which == "banner"
        jid = members[0][1]["jid"] if banner else which
        joint_col, row = G.cell_of_jid(jid, rows)
        slot = G.slot_of(page, joint_col, row, rows, cols)
        name = ("banner_%s" % page) if banner else \
               ("card_%s_c%d_r%d" % (page, joint_col, row))

        centre = Vector((sum(m[1]["cx"] for m in members) / len(members) * scale,
                         sum(m[1]["cy"] for m in members) / len(members) * scale,
                         sum(m[1]["cz"] for m in members) / len(members) * scale))

        # Everything one cell needs lives in one collection, so a card can be
        # found, hidden or soloed on its own.
        col = bpy.data.collections.new(name)
        col["umvc3_card_collection"] = True
        cards_col.children.link(col)

        # The card is the FACE mesh, not a separate empty: clicking the thing you
        # see in the viewport then selects the thing you should move. A cell the
        # `face` model has no mesh for - the two the banner plate covers - falls
        # back to whichever overlay is present.
        by_kind = {ob.get("umvc3_kind"): ob for ob, _ in members}
        root = next((by_kind[k] for k in ("face", "sel1", "sel2", "seld1",
                                          "seld2", "selr1") if k in by_kind),
                    members[0][0])

        for ob, _c in members:
            # Imported meshes carry absolute coordinates with their origin at the
            # world origin, which makes rotate and scale pivot about the middle
            # of the book. Move each origin onto the card.
            ob.data.transform(Matrix.Translation(-centre))
            ob.location = centre
            for c_old in list(ob.users_collection):
                c_old.objects.unlink(ob)
            col.objects.link(ob)
            ob["umvc3_card_of"] = name

        for ob, _c in members:
            if ob is root:
                continue
            ob.parent = root
            # Both sit at `centre`, and matrix_world is only refreshed when the
            # depsgraph next evaluates - deriving this from the location instead
            # of reading it back keeps a stale identity from teleporting every
            # overlay to the origin.
            ob.matrix_parent_inverse = Matrix.Translation(centre).inverted()
            # The overlays are drawn in FRONT of the card and are deliberately
            # wider than it. Left visible they hide the portraits and take every
            # click, which is how a card gets moved without them.
            if hide_overlays:
                ob.hide_set(True)

        root["umvc3_card"] = True
        root["umvc3_page"] = page
        root["umvc3_joint_col"] = joint_col
        root["umvc3_row"] = row
        root["umvc3_jid"] = jid
        root["umvc3_slot"] = slot
        root["umvc3_is_banner"] = banner
        root.name = name
        empties[key] = root

    # Every card moved into its own collection, so the per-model ones the card
    # models left behind are empty. Drop them: the outliner should show one tree,
    # not a second, parallel one full of nothing.
    for entry_name, c in list(per_entry.items()):
        if not c.objects and not c.children:
            bpy.data.collections.remove(c)
            del per_entry[entry_name]

    # --- what the schedulers place ----------------------------------------
    # The card archive holds the layouts for its own homeless models: the big
    # card, its plates. Runs after the card regroup, so the collections it
    # instances are the ones that survived it.
    n_sdl = sum(k for _leaf, k in
                place_sdl_layout(entries, per_entry, top, scale, report,
                                 animate=animate, scene=context.scene,
                                 arc_path=src)) \
        if place_layout else 0

    # --- portraits ---------------------------------------------------------
    n_portraits = 0
    if load_portraits and game_dir:
        pdir = R.portrait_dir(game_dir)
        if not os.path.isdir(pdir):
            report("[umvc3] no portrait folder at %s" % pdir)
        else:
            seen = {}
            for key, e in empties.items():
                if e["umvc3_is_banner"]:
                    continue
                slot = table.get(e["umvc3_slot"])
                stem = R.portrait_stem(slot)
                e["umvc3_slot_label"] = slot.label if slot else "UNKNOWN"
                e["umvc3_slot_source"] = slot.source if slot else "empty"
                # Who is on this card, as an editable assignment rather than
                # something re-derived from the slot every time.
                e["umvc3_char"] = R.key_of_slot(slot)
                if not stem:
                    continue
                if stem not in seen:
                    p = R.find_portrait(game_dir, stem)
                    seen[stem] = R.load_portrait(p, cache, stem) if p else None
                img = seen[stem]
                if img is None:
                    continue
                face = card_face(e)
                if face is not None and face.data.materials:
                    if _set_material_image(face.data.materials[0], img):
                        n_portraits += 1

    # Everything so far came out of the archive the scene was opened from; say
    # so on the datablocks, because from here on it is not the only one.
    for ob in context.scene.objects:
        if ob.get("umvc3_entry") is not None:
            ob[O_ARC] = os.path.abspath(src)
    for img in tex.images.values():
        if img is not None:
            img[O_ARC] = os.path.abspath(src)

    # --- the rest of the screen --------------------------------------------
    screen, n_screen = [], 0
    if load_screen and game_dir:
        for p in screen_arcs(game_dir):
            n = import_screen_arc(context, p, scale, top, report,
                                  place_layout=place_layout, animate=animate)
            if n:
                screen.append(os.path.abspath(p))
                n_screen += n
                report("[umvc3] %s: %d model(s)" % (os.path.basename(p), n))

    # Origins and parenting were just rewritten wholesale; flush them so anything
    # reading matrix_world next - the panel, an operator, the exporter - sees the
    # scene as it now is rather than as it was before the regroup.
    context.view_layer.update()

    sc = context.scene
    sc[S_ARC] = os.path.abspath(src)
    setattr(sc, S_ROWS, rows)
    setattr(sc, S_COLS, cols)
    sc["umvc3_arc"] = os.path.abspath(src)          # the generic exporter's key
    sc["umvc3_scale"] = scale
    sc[S_SCREEN] = screen
    if game_dir:
        setattr(sc, S_GAME, os.path.abspath(game_dir))
    n_graphs = restore_shader_graphs(game_dir, report) if game_dir else 0
    return {"rows": rows, "cols": cols, "cards": n_cards,
            "groups": len(empties), "portraits": n_portraits, "source": src,
            "scenery": len(per_entry), "graphs": n_graphs,
            "screen": n_screen, "screen_arcs": screen, "placed": n_sdl}


def restore_shader_graphs(game_dir, report=print):
    """Put authored node graphs back on their materials after an import.

    The importer builds every material the same way - one image into a Principled
    BSDF - because that is all the archive describes. A material carrying a
    shader is different: its graph IS the shader, and it lives in a file beside
    the bytecode it compiled to. Without this, importing silently replaces an
    authored glow with the stock stub and the work has to be redone by hand.
    """
    import json
    import glob as _glob
    from . import shader as SH
    out_dir = os.path.join(game_dir, "shaders")
    if not os.path.isdir(out_dir):
        return 0

    def find_image(entry, name):
        # Prefer the archive resource the graph named; fall back to the image's
        # own name so a hand-picked sheet still resolves.
        if entry:
            for img in bpy.data.images:
                if img.get("umvc3_entry") == entry:
                    return img
        return bpy.data.images.get(name)

    n = 0
    for path in sorted(_glob.glob(os.path.join(out_dir, "*.nodes.json"))):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as err:
            report("[umvc3] could not read %s (%s)" % (os.path.basename(path), err))
            continue
        mat = bpy.data.materials.get(data.get("material") or "")
        if mat is None or mat.node_tree is None:
            continue
        for note in SH.graph_from_dict(mat, data, find_image):
            report("[umvc3] %s: %s" % (mat.name, note))
        n += 1
        report("[umvc3] restored the authored graph on %s (%d nodes)"
               % (mat.name, len(data.get("nodes", []))))
    return n


# ==================================================================== export ==
def card_objects(scene):
    """Every imported card mesh, grouped by the archive entry it came from."""
    out = {}
    for ob in scene.objects:
        if ob.type == "MESH" and "umvc3_jid" in ob.keys() and "umvc3_mesh_index" in ob.keys():
            out.setdefault(ob["umvc3_entry"], []).append(ob)
    return out


def new_card_objects(scene):
    """Cards cloned with Add Card, which become new meshes on write."""
    out = {}
    for ob in scene.objects:
        if ob.type == "MESH" and ob.get("umvc3_new_from") is not None:
            out.setdefault(ob["umvc3_entry"], []).append(ob)
    return out


def _world_positions(ob, scale):
    mtx = ob.matrix_world
    return [tuple((mtx @ v.co)[k] / scale for k in range(3)) for v in ob.data.vertices]


def _uvs(ob):
    """Per-vertex UVs in the file's orientation (v flipped), or None."""
    me = ob.data
    if not me.uv_layers.active:
        return None
    uvl = me.uv_layers.active
    per_vert = {}
    for loop in me.loops:
        per_vert.setdefault(loop.vertex_index, uvl.data[loop.index].uv)
    return [(per_vert[i][0], 1.0 - per_vert[i][1]) if i in per_vert else (0.0, 0.0)
            for i in range(len(me.vertices))]


def cell_from_position(ob_empty, rows, cols, geom):
    """Nearest (joint_col, row) to where a card actually sits."""
    xs, ys = geom["xs"], geom["ys"]
    page = ob_empty["umvc3_page"]
    x = ob_empty.location.x / geom["scale"]
    y = ob_empty.location.y / geom["scale"]
    cand_x = xs[page]
    joint_col = min(range(len(cand_x)), key=lambda i: abs(cand_x[i] - x))
    row = min(range(len(ys)), key=lambda i: abs(ys[i] - y))
    return joint_col, row


def grid_geometry(scene, rows, cols):
    """Cell centres, taken from where the cards currently are."""
    scale = scene.get("umvc3_scale", 0.01)
    xs, ys = {"a": {}, "b": {}}, {}
    for ob in scene.objects:
        if not ob.get("umvc3_card") or ob.get("umvc3_is_banner"):
            continue
        xs[ob["umvc3_page"]].setdefault(ob["umvc3_joint_col"], []).append(
            ob.location.x / scale)
        ys.setdefault(ob["umvc3_row"], []).append(ob.location.y / scale)
    out_x = {p: [sum(v) / len(v) for _, v in sorted(d.items())] for p, d in xs.items()}
    out_y = [sum(v) / len(v) for _, v in sorted(ys.items())]
    return {"xs": out_x, "ys": out_y, "scale": scale}


def export_css(context, out_arc, source_arc=None, follow_page=True,
               refit_weights=True, report=print):
    """Write the edited scene back into an archive.

    Positions come from Blender; joint ids come from the cards' own properties,
    because a card's cell is its id and dragging it must not rewire the grid.
    """
    scene = context.scene
    src = source_arc or scene.get(S_ARC) or scene.get("umvc3_arc")
    if not src or not os.path.isfile(src):
        raise RuntimeError("no source archive - import a scene first")
    version, entries = M.read_arc(src)
    by_key = {e.key: e for e in entries}
    rows, cols = scene_grid(scene)
    scale = scene.get("umvc3_scale", 0.01)      # a real ID property, set with []

    context.view_layer.update()          # matrix_world is evaluated lazily
    surfaces = {}
    groups = card_objects(scene)
    fresh_by_entry = new_card_objects(scene)
    for k in fresh_by_entry:
        groups.setdefault(k, [])
    stats = {"models": 0, "cards": 0, "renumbered": 0, "retargeted": 0,
             "added": 0, "clamped": 0, "moved": 0, "reuvd": 0}
    off_page = {}
    moved_names = []
    reuvd_names = []

    for entry_name, objs in sorted(groups.items()):
        mod_e = by_key.get((entry_name, M.EXT_HASHES["mod"]))
        mrl_e = by_key.get((entry_name, M.EXT_HASHES["mrl"]))
        if mod_e is None or mrl_e is None:
            report("[umvc3] %s missing from the source archive, skipped" % entry_name)
            continue
        kind = G.model_kind(entry_name)
        if not kind:
            continue
        page = kind[1]

        def surface(pg):
            if pg not in surfaces:
                surfaces[pg] = pagefit.page_surface(entries, pg)
            return surfaces[pg]

        def page_at(pts):
            """Which half of the open book a card's centre sits over.

            Chosen per card, not per vertex: a card straddling the spine would
            otherwise get one half seated on each page and tear down the middle.
            A card can legitimately end up over the other page - joint column 0
            is right at the spine - and it should then follow the page it is
            actually on, not the one its model belongs to.

            The margin matters. Testing `cx < 0` is discontinuous exactly where
            joint column 0 lives, so a card sitting near the spine flips pages on
            nothing more than the float error of a round trip, and its depth
            jumps by the ~20 units between the two surfaces. Inside the gutter -
            which neither page samples anyway, page A stops at x=0 and page B
            starts at x=27 - keep the model's own page."""
            cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2.0
            if cx < -SPINE_MARGIN:
                return "a"
            if cx > SPINE_MARGIN:
                return "b"
            return page

        b = mod_e.data
        src_cards = {c["index"]: c for c in G.read_cards(b, rows=rows)}
        field = G.weight_field(list(src_cards.values())) if refit_weights else None
        # "Moved" has to mean "moved enough to change the file". Positions are
        # quantised to a u16, so anything under half a step re-encodes to the
        # same bytes; a threshold below that just reports float noise from the
        # round trip through Blender's float32 coordinates as an edit.
        half_step = M.model_dequant(b).scale / M.POS_SCALE * 0.5

        # --- where every vertex ends up ------------------------------------
        placed, uvs = {}, {}
        for ob in objs:
            mi = ob["umvc3_mesh_index"]
            c = src_cards.get(mi)
            if c is None:
                continue
            if len(ob.data.vertices) != c["nverts"]:
                raise RuntimeError(
                    "%s has %d vertices but mesh %d expects %d. Topology is "
                    "preserved - do not add or delete vertices."
                    % (ob.name, len(ob.data.vertices), mi, c["nverts"]))
            pts = _world_positions(ob, scale)
            if follow_page:
                # Keep each vertex's clearance over the paper: the card's tilt
                # then follows the page wherever it lands. A deliberate z edit
                # still comes through, because it rides on top of this delta.
                dst = surface(page_at(pts))
                src_s = surface(page_at(c["pts"]))
                pts = [(p[0], p[1], p[2] + dst(p[0], p[1]) - src_s(o[0], o[1]))
                       for p, o in zip(pts, c["pts"])]
                cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2.0
                cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2.0
                if not dst.contains(cx, cy):
                    off_page.setdefault(ob.parent.name if ob.parent else ob.name,
                                        (round(cx, 1), round(cy, 1)))
            delta = max(max(abs(p[k] - o[k]) for k in range(3))
                        for p, o in zip(pts, c["pts"]))
            if delta > half_step:
                stats["moved"] += 1
                moved_names.append((round(delta, 3), G.leaf(entry_name), c["jid"]))
            placed[mi] = pts
            uvs[mi] = _uvs(ob)
            stats["cards"] += 1

        # --- cards cloned with Add Card ------------------------------------
        fresh = []
        for ob in fresh_by_entry.get(entry_name, ()):
            tpl = ob["umvc3_new_from"]
            if tpl not in src_cards:
                report("[umvc3] %s clones mesh %d, which is not a card - skipped"
                       % (ob.name, tpl))
                continue
            pts = _world_positions(ob, scale)
            if follow_page:
                o_pts = src_cards[tpl]["pts"]
                dst = surface(page_at(pts))
                src_s = surface(page_at(o_pts))
                pts = [(p[0], p[1], p[2] + dst(p[0], p[1]) - src_s(o[0], o[1]))
                       for p, o in zip(pts, o_pts)]
            parent = ob.parent
            jid = parent["umvc3_jid"] if parent and parent.get("umvc3_card") \
                else ob.get("umvc3_jid")
            fresh.append({"template": tpl, "material": 0, "positions": pts,
                          "uvs": _uvs(ob), "_jid": int(jid)})

        if not placed and not fresh:
            continue

        # --- make the decode cover everything ------------------------------
        allp = [p for pts in placed.values() for p in pts] + \
               [p for s in fresh for p in s["positions"]]
        nb, q = G.fit_decode(b, allp)
        if nb is not b:
            stats["retargeted"] += 1
        bb = bytearray(nb)
        meshes = {m["index"]: m for m in M.read_meshes(nb)}
        for mi, pts in placed.items():
            n_uv = G.write_card(bb, q, meshes[mi], pts, field, uvs.get(mi))
            if n_uv:
                stats["reuvd"] += 1
                reuvd_names.append((n_uv, G.leaf(entry_name), src_cards[mi]["jid"]))
        mod_data = bytes(bb)

        # --- joint ids -----------------------------------------------------
        want = {}
        for ob in objs:
            mi = ob["umvc3_mesh_index"]
            if mi not in placed:
                continue
            parent = ob.parent
            jid = parent["umvc3_jid"] if parent and parent.get("umvc3_card") \
                else ob.get("umvc3_jid")
            if ob.get("umvc3_is_banner"):
                jid = ob["umvc3_jid"]          # plates keep their own ids
            if jid is not None and jid != src_cards[mi]["jid"]:
                want[mi] = int(jid)
        mrl_data = mrl_e.data
        if want:
            mod_data, mrl_data = G.renumber(mod_data, mrl_data, want,
                                            label=G.leaf(entry_name))
            stats["renumbered"] += len(want)

        # --- append the new cards ------------------------------------------
        # Renumber first, then append: giving a new card an id an existing card
        # still holds, and only then renaming that one, collides on the hash.
        if fresh:
            names = M.read_mod_material_names(mod_data)
            live = {m["index"]: m for m in M.read_meshes(mod_data)}
            new_names, tpl_mats = [], []
            for s in fresh:
                tpl_mat = live[s["template"]]["material"]
                tpl_mats.append(tpl_mat)
                g = G.MAT_ID.match(names[tpl_mat])
                cand = "%s%02d%s" % (g.group(1), s["_jid"], g.group(3))
                if cand in names or cand in new_names:
                    raise RuntimeError("%s: material %s already exists - two cards "
                                       "want joint id %d"
                                       % (G.leaf(entry_name), cand, s["_jid"]))
                new_names.append(cand)

            mod_data, first_new = M.mod_add_material_slots(mod_data, new_names)
            for i, s in enumerate(fresh):
                s["material"] = first_new + i
            pre_count = M._u16(mod_data, M.H_MESHCOUNT)
            mod_data = M.mod_append_meshes(mod_data, fresh)

            groups_by_tpl = {}
            for i, tm in enumerate(tpl_mats):
                groups_by_tpl.setdefault(tm, []).append(i)
            for tpl_mat, idxs in groups_by_tpl.items():
                entry = G.mrl_entries(mrl_data).get(M.mt_hash(names[tpl_mat]))
                if entry is None:
                    raise RuntimeError("%s: template material %s has no .mrl entry"
                                       % (G.leaf(entry_name), names[tpl_mat]))
                mrl_data = M.mrl_add_materials(mrl_data, entry,
                                               [new_names[i] for i in idxs])
            mb = bytearray(mrl_data)
            pos = G.mrl_entries(mrl_data)
            for i, s in enumerate(fresh):
                G.write_joint_id(mb, pos[M.mt_hash(new_names[i])], s["_jid"])
            mrl_data = bytes(mb)

            # weights belong to where the new card sits, not where it was cloned
            if field is not None:
                bb2 = bytearray(mod_data)
                added = {m["index"]: m for m in M.read_meshes(mod_data)}
                vert_off = M._u64(bb2, M.H_VERTOFF)
                for i, s in enumerate(fresh):
                    m = added[pre_count + i]
                    for j in range(m["nverts"]):
                        vo = vert_off + m["vbufoff"] + (m["vtxlo"] + j) * m["stride"]
                        M.write_skin(bb2, vo, field(s["positions"][j][0],
                                                    s["positions"][j][1]))
                mod_data = bytes(bb2)
            stats["added"] += len(fresh)

        bb = bytearray(mod_data)
        M.write_bbox(bb, *M.mod_geometry_bounds(mod_data))
        mod_data = bytes(bb)

        mod_e.data, mod_e.dirty = mod_data, True
        if mrl_data != mrl_e.data:
            mrl_e.data, mrl_e.dirty = mrl_data, True
        stats["models"] += 1

    owns_main = owner_of(src, True)

    # --- textures edited in Blender ----------------------------------------
    tex_written, tex_failed = write_textures(by_key, owns_main)

    # --- geometry the card path does not own -------------------------------
    geom, geom_problems = export_custom_meshes(context.scene, by_key, scale, report,
                                               owns=owns_main)

    # --- make the archive show what Blender shows --------------------------
    rebound, rebind_notes = rebind_materials(context.scene, by_key, report, owns=owns_main)
    flat_painted, flat_skipped = bake_flat_materials(context.scene, by_key, report,
                                                     owns=owns_main)

    # --- the animation the schedulers drive --------------------------------
    layouts = ANIM.export_layouts(context.scene, by_key, scale, owns_main, report)

    size = M.write_arc(out_arc, version, entries)

    # --- the other archives the screen is spread across --------------------
    # Written beside whatever the card archive was written to, under their own
    # names: an install therefore lands on the game's own copies, and an export
    # to a scratch folder keeps the set together.
    screen = export_screen_arcs(context.scene, os.path.dirname(os.path.abspath(out_arc)),
                                scale, report)

    stats.update({"geometry": geom, "geometry_problems": geom_problems,
                  "rebound": rebound, "rebind_notes": rebind_notes,
                  "layouts": layouts,
                  "flat": flat_painted, "flat_skipped": flat_skipped,
                  "textures": tex_written, "failed": tex_failed, "size": size,
                  "rows": rows, "cols": cols, "out": out_arc,
                  "off_page": off_page, "screen": screen,
                  "moved_names": sorted(moved_names, reverse=True),
                  "reuvd_names": sorted(reuvd_names, reverse=True)})
    for n, leaf, jid in stats["reuvd_names"]:
        report("[umvc3] uvs written: %s joint %d, %d vertex(es)" % (leaf, jid, n))
    for name, (cx, cy) in sorted(off_page.items()):
        report("[umvc3] %s sits off the book at (%.0f, %.0f) - its depth is held "
               "at the page edge, so it will float rather than lie on the paper"
               % (name, cx, cy))
    return stats


def write_textures(by_key, owns=None):
    """Re-encode every edited image into the archive entry it came from."""
    written, failed = 0, []
    for img in bpy.data.images:
        name = img.get("umvc3_entry")
        if not name or not M.texture_is_modified(img):
            continue
        if owns is not None and not owns(img):
            continue
        e = by_key.get((name, M.EXT_HASHES["tex"]))
        if e is None:
            continue
        try:
            e.data = M.encode_image_to_tex(img, e.data)
            e.dirty = True
            written += 1
        except RuntimeError as err:
            failed.append("%s (%s)" % (name, err))
    return written, failed


def export_screen_arcs(scene, out_dir, scale, report=print):
    """Write back the other archives the screen is spread across.

    Everything the card archive gets except the card path itself, which is
    meaningless here - these models are not cards. An archive nothing touched is
    not written at all: an install should not churn files it has no edit for,
    and a `.bak` taken over an already-modified file is worth nothing.

    -> [(path, models, textures)] for the ones that changed.
    """
    done = []
    for src in scene.get(S_SCREEN, ()) or ():
        if not os.path.isfile(src):
            report("[umvc3] %s is gone; its models cannot be written back"
                   % os.path.basename(src))
            continue
        version, entries = M.read_arc(src)
        by_key = {e.key: e for e in entries}
        owns = owner_of(src, False)
        tex_n, tex_failed = write_textures(by_key, owns)
        geom, problems = export_custom_meshes(scene, by_key, scale, report, owns=owns)
        rebind_materials(scene, by_key, report, owns=owns)
        bake_flat_materials(scene, by_key, report, owns=owns)
        ANIM.export_layouts(scene, by_key, scale, owns, report)
        for p in problems:
            report("[umvc3] %s: geometry NOT written: %s" % (os.path.basename(src), p))
        for f in tex_failed:
            report("[umvc3] %s: texture NOT written: %s" % (os.path.basename(src), f))
        if not any(e.dirty for e in entries):
            continue
        out = os.path.join(out_dir, os.path.basename(src))
        if os.path.isfile(out) and not os.path.isfile(out + ".bak"):
            shutil.copy2(out, out + ".bak")
        M.write_arc(out, version, entries)
        done.append((out, len(geom), tex_n))
        report("[umvc3] %s written: %d model(s), %d texture(s)"
               % (os.path.basename(out), len(geom), tex_n))
    return done


# The share of a texture a flat colour may cover. A material mapped across most
# of its sheet is not asking to be flooded - and archive textures are shared, so
# flooding one would take other meshes' art with it. Small footprints, like the
# grid lines' single texel, are unambiguous.
FLAT_FOOTPRINT_LIMIT = 0.05
# Texels of margin painted around a footprint, for half-float uvs and filtering.
FLAT_BLEED = 2


def mesh_to_spec(ob, scale, index):
    """Blender mesh -> a replacement spec in game units, or None if unusable.

    Reads the EVALUATED mesh, so modifiers count: a grid can be tuned with an
    Array or a Solidify rather than by moving 1674 vertices by hand.

    The archive stores one uv per vertex while Blender stores one per corner, so
    corners that disagree are split into separate vertices. Merging them instead
    would silently weld the seams - and on the grid lines the uv IS the ribbon's
    width coordinate, so a weld there flattens the glow.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        uvl = me.uv_layers.active
        mw = ob.matrix_world
        verts, lookup, tris = [], {}, []
        for t in me.loop_triangles:
            for li, vi in zip(t.loops, t.vertices):
                # The importer flips v, so undo it - but ONLY where there is a uv
                # layer to undo. Flipping the (0,0) stand-in for a mesh that has
                # no uvs writes (0,1), which differs from what the archive holds
                # and makes every such mesh look edited forever.
                uv = (uvl.data[li].uv[0], 1.0 - uvl.data[li].uv[1]) if uvl else (0.0, 0.0)
                key = (vi, round(uv[0], 5), round(uv[1], 5))
                slot = lookup.get(key)
                if slot is None:
                    slot = len(verts)
                    if slot > 0xFFFF:
                        return None, "more than 65535 vertices after uv splitting"
                    lookup[key] = slot
                    p = mw @ me.vertices[vi].co
                    verts.append(((p.x / scale, p.y / scale, p.z / scale), uv))
                tris.append(slot)
        if not verts or not tris:
            return None, "no triangles"
        return {"index": index,
                "positions": [v[0] for v in verts],
                "uvs": [v[1] for v in verts],
                "indices": tris}, None
    finally:
        ev.to_mesh_clear()


def export_custom_meshes(scene, by_key, scale, report=print, owns=None):
    """Write back geometry for models the card path does not own - chs_meku and
    friends. Only meshes that actually differ are rewritten: an untouched scene
    must export byte-for-byte, and rewriting everything would also churn the
    vertex buffer on every install.

    `owns` scopes this to one archive. Two of them carry `p_chs_hnd1` under the
    same name, so without it the cursor edited in one would be written into both.
    """
    by_entry = {}
    for ob in scene.objects:
        entry = ob.get("umvc3_entry")
        idx = ob.get("umvc3_mesh_index")
        if ob.type != "MESH" or entry is None or idx is None:
            continue
        if G.model_kind(entry):
            continue                     # cards go through the grid path
        if owns is not None and not owns(ob):
            continue
        by_entry.setdefault(entry, []).append((ob, idx))

    changed, problems = [], []
    for entry, items in sorted(by_entry.items()):
        e = by_key.get((entry, M.EXT_HASHES["mod"]))
        if e is None:
            continue
        src = e.data
        live = {m["index"]: m for m in M.read_meshes(src)}
        q = M.model_dequant(src)
        vert_off = M._u64(src, M.H_VERTOFF)
        specs = []
        for ob, idx in sorted(items, key=lambda t: t[1]):
            m = live.get(idx)
            if m is None:
                continue
            spec, why = mesh_to_spec(ob, scale, idx)
            if spec is None:
                problems.append("%s: %s" % (ob.name, why))
                continue
            # Compare CONTENT, not vertex order. Splitting corners by uv rebuilds
            # the vertex list in triangle order, so an index-by-index comparison
            # says "changed" for a mesh nobody touched - which it did, and every
            # untouched model got rewritten. Compare at the precision the archive
            # can express, too: the decode is quantised, so exact floats never
            # survive a round trip.
            lay = M.layout_for(m["fmt"], m["stride"])
            # Some models store float32 positions rather than quantised ones -
            # `0000` does. Reading those as u16 gives garbage, so they compared
            # unequal every time and were rewritten on every export.
            f32_pos = bool(lay) and lay.get("pos") == "f32"
            step = 1e-3 if f32_pos else q.scale / M.POS_SCALE
            stored, wanted = [], []
            for j in range(m["nverts"]):
                vo = vert_off + m["vbufoff"] + (m["vtxlo"] + j) * m["stride"]
                uv = (0.0, 0.0)
                if lay and lay["uv0"] is not None:
                    uv = (M._half(src, vo + lay["uv0"]),
                          M._half(src, vo + lay["uv0"] + 2))
                p = struct.unpack_from("<3f", src, vo) if f32_pos else \
                    q.decode(struct.unpack_from("<3H", src, vo))
                stored.append(tuple(p) + uv)
            outside = False
            for p, uv in zip(spec["positions"], spec["uvs"]):
                try:
                    rt = tuple(p) if f32_pos else tuple(q.decode(q.encode(p)))
                except ValueError:
                    # Past what the current decode can express, so it has
                    # certainly moved. Say so instead of raising - the write
                    # below widens the decode to take it.
                    outside = True
                    break
                wanted.append(rt + tuple(uv))
            # Compare in game units against the quantisation step, not exactly.
            # A vertex round-tripped through Blender's float32 and back lands
            # one least-significant bit away often enough that exact equality
            # calls every mesh edited - and then an untouched scene rewrites the
            # whole model. Anything smaller than a step the archive cannot store
            # anyway, so it is not an edit.
            same = (not outside and len(wanted) == m["nverts"]
                    and len(spec["indices"]) == m["idxcount"] and lay is not None)
            if same:
                for a, b in zip(sorted(wanted), sorted(stored)):
                    if (max(abs(a[k] - b[k]) for k in range(3)) > 1.5 * step
                            or abs(a[3] - b[3]) > 0.002 or abs(a[4] - b[4]) > 0.002):
                        same = False
                        break
            if same:
                continue
            specs.append(spec)
        if not specs:
            continue
        # Geometry grown past the model's decode range has to widen it, not
        # fail: the range is a per-model uniform scale, and moving a vertex
        # outside it is exactly what tuning a grid does. fit_decode unions with
        # what is already there and re-encodes the rest, so nothing else shifts.
        # Models storing float32 positions have no range to outgrow.
        quantised = any(
            (M.layout_for(live[s["index"]]["fmt"], live[s["index"]]["stride"]) or {})
            .get("pos") != "f32" for s in specs)
        if quantised:
            want = [p for s in specs for p in s["positions"]]
            widened, q2 = G.fit_decode(src, want)
            if widened is not src:
                src = widened
                report("[umvc3] %s: decode widened to fit the edited geometry"
                       % G.leaf(entry))
        try:
            e.data = M.mod_replace_meshes(src, specs)
            e.dirty = True
        except (RuntimeError, ValueError) as err:
            problems.append("%s: %s" % (G.leaf(entry), err))
            continue
        for s in specs:
            grew = s["index"] not in live or len(s["positions"]) != live[s["index"]]["nverts"]
            changed.append("%s mesh %d: %d verts, %d tris%s"
                           % (G.leaf(entry), s["index"], len(s["positions"]),
                              len(s["indices"]) // 3, " (new segment)" if grew else ""))
    for c in changed:
        report("[umvc3] geometry written: %s" % c)
    for p in problems:
        report("[umvc3] geometry NOT written: %s" % p)
    return changed, problems


def rebind_materials(scene, by_key, report=print, owns=None):
    """Point a material at whatever texture it is showing in Blender.

    Swapping the image on a material is the other obvious way to change what a
    mesh looks like, and copying pixels around would be the wrong answer: the
    material should SAMPLE the texture it appears to. That is one dword in the
    MRL, so the model ends up bound exactly as the viewport shows it.

    Portraits are left alone. The importer deliberately shows a character's
    portrait on its card, the game binds those per slot at runtime, and they go
    back out as loose .tex files - rebinding would be meaningless and copying
    them into the shared sheet would destroy it.
    """
    done, notes = [], []
    seen, noted = set(), set()
    # Which materials a portrait can appear on, decided once. A card's face
    # material is on its overlays too, so asking the object being visited would
    # make the advice depend on the order the scene happens to be walked.
    faces = portrait_materials(scene)
    for ob in scene.objects:
        if ob.type != "MESH" or ob.get("umvc3_entry") is None:
            continue
        if owns is not None and not owns(ob):
            continue
        for mat in ob.data.materials:
            if mat is None or mat.name in seen:
                continue
            tex = mat.get("umvc3_texture")
            img = M.material_shown_image(mat)
            if not tex or img is None:
                continue
            shown = img.get("umvc3_entry")
            if shown == tex:
                continue
            if not shown:
                # An image loaded from disk is in no archive, so there is no
                # binding that reaches it. Saying nothing here is what let an
                # edit look applied and ship unchanged; the card case is the
                # portrait path's, and the rest is Replace Texture's, which
                # re-encodes the pixels into the texture the mesh samples.
                if not img.get("umvc3_portrait") and mat.name not in noted:
                    noted.add(mat.name)
                    notes.append("%s shows %s, which is not in the archive - %s"
                                 % (mat.name, img.name,
                                    "Install writes it as this card's portrait, "
                                    "as it is" if mat.name in faces else
                                    "use Replace Texture to put those pixels in %s"
                                    % G.leaf(tex)))
                continue
            seen.add(mat.name)
            mrl_e = by_key.get((ob["umvc3_entry"], M.EXT_HASHES["mrl"]))
            if mrl_e is None:
                continue
            textures, _ = M.parse_mrl_bytes(mrl_e.data)
            if shown not in textures:
                notes.append("%s shows %s, which %s does not list - the model can "
                             "only sample its own textures"
                             % (mat.name, G.leaf(shown), G.leaf(ob["umvc3_entry"])))
                continue
            nb = M.set_mrl_texture_binding(mrl_e.data, M.mt_hash(mat.name),
                                           textures.index(shown))
            if nb is None:
                notes.append("%s could not be rebound - its shader keeps the base "
                             "map somewhere this does not know" % mat.name)
                continue
            mrl_e.data, mrl_e.dirty = nb, True
            mat["umvc3_texture"] = shown
            done.append("%s -> %s" % (mat.name, G.leaf(shown)))
    for m in done:
        report("[umvc3] material rebound: %s" % m)
    for m in notes:
        report("[umvc3] material NOT rebound: %s" % m)
    return done, notes


BAKE_SAMPLES = 16


def _uv_area(ob, slot):
    """Area the material's faces cover in uv space, 1.0 being the whole sheet."""
    uvl = ob.data.uv_layers.active
    if uvl is None:
        return 0.0
    total = 0.0
    for p in ob.data.polygons:
        if p.material_index != slot:
            continue
        pts = [uvl.data[li].uv for li in p.loop_indices]
        for i in range(1, len(pts) - 1):
            a, b, c = pts[0], pts[i], pts[i + 1]
            total += abs((b[0] - a[0]) * (c[1] - a[1])
                         - (c[0] - a[0]) * (b[1] - a[1])) / 2.0
    return total


def _bake_begin(scene, objs):
    """Cycles, colour only - no lighting - and the objects visible enough to
    bake. Returns what to hand back to _bake_end."""
    saved = {
        "engine": scene.render.engine,
        "direct": scene.render.bake.use_pass_direct,
        "indirect": scene.render.bake.use_pass_indirect,
        "color": scene.render.bake.use_pass_color,
        "target": scene.render.bake.target,
        "margin": scene.render.bake.margin,
        "samples": getattr(getattr(scene, "cycles", None), "samples", None),
        "selected": [o for o in scene.objects if o.select_get()],
        "active": bpy.context.view_layer.objects.active,
        # the importer hides the hover overlays, and a hidden object bakes to
        # nothing at all
        "hidden": [(o, o.hide_viewport, o.hide_render) for o in objs],
    }
    scene.render.engine = "CYCLES"
    if hasattr(scene, "cycles"):
        scene.cycles.samples = BAKE_SAMPLES
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.use_pass_color = True
    for o in scene.objects:
        o.select_set(False)
    for o in objs:
        o.hide_viewport = o.hide_render = False
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    return saved


def _bake_end(scene, saved):
    scene.render.engine = saved["engine"]
    scene.render.bake.use_pass_direct = saved["direct"]
    scene.render.bake.use_pass_indirect = saved["indirect"]
    scene.render.bake.use_pass_color = saved["color"]
    scene.render.bake.target = saved["target"]
    scene.render.bake.margin = saved["margin"]
    if saved["samples"] is not None and hasattr(scene, "cycles"):
        scene.cycles.samples = saved["samples"]
    for o, hv, hr in saved["hidden"]:
        o.hide_viewport, o.hide_render = hv, hr
    for o in scene.objects:
        o.select_set(False)
    for o in saved["selected"]:
        try:
            o.select_set(True)
        except RuntimeError:
            pass
    bpy.context.view_layer.objects.active = saved["active"]


def _emit_shader(mat):
    """Route whatever feeds Base Color into an Emission shader, and return a
    callable that puts the material back.

    Baking the DIFFUSE pass instead scales the answer by the BSDF's own
    parameters - a material at Metallic 0.55 baked its red as a third of itself -
    and the pass does not evaluate every node. Emission is the plain "run this
    graph and give me the colour" bake, which is what a game texture wants.
    """
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    inp = M.base_color_input(mat)
    if nt is None or out is None or inp is None:
        return None
    surface = out.inputs["Surface"]
    was = surface.links[0].from_socket if surface.is_linked else None
    em = nt.nodes.new("ShaderNodeEmission")
    if inp.is_linked:
        nt.links.new(em.inputs["Color"], inp.links[0].from_socket)
    else:
        em.inputs["Color"].default_value = inp.default_value
    nt.links.new(surface, em.outputs["Emission"])

    def restore():
        if was is not None:
            nt.links.new(surface, was)
        nt.nodes.remove(em)
    return restore


def bake_flat(objs, mat):
    """One colour for a material, by letting Blender render it.

    For geometry whose uvs collapse to a point - the grid lines, where every
    vertex samples the same texel - there is no uv area to rasterise into, so
    baking to an image writes nothing. Baking to a colour attribute needs no uvs
    at all, and one colour is the only thing such a mesh can show anyway.

    The new attribute has to be made ACTIVE. These meshes already carry the
    colours the .mod stores, and the bake writes into whichever attribute is
    active - so without this it quietly filled `color0` and left this one at the
    value it was created with, which reads back as a perfectly plausible result.

    Attributes and node edits are undone, so the scene comes out as it went in.
    """
    scene = bpy.context.scene
    saved = _bake_begin(scene, objs)
    unemit = _emit_shader(mat)
    attrs = []
    try:
        for ob in objs:
            me = ob.data
            prev = getattr(me.color_attributes.active_color, "name", None)
            a = me.color_attributes.new(name="umvc3_bake",
                                        type="FLOAT_COLOR", domain="CORNER")
            me.color_attributes.active_color = a
            attrs.append((ob, a.name, prev))
        scene.render.bake.target = "VERTEX_COLORS"
        bpy.ops.object.bake(type="EMIT")
        tot, n = [0.0, 0.0, 0.0], 0
        for ob, name, _ in attrs:
            for d in ob.data.color_attributes[name].data:
                c = d.color          # linear, like every other colour here
                for i in range(3):
                    tot[i] += c[i]
                n += 1
        return tuple(v / n for v in tot) if n else None
    finally:
        for ob, name, prev in attrs:
            me = ob.data
            a = me.color_attributes.get(name)
            if a is not None:
                me.color_attributes.remove(a)
            if prev is not None and prev in me.color_attributes:
                me.color_attributes.active_color = me.color_attributes[prev]
        if unemit is not None:
            unemit()
        _bake_end(scene, saved)


def bake_image(objs, mat, W, H, seed):
    """Render the material into the whole texture, through its own uvs.

    `seed` is the texture as it stands, top-down bytes; the bake only writes
    where the faces land, so starting from it keeps everything else on a shared
    sheet intact. Returns the same shape back.
    """
    scene = bpy.context.scene
    img = bpy.data.images.new("umvc3_bake", width=W, height=H, alpha=True)
    px = [0.0] * (W * H * 4)
    for y in range(H):                       # bytes are top-down, Blender is not
        s, d = ((H - 1 - y) * W) * 4, (y * W) * 4
        for i in range(W * 4):
            px[d + i] = seed[s + i] / 255.0
    img.pixels[:] = px
    unemit = _emit_shader(mat)
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    was_active = mat.node_tree.nodes.active
    mat.node_tree.nodes.active = node      # the bake target is the ACTIVE node
    saved = _bake_begin(scene, objs)
    try:
        scene.render.bake.target = "IMAGE_TEXTURES"
        scene.render.bake.margin = 4
        bpy.ops.object.bake(type="EMIT")
        return M.image_pixels_topdown(img, W, H)
    finally:
        _bake_end(scene, saved)
        mat.node_tree.nodes.active = was_active
        mat.node_tree.nodes.remove(node)
        if unemit is not None:
            unemit()
        bpy.data.images.remove(img)


def bake_flat_materials(scene, by_key, report=print, owns=None):
    """Write every material into the texture its mesh samples, however it is shaded.

    The engine has no shader graph - what a mesh shows comes from its texture -
    so anything other than "show my own texture" has to be resolved to pixels.
    Rather than understand node graphs, this lets Blender render them: a flat
    colour is read straight off, and everything else - ambient occlusion, a mix,
    a procedural texture, whatever - is baked with Cycles, which is the same
    evaluator the viewport uses.

    Materials that simply show an image are left alone: edited pixels and swapped
    textures already have their own, cheaper, exact paths.
    """
    jobs, skipped = {}, []
    for ob in scene.objects:
        if ob.type != "MESH" or ob.get("umvc3_entry") is None:
            continue
        if owns is not None and not owns(ob):
            continue
        me = ob.data
        uvl = me.uv_layers.active
        if uvl is None:
            continue
        for slot, mat in enumerate(me.materials):
            if mat is None:
                continue
            if mat.get("umvc3_shader_crc"):
                # This material ships a real shader, which evaluates the graph
                # per pixel on the GPU. Baking it into the texture as well would
                # have the flattened answer showing through the live one - and
                # the two disagree by construction, because baking is what the
                # shader exists to stop doing.
                continue
            src = M.base_color_source(M.base_color_input(mat))
            if src is not None and src.type == "TEX_IMAGE":
                continue                       # an image: handled elsewhere
            rgb = M.material_flat_color(mat)
            # Only a deliberate recolour: either the user unlinked an image that
            # the importer had put there, or they changed a colour it left alone.
            was = mat.get("umvc3_base")
            if rgb is not None and not mat.get("umvc3_had_image", True) and \
                    was is not None and \
                    max(abs(a - b) for a, b in zip(rgb, was)) < 1e-4:
                continue
            tex = mat.get("umvc3_texture")
            if not tex:
                skipped.append("%s (no texture bound)" % mat.name)
                continue
            e = by_key.get((tex, M.EXT_HASHES["tex"]))
            if e is None:
                skipped.append("%s (%s not in this archive)" % (mat.name, G.leaf(tex)))
                continue
            us, vs = [], []
            for poly in me.polygons:
                if poly.material_index != slot:
                    continue
                for li in poly.loop_indices:
                    u, v = uvl.data[li].uv
                    us.append(u)
                    vs.append(v)
            if not us:
                continue
            j = jobs.setdefault(e.key, {"entry": e, "mats": {}})
            m = j["mats"].setdefault(mat.name, {"mat": mat, "rgb": rgb, "objs": [],
                                                "rects": [], "area": 0.0})
            m["objs"].append(ob)
            m["rects"].append((min(us), max(us), min(vs), max(vs)))
            m["area"] += _uv_area(ob, slot)

    painted = []
    for j in jobs.values():
        e = j["entry"]
        info = M.tex_info(e.data)
        if info is None:
            continue
        W, H = info["width"], info["height"]
        use_alpha = info["fmt"] not in M.BC1_CODES
        px = M.decode_bc(info["payload"], W, H, use_alpha, bottom_up=False)
        flat = [0] * (W * H * 4)
        for i in range(W * H * 4):
            v = px[i]
            flat[i] = int((0.0 if v < 0.0 else (1.0 if v > 1.0 else v)) * 255 + 0.5)
        touched = False
        rects = []
        for name, m in sorted(j["mats"].items()):
            rgb = m["rgb"]
            if rgb is None and m["area"] > 1e-9:
                # Real uv area: render the material through its own mapping, so a
                # gradient or a procedural lands where it belongs rather than
                # collapsing to an average.
                try:
                    flat = bake_image(m["objs"], m["mat"], W, H, flat)
                    touched = True
                    painted.append("%s -> %s baked through its uvs"
                                   % (name, G.leaf(e.name)))
                except Exception as err:
                    skipped.append("%s could not be baked (%s)" % (name, err))
                continue
            if rgb is None:
                # No uv area to rasterise into - one texel is all this mesh can
                # show, so render the material and take its colour.
                try:
                    rgb = bake_flat(m["objs"], m["mat"])
                except Exception as err:
                    skipped.append("%s could not be baked (%s)" % (name, err))
                    continue
                if rgb is None:
                    skipped.append("%s baked to nothing" % name)
                    continue
            for r in m["rects"]:
                rects.append((name, rgb) + r)
        for name, rgb, u0, u1, v0, v1 in rects:
            # the importer stores v flipped, so undo that to get file rows back
            x0, x1 = int(math.floor(u0 * W)), int(math.ceil(u1 * W))
            y0, y1 = int(math.floor((1.0 - v1) * H)), int(math.ceil((1.0 - v0) * H))
            # Bleed. Two reasons, and they compound: uvs are stored as halves, so
            # a coordinate meant for one texel can land a fraction either side of
            # the boundary, and the sampler filters - paint a lone texel and what
            # shows is that texel blended with the neighbours it did not touch.
            x0, x1 = x0 - FLAT_BLEED, x1 + FLAT_BLEED
            y0, y1 = y0 - FLAT_BLEED, y1 + FLAT_BLEED
            # Snap out to whole BC1/BC3 blocks. A block holds two endpoint
            # colours for its 4x4 texels, so a region ending mid-block leaves
            # that block interpolating between the new colour and the old one -
            # solid red came back as a muddy 123,70,85. Whole blocks encode the
            # flat colour exactly.
            x0, y0 = x0 & ~3, y0 & ~3
            x1, y1 = (x1 + 3) & ~3, (y1 + 3) & ~3
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(W, x1), min(H, y1)
            if x1 <= x0 or y1 <= y0:
                skipped.append("%s maps outside %s" % (name, G.leaf(e.name)))
                continue
            share = float((x1 - x0) * (y1 - y0)) / float(W * H)
            if share > FLAT_FOOTPRINT_LIMIT:
                skipped.append("%s covers %.0f%% of %s - paint the image instead"
                               % (name, 100 * share, G.leaf(e.name)))
                continue
            col = [M.linear_to_srgb(c) for c in rgb]
            for y in range(y0, y1):
                for x in range(x0, x1):
                    o = (y * W + x) * 4
                    flat[o], flat[o + 1], flat[o + 2] = col
                    flat[o + 3] = 255
            touched = True
            painted.append("%s -> %s rgb(%d, %d, %d), %d texel(s)"
                           % (name, G.leaf(e.name), col[0], col[1], col[2],
                              (x1 - x0) * (y1 - y0)))
        if touched:
            e.data = info["header"] + M.encode_bc(flat, W, H, use_alpha)
            e.dirty = True

    for m in painted:
        report("[umvc3] material baked: %s" % m)
    for m in skipped:
        report("[umvc3] material NOT baked: %s" % m)
    return painted, skipped


# =============================================================== shaders =====
# The game never compiles HLSL - it has no D3DCompiler import - so authored
# shaders have to arrive as compiled ps_3_0 bytecode and be swapped in at
# CreatePixelShader time by umvc3_shaderdump.asi. That is the whole reason this
# writes .bin files and an ini rather than anything into the .arc.
FXC_CANDIDATES = (
    r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\fxc.exe",
    r"C:\Program Files (x86)\Windows Kits\10\bin\*\x86\fxc.exe",
    r"C:\Program Files\Windows Kits\10\bin\*\x64\fxc.exe",
)


def find_fxc():
    import glob
    best = None
    for pat in FXC_CANDIDATES:
        for p in glob.glob(pat):
            if best is None or p > best:      # highest SDK version wins
                best = p
    return best


def write_shaders(game_dir, report=print):
    """Translate every material carrying a shader target into ps_3_0 bytecode.

    A material opts in by having `umvc3_shader_crc` - the crc of the game shader
    it should replace, which the ASI's identify pass discovers by watching draws
    of that mesh's vertex count. Without it there is nothing to key the
    replacement on, so the material is skipped rather than guessed at.
    """
    from . import shader as SH
    fxc = find_fxc()
    if not fxc:
        return [], ["no fxc.exe found - install the Windows SDK to author shaders"]
    out_dir = os.path.join(game_dir, "shaders")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        return [], ["cannot create %s (%s)" % (out_dir, e)]

    written, problems, entries = [], [], []
    for mat in bpy.data.materials:
        crc = mat.get("umvc3_shader_crc")
        if not crc:
            continue
        inp = M.base_color_input(mat)
        if inp is None:
            problems.append("%s has no Principled BSDF" % mat.name)
            continue
        # Alpha travels too: a laser fades by going transparent, not by darkening.
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        alpha_in = bsdf.inputs["Alpha"] if bsdf and "Alpha" in bsdf.inputs else None
        bad = SH.unsupported_nodes(inp)
        if alpha_in is not None:
            bad += SH.unsupported_nodes(alpha_in)
        if bad:
            problems.append("%s uses nodes this cannot translate: %s"
                            % (mat.name, ", ".join("%s (%s)" % b for b in bad)))
            continue
        try:
            src, notes = SH.emit_hlsl(mat, inp, alpha_in)
        except SH.Unsupported as e:
            problems.append("%s: %s" % (mat.name, e))
            continue
        for n in notes:
            report("[umvc3] shader: %s" % n)
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in mat.name)
        hlsl = os.path.join(out_dir, safe + ".hlsl")
        binp = os.path.join(out_dir, safe + ".bin")
        with open(hlsl, "w") as f:
            f.write(src)
        import subprocess
        r = subprocess.run([fxc, "/nologo", "/T", "ps_3_0", "/E", "main",
                            "/Fo", binp, hlsl],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.isfile(binp):
            # fxc's message names the line, and the .hlsl is on disk beside it,
            # so the failure is inspectable rather than just "it did not build".
            problems.append("%s failed to compile: %s"
                            % (mat.name, (r.stderr or r.stdout or "").strip().splitlines()[-1:]))
            continue
        # Save the graph next to what it generated, so importing gives the nodes
        # back rather than the stock stub. The .hlsl is the output; this is the
        # source, and authoring means editing this.
        try:
            import json
            with open(os.path.join(out_dir, safe + ".nodes.json"), "w") as f:
                json.dump(SH.graph_to_dict(mat), f, indent=1)
        except Exception as err:
            problems.append("%s: could not save its node graph (%s)" % (mat.name, err))
        crc_s = crc if isinstance(crc, str) else "%08X" % int(crc)
        entries.append((crc_s.upper(), "shaders\\%s.bin" % safe))
        written.append("%s -> %s (crc %s)" % (mat.name, os.path.basename(binp), crc_s))

    if entries:
        # Written by hand rather than with WritePrivateProfileString: that adds a
        # BOM, and GetPrivateProfileString cannot find a section behind one.
        ini = os.path.join(game_dir, "umvc3_shaderdump.ini")
        keep = []
        if os.path.isfile(ini):
            with open(ini, "r") as f:
                for line in f:
                    if line.strip().lower().startswith("[replace]"):
                        break
                    keep.append(line.rstrip("\r\n"))
        with open(ini, "wb") as f:
            for line in keep:
                f.write((line + "\r\n").encode("ascii", "replace"))
            f.write(b"[replace]\r\n")
            for crc_s, path in entries:
                f.write(("%s=%s\r\n" % (crc_s, path)).encode("ascii", "replace"))
        report("[umvc3] %d shader(s) registered in %s" % (len(entries), ini))
    for w in written:
        report("[umvc3] shader built: %s" % w)
    for p in problems:
        report("[umvc3] shader NOT built: %s" % p)
    return written, problems


# ================================================================== install ===
def unmodified_portrait(img):
    """Is this image still the portrait file it was loaded from?

    Carrying the tag is not enough. A portrait is changed in place as readily as
    it is replaced - point the datablock at your own art, or paint on it - and
    the tag says which portrait the image stands for, not that it still looks
    like it. Trusting the tag alone is what made an edited She-Hulk install as
    nothing at all, leaving the stock portrait, frame and background and all,
    in the game.
    """
    p = img.get("umvc3_portrait")
    if not p or not os.path.isfile(p) or img.is_dirty:
        return False
    here = bpy.path.abspath(img.filepath) if img.filepath else ""
    if not here:
        # decoded straight into the datablock, which is the format 42 route -
        # there was never a file, so there is nothing that could have changed
        return True
    # By FILE NAME, not by path. A portrait is opened through a `.dds` named
    # after it, but which cache directory holds it depends on what the scene was
    # opened from: importing a screen caches beside the archive, Set Portrait
    # beside the portrait. Comparing whole paths called 133 untouched cards
    # edited, and re-encoding those would have installed the greyscale preview
    # of every format 42 portrait in the game.
    return os.path.basename(here) == os.path.basename(p) + ".dds"


def card_portrait_edits(scene, game_dir):
    """Cards showing an image the game would not show back.

    Putting an image on a card's material is the obvious way to say "this card
    should look like this", and it is an edit to a *portrait*, not to a texture:
    a card samples the shared card sheet, and what a player sees on it is the
    character's own `.tex`, bound per slot at runtime. So this is the only path
    that can carry such an edit - rebinding cannot (the sheet is not what
    shows), and painting the sheet would take every other card down with it.

    -> [(card, image, Slot, portrait stem)] for the cards whose face has moved
    off the portrait it was imported with. Whether that image is already
    installed is the writer's business: the card goes on showing the source
    image - it is the user's, and they may still be working on it - so the
    written file is the only record of what the game has.
    """
    ce = R.read_ce_roster(game_dir)
    out = []
    for ob in scene.objects:
        if not ob.get("umvc3_card") or ob.get("umvc3_is_banner"):
            continue
        face = card_face(ob)
        if face is None or not face.data.materials:
            continue
        mat = face.data.materials[0]
        img = M.material_shown_image(mat)
        # An archive texture here is the untouched import state - a card whose
        # portrait would not load still shows the sheet - and rebinding owns it.
        if img is None or img.get("umvc3_entry"):
            continue
        who = R.resolve(ob.get("umvc3_char") or "", ce)
        stem = R.portrait_stem(who)
        stock = unmodified_portrait(img)
        shown = img.get("umvc3_portrait")
        # By name, not by path: a card still showing the portrait it was
        # imported with has not been edited, even when the scene is being
        # installed into a different copy of the game than it was read from.
        # It has to still BE that portrait, though - see above.
        if stem and stock and R.is_portrait_of(shown, stem):
            continue
        # A card with no character showing some portrait is a card as it was
        # imported or cloned, not an edit - a clone inherits the face of the
        # card it came from. Only art from outside is somebody asking for this.
        if not stem and stock:
            continue
        out.append((ob, img, who, stem))
    return out


def _soft_alpha(img):
    """Has this image alpha that BC1's single bit cannot represent?

    Only worth saying when it is genuinely part-way: fully opaque art has
    nothing to lose, and a clean cut-out survives the trip exactly.
    """
    lo, hi = M.BC1_ALPHA_CUTOFF / 255.0 * 0.5, 1.0 - 1.0 / 255.0
    try:
        return any(lo < a < hi for a in img.pixels[3::4])
    except (RuntimeError, ValueError, AttributeError):
        return False


def write_portraits(game_dir, scene=None, report=print):
    """Write back every portrait the scene changed.

    Two ways to change one and both have to work: painting the portrait the
    importer put on a card, and putting a different image on that card's
    material. The second used to reach nothing at all - the image is in no
    archive, so every other export path skipped it - and the card came back from
    the install still wearing the portrait it shipped with.

    An image put on a material ships as it is. Fitting it into the art window
    and laying the torn-photo frame over the margin is what **Set Portrait**
    is for, asked for explicitly; doing it here would mean the only way to put
    an exact image on a card is a path that always edits it.

    Painted ones go first, so that by the time a card's image is copied to
    another character the file it names is already what its pixels say.
    """
    written, failed = [], []
    for img in bpy.data.images:
        path = img.get("umvc3_portrait")
        if not path or not (img.is_dirty or img.get("umvc3_portrait_dirty")):
            continue
        try:
            with open(path, "rb") as f:
                ref = f.read()
            data = R.portrait_bytes(img, ref)
            with open(path, "wb") as f:
                f.write(data)
            img["umvc3_portrait_dirty"] = False
            written.append(os.path.basename(path))
        except Exception as err:
            failed.append("%s (%s)" % (os.path.basename(path), err))

    for card, src, who, stem in (card_portrait_edits(scene, game_dir)
                                 if scene is not None else ()):
        if not stem:
            failed.append("%s shows %s but has no character assigned - the game "
                          "binds portraits per character, so there is no file to "
                          "write" % (card.name, src.name))
            continue
        out = R.portrait_path(game_dir, stem, 0)
        # An UNTOUCHED portrait file is already a portrait: right size, already a
        # format the game reads. Copy it rather than re-encode what Blender was
        # shown - stock portraits are format 42, of which only the alpha has ever
        # been decoded, and rebuilding one from that luminance preview would
        # install a greyscale card. One the user has since repointed or painted
        # is not that file any more, whatever its tag says, and copying it would
        # install exactly the art they replaced.
        from_file = src.get("umvc3_portrait") if unmodified_portrait(src) else None
        # Any stock portrait donates the header for the rest; the format field
        # is rewritten to 19 regardless, because 42 is not decodable by anything
        # this pipeline can write.
        ref_path = R.find_portrait(game_dir, stem) or R.find_portrait(game_dir, "Ryu")
        if not from_file and not ref_path:
            failed.append("%s: no portrait in %s to take a header from"
                          % (card.name, R.portrait_dir(game_dir)))
            continue
        try:
            if from_file:
                with open(from_file, "rb") as f:
                    data = f.read()
            else:
                # The image as it stands, scaled to the .tex and encoded. No
                # window, no frame: this path means "put THIS on the card", and
                # anything laid over it is the install second-guessing the art.
                # Set Portrait is where fitting into the torn photo lives.
                with open(ref_path, "rb") as f:
                    ref = f.read()
                data = R.portrait_bytes(src, ref)
            # The card keeps showing the user's own image, so what has already
            # been installed is not recorded anywhere but the file itself.
            # Comparing against it is what stops every install rewriting every
            # custom portrait - and it is the truth, not a note about it.
            if not R.file_differs(out, data):
                continue
            if os.path.isfile(out) and not os.path.isfile(out + ".bak"):
                shutil.copy2(out, out + ".bak")
            with open(out, "wb") as f:
                f.write(data)
        except Exception as err:
            failed.append("%s -> %s (%s)" % (card.name, os.path.basename(out), err))
            continue
        written.append(os.path.basename(out))
        report("[umvc3] portrait %s: %s shows %s -> %s (%s)"
               % ("copied" if from_file else "written", card.name, src.name,
                  os.path.basename(out), who.label))
        if not from_file and _soft_alpha(src):
            report("[umvc3] %s has partly transparent pixels; a portrait carries "
                   "one bit of alpha, so they are kept or punched out at %d%%, "
                   "not faded" % (src.name, round(M.BC1_ALPHA_CUTOFF * 100 / 255.0)))
    return written, failed


NEW_ROW_SLOTS = 8          # g_newRow[8], applied as g_newRow[slot % 8]
DEFAULT_NEW_ROWS = (16, 19, 18, 12, 36, 29, 31, 32)


def assignments(scene, rows, cols):
    """{slot: assignment key} for every card in the scene."""
    out = {}
    for ob in scene.objects:
        if not ob.get("umvc3_card") or ob.get("umvc3_is_banner"):
            continue
        slot = G.slot_of(ob["umvc3_page"], ob["umvc3_joint_col"], ob["umvc3_row"],
                         rows, cols)
        key = ob.get("umvc3_char")
        if key:
            out[slot] = key
    return out


def plan_placement(scene, rows, cols, ce_roster):
    """Turn the scene's assignments into what the game actually reads.

    Two different mechanisms, because the engine has two:

      * **vanilla characters** are placed by the grid table, so they become the
        plugin's `[Layout]` - slot -> character id, for slots 0-55 only.
      * **CloneEngine characters** are claimed by CE from slot 56 up **by index**
        and the table is ignored there, so placing one means putting it at that
        index in Characters.ini.

    -> (layout {slot: id}, ce_order [CharacterID], problems [str])
    """
    keys = assignments(scene, rows, cols)
    layout, ce_at, problems = {}, {}, []
    seen_ce = {}
    for slot, key in sorted(keys.items()):
        source, ident = R.parse_key(key)
        if source == "vanilla":
            # A blank is the absence of a placement, not a placement of nobody:
            # the cells behind the banner plate and the tail past CE's roster are
            # blank by construction and have nothing to report.
            if ident in R.UNKNOWN_IDS:
                continue
            if slot >= R.VANILLA_SLOTS:
                problems.append(
                    "slot %d holds %s, but CloneEngine claims every slot from %d "
                    "up by index and ignores the table there"
                    % (slot, R.display_name(R.VANILLA_NAMES.get(ident, str(ident))),
                       R.VANILLA_SLOTS))
                continue
            layout[slot] = ident
        elif source == "clone-engine":
            if slot < R.VANILLA_SLOTS:
                problems.append(
                    "slot %d holds the CloneEngine character %s, but CE only owns "
                    "slots %d and up" % (slot, ident, R.VANILLA_SLOTS))
                continue
            if ident not in ce_roster:
                problems.append("%s is not a playable entry in Characters.ini" % ident)
                continue
            # CE deals its roster out one entry per slot, so the same character
            # on two cards leaves some other character with nowhere to go. Catch
            # it here, by name, rather than let the rewrite discover it.
            if ident in seen_ce:
                problems.append(
                    "%s is on two cards, slots %d and %d - CloneEngine gives each "
                    "character exactly one slot, so placing it twice would push "
                    "another character out of the roster"
                    % (ident, seen_ce[ident], slot))
                continue
            seen_ce[ident] = slot
            ce_at[slot - R.VANILLA_SLOTS] = ident

    # CE reads its roster as a dense list, so the order is index 0 upward; any
    # index nobody claimed keeps whichever character is spare, so nothing is
    # dropped from the roster just because it was not placed.
    spare = [c for c in ce_roster if c not in set(ce_at.values())]
    ce_order, si = [], 0
    for i in range(len(ce_roster)):
        if i in ce_at:
            ce_order.append(ce_at[i])
        elif si < len(spare):
            ce_order.append(spare[si])
            si += 1
    return layout, ce_order, problems


def write_ini(game_dir, stage=4, new_rows=None, layout=None):
    """The plugin's ini. Never with a BOM - GetPrivateProfileIntA cannot find
    [Config] behind one and silently returns the default."""
    new_rows = list(new_rows or DEFAULT_NEW_ROWS)[:NEW_ROW_SLOTS]
    path = os.path.join(game_dir, "umvc3_cssslots.ini")
    lines = [
        "[Config]",
        "; Each stage includes the ones below it.",
        ";   0 = inert (loaded, patches nothing)",
        ";   1 = relocate the grid table only",
        ";   2 = + walk the grid as the new rows x columns",
        ";   3 = + give the new cells their own cards",
        ";   4 = + tell the cursor the new grid size",
        "Stage=%d" % stage,
        "",
        "; Character ids written into every added row, left to right across both",
        "; sides, and repeated every 8 slots. CloneEngine claims each slot from 56",
        "; up by index and substitutes its own roster there, so these are only ever",
        "; visible if CE is not installed.",
        "[NewRows]",
    ]
    for i, v in enumerate(new_rows):
        lines.append("Slot%d=%d" % (i, v))
    if layout:
        lines += [
            "",
            "; Where each vanilla character sits, straight out of the Blender",
            "; scene: slot -> character id. Slots not listed are worked out the",
            "; old way. Only slots 0-%d mean anything - CloneEngine claims every"
            % (R.VANILLA_SLOTS - 1),
            "; slot above that by index, so CE characters are placed by their",
            "; order in Characters.ini instead.",
            "[Layout]",
        ]
        for slot in sorted(layout):
            lines.append("Slot%d=%d" % (slot, layout[slot]))
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


PLUGIN_ROWS, PLUGIN_COLS = 9, 16
# vfn17 divides by the row count in a fixed instruction shape; the magic must be
# the unsigned one. magic.py verifies these exhaustively.
DIVIDE_MAGIC = {7: (0x24924925, 2), 8: (0x00000000, 2), 9: (0xC71C71C8, 3),
                16: (0x00000000, 3), 18: (0xC71C71C8, 4)}


def plugin_mismatch(rows, cols):
    """What the compiled plugin would have to change to match this grid.

    NEW_ROWS and COLS are compile-time constants in umvc3_cssslots.cpp - only
    Stage and [NewRows] come from the ini - so a grid this plugin was not built
    for cannot be fixed by writing a file."""
    if (rows, cols) == (PLUGIN_ROWS, PLUGIN_COLS):
        return None
    msg = ["the installed plugin is built for %d rows x %d columns, this scene "
           "is %d x %d" % (PLUGIN_ROWS, PLUGIN_COLS, rows, cols),
           "rebuild asi/umvc3_cssslots.cpp with NEW_ROWS = %d, COLS = %d" % (rows, cols)]
    if cols & (cols - 1):
        msg.append("WARNING: %d columns is not a power of two - col = slot & (COLS-1) "
                   "and row = slot >> log2(COLS) stop working and both need "
                   "mod/div detours" % cols)
    m = DIVIDE_MAGIC.get(rows)
    if m:
        msg.append("vfn17 divide: MAGIC 0x%08X at 0x36E091, SHIFT %d at 0x36E0A1"
                   % (m[0], m[1]))
    else:
        msg.append("vfn17 divide: run magic.py to derive the magic/shift for /%d" % rows)
    return msg


def install(context, game_dir, follow_page=True, refit_weights=True,
            do_portraits=True, do_ini=True, do_placement=True, stage=4,
            report=print):
    """Write the scene into the game: archives, portraits, placement, ini."""
    ui = os.path.join(game_dir, UI_DIR)
    if not os.path.isdir(ui):
        raise RuntimeError("no %s under %s" % (UI_DIR, game_dir))
    primary = os.path.join(ui, ARC_NAME)
    stats = export_css(context, primary, follow_page=follow_page,
                       refit_weights=refit_weights, report=report)
    # The game loads mnchscmn_en.arc, not mnchscmn.arc. Write both or you will
    # test nothing.
    alt = os.path.join(ui, ARC_ALT)
    with open(primary, "rb") as f:
        blob = f.read()
    with open(alt, "wb") as f:
        f.write(blob)
    stats["archives"] = [primary, alt]

    # The same for the rest of the screen: each was read from the localised copy
    # where there is one, and the unlocalised one beside it would otherwise still
    # hold the old models.
    for out, _models, _texs in stats.get("screen", ()):
        stats["archives"].append(out)
        base = os.path.basename(out)
        if not base.endswith("_en.arc"):
            continue
        sib = os.path.join(os.path.dirname(out), base[:-len("_en.arc")] + ".arc")
        if not os.path.isfile(sib):
            continue
        if not os.path.isfile(sib + ".bak"):
            shutil.copy2(sib, sib + ".bak")
        shutil.copy2(out, sib)
        stats["archives"].append(sib)

    if do_portraits:
        stats["portraits"], stats["portraits_failed"] = write_portraits(
            game_dir, context.scene, report)
    stats["shaders"], stats["shaders_failed"] = write_shaders(game_dir, report)

    layout, ce_order, problems = {}, [], []
    if do_placement:
        ce_roster = R.read_ce_roster(game_dir)
        layout, ce_order, problems = plan_placement(
            context.scene, stats["rows"], stats["cols"], ce_roster)
        for p in problems:
            report("[umvc3] placement: %s" % p)
        if problems:
            # An ambiguous layout has no single right answer, and this rewrites
            # the roster the rest of the game reads. Say what is wrong and leave
            # Characters.ini alone rather than guess.
            report("[umvc3] Characters.ini left untouched until the %d placement "
                   "problem(s) above are resolved" % len(problems))
        elif ce_order and ce_order != ce_roster:
            ini = os.path.join(game_dir, "Characters.ini")
            if not os.path.isfile(ini + ".bak"):
                import shutil
                shutil.copy2(ini, ini + ".bak")
            _, seq = R.rewrite_characters_ini(ini, ce_order)
            stats["characters_ini"] = sum(1 for a, b in zip(seq, ce_roster) if a != b)
            report("[umvc3] Characters.ini reordered - %d entr(ies) changed slot"
                   % stats["characters_ini"])
    stats["layout"] = layout
    stats["placement_problems"] = problems

    if do_ini:
        stats["ini"] = write_ini(game_dir, stage=stage, layout=layout or None)
    stats["plugin"] = plugin_mismatch(stats["rows"], stats["cols"])
    return stats
