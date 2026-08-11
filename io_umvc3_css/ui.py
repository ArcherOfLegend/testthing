"""Panel and operators for the character-select scene."""
import os
import shutil
import tempfile

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       StringProperty)
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import anim as A
from . import grid as G
from . import mod as M
from . import portraits as P
from . import roster as R
from . import scene as S
from . import verify as V


def prefs(context):
    try:
        return context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


def default_game_dir(context):
    p = prefs(context)
    from_pref = bpy.path.abspath(p.game_dir) if p and p.game_dir else ""
    return getattr(context.scene, S.S_GAME, "") or from_pref


def selected_cards(context):
    out = []
    for ob in context.selected_objects:
        if ob.get("umvc3_card"):
            out.append(ob)
        elif ob.parent is not None and ob.parent.get("umvc3_card"):
            out.append(ob.parent)
    seen, uniq = set(), []
    for ob in out:
        if ob.name not in seen:
            seen.add(ob.name)
            uniq.append(ob)
    return uniq


def active_card(context):
    ob = context.active_object
    if ob is None:
        return None
    if ob.get("umvc3_card"):
        return ob
    if ob.parent is not None and ob.parent.get("umvc3_card"):
        return ob.parent
    return None


def _pending_portrait(card):
    """The image of the user's own that a card's face has been given.

    Drawn every redraw, so it stays inside the scene: an image belonging to
    neither the archive nor the portrait folder is one the user brought in, and
    that is the one worth naming. Which character's file it becomes is the
    installer's business, and needs Characters.ini to answer."""
    if card.get("umvc3_is_banner"):
        return None
    face = S.card_face(card)
    if face is None or not face.data.materials:
        return None
    img = M.material_shown_image(face.data.materials[0])
    if img is None or img.get("umvc3_entry"):
        return None
    # A portrait datablock the user has repointed or painted is their art now,
    # whatever its tag still says, and is exactly what wants naming here.
    if img.get("umvc3_portrait") and S.unmodified_portrait(img):
        return None
    return img


# ================================================================ operators ===
class UMVC3_OT_css_import(bpy.types.Operator):
    """Open the whole character select: every model, its portraits, and the
    cards grouped with the overlays that highlight them"""
    bl_idname = "umvc3.css_import"
    bl_label = "Import Character Select"
    bl_options = {"REGISTER", "UNDO"}

    game_dir: StringProperty(
        name="Game Folder", subtype="DIR_PATH",
        description="The UMvC3 install. Portraits and CloneEngine's roster are "
                    "read from here; leave blank to load an archive only")
    arc_path: StringProperty(
        name="Archive", subtype="FILE_PATH",
        description="Override which .arc to open. Blank uses the game folder's "
                    "mnchscmn_en.arc, which is the one the game actually loads")
    scale: FloatProperty(
        name="Scale", default=0.01, min=0.0001, max=10.0,
        description="Game units are large (~1500 across); 0.01 keeps the screen "
                    "inside Blender's default clipping")
    load_portraits: BoolProperty(
        name="Load Portraits", default=True,
        description="Put each character's real portrait on their card")
    hide_overlays: BoolProperty(
        name="Hide Overlays", default=True,
        description="Hide the hover/select frames. They are drawn in front of "
                    "the cards and are wider than them, so left visible they "
                    "cover the portraits and take every click")
    place_layout: BoolProperty(
        name="Place From Layout", default=True,
        description="Put the models that carry no coordinates of their own - "
                    "the big card and its plates, the cursor - where the .sdl "
                    "scheduler draws them, instanced onto an empty per node. "
                    "The book and its card grids are left where they are, "
                    "because that is where an edit is written back from")
    animate: BoolProperty(
        name="Import Animation", default=True,
        description="Bring the schedulers' keyframes across as Blender "
                    "animation - the card stack flying in, the cards rolling "
                    "through their slots, the cursor. Each clip becomes its own "
                    "action, laid back out as NLA strips so the whole timeline "
                    "still plays, and the scene opens at the settle frame, so it "
                    "looks the same as it would without this")
    load_screen: BoolProperty(
        name="Whole Screen", default=True,
        description="Also load the models in the other character-select "
                    "archives - the team and assist panels, the cursor. They "
                    "are authored about the same origin, so they arrive where "
                    "they sit on screen, and they are written back to their own "
                    "archives on install")

    def invoke(self, context, event):
        if not self.game_dir:
            self.game_dir = default_game_dir(context)
        return context.window_manager.invoke_props_dialog(self, width=460)

    def execute(self, context):
        gd = bpy.path.abspath(self.game_dir) if self.game_dir else None
        arc = bpy.path.abspath(self.arc_path) if self.arc_path else None
        if gd and not os.path.isdir(gd):
            self.report({"ERROR"}, "No such folder: %s" % gd)
            return {"CANCELLED"}
        try:
            r = S.import_css(context, game_dir=gd, arc_path=arc, scale=self.scale,
                             load_portraits=self.load_portraits,
                             hide_overlays=self.hide_overlays,
                             load_screen=self.load_screen,
                             place_layout=self.place_layout,
                             animate=self.animate,
                             report=lambda m: self.report({"INFO"}, m))
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        msg = "%d x %d grid: %d card meshes in %d groups, %d portraits" % (
            r["rows"], r["cols"], r["cards"], r["groups"], r["portraits"])
        if r.get("screen"):
            msg += ", %d model(s) from %d other archive(s)" % (
                r["screen"], len(r["screen_arcs"]))
        if r.get("placed"):
            msg += ", %d placed from the layout" % r["placed"]
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class UMVC3_OT_css_export(bpy.types.Operator, ExportHelper):
    """Write the edited screen to an .arc, without touching the game"""
    bl_idname = "umvc3.css_export"
    bl_label = "Export Character Select"
    filename_ext = ".arc"
    filter_glob: StringProperty(default="*.arc", options={"HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = S.ARC_NAME
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        sc = context.scene
        try:
            r = S.export_css(context, self.filepath,
                             follow_page=sc.umvc3_css_follow_page,
                             refit_weights=sc.umvc3_css_refit,
                             report=lambda m: self.report({"INFO"}, m))
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        msg = "%d models, %d cards (%d moved, %d re-uv'd, %d renumbered), %d KB" % (
            r["models"], r["cards"], r["moved"], r["reuvd"], r["renumbered"],
            r["size"] // 1024)
        if r.get("layouts"):
            msg += "; animation: %s" % ", ".join(
                "%s (%d track%s)" % (leaf, len(t), "" if len(t) == 1 else "s")
                for leaf, t in r["layouts"])
        if r.get("screen"):
            msg += "; %s" % ", ".join(os.path.basename(p) for p, _m, _t in r["screen"])
        if r.get("off_page"):
            self.report({"WARNING"}, msg + "; %d card(s) sit off the book - see "
                                           "the console" % len(r["off_page"]))
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class UMVC3_OT_css_load_screen(bpy.types.Operator):
    """Add the models in the other character-select archives to this scene.

    For a scene imported before they were loaded: re-importing would bring them
    in as well, and throw away every edit in the scene on the way"""
    bl_idname = "umvc3.css_load_screen"
    bl_label = "Load Rest Of Screen"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        gd = bpy.path.abspath(getattr(context.scene, S.S_GAME, "") or "")
        if not gd or not os.path.isdir(gd):
            self.report({"ERROR"}, "Set the game folder first")
            return {"CANCELLED"}
        try:
            added, arcs = S.load_screen_into(context, gd,
                                             report=lambda m: print("[umvc3] " + m))
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if not added:
            self.report({"WARNING"}, "nothing to add - %s"
                        % ("already loaded" if arcs else "no other archive found"))
            return {"CANCELLED"}
        self.report({"INFO"}, "%d model(s) from %s"
                    % (added, ", ".join(os.path.basename(p) for p in arcs)))
        return {"FINISHED"}


def clip_items(self, context):
    """Every clip action in the scene, as <layout> | <clip>."""
    out = []
    for act in sorted(bpy.data.actions, key=lambda a: a.name):
        if act.get(A.A_CLIP) is None:
            continue
        rng = list(act.get(A.A_RANGE) or [0, 0])
        out.append((act.name, act.name, "frames %d to %d" % (rng[0], rng[1])))
    return out or [("", "no clips imported", "")]


class UMVC3_OT_css_edit_clip(bpy.types.Operator):
    """Put one clip in front to work on.

    The clips play from their NLA strips; this assigns the chosen one as the
    active action too, so the dope sheet and graph editor show that clip alone,
    and sets the preview range to the frames it covers. Done puts it back"""
    bl_idname = "umvc3.css_edit_clip"
    bl_label = "Edit Clip"
    bl_options = {"REGISTER", "UNDO"}

    clip: EnumProperty(name="Clip", items=clip_items)

    def execute(self, context):
        act = bpy.data.actions.get(self.clip)
        if act is None:
            self.report({"ERROR"}, "no such clip")
            return {"CANCELLED"}
        entry, n = act.get(A.O_SDL), 0
        for ob in context.scene.objects:
            if ob.get(A.O_SDL) != entry:
                continue
            slot = A.slot_of(act, ob)
            if slot is None:
                continue
            ad = ob.animation_data or ob.animation_data_create()
            ad.action = act
            ad.action_slot = slot
            n += 1
        lo, hi = (list(act.get(A.A_RANGE)) or [0, 0])[:2]
        sc = context.scene
        sc.use_preview_range = True
        sc.frame_preview_start, sc.frame_preview_end = int(lo), int(hi)
        sc.frame_current = int(lo)
        self.report({"INFO"}, "%s: %d node(s), frames %d to %d"
                    % (act.name, n, lo, hi))
        return {"FINISHED"}


class UMVC3_OT_css_end_clip(bpy.types.Operator):
    """Stop working on one clip: back to the whole timeline, played from the
    strips. Nothing is discarded - the clip's action is where its keys live"""
    bl_idname = "umvc3.css_end_clip"
    bl_label = "Done"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = 0
        for ob in context.scene.objects:
            ad = ob.animation_data
            if ob.get(A.O_SDL) and ad is not None and ad.action is not None:
                ad.action = None
                n += 1
        context.scene.use_preview_range = False
        self.report({"INFO"}, "back to the whole timeline (%d node(s))" % n)
        return {"FINISHED"}


class UMVC3_OT_css_verify(bpy.types.Operator):
    """Run the pre-install checks on what would be exported, changing nothing.

    Joint ids against names, .mrl bindings one-to-one, no two cards in a cell,
    cards aligned, weights sane, and drift against the stock archive"""
    bl_idname = "umvc3.css_verify"
    bl_label = "Verify"

    def execute(self, context):
        sc = context.scene
        tmp = os.path.join(tempfile.gettempdir(), "umvc3_css_verify.arc")
        try:
            r = S.export_css(context, tmp, follow_page=sc.umvc3_css_follow_page,
                             refit_weights=sc.umvc3_css_refit, report=lambda m: None)
            problems, warnings, lines = V.verify_file(
                tmp, r["rows"], r["cols"] // 2, stock_path=sc.get(S.S_ARC))
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        for l in lines:
            print("[umvc3] " + l)
        for p in problems[:20]:
            print("[umvc3] PROBLEM: " + p)
        for w in warnings[:20]:
            print("[umvc3] off-grid: " + w)
        if problems:
            self.report({"WARNING"}, "%d problem(s) - see the console" % len(problems))
        elif warnings:
            # A rearranged screen is the point of this addon, so this is news,
            # not an error.
            self.report({"INFO"}, "checks passed; %d card(s) sit off the regular "
                                  "grid - see the console" % len(warnings))
        else:
            self.report({"INFO"}, "all checks passed (%d models)" % len(lines))
        return {"FINISHED"}


class UMVC3_OT_css_install(bpy.types.Operator):
    """Write the screen into the game: both archives, edited portraits, and the
    plugin ini. Backs up anything it overwrites the first time"""
    bl_idname = "umvc3.css_install"
    bl_label = "Install Into Game"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        sc = context.scene
        gd = bpy.path.abspath(getattr(sc, S.S_GAME, "") or "")
        if not gd or not os.path.isdir(gd):
            self.report({"ERROR"}, "Set the game folder first")
            return {"CANCELLED"}
        for name in (S.ARC_NAME, S.ARC_ALT):
            p = S.arc_in(gd, name)
            if os.path.isfile(p) and not os.path.isfile(p + ".bak"):
                shutil.copy2(p, p + ".bak")
        try:
            r = S.install(context, gd,
                          follow_page=sc.umvc3_css_follow_page,
                          refit_weights=sc.umvc3_css_refit,
                          do_portraits=sc.umvc3_css_write_portraits,
                          do_ini=sc.umvc3_css_write_ini,
                          do_placement=sc.umvc3_css_write_placement,
                          stage=sc.umvc3_css_stage,
                          report=lambda m: print("[umvc3] " + m))
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        msg = "installed %d models, %d cards" % (r["models"], r["cards"])
        if r.get("screen"):
            msg += ", %d other archive(s): %s" % (
                len(r["screen"]),
                ", ".join(os.path.basename(p) for p, _m, _t in r["screen"]))
        if r.get("reuvd"):
            msg += ", %d re-uv'd" % r["reuvd"]
        if r.get("portraits"):
            msg += ", %d portrait(s)" % len(r["portraits"])
        if r.get("flat"):
            msg += ", %d flat colour(s)" % len(r["flat"])
        if r.get("rebound"):
            msg += ", %d material(s) rebound" % len(r["rebound"])
        level = "INFO"
        if r.get("layout"):
            msg += ", %d placed" % len(r["layout"])
        if r.get("characters_ini"):
            msg += ", Characters.ini reordered (%d moved)" % r["characters_ini"]
        if r.get("placement_problems"):
            for p in r["placement_problems"]:
                print("[umvc3] placement: " + p)
            msg += "; %d placement problem(s)" % len(r["placement_problems"])
            level = "WARNING"
        if r.get("off_page"):
            msg += "; %d card(s) sit off the book" % len(r["off_page"])
            level = "WARNING"
        if r.get("plugin"):
            for line in r["plugin"]:
                print("[umvc3] PLUGIN: " + line)
            msg += " - PLUGIN REBUILD NEEDED, see the console"
            level = "WARNING"
        if r.get("flat_skipped"):
            msg += "; %d flat colour(s) not baked - see the console" % len(r["flat_skipped"])
            level = "WARNING"
        if r.get("portraits_failed"):
            msg += "; failed: " + ", ".join(r["portraits_failed"])
            level = "WARNING"
        self.report({level}, msg)
        return {"FINISHED"}


class UMVC3_OT_css_renumber(bpy.types.Operator):
    """Give the selected cards the joint id of the cell they now sit in.

    Dragging a card does not renumber it - where a card is drawn and which slot
    it answers to are independent - so this is how you move one between cells"""
    bl_idname = "umvc3.css_renumber"
    bl_label = "Renumber From Position"
    bl_options = {"REGISTER", "UNDO"}

    all_cards: BoolProperty(name="All Cards", default=False)

    def execute(self, context):
        sc = context.scene
        rows, cols = sc.umvc3_css_rows, sc.umvc3_css_cols
        geom = S.grid_geometry(sc, rows, cols)
        targets = [o for o in sc.objects if o.get("umvc3_card")] if self.all_cards \
            else selected_cards(context)
        targets = [o for o in targets if not o.get("umvc3_is_banner")]
        if not targets:
            self.report({"ERROR"}, "Select a card")
            return {"CANCELLED"}

        taken = {}
        for o in sc.objects:
            if o.get("umvc3_card") and o not in targets:
                taken[(o["umvc3_page"], o["umvc3_jid"])] = o.name
        changed, clashes = 0, []
        for ob in targets:
            col, row = S.cell_from_position(ob, rows, cols, geom)
            jid = G.jid_of(col, row, rows)
            key = (ob["umvc3_page"], jid)
            if key in taken:
                clashes.append("%s -> %s" % (ob.name, taken[key]))
                continue
            taken[key] = ob.name
            if jid != ob["umvc3_jid"]:
                changed += 1
            ob["umvc3_joint_col"], ob["umvc3_row"], ob["umvc3_jid"] = col, row, jid
            ob["umvc3_slot"] = G.slot_of(ob["umvc3_page"], col, row, rows, cols)
            new_name = "card_%s_c%d_r%d" % (ob["umvc3_page"], col, row)
            cc = S.card_collection(ob)
            if cc is not None:
                cc.name = new_name          # keep the outliner honest
            for mesh in S.card_meshes(ob):
                mesh["umvc3_card_of"] = new_name
                if mesh is not ob:
                    mesh.name = "%s_%s" % (new_name, mesh.get("umvc3_kind", "mesh"))
            ob.name = new_name
        if clashes:
            self.report({"WARNING"}, "%d renumbered; %d would collide: %s"
                        % (changed, len(clashes), ", ".join(clashes[:4])))
        else:
            self.report({"INFO"}, "%d card(s) renumbered" % changed)
        return {"FINISHED"}


class UMVC3_OT_css_select_group(bpy.types.Operator):
    """Promote the selection from an overlay mesh to the card that owns it.

    Rarely needed: the card IS the mesh you see, and its overlays are hidden and
    parented to it. This is the way back if you pick an overlay in the outliner"""
    bl_idname = "umvc3.css_select_group"
    bl_label = "Select Whole Card"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        cards = selected_cards(context)
        if not cards:
            self.report({"ERROR"}, "Select part of a card first")
            return {"CANCELLED"}
        for o in context.selected_objects:
            o.select_set(False)
        for c in cards:
            c.select_set(True)
        context.view_layer.objects.active = cards[0]
        self.report({"INFO"}, "selected %d card(s); moving one carries its %d "
                              "meshes" % (len(cards), len(S.card_meshes(cards[0]))))
        return {"FINISHED"}


class UMVC3_OT_css_show_overlays(bpy.types.Operator):
    """Show or hide the hover and select overlays.

    They are drawn in front of the cards and are deliberately wider, so with
    them visible the screen is a wall of frames and every click lands on one"""
    bl_idname = "umvc3.css_show_overlays"
    bl_label = "Toggle Overlays"
    bl_options = {"REGISTER", "UNDO"}

    show: BoolProperty(name="Show", default=True)
    selected_only: BoolProperty(name="Selected Cards Only", default=False)

    def execute(self, context):
        cards = selected_cards(context) if self.selected_only else \
            [o for o in context.scene.objects if o.get("umvc3_card")]
        n = 0
        for card in cards:
            for ob in S.card_meshes(card):
                if ob is card:
                    continue
                ob.hide_set(not self.show)
                n += 1
        self.report({"INFO"}, "%s %d overlay mesh(es)"
                    % ("showed" if self.show else "hid", n))
        return {"FINISHED"}


# Blender keeps no reference to the strings an EnumProperty callback returns, so
# they must be kept alive here or the UI shows garbage. Keyed on Characters.ini's
# mtime, so adding a character to it refreshes the list without a reload.
_ENUM_CACHE = {"key": None, "items": [], "index": {}}


def _rebuild_items(gd):
    rows = R.characters(gd or None)
    by_source = {"special": [], "vanilla": [], "clone-engine": []}
    for key, label, source in rows:
        by_source[source].append((key, label))
    items = []
    for source, heading in (("special", "Special"), ("vanilla", "Vanilla"),
                            ("clone-engine", "CloneEngine")):
        for key, label in by_source[source]:
            items.append((key, label, "%s: %s" % (heading, label)))
    if not items:
        items = [(R.BLANK_KEY, "(blank)", "")]
    _ENUM_CACHE["items"] = items
    _ENUM_CACHE["index"] = {it[0]: i for i, it in enumerate(items)}


def character_items(self, context):
    """Every character the game knows, read live from Characters.ini."""
    ctx = context or bpy.context
    gd = ""
    try:
        gd = bpy.path.abspath(getattr(ctx.scene, S.S_GAME, "") or "")
    except AttributeError:
        pass
    ini = os.path.join(gd, "Characters.ini") if gd else ""
    stamp = (ini, os.path.getmtime(ini)) if ini and os.path.isfile(ini) else None
    if _ENUM_CACHE["key"] != stamp or not _ENUM_CACHE["items"]:
        _ENUM_CACHE["key"] = stamp
        _rebuild_items(gd)
    return _ENUM_CACHE["items"]


def _apply_character(context, card, key):
    """Put `key` on a card and swap its portrait preview to match.

    -> 'ok' | 'no-portrait' | 'no-face' | 'no-game'."""
    card["umvc3_char"] = key
    gd = bpy.path.abspath(getattr(context.scene, S.S_GAME, "") or "")
    who = R.resolve(key, R.read_ce_roster(gd) if gd else ())
    card["umvc3_slot_label"] = who.label
    card["umvc3_slot_source"] = who.source
    face = S.card_face(card)
    if face is None or not face.data.materials:
        return "no-face"
    if not gd:
        return "no-game"
    stem = R.portrait_stem(who)
    path = R.find_portrait(gd, stem) if stem else None
    if not path:
        # blanks and the RANDOM plates legitimately have no portrait file
        card["umvc3_portrait_missing"] = bool(stem)
        return "no-portrait" if stem else "ok"
    img = R.load_portrait(path, M.cache_dir_for(path), stem)
    if img is not None:
        S._set_material_image(face.data.materials[0], img)
    card["umvc3_portrait_missing"] = False
    return "ok"


# --- the inline dropdown ----------------------------------------------------
# `umvc3_char` stays the source of truth as a plain string key, and this enum is
# only a view onto it. A dynamic EnumProperty otherwise stores the *index* of the
# chosen item, and reordering Characters.ini - which placing a CloneEngine
# character does - would then silently repoint every card at whoever moved into
# that position. get/set means Blender stores nothing of its own.
def _char_get(self):
    items = character_items(None, bpy.context)
    key = self.get("umvc3_char") or R.BLANK_KEY
    return _ENUM_CACHE["index"].get(key, 0)


def _char_set(self, value):
    items = character_items(None, bpy.context)
    if 0 <= value < len(items):
        _apply_character(bpy.context, self, items[value][0])


class UMVC3_OT_css_assign(bpy.types.Operator):
    """Put the active card's character on every other selected card too.

    The card panel's dropdown assigns one card; this is the bulk version"""
    bl_idname = "umvc3.css_assign"
    bl_label = "Assign To Selected"
    bl_options = {"REGISTER", "UNDO"}

    character: EnumProperty(name="Character", items=character_items)

    def invoke(self, context, event):
        card = active_card(context)
        if card is not None and card.get("umvc3_char"):
            try:
                self.character = card["umvc3_char"]
            except TypeError:
                pass                      # no longer in Characters.ini
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        cards = [c for c in selected_cards(context) if not c.get("umvc3_is_banner")]
        if not cards:
            self.report({"ERROR"}, "Select a card")
            return {"CANCELLED"}
        missing = 0
        for card in cards:
            if _apply_character(context, card, self.character) == "no-portrait":
                missing += 1
        who = R.resolve(self.character, R.read_ce_roster(
            bpy.path.abspath(getattr(context.scene, S.S_GAME, "") or "")))
        msg = "%d card(s) -> %s" % (len(cards), who.label)
        if missing:
            self.report({"WARNING"}, msg + "; no portrait file yet - use Set Portrait")
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


def _yaw_of(card):
    """How far a card's own long axis is from the grid's, in degrees.

    A squared card reads near 0; a parallelogram left over from flattening a
    tilted card reads tens of degrees."""
    import math
    ob = S.card_face(card) or card
    vs = [v.co for v in ob.data.vertices]
    if len(vs) < 3:
        return 0.0
    n = len(vs)
    cx = sum(v.x for v in vs) / n
    cy = sum(v.y for v in vs) / n
    sxx = sxy = syy = 0.0
    for v in vs:
        dx, dy = v.x - cx, v.y - cy
        sxx += dx * dx
        sxy += dx * dy
        syy += dy * dy
    th = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    best = None
    for k in (0, 1):
        a = th + k * math.pi / 2
        ux, uy = math.cos(a), math.sin(a)
        proj = [(v.x - cx) * ux + (v.y - cy) * uy for v in vs]
        ext = max(proj) - min(proj)
        if best is None or ext > best[0]:
            best = (ext, ux, uy)
    ang = math.degrees(math.atan2(best[1], best[2]))
    while ang > 45.0:
        ang -= 90.0
    while ang < -45.0:
        ang += 90.0
    return abs(ang)


class UMVC3_OT_css_square(bpy.types.Operator):
    """Restore the selected cards' shape from the archive they came from.

    Flattening with S Z 0 projects rather than rotates, so a card that was
    tilted in 3D first lands as a parallelogram - sheared and foreshortened, and
    no rotation will square it again. This puts the original rectangle back,
    keeping where you have since moved the card, and its UVs"""
    bl_idname = "umvc3.css_square"
    bl_label = "Square Cards"
    bl_options = {"REGISTER", "UNDO"}

    keep_flat: BoolProperty(
        name="Keep Flat", default=True,
        description="Hold the card on the plane it is on now. Off, it gets the "
                    "depth and tilt it had on the page")
    selected_only: BoolProperty(name="Selected Cards Only", default=True)
    reference: StringProperty(
        name="Reference .arc", subtype="FILE_PATH",
        description="Archive to take the original shape from. Blank uses the one "
                    "this scene was imported from - which is no good if you have "
                    "already installed the damage, since that IS the source. "
                    "Point it at a known-good build instead")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def execute(self, context):
        from mathutils import Vector
        scene = context.scene
        src = bpy.path.abspath(self.reference) if self.reference \
            else scene.get(S.S_ARC)
        if not src or not os.path.isfile(src):
            self.report({"ERROR"}, "No reference archive - import a scene first "
                                   "or pick one")
            return {"CANCELLED"}
        cards = selected_cards(context) if self.selected_only else \
            [o for o in scene.objects if o.get("umvc3_card")]
        if not cards:
            self.report({"ERROR"}, "Select a card")
            return {"CANCELLED"}

        rows, _cols = S.scene_grid(scene)
        scale = scene.get("umvc3_scale", 0.01)
        _v, entries = M.read_arc(src)
        by_entry = {}
        fixed, skipped, worst = 0, 0, 0.0
        for card in cards:
            for ob in S.card_meshes(card):
                name = ob.get("umvc3_entry")
                mi = ob.get("umvc3_mesh_index")
                if name is None or mi is None:
                    skipped += 1          # a card added in Blender has no source
                    continue
                if name not in by_entry:
                    e = next((x for x in entries if x.ext == "mod" and x.name == name),
                             None)
                    by_entry[name] = {c["index"]: c for c in
                                      G.read_cards(e.data, rows=rows)} if e else {}
                c = by_entry[name].get(mi)
                if c is None or len(ob.data.vertices) != len(c["pts"]):
                    skipped += 1
                    continue
                pts = c["pts"]
                n = len(pts)
                cx = sum(p[0] for p in pts) / n
                cy = sum(p[1] for p in pts) / n
                cz = sum(p[2] for p in pts) / n
                # the plane the card sits on now, so squaring does not undo a
                # flatten the user did on purpose
                flat_z = (sum(v.co.z for v in ob.data.vertices)
                          / len(ob.data.vertices)) if self.keep_flat else None
                for i, v in enumerate(ob.data.vertices):
                    before = Vector(v.co)
                    v.co.x = (pts[i][0] - cx) * scale
                    v.co.y = (pts[i][1] - cy) * scale
                    v.co.z = flat_z if flat_z is not None else (pts[i][2] - cz) * scale
                    worst = max(worst, (Vector(v.co) - before).length / scale)
                ob.data.update()
                fixed += 1

        # A card restored from a reference that carries the same damage comes
        # back just as skewed, and the operator would otherwise report success.
        still = [c.name for c in cards if _yaw_of(c) > 5.0]
        msg = "squared %d mesh(es), moved a vertex by up to %.1f units" % (fixed, worst)
        if skipped:
            msg += "; %d skipped (no geometry in the reference)" % skipped
        if still:
            self.report({"WARNING"}, msg + "; %d still skewed (%s) - the reference "
                                           "has the same damage, point it at a "
                                           "clean build"
                        % (len(still), ", ".join(still[:3])))
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class UMVC3_OT_css_set_portrait(bpy.types.Operator, ImportHelper):
    """Build the active card's portrait from an image.

    Fits it into the 112x76 art window, lays the recovered torn-photo frame back
    over the margin and writes format 19 - format 42, what the stock portraits
    use, is not decodable by anything this pipeline can write. Creates the .tex
    if the assigned character has none yet"""
    bl_idname = "umvc3.css_set_portrait"
    bl_label = "Set Portrait"
    filter_glob: StringProperty(default="*.png;*.tga;*.jpg", options={"HIDDEN"})

    card_aspect: BoolProperty(
        name="Correct For Card Shape", default=False,
        description="Crop to the card's aspect before filling the window, "
                    "cancelling the horizontal squash. Off by default: the 50 "
                    "stock portraits are not made by this pipeline, so "
                    "correcting only some looks worse than a uniform squash")

    def execute(self, context):
        card = active_card(context)
        if card is None:
            self.report({"ERROR"}, "Select a card")
            return {"CANCELLED"}
        face = S.card_face(card)
        if face is None or not face.data.materials:
            self.report({"ERROR"}, "%s has no face mesh to put a portrait on" % card.name)
            return {"CANCELLED"}
        gd = bpy.path.abspath(getattr(context.scene, S.S_GAME, "") or "")
        if not gd:
            self.report({"ERROR"}, "Set the game folder first")
            return {"CANCELLED"}

        who = R.resolve(card.get("umvc3_char") or "", R.read_ce_roster(gd))
        stem = R.portrait_stem(who)
        if not stem:
            self.report({"ERROR"}, "%s has no character assigned - use Assign "
                                   "Character first" % card.name)
            return {"CANCELLED"}

        # Any stock portrait serves as the header donor; the format field is
        # rewritten to 19 regardless of what the reference was.
        ref_path = R.find_portrait(gd, stem) or R.find_portrait(gd, "Ryu")
        if not ref_path:
            self.report({"ERROR"}, "no portrait in %s to take a header from"
                        % R.portrait_dir(gd))
            return {"CANCELLED"}
        try:
            with open(ref_path, "rb") as f:
                ref = f.read()
            src = bpy.data.images.load(self.filepath, check_existing=False)
            try:
                aspect = None
                if self.card_aspect:
                    aspect = _card_aspect(card)
                data = P.build_from_image(src, ref, aspect)
            finally:
                bpy.data.images.remove(src)
            out = R.portrait_path(gd, stem, 0)
            existed = os.path.isfile(out)
            if existed and not os.path.isfile(out + ".bak"):
                shutil.copy2(out, out + ".bak")
            with open(out, "wb") as f:
                f.write(data)
        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        img = R.load_portrait(out, M.cache_dir_for(out), stem)
        if img is not None:
            img.reload()
            S._set_material_image(face.data.materials[0], img)
        self.report({"INFO"}, "%s -> %s (%s)"
                    % (who.label, os.path.basename(out),
                       "replaced" if existed else "created"))
        return {"FINISHED"}


def _card_aspect(card):
    """The card's own width:height in game units, for squash correction."""
    xs = [v.co.x for v in card.data.vertices]
    ys = [v.co.y for v in card.data.vertices]
    h = max(ys) - min(ys)
    return (max(xs) - min(xs)) / h if h else None


class UMVC3_OT_css_add_card(bpy.types.Operator):
    """Clone the active card, and its hover/select overlays, into a free cell"""
    bl_idname = "umvc3.css_add_card"
    bl_label = "Add Card"
    bl_options = {"REGISTER", "UNDO"}

    joint_col: IntProperty(name="Joint Column", default=0, min=0)
    row: IntProperty(name="Row", default=0, min=0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        card = active_card(context)
        if card is None:
            self.report({"ERROR"}, "Select a card to clone")
            return {"CANCELLED"}
        sc = context.scene
        rows, cols = sc.umvc3_css_rows, sc.umvc3_css_cols
        page = card["umvc3_page"]
        jid = G.jid_of(self.joint_col, self.row, rows)
        for o in sc.objects:
            if o.get("umvc3_card") and o["umvc3_page"] == page and o["umvc3_jid"] == jid:
                self.report({"ERROR"}, "cell (%d,%d) on page %s is taken by %s"
                            % (self.joint_col, self.row, page, o.name))
                return {"CANCELLED"}

        geom = S.grid_geometry(sc, rows, cols)
        scale = geom["scale"]
        name = "card_%s_c%d_r%d" % (page, self.joint_col, self.row)

        xs = geom["xs"].get(page) or []
        x = xs[self.joint_col] * scale if self.joint_col < len(xs) else card.location.x
        y = geom["ys"][self.row] * scale if self.row < len(geom["ys"]) else card.location.y
        loc = (x, y, card.location.z)

        col = bpy.data.collections.new(name)
        col["umvc3_card_collection"] = True
        parent_col = S.card_collection(card)
        holder = next((c for c in bpy.data.collections
                       if parent_col is not None and parent_col.name in
                       [ch.name for ch in c.children]), None)
        (holder or sc.collection).children.link(col)

        clones = []
        for src in S.card_meshes(card):
            new = src.copy()
            new.data = src.data.copy()
            new.name = "%s_%s" % (name, src.get("umvc3_kind", "mesh"))
            col.objects.link(new)
            new["umvc3_new_from"] = src["umvc3_mesh_index"]
            del new["umvc3_mesh_index"]
            new["umvc3_jid"] = jid
            new["umvc3_card_of"] = name
            new.location = loc
            new.parent = None
            clones.append((src, new))

        root = next((n for s, n in clones if s.get("umvc3_kind") == "face"),
                    clones[0][1])
        root.name = name
        root["umvc3_card"] = True
        root["umvc3_page"] = page
        root["umvc3_is_banner"] = card["umvc3_is_banner"]
        root["umvc3_joint_col"] = self.joint_col
        root["umvc3_row"] = self.row
        root["umvc3_slot"] = G.slot_of(page, self.joint_col, self.row, rows, cols)
        from mathutils import Matrix
        for _s, new in clones:
            if new is root:
                continue
            new.parent = root
            new.matrix_parent_inverse = Matrix.Translation(root.location).inverted()
            new.hide_set(True)

        self.report({"INFO"}, "cloned %d mesh(es) into collection %s - they become "
                              "new meshes when the archive is written"
                    % (len(clones), name))
        return {"FINISHED"}


# ==================================================================== panels ===
# The panels live in the Properties editor, next to the data they describe: a
# card's character and cell are per-object, the grid and the write options are
# per-scene. The viewport sidebar is a tool shelf, and none of this is a tool.
class UMVC3_PT_css(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_label = "UMVC3 Character Select"

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        arc = sc.get(S.S_ARC)
        if not arc:
            layout.label(text="No character select loaded", icon="INFO")
            layout.operator(UMVC3_OT_css_import.bl_idname, icon="FILE_FOLDER")
            return

        box = layout.box()
        box.label(text=os.path.basename(arc), icon="PACKAGE")
        cards = [o for o in sc.objects if o.get("umvc3_card")]
        pending = [o for o in sc.objects if o.get("umvc3_new_from") is not None]
        box.label(text="%d cards, %d x %d grid" % (len(cards), sc.umvc3_css_rows,
                                                   sc.umvc3_css_cols))
        if pending:
            box.label(text="%d new card mesh(es) pending" % len(pending), icon="ADD")
        # The schedulers' animation, if it was brought in. Says what is animated
        # and over how long, because the timeline is the only other clue and it
        # is shared with anything else in the scene.
        layouts = [c for c in bpy.data.collections if c.get("umvc3_sdl_last_frame")]
        if layouts:
            clips = [a for a in bpy.data.actions if a.get(A.A_CLIP) is not None]
            box.label(text="animated: %s (to frame %d)"
                      % (", ".join(sorted(str(c.get("umvc3_sdl", "?")).split("\\")[-1]
                                          for c in layouts)),
                         max(int(c["umvc3_sdl_last_frame"]) for c in layouts)),
                      icon="ANIM")
            if clips:
                row = box.row(align=True)
                row.operator_menu_enum(UMVC3_OT_css_edit_clip.bl_idname, "clip",
                                       text="%d clips" % len(clips), icon="ACTION")
                row.operator(UMVC3_OT_css_end_clip.bl_idname, icon="LOOP_BACK")
        screen = list(sc.get(S.S_SCREEN) or ())
        if screen:
            box.label(text="with %s" % ", ".join(os.path.basename(p) for p in screen),
                      icon="PACKAGE")
        else:
            # A scene imported before these were loaded; offer them rather than
            # leave re-importing - which discards every edit - as the only way.
            box.operator(UMVC3_OT_css_load_screen.bl_idname, icon="PACKAGE")

        col = layout.column(align=True)
        col.prop(sc, "umvc3_css_rows")
        col.prop(sc, "umvc3_css_cols")
        if (sc.umvc3_css_rows, sc.umvc3_css_cols) != (S.PLUGIN_ROWS, S.PLUGIN_COLS):
            b = layout.box()
            b.label(text="Plugin is built for %d x %d" % (S.PLUGIN_ROWS, S.PLUGIN_COLS),
                    icon="ERROR")
            b.label(text="rows/columns are compile-time constants -")
            b.label(text="rebuild umvc3_cssslots.cpp to match.")

        layout.prop(sc, S.S_GAME, text="Game")


class UMVC3_PT_css_card(bpy.types.Panel):
    """Properties > Object, so it sits with the object it describes and is
    visible without holding the viewport sidebar open."""
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_label = "UMVC3 Card"

    @classmethod
    def poll(cls, context):
        # Only for objects that are part of a card, so the Object tab stays
        # clean for everything else in the scene.
        return active_card(context) is not None

    def draw(self, context):
        layout = self.layout
        card = active_card(context)
        if card is None:
            layout.label(text="Select a card", icon="INFO")
            return
        box = layout.box()
        box.label(text=card.name, icon="TEXTURE")
        box.label(text="%d meshes in this collection" % len(S.card_meshes(card)),
                  icon="OUTLINER_COLLECTION")
        picked = context.active_object
        if picked is not None and picked is not card:
            warn = box.column(align=True)
            warn.label(text="an overlay is active, not the card", icon="ERROR")
            warn.operator(UMVC3_OT_css_select_group.bl_idname, icon="GROUP")
        if card.get("umvc3_is_banner"):
            box.label(text="banner plate (RANDOM + logo)")
        else:
            box.label(text="page %s  joint col %d  row %d"
                      % (card["umvc3_page"], card["umvc3_joint_col"], card["umvc3_row"]))
            box.label(text="joint id %d  ->  slot %d"
                      % (card["umvc3_jid"], card["umvc3_slot"]))

            row = box.row(align=True)
            row.prop(card, "umvc3_character", text="", icon="USER")
            stored = card.get("umvc3_char")
            if stored and stored not in _ENUM_CACHE["index"]:
                box.label(text="%s is not in Characters.ini" % stored, icon="ERROR")
            if card.get("umvc3_portrait_missing"):
                box.label(text="no portrait file yet - use Set Portrait",
                          icon="IMAGE_DATA")
            pending = _pending_portrait(card)
            if pending is not None:
                # Say so here rather than leave the user to discover from the
                # game which face a card is going to ship with.
                box.label(text="portrait: %s (installed as it is)" % pending.name,
                          icon="IMAGE_DATA")
            src = card.get("umvc3_slot_source")
            slot = card.get("umvc3_slot", 0)
            if src == "clone-engine" and slot < R.VANILLA_SLOTS:
                box.label(text="CE only owns slots %d+" % R.VANILLA_SLOTS,
                          icon="ERROR")
            elif src == "vanilla" and slot >= R.VANILLA_SLOTS:
                box.label(text="CloneEngine overrides this slot", icon="ERROR")
        col = layout.column(align=True)
        col.operator(UMVC3_OT_css_assign.bl_idname, icon="USER")
        col.operator(UMVC3_OT_css_set_portrait.bl_idname, icon="IMAGE_DATA")
        col.operator(UMVC3_OT_css_add_card.bl_idname, icon="DUPLICATE")
        col.operator(UMVC3_OT_css_renumber.bl_idname, icon="SORTSIZE")
        col.operator(UMVC3_OT_css_square.bl_idname, icon="MESH_PLANE")

        row = layout.row(align=True)
        row.label(text="Overlays:")
        row.operator(UMVC3_OT_css_show_overlays.bl_idname, text="Show",
                     icon="HIDE_OFF").show = True
        row.operator(UMVC3_OT_css_show_overlays.bl_idname, text="Hide",
                     icon="HIDE_ON").show = False


class UMVC3_PT_css_write(bpy.types.Panel):
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_label = "Write"
    bl_parent_id = "UMVC3_PT_css"

    @classmethod
    def poll(cls, context):
        return context.scene.get(S.S_ARC) is not None

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        col = layout.column(align=True)
        col.prop(sc, "umvc3_css_follow_page")
        col.prop(sc, "umvc3_css_refit")
        col.prop(sc, "umvc3_css_write_portraits")
        col.prop(sc, "umvc3_css_write_placement")
        col.prop(sc, "umvc3_css_write_ini")
        if sc.umvc3_css_write_ini:
            col.prop(sc, "umvc3_css_stage")
        layout.operator(UMVC3_OT_css_verify.bl_idname, icon="CHECKMARK")
        layout.operator(UMVC3_OT_css_export.bl_idname, icon="FILE_TICK")
        row = layout.row()
        row.enabled = bool(getattr(sc, S.S_GAME, ""))
        row.operator(UMVC3_OT_css_install.bl_idname, icon="EXPORT")


CLASSES = (UMVC3_OT_css_import, UMVC3_OT_css_export, UMVC3_OT_css_verify,
           UMVC3_OT_css_load_screen, UMVC3_OT_css_edit_clip, UMVC3_OT_css_end_clip,
           UMVC3_OT_css_install, UMVC3_OT_css_renumber, UMVC3_OT_css_set_portrait,
           UMVC3_OT_css_add_card, UMVC3_OT_css_select_group,
           UMVC3_OT_css_show_overlays, UMVC3_OT_css_assign, UMVC3_OT_css_square,
           UMVC3_PT_css, UMVC3_PT_css_card, UMVC3_PT_css_write)


def menu_import(self, context):
    self.layout.operator(UMVC3_OT_css_import.bl_idname, text="UMVC3 Character Select")


PROPS = {
    "umvc3_css_rows": IntProperty(
        name="Rows", default=9, min=1, max=64,
        description="Rows the grid is laid out as. Used for joint ids, slots and "
                    "the plugin ini - the plugin's own row count is compiled in"),
    "umvc3_css_cols": IntProperty(
        name="Columns", default=16, min=2, max=64,
        description="Columns across both pages. Stays extensible by immediates "
                    "only while it is a power of two"),
    "umvc3_css_stage": IntProperty(
        name="Plugin Stage", default=4, min=0, max=4,
        description="0 inert, 1 relocate the table, 2 walk the new grid, "
                    "3 new cards, 4 tell the cursor. Use these to attribute a "
                    "symptom to a layer"),
    "umvc3_css_follow_page": BoolProperty(
        name="Follow Page Bow", default=True,
        description="Carry each moved card's depth along the curve of the page. "
                    "Off, a card moved in x or y sinks behind the paper and the "
                    "page shows through as a blob over its neighbours"),
    "umvc3_css_refit": BoolProperty(
        name="Refit Skin Weights", default=True,
        description="Give moved cards the lattice weights belonging to where "
                    "they now sit, so the runtime page curl bends them correctly"),
    "umvc3_css_write_portraits": BoolProperty(
        name="Write Portraits", default=True,
        description="Write edited portraits back into the loose .tex folder"),
    "umvc3_css_write_ini": BoolProperty(name="Write Plugin Ini", default=True),
    "umvc3_css_write_placement": BoolProperty(
        name="Write Placement", default=True,
        description="Make who-sits-where real: vanilla characters go into the "
                    "plugin's [Layout], and CloneEngine ones by reordering the "
                    "playable entries of Characters.ini (backed up first)"),
    S.S_GAME: StringProperty(name="Game Folder", subtype="DIR_PATH"),
}


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    for name, prop in PROPS.items():
        setattr(bpy.types.Scene, name, prop)
    bpy.types.Object.umvc3_character = EnumProperty(
        name="Character", items=character_items, get=_char_get, set=_char_set,
        description="Who is on this card. Read live from Characters.ini; "
                    "picking one swaps the portrait shown here and is what "
                    "gets written on install")
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    if hasattr(bpy.types.Object, "umvc3_character"):
        del bpy.types.Object.umvc3_character
    for name in PROPS:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
