"""UMVC3 character select - Blender addon.

Opens Ultimate Marvel vs. Capcom 3's character-select screen as an editable
Blender scene: the card grid, the hover and select overlays grouped with the
cards they belong to, and every character's real portrait on their own card.
Edit it, then write it back into the game.

It also carries the generic MT Framework round-trip (`mod`), so any `.arc` of
models and textures can be opened and saved - the character-select layer is
`scene`/`grid`/`roster` on top of that.

**This supersedes the standalone `io_umvc3_mod.py` addon.** Both register the
same operators, so disable that one if it is still enabled.
"""
bl_info = {
    "name": "UMVC3 Character Select + MT Framework archive",
    "author": "reverse-engineered for UMvC3 nativePCx64",
    "version": (3, 2, 0),
    "blender": (3, 0, 0),
    "location": "Properties > Scene / Object;  File > Import/Export",
    "description": "Import the whole character-select screen, edit it, and write "
                   "it back into the game",
    "category": "Import-Export",
}

import bpy
from bpy.props import StringProperty

from . import mod
from . import ui


class UMVC3_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    game_dir: StringProperty(
        name="Game Folder", subtype="DIR_PATH",
        description="Your UMvC3 install - the folder holding umvc3.exe, "
                    "Characters.ini and nativePCx64. Used as the default when "
                    "importing, so you only set it once")

    def draw(self, context):
        self.layout.prop(self, "game_dir")
        self.layout.label(
            text="The game loads nativePCx64/ui/mnchscmn_en.arc, not mnchscmn.arc.",
            icon="INFO")


def register():
    bpy.utils.register_class(UMVC3_AddonPreferences)
    mod.register()
    ui.register()


def unregister():
    ui.unregister()
    mod.unregister()
    bpy.utils.unregister_class(UMVC3_AddonPreferences)
