# UMVC3 character select screen — Blender round-trip toolkit

Target asset: **`ui\chs\chs_meku\chs_meku.mod`** inside
`nativePCx64/ui/mnchscmn.arc` — the flip-card grid of the character select
screen ("meku" = めくる, *to flip*).

MOD v211, 4555 verts / 23682 indices / 12 meshes / 8 materials / 69 bones.
Mesh 2 covers the left half (X −603..0), meshes 7–11 the right half (0..+603).

**What the screen is actually made of.** `chs_meku.mod` is the card-grid
geometry itself. Its three 1280×720 atlases are the pieces the grid can show:

| Texture | Contents |
|---|---|
| `meku_chs01_BM` | Capcom-blue / Marvel-red background panel |
| `meku_chs02_BM` | stage thumbnails |
| `meku_chs03_BM` | "VERSUS" panel and card backs |

The **character portrait slots** are a different model: `chs_meku_face_a.mod`
and `chs_meku_face_b.mod` (P1/P2), 26 card slots each. The portraits
themselves are not in any of these — they are the 417 loose `.tex` files in
`nativePCx64/ui/chs/chs_face_a/chs_cs_f/` (`f_Ryu00`, `f_CapAmerica03`, …),
applied per slot at runtime. So edit `chs_meku` for the grid's shape and
layout, `chs_meku_face_*` for the portrait slots, and the loose textures for
the portraits.

## The addon

**`io_umvc3_css/` is the Blender addon.** Install it once (Blender ▸ Edit ▸
Preferences ▸ Add-ons ▸ Install from Disk ▸ pick the folder, or zip it first),
set your game folder in its preferences, and it does two things:

- **Character select as a scene** — *File ▸ Import ▸ UMVC3 Character Select*, or
  **Properties ▸ Scene ▸ UMVC3 Character Select**. Opens the whole screen with
  every character's real portrait on their own card. **Each card is its own
  collection**, holding the card plus the five hover/select overlays that belong
  to it; the overlays are hidden (they are drawn in front of the cards and are
  wider than them) and parented to the card, so clicking the card in the
  viewport and dragging carries everything it needs. Swap portraits, add cards,
  then **Install Into Game**.
- **Where the game actually draws things** — some models carry no coordinates of
  their own: the big character card, its plates, the cursor. They are placed by
  the `.sdl` scheduler resources, a node tree with animated transforms that the
  engine binds units to by name. **Place From Layout** reads it and puts each
  model where the game draws it, at the end of the fly-in. The models are
  *instanced* onto an empty per node rather than moved — one `chs_card` is drawn
  three times per player — and the book and its card grids are deliberately left
  where they are, because that is where an edit is written back from.
- **The screen animates, and so does the scene** — those transforms are
  keyframed, and **Import Animation** (on by default) brings the keys across as
  Blender animation: the card stack flying in from off-screen left, the cards
  rolling through their three slots, the cursor, the book opening. Press play.
  **Each clip is its own action.** The clip table — `start`, `sel1`,
  `sel1_decide`, … `start_vs` — is what an edit is actually about, so every clip
  becomes an Action named `chs_card1p | sel1`, holding that clip's keys for every
  node in the layout at once. They are laid back out as **NLA strips** at the
  frames they cover, so the whole timeline still plays and a clip you edit is a
  clip the timeline immediately plays differently — there is no second copy to
  keep in sync. **Scene ▸ UMVC3 Character Select ▸ *n* clips** puts one in front
  to work on and sets the preview range to it; **Done** goes back to the whole
  thing. Then **Export** or **Install Into Game** writes it into the `.sdl`. A
  layout you did not touch is not rewritten at all — it comes out byte-identical.
- **The whole screen, not just the book** — the character select is spread
  across archives: the book and its cards are in `mnchscmn`, the team and assist
  panels in `mnchs`, the cursor in `mnchsstg` (`mnchsea` carries no geometry).
  They are authored in the same units about the same origin, so **Whole Screen**
  — on by default — brings them in at one scale and each lands where it sits on
  screen. They edit and write back like anything else: each goes home to its own
  archive, and one an edit never touched is not rewritten at all. A scene
  imported before this existed can pick them up in place with **Load Rest Of
  Screen**, which does not discard the edits in it the way re-importing would.
- **Any MT Framework archive** — *File ▸ Import ▸ UMVC3 Archive (.arc)*, exactly
  as before. This half is the old `io_umvc3_mod.py` addon, moved inside.

> **Disable the standalone `io_umvc3_mod.py` addon if you still have it
> enabled.** Both register the same operators. The file at the top level is now
> a compatibility shim so the headless scripts here keep working; it no longer
> carries `bl_info`, so Blender will not offer it as an addon.

**Where the panels are.** In the Properties editor, beside the data they
describe — nothing lives in a viewport sidebar tab:

| Panel | Where | What |
|---|---|---|
| **UMVC3 Card** | Properties ▸ **Object** | who is on this card, its cell and slot, portrait, add/renumber. Appears only when a card (or one of its overlays) is active |
| **UMVC3 Character Select** | Properties ▸ **Scene** | the archives, rows × columns, game folder |
| **Write** | Properties ▸ Scene | follow-page / refit / placement toggles, Verify, Export, Install |
| **UMVC3 Archive** | Properties ▸ Scene | the generic archive round-trip and texture replace/revert |

What it takes care of for you, because none of it is optional:

| When you… | it… |
|---|---|
| move a card | carries its depth along the bow of the open book, so it does not sink behind the page |
| move a card | refits its skin weights for the new position, so the runtime page curl still bends it right |
| move a card | leaves its joint id alone — where a card is drawn and which slot it answers to are independent. **Renumber From Position** is how you actually move one between cells |
| add a card | appends the mesh, its material, its `.mrl` entry, and writes the joint id into bits 21..28 where the engine reads it |
| retarget a card's UVs | writes them back with the card. The UVs are what frames a portrait inside its card, so this is how a crop is authored; an untouched card still re-encodes to the same bytes, since a half read into a float32 and packed back is the same half |
| assign a character | pick from the **dropdown on the card**, read live from `Characters.ini`; the portrait shown in Blender swaps as you pick |
| move a character | makes it real: vanilla ones go into the plugin's `[Layout]`, CloneEngine ones by reordering the playable entries of `Characters.ini` (backed up first) |
| set a portrait | fits the image into the 112×76 art window, lays the recovered torn-photo frame back over the margin and writes format 19 — creating the `.tex` if that character had none |
| move or retime an animation key | writes that track back and leaves every other key alone, keeping each key's interpolation code — including the two the game only uses in the versus zoom |
| edit a key on a clip boundary | merges the two clips that share it: the copy that differs from the shipped file is the edit and wins, and two clips edited apart at one frame is reported rather than guessed |
| animate a node the file never animated | adds the keys to the track it already has; if the node has no such track at all, the property record is inserted with its siblings and every record index after it moved along |
| put an image on a card's material | writes it, **as it is**, as that character's portrait: what a player sees on a card is the character's own loose `.tex`, bound per slot at runtime, not the sheet the card samples. No window, no frame — scaled to the `.tex` and encoded, nothing laid over it. The card keeps showing your image, so you can edit it and install again; **Set Portrait** is the path that fits art into the torn photo |
| give that image transparency | carries it as BC1's **one bit** of alpha: above 50% a texel is kept, below it the texel is punched out and its colour is not stored at all. It is a cut-out, not a fade, and the colour under a transparent pixel is never shipped — which is what a dropped alpha used to do, since tools leave anything at all under alpha 0. Whether the game *blends* on it is the card shader's business; where it does not, a punched texel reads black rather than as garbage |
| flatten a tilted card | **Square Cards** puts the rectangle back. `S Z 0` *projects* rather than rotates, so a card tilted in 3D first lands as a parallelogram, and no rotation squares it again |
| install | writes **both** `mnchscmn_en.arc` and `mnchscmn.arc` (the game loads the `_en` one), backs up what it overwrites, and writes the plugin ini without a BOM |
| change rows/columns | tells you that those are **compile-time constants** in `umvc3_cssslots.cpp` and hands you the values to rebuild with, including the divide magic |

**Verify** runs the pre-install checks and separates hard problems (a joint id
that does not match its name, scrambled `.mrl` bindings, two cards in one cell,
broken weights) from warnings that just mean cards no longer sit on a regular
lattice — which is the entire point if you moved them deliberately.

Portraits show in colour where they are format 19. The 50 vanilla ones are still
format 42, whose packing has never been worked out; its **alpha channel holds
the whole portrait as luminance**, so those preview as greyscale. Anything the
addon writes goes out as format 19, which round-trips correctly.

## Files

| File | Purpose |
|---|---|
| `io_umvc3_css/` | **the Blender addon** — character select scene, plus the generic archive round-trip |
| `io_umvc3_css/scene.py` | import/export/install the character-select scene |
| `io_umvc3_css/grid.py` | what a card is: cells, slots, joint ids, the weight field, the page bow |
| `io_umvc3_css/roster.py` | character ids, CloneEngine's roster, portrait `.tex` |
| `io_umvc3_css/sdl.py` | the `.sdl` scheduler resources — the node tree that says where every model with no coordinates of its own is drawn, and when. Reads and writes them |
| `io_umvc3_css/anim.py` | that animation as Blender actions — one per clip, laid out as NLA strips — and back again |
| `io_umvc3_css/verify.py` | the pre-install checks |
| `io_umvc3_css/mod.py` | ARC/MOD/MRL/TEX formats and the whole-archive round-trip |
| `io_umvc3_css/portraits.py` | fitting art into the card frame, and writing portrait `.tex` |
| `io_umvc3_css/ui.py` | the Properties panels |
| `io_umvc3_mod.py` | compatibility shim onto `io_umvc3_css.mod`, for the headless scripts |
| `pagefit.py`, `frame_data.py` | compatibility shims onto the addon's page surface and recovered card frame |

**Building and installing a grid** — the headless path the addon wraps:

| File | Purpose |
|---|---|
| `buildgrid.py` | **the grid rebuild** — any rows × columns: splits source columns, moves and scales cards, clones missing cells, renumbers joint ids, refits weights, follows the page bow |
| `buildplanet.py` | move an already-regridded archive's cards onto a spherical cap |
| `hidebook.py` | collapse chosen meshes so they stop drawing (reversible) |
| `galaxy.py` | paint the full-screen backdrop and the grid lines |
| `gridlines.py` | draw the MvC3 grid as real geometry on the card sphere |
| `fillcards.py` | retarget card UVs so each portrait fills its whole cell |

**Verify before installing** — all of these run against a built archive:

| File | Purpose |
|---|---|
| `verifygrid.py` | the pre-install checks: joint ids, cell occupancy, `.mrl` bindings, drift vs stock, weight sanity |
| `verifypatch.py` | every patch site in the plugin vs the stock exe, read straight out of the `.cpp` |
| `clearance.py` | how far in front of the page each card sits — negative means it has sunk behind |
| `overlap.py` | which meshes are wider than one cell, or sit off their cell |
| `cardsizes.py` | flags a card that is not the size its row says |
| `cellcheck.py` | which (column, row) cells actually have a card |
| `checkskin.py` | which vertices would fly off once the page curls |
| `row0probe.py` | x extent of every row-0 mesh, stock vs rebuilt — the banner plate's row |

**Portraits:**

| File | Purpose |
|---|---|
| `import_portraits.py` | roster icons → portrait `.tex` |
| `fixportraits.py` | repair CloneEngine's undecodable format-42 portraits |
| `ce_portraits.py` | decode format-42 portraits to PNG for inspection |
| `texsurvey.py` | format/size survey of installed portraits |
| `frame_template.py` | recover the shared card frame by comparing 30 stock portraits → `frame_data.py` |
| `img2tex.py` | encode your own image into a `.tex` (via Blender) |

**Survey and measurement** — how the findings above were established:

| File | Purpose |
|---|---|
| `readgrid.py` | read the vanilla grid table out of the unpacked exe |
| `idnames.py` | recover the character id → internal name table from the exe |
| `magic.py` | verify a replacement divide magic before rebuilding the plugin |
| `screenroom.py` | measure the book's screen extent against the UI overlays |
| `layout.py` | survey the grid: cell, position, depth, size |
| `modelsurvey.py` | every model's bones, meshes, bounds and textures |
| `decode.py`, `fitscale.py` | the evidence for the uniform decode |
| `bones.py`, `boneprobe.py` | dump and compare the bone sections |
| `bboxprobe.py`, `invprobe.py` | the in-game probes that proved the header box inert |
| `arcsurvey.ps1` | survey `.arc` headers (how the packing rules were derived) |

**Round-trip and debug dumps:**

| File | Purpose |
|---|---|
| `arc.ps1` | list/extract an `.arc` |
| `arcpack.ps1` | pack a directory into an `.arc` |
| `tex2dds.ps1` | convert `.tex` → `.dds` (standalone; the addon does this itself) |
| `roundtrip.ps1` | verify position decode→encode is lossless for a `.mod` |
| `mod2obj.ps1` | dump a `.mod` to OBJ + print the mesh table |
| `objview.ps1` | ASCII render of an OBJ, to eyeball geometry |
| `mrlinfo.ps1` | dump an `.mrl`'s texture and material tables |
| `texinfo.ps1` | decode `.tex` headers (size / format / bpp) |
| `teximg.py` | dump an image full-res to PNG, or diff two images |
| `cropng.py` | crop a saved screenshot |

**Tests** — `test_css_addon.py` drives the whole character-select path,
`test_css_anim.py` the animation round-trip, `test_addon.py` the single-`.mod`
round-trip.

**Directories:**

| Directory | Contents |
|---|---|
| `io_umvc3_css/` | the Blender addon |
| `asi/` | the ASI plugin — `umvc3_cssslots.cpp`, its ini, and built `.asi` variants |
| `ghidra_scripts/` | the Ghidra scripts the engine findings were derived with |
| `drive/` | poke/peek and screenshot helpers for a running game, plus captures |
| `backup/` | stock and built archives, and the original exe |
| `portraits/`, `texpng/`, `extracted/`, `probe/` | working data: extracted assets, generated portraits, probe archives and captures |
| `steamless/` | the unpacked exe the static analysis runs against |

All scripts live in this one folder and take absolute paths, so you can run
them from anywhere. Examples below assume this directory is the working dir.
Most take their inputs from environment variables (`UMVC3_ARC`, `UMVC3_EXE`,
`UMVC3_WIDTH`, …) rather than arguments.

Re-running the tests. `test_css_addon.py` drives the whole character-select path
against your real install; `test_addon.py` checks the single-`.mod` round-trip
is still bit-identical and expects the `extracted/` folder from step 1:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
    --background --factory-startup --python .\test_css_addon.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
    --background --factory-startup --python .\test_css_anim.py
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
    --background --factory-startup --python .\test_addon.py
```

## Quick start — open an archive in Blender

Install the `io_umvc3_css` addon (see above). Then:

1. **File ▸ Import ▸ UMVC3 Archive (.arc)** — pick e.g. `mnchscmn.arc`.
   Every model in it is imported (one collection each, textured), and every
   texture is decoded and loaded into the blend. No extracting first.
2. **Edit** — move vertices, retarget UVs, recolour, paint on textures.
3. **File ▸ Export ▸ UMVC3 Archive (.arc)** — or **Properties ▸ Scene ▸ UMVC3
   Archive** ▸ *Save Archive As…*. Back up the original and drop the
   new one in.

The addon reads and writes archives itself — Python's `zlib.compress(data, 6)`
is byte-identical to the shipped payloads, so **an archive saved with no edits
comes out bit-identical to the source**. Only entries you actually changed are
re-encoded; everything else is passed through untouched, including resource
types the addon doesn't understand (`.lmt` animations and unknown blobs).

Import options: *Import Models* / *Import Textures* toggles, and a **Name
Filter** so you can pull in just one model from a large archive.

### Editing a texture

**Easiest way — the panel.** **Properties ▸ Scene ▸ UMVC3 Archive**. Under
*Texture*, pick the texture from the dropdown (they are named after the
resource, e.g. `meku_chs01_BM_NOMIP`), then:

- **Replace…** — choose a PNG/JPG/TGA/DDS of your own. It is rescaled to the
  archive texture's dimensions automatically on save; your source file and the
  image you picked are never modified.
- **Revert** — restore that texture to the version in the archive.

The panel shows the entry name, its dimensions, and flags anything edited.
Reverting everything makes the saved archive bit-identical to the source again.

**Manual route**, if you prefer Blender's own UI: switch an editor to **Image
Editor**, pick the image from the browse dropdown in the header, press `N` ▸
**Image** tab, and edit the file path field there (folder icon to browse). You
can also paint on the image directly — painting marks it dirty, which the addon
also treats as edited.

Caveats:

- Swapping which *image* a material's Image Texture node points at is only a
  preview change. The addon re-encodes the tagged image, so change that one —
  via the Scene panel, the Image Editor, or by painting.
- Single-mip BC1/BC3 only (every UI texture qualifies). A mipped texture is
  reported as a failure in the save report rather than written wrong.

## Manual workflow (extract / repack)

The PowerShell tools still work if you want the files on disk — useful for
diffing, or for editing resource types Blender doesn't open.

**1. Extract**

```powershell
.\arc.ps1 -Path "<game>\nativePCx64\ui\mnchscmn.arc" -Out D:\umvc3work\extract
```

> **Extract somewhere outside Program Files.** These scripts live in the game
> folder, but working data should not. Files written under Program Files here
> have twice come back wrong — a directory disappeared between runs, and an
> extracted `.mod` later read back as a third, corrupted variant that matched
> neither the original nor an edited copy. Every tool takes absolute paths, so
> point `-Out` at a normal writable folder and pass that same folder to Blender
> and to `arcpack.ps1`. If you do work in place, re-extract before packing.

**2. Install the addon** — Blender ▸ Edit ▸ Preferences ▸ Add-ons ▸ Install…
▸ pick `io_umvc3_mod.py` ▸ enable it.

**3. Import** — File ▸ Import ▸ UMVC3 Model (.mod), choose
`extract/ui/chs/chs_meku/chs_meku.mod`.

Scale defaults to `0.01` because the model is ~1500 game units wide, which
would otherwise sit outside Blender's default viewport clipping. You get one
empty parent plus one object per mesh, with UVs and vertex colours.

**4. Edit** — move vertices, retarget UVs, recolour.

> **Do not add or delete vertices or faces.** The exporter patches the
> original file in place and refuses to run if a vertex count changed. See
> *Why topology is locked* below.

**5. Export** — File ▸ Export ▸ UMVC3 Model (.mod). It reuses the imported
file as the template automatically. Enable **Expand Bounding Box** if you moved
geometry outside the range the model's positions currently encode. Despite the
name it does not stretch the header box — that box is inert (see *Positions*
below). It **retargets the uniform decode**: it widens the single scale, moves
the origin, re-encodes every vertex and rewrites the inverse-bind matrices, and
only does so if something actually falls outside. Leave it off and an
out-of-range coordinate is clamped and reported instead.

**6. Repack** — point it at the folder and name the output:

```powershell
.\arcpack.ps1 -Dir .\extract -Out .\mnchscmn.arc
```

Back up the original, then drop the new archive in.

Entry names come from each file's path relative to `-Dir`, minus the extension
(`extract\ui\chs\chs_meku\chs_meku.mod` → `ui\chs\chs_meku\chs_meku`), and the
extension maps back to the resource-type hash — so it round-trips whatever
`arc.ps1` wrote, unknown types included. Files whose extension is neither a
known type nor an 8-hex-digit hash are skipped and reported, which is what
keeps generated junk like `_dds_cache\*.dds` out of the archive.

Optional `-Template <original.arc>` reuses the original entry ordering. The
game indexes by name so ordering shouldn't matter, but it makes a rebuild
byte-comparable against the original, which is a strong sanity check:

```powershell
.\arcpack.ps1 -Dir .\extract -Out .\mnchscmn.arc -Template "<game>\nativePCx64\ui\mnchscmn.arc"
```

## Format notes

ARC v7: 8-byte header (`ARC\0`, u16 version, u16 count), then 80-byte entries —
`char name[64]; u32 extHash; u32 compSize; u32 decompSize|flags<<29; u32 offset`
— zlib-deflated payloads. Ext hashes: `241F5DEB`=tex, `58A15856`=mod,
`2749C8A8`=mrl, `76820D81`=lmt.

MOD v211 mesh entry (56 bytes), fields that matter:

| Offset | Field |
|---|---|
| +8 u8 | vertex format id (9 / 0x39 / 0x41) |
| +10 u8 | **vertex stride** (+11 = flags) |
| +16 u32 | byte offset of this mesh's vertex segment |
| +24 u32 | first index |
| +28 u32 | index count |
| +40 u16 | first vertex in segment |
| +42 u16 | last vertex in segment (inclusive) |

Indices are a plain **triangle list**, absolute within the segment.

### Positions: one uniform scale, and the header box is inert

This was the most expensive mistake in the project, so it is worth stating
plainly. Positions are 3× u16 with **32767** (not 65535) as full scale, but they
are **not** normalised per axis over the header bounding box. There is a
**single uniform scale for x, y and z**:

```
p = origin + raw / 32767 * S          # one S for all three axes
```

`origin` and `S` both live in the **inverse-bind matrices**, as
`invBind[j] = D · bindWorld[j]⁻¹` with `D = scale(S) · translate(origin)`.
Recover `D` as `invBind[0] · bindWorld[0]` — that is `M.model_dequant()`.

**The header bounding box does not affect rendering at all.** Proved three ways:

- Raw ranges in stock `chs_meku_face_a` are `x 0..18984, y 0..25430, z 0..2507`
  — exactly the values that make the header box tight under a uniform scale.
  Per-axis normalisation would require `0..32767` on all three. All 20 models in
  the archive agree.
- Sweeping the scale against the bone lattice (explicit float matrices, so a
  fixed ruler in engine space) bottoms out near `S`, not near the box extents:
  mean weight error **0.22 uniform vs 0.86 per-axis**.
- **In game**: shifting `bbmin.y` by −100 and growing `ext.y` by +200 changed
  nothing visible, while scaling the inverse-bind rows by 0.75 visibly shrank
  that page.

Decoding per axis stretches each axis by a different factor. That, not the bone
lattice, is what made an early 16-row build render huge and splayed, and it
silently distorted the working 8-row build too.

**To make room for geometry outside the current range, retarget the decode**
(`M.mod_retarget_dequant`): it re-encodes every vertex and rewrites all
inverse-bind matrices, so the geometry the engine sees is unchanged (drift stays
under half a quantisation step). Prepending the same transform to every bone
factors straight out of the skinning sum, which is why this is safe. Growing the
header box does nothing.

Verified lossless over all 13665 components of `chs_meku.mod`.

Stride-40 vertex layout, as used by fmt 41/49/65:

| Offset | Field |
|---|---|
| +0 | position, 3× u16 (+1 u16 unknown) |
| +8 | normal, 4× int8 |
| +12 | tangent, 4× int8 |
| +16 | bone indices, 4× u8 |
| +20 | bone weights, 4× u8 |
| +24 | UV0, 2× half |
| +28 | UV1, 2× half |
| +32 | colour0 RGBA8 |
| +36 | colour1 RGBA8 |

**Fmt 57 at stride 40 — the format every card mesh uses — is skinned, and lays
those middle bytes out differently**: seven weights, not four, and eight bone
indices rather than four:

| Offset | Field |
|---|---|
| +0 | position, 3× u16 |
| +6 | weight0, u16 / 32767 |
| +8 | normal, 4× u8 |
| +12 | weights 1..4, 4× u8 / 255 |
| +16 | bone indices, 8× u8 — **direct, not through the remap table** |
| +24 | UV0, 2× half |
| +28 | weights 5 and 6, 2× half |
| +32 | colour0 RGBA8, +36 colour1 RGBA8 |

Weights sum to 1.000 across all 755 stock vertices. Use `M.read_skin` /
`M.write_skin` rather than unpacking this by hand. The model's 256-byte remap
table maps *bone id* (10..26) to index (0..16); vertices index bones directly,
so the remap is not involved in skinning.

Stride 24 = pos, normal@8, colour@12, UV@16, colour2@20.
Stride 12 = pos, normal@8. Stride 28 = pos, boneIdx@8, weights@12, normal@24.

**Layout is keyed by the format id at mesh+8, not by stride.** Stride 20 has
two different layouts: fmt 1 stores **float32** positions (normal@12, UV@16),
fmt 9 stores the usual u16 triple (normal@8, colour@12, UV@16). Pairs seen in
`mnchscmn.arc`: `(1,20) (9,12) (9,20) (9,24) (57,28)`, plus stride 40 for fmt
41/49/57/65 which all share one layout. The addon falls back to a stride-only
default so an unseen format id still loads.

Float32 positions can't round-trip bit-exactly (Blender stores coordinates as
float32, so scaling in and back out loses a bit), so the exporter rewrites such
a component only when it actually moved. u16 positions don't need this — the
quantisation absorbs the error.

## SDL — where and when the engine draws things

`rScheduler` (`.sdl`, ext hash `4C0DB839`): a header, a flat record table, then
each record's key table and values, then a string table.

```
+0x00 "SDL\0"   +0x04 u16 version (0x16)   +0x06 u16 record count
+0x08 u32 rScheduler's DTI hash            +0x18 u64 string table offset
0x20  record[count], 0x30 bytes each
```

| record | field |
|---|---|
| +0x00 u8 | **storage kind** — how wide a value is. 2 marks an object |
| +0x01 u8 | MT property type: 3 bool, 6 u32, 10 s32, 12 f32, 14 string, 15 colour, 20 vector3, 128 resource |
| +0x02 u16 | **key count** |
| +0x04 u32 | property: its owner's record index. Object: a class category |
| +0x08 u64 | name, as an offset into the string table |
| +0x10 u32 | object: the DTI hash of its class |
| +0x20 u64 | key table, one u32 per key |
| +0x28 u64 | values, `kind` bytes each |

**The table starts at 0x20 and record 0 is `Root`** — which is why owner indices
look one-based if you start at 0x50. `rScheduler__convert` @ `0x140522670` is
the load-time fixup and settles all of this: it walks from 0x20, reads the kind
and key count, relocates the name against the string table, resolves +0x10
through `MtDTI__findByHash`, and relocates the key table and values for kinds
6..16 only.

A key word is **`frame | interpolation << 24`**. Value width is the *kind*, not
16: kind 6 and 9 and 12 and 15 are 4 bytes, 8 is 16, 11 is 1, 13 and 14 are 8,
16 is a 64-byte matrix. Reading everything as 16 quietly misreads any multi-key
scalar track — `mTransparency`, `mFrame`, `mDepth` — as the next key's bytes.

Interpolation codes across every `.sdl` in the game are 0, 2, 3 and 5. Integer,
bool and string tracks are always 0; float and vector tracks are 3, sometimes 5,
and **sometimes 0 on individual keys of a moving track**, which is a hold. So 0
imports as Blender's CONSTANT and everything else as LINEAR. What separates 3
from 5, and the exact curve either draws between two keys, is not decoded — the
code is preserved per key instead, so a round trip never retypes a track.

Rotation is `uCoord`'s order 0 (`uCoord__setEulerRotation` @ `0x140547b50`),
which builds `Rz . Ry . Rx` transposed for MT's row-vector convention — exactly
Blender's `XYZ`. No `.sdl` in these archives sets any other order.

## Textures

Import builds one Blender material per MOD material slot and assigns it per
mesh. `.tex` files are converted to `.dds` on the fly into a `_dds_cache`
folder next to the `.mod` (or your temp dir if that isn't writable — the game
lives under Program Files). `tex2dds.ps1` does the same conversion standalone.

**rTexture (`.tex`)** — 24-byte header, then a raw BC surface:

| Field | Meaning |
|---|---|
| u32 @+8 | `mips = v & 0x3F`, `width = (v>>6) & 0x1FFF`, `height = (v>>19) & 0x1FFF` |
| u32 @+12 | byte 1 is a format code: 19 → BC1/DXT1, 23/31/42 → BC3/DXT5 |

The converter decides BC1 vs BC3 from measured bits-per-pixel, which is
self-validating, and only falls back to the format code.

**Mesh → material.** The material index is a nibble-shifted 16-bit field
spanning bytes +5/+6 of the mesh entry:

```
materialIndex = (b[+5] >> 4) | (b[+6] << 4)
```

Verified across all 21 models in `mnchscmn.arc`: never out of range, and a
perfect permutation of 0..N-1 on every model where meshCount == materialCount.

**Material → MRL.** MOD material names (`XfBAD_W_22__m01_`) hash to MRL
material ids with reflected CRC32 (poly `EDB88320`, init `FFFFFFFF`) and **no
final XOR** — i.e. `zlib.crc32(name) ^ 0xFFFFFFFF`. Confirmed 8/8.

MRL layout: `header(40) | textures(88 each) | materials(72 each) | block data`.
Texture entries carry the path at +24. Each 72-byte material entry owns **two**
variable-size blocks, as `(u64 pointer, u32 size)` pairs split across the entry:

| Offset | Field |
|---|---|
| +8 | name hash (`mt_hash`) |
| +12 | block 0 size |
| +28 | flags — **joint id in bits 21..28** |
| +52 | block 1 size |
| +56 | block 0 pointer (u64) |
| +64 | block 1 pointer (u64) |

**The joint id, and why renaming a material does nothing.** The character select
finds a card with `cChrTrace__findByJointId(model, i)`, which scans the model's
materials for one whose id matches. That id is **bits 21..28 of the dword at +28
in the `.mrl` material entry**. The material *name* (`Xf<shader>__mNN_`) mirrors
it and is the readable form, but the engine never reads the name — renaming a
material alone changes nothing.

Numbering is `colIdx * ROWS + row`, where `colIdx` counts **inward to outward**
(colIdx 0 is nearest the screen centre). `face_a` and `face_b` legitimately have
no card at grid row 0, columns 1 and 2: one wide banner plate (the CAPCOM /
RANDOM plate, 348 units across) covers those cells.

**Character ids.** `idnames.py` recovers the ordered internal-name table at
rva `0xC553A0`; portraits are `f_<Name><colour>_BM_HQ_NOMIP.tex`. Three
unrelated strings sit in front of the table, so **character id = table index −
2**. Confirmed by the vanilla split: page A holds exactly ids 1–25 (Capcom) and
page B ids 26–50 (Marvel), with 53 and 54 the two RANDOM plates. Ids 0, 52 and
55 draw the UNKNOWN plate.

### Replacing a texture with your own

**Editing the material or swapping the image in Blender changes nothing in
game.** The exporter writes back only vertex positions, UVs and vertex colours
— materials are never serialised into the `.mod`. That is exactly why an
unedited export comes out byte-identical. Blender materials are preview only.

To change what the game actually draws, replace the `.tex` inside the archive:

```powershell
# 1. encode your image into a .tex shaped like the one you are replacing
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
    --background --factory-startup --python .\img2tex.py -- `
    --image D:\art\my_panel.png `
    --like  .\extract\ui\chs\chs_meku\meku_chs01_BM_NOMIP.tex `
    --out   .\extract\ui\chs\chs_meku\meku_chs01_BM_NOMIP.tex

# 2. repack and install
.\arcpack.ps1 -Dir .\extract -Out .\mnchscmn.arc
```

`--like` takes the reference's width, height, mip count and format code and
reuses its 24-byte header verbatim, so the result is a drop-in replacement the
game already knows how to read. Your image is rescaled automatically if its
dimensions differ.

Constraints:

- **BC1 and BC3, single-mip only.** That covers every UI texture (all are
  `NOMIP`). A mipped reference is rejected with a clear error rather than
  written wrong.
- **You replace a texture's contents, not which texture a mesh uses.**
  Re-pointing a material at a *different* texture means editing the MRL
  binding, which is not reversed — see below. Overwriting the texture the mesh
  already samples achieves the same thing.
- Encoder quality: re-encoding an existing texture costs about **1/255 mean
  error** per channel with alpha essentially exact. That measurement is a
  double compression; a fresh source image only takes one generation.

Verified end to end: a 512×512 image encoded into the 1280×720 BC1 slot,
packed, and re-extracted came back byte-identical and rendered correctly.

### Known gap: which texture slot a material binds

**This is not reversed.** The per-material texture binding lives inside the
1184-byte MRL parameter blocks as serialised runtime structures with pointer
placeholders; no plain texture index survives there. A promising-looking field
at material +30 fits `chs_meku` and `chs_card` but fails on 351 of 388
materials across the archive, so it is not used.

What the importer does instead:

1. one texture in the MRL → every material uses it (**certain**)
2. textureCount == materialCount → match by index
3. otherwise → first texture that isn't `_DM`/`_SPE`/`_NM`/`_MM` (**a guess**)

Every texture the model references is loaded into the blend regardless, so
correcting a wrong guess is two clicks in the Image dropdown of the material's
Image Texture node — no re-import. The import log prints the rule used per
material, so you can see which assignments are certain and which are guesses.

None of this affects export: materials are not written back, and the exporter
still reproduces the source file byte for byte.

## What actually constrains the grid

Three ceilings on how big the character-select grid can get, tightest last:

1. The bone lattice is a 4×4 control grid spanning y ±360.
2. **The drawn book page is tighter.** The stock 7 rows span y ±304.6 and fill
   it; a row beyond that renders below the book, under the HUD bar.
3. **The screen is tightest of all.** The book occupies screen y 215..642, the
   control bar starts at 650, and the book's top edge (~192) already touches the
   TIME readout's "∞" (~197). Growing the book taller buys only about 1.16×, and
   means sliding it behind TIME.

Horizontally there is ~300 px spare either side (the book uses 665 of 1280), so
**height is the scarce axis and width is the free one** — more columns beats more
rows. Column count is extensible while it stays a **power of two**, because the
engine derives cell from slot with `col = slot & (COLS-1)` and
`row = slot >> log2(COLS)`; 12 columns would need real mod/div detours.

**The open book bows in depth, so never move a card in x or y alone.** z runs
~34→39 down a column and 36→63 across the page. A card moved without carrying
its depth ends up behind the page over a near-tangent region, which shows in
game as a large soft blob swallowing several cards. Fit a global 2D surface, not
a local one — that is what `pagefit.py` does and what the addon applies for you
on every card move.

**Watch the page/column split.** A page is chosen by column, but the grid table
is linear in slot, so changing the column count re-divides slots 0–55 between
the two pages. At 16 columns the split becomes 32/24 while each page needs 26,
which forces 4 Marvel characters onto the Capcom page.

The scale that ties units to pixels, measured rather than assumed: the stock
grid is 609.2 units over 427 px, i.e. **1.427 units per pixel** (`screenroom.py`).

## The plugin — rows and columns are engine-side

The archive decides where cards are *drawn*. It does not decide how many slots
the engine believes exist, how the cursor steps, or which page a column belongs
to — all of that is code. `asi/umvc3_cssslots.cpp` is an ASI plugin that patches
those sites in `umvc3.exe`.

- **`NEW_ROWS` and `COLS` are compile-time constants.** Only `Stage` and
  `[NewRows]` come from the ini. Set a grid the plugin was not built for and the
  addon says so and prints the constants — and the divide magic — to rebuild
  with, rather than shipping a silent mismatch.
- **The divisor is two immediates, not one.** A `slot / ROWS` becomes a
  multiply-high by a magic constant plus a shift; both have to be replaced
  together, which is what `magic.py` verifies before you rebuild.
- **The grid table has to be rebuilt, not copied** — it is linear in slot, so a
  new column count re-divides it (see the page/column split above).
- **The cursor keeps its own copy of the grid size.** It is a separate object,
  which is why directional input kept moving wrongly long after the grid itself
  looked right. Verified in game after the fix: every direction steps exactly one
  cell, the spine is crossed correctly, both wraps land on the true grid edges,
  all 9 rows are reachable, and a slot-128 CloneEngine character selects through
  to assist type.
- **Beware constants that look like row counts and are not.** Several `0x1C` and
  `7` immediates near the CSS setup routine are unrelated bounds; patching them
  because the number matched is how earlier attempts broke the screen.
- `verifypatch.py` checks **every patch site in the plugin against the stock
  exe**, reading the tables straight out of the `.cpp`. A wrong `expect` is
  caught before a launch instead of showing up as a `GAVE UP` line in the log.
- Use the plugin's **stages** to attribute a symptom to a layer. Stage 1 applies
  the archive with no code patches at all, which is how the page-depth bug got
  separated from the engine work.

**CloneEngine is a hard constraint**, not a preference: it claims every roster
slot from 56 up by index. That is why vanilla keeps rows 0–6 (slots 0–55) as
they are and any expansion goes above that line.

Write the plugin ini **without a BOM** — `GetPrivateProfileIntA` cannot find
`[Config]` behind one and silently returns the default. The game holds the
`.asi` open, so stop the process before copying a new build over it.

## The galaxy screen — replacing the comic book

Three passes, each its own script, each installable and revertible on its own.
Verified in game.

| script | does |
|---|---|
| `buildplanet.py` | moves an already-regridded archive's cards onto a spherical cap |
| `hidebook.py` | collapses chosen meshes so they stop drawing |
| `galaxy.py` | paints the full-screen backdrop and the grid lines |

**`buildplanet.py` is a placement pass only** — it takes the archive
`buildgrid.py` produced, so cells, joint ids and clone work are already done. It
**rigid-binds every card vertex to bone 0**, because the page's curve is not art
but the 4×4 lattice of 16 bones: a card placed on a dome and left weighted to
that lattice gets the book's arch applied on top and folds. Bone 0 is the root at
(0, 0, −0.2), effectively identity, and confirmed in game not to be animated.
Overlay layering is measured per model from the source and re-applied along the
sphere normal (`selr1` runs +21 proud of `face`), or the hover frames z-fight.

**Size the dome to the book's footprint, not the screen.** The character body art
flanks the grid, so a dome spanning the full width covers it.
`UMVC3_WIDTH=900 UMVC3_HEIGHT=560` gives 670 × 436 px against the book's
665 × 427 — the layout that demonstrably left the art clear. At 1700 × 1000 it
covered the art *and* ran off the top and bottom.

**`hidebook.py`** collapses a mesh by copying vertex 0's **whole record** over
every other vertex — not just its position. These meshes are skinned to a
69-bone rig, so vertices sharing a position but not their weights get pulled
apart again the moment the book animates; byte-identical vertices transform
identically whatever the rig does. It also needs no knowledge of the vertex
layout, which matters because `chs_meku` mixes strides 12/24/28/40 across formats
9, 57 and 65. Nothing is removed and no table changes size, so it is fully
reversible.

**The character-select backdrop is `meku_menu_co00_BM_NOMIP`** (1280×720, format
19) — *not* any of the `meku_chs01/02/03` atlases. Material-to-texture binding is
a known gap (see above), so this was settled by flooding each 1280×720 candidate
with a different flat colour and launching once: the whole screen turned yellow.
A flat-colour BC1 payload is trivial to hand-build (`c0 == c1`, indices 0), which
makes that probe cost seconds rather than a full encode.

`chs_meku`'s meshes 0, 1, 3 and 4 turned out not to be a backdrop panel at all —
rendered in isolation they are a **frame with a hollow centre**, the border
decoration that surrounded the book, and it stayed on screen after the pages
went. That also proves the backdrop is drawn by the game as its own full-screen
layer, not carried on `chs_meku` geometry.

**The projection is orthographic, 1.364 game units per pixel.** Measured, not
assumed: autocorrelating the column profile of a screenshot gives a uniform 44 px
column pitch, and 15 gaps × 44 px = 660 px for 900 units. Fitting a perspective
model to the apex (z 200) and the rim (z 135) returns the same scale for both, so
there is no measurable foreshortening across the dome. That is what makes the
grid lines drawable: under an orthographic projection a line of constant latitude
has a constant screen y, so the horizontals come out perfectly straight and only
the verticals curve, pinching toward the poles — which is the vanilla look,
falling out of the geometry rather than being faked.

## Why topology is locked

Between the mesh table and the vertex buffer sits a ~20 KB block (4×4
matrices, purpose not identified) that is copied verbatim. Changing vertex or
index counts would require rebuilding every offset in the header and mesh
table *and* understanding that block. Patching in place instead makes a
malformed file essentially impossible, at the cost of fixed topology.

Lifting that restriction is possible — all the offset fields are decoded —
but it needs the unknown block characterised first.

## Verified

Archive workflow, against Blender 5.2 and `mnchscmn.arc`:

- Opens all 113 entries → 21 models (400 meshes) and 54 textures, every one
  decoding to real pixels.
- **Saving with no edits reproduces the source archive bit for bit.**
- After moving one mesh and forcing one texture through the encoder, exactly
  those 2 entries changed; both kept their original size and the texture
  re-decoded correctly as 512×64 fmt 42.
- `zlib.compress(data, 6)` matches all 113 shipped payloads byte for byte
  (level 9 matches only 10/113).
- Texture Replace/Revert: a 300×200 PNG assigned to a 1280×720 BC1 slot encodes
  to exactly the right payload size, the source image is left at 300×200
  (never resized in place), and Revert returns the archive to bit-identical.

Gotcha worth knowing if you touch this code: assigning `colorspace_settings`
to a file-backed image makes Blender re-read the file, which silently undoes a
prior `scale()`. The encoder sets colourspace **before** scaling, and works on
a throwaway copy so the user's image is never mutated.

Animation, against Blender 5.2 and the real archive. The clip actions and the
NLA strips are checked by *playing* them: every figure below is the evaluated
scene, not the keys that were written into it.

- **`build()` reproduces 1657 of the 1664 `.sdl` files the game ships byte for
  byte**, including all 174 in the character-select archives. The seven that
  differ are main-menu files whose value blocks overlap; they rebuild to a
  valid, equivalent file, and nothing rewrites a resource it did not edit.
- Every node's own transform matches the file at nine frames across the whole
  605-frame timeline, worst error 1.2e-7 — and the parented chain composes to
  the same world matrix the engine builds, worst 2.4e-7. That is the strips
  playing, so splitting 605 frames into 19 clips loses nothing: a clip that
  holds a value it has no key for carries it at both ends, or the channel would
  fall back to the rest pose the moment a clip had nothing to say about it.
- Exporting a scene with the animation untouched leaves all four animated
  layouts byte-identical — the boundary values each clip carries are dropped
  again on the way out, because they say nothing the track did not already say.
- Moving one key *in the `start` clip* writes that key and no other, keeps the
  key count, and preserves every interpolation code including the two 5s in the
  versus zoom. Adding a key at frame 300 to `rollup3` lands at frame 300 with
  the right value, comes back in that same clip on re-import, and the other
  player's layout is not rewritten.
- A property record added to a node that never had that track leaves every
  other node's parent, model and keys identical, and the clip table intact.

Single-model tests, against `chs_meku.mod`:

- Import yields 12 meshes, 4555 verts, 7894 tris — matching the header's own
  vertex count and `indexCount / 3`.
- **Import → export with no edits reproduces the source file byte for byte.**
- After moving one mesh, every changed byte lands inside the vertex buffer;
  header, bones, materials and index buffer are untouched.
- Position decode → encode is lossless across all 13665 components.
- `arcpack.ps1` reproduces `mnchscmn.arc`, `game.arc` (508 files) and `lic.arc`
  (824 files) **bit for bit** from their extracted folders — recompressing every
  entry from scratch, so the game's zlib settings match .NET `Optimal` exactly.
  Those three also cover all observed `dataStart` values (32768 / 65536 / 98304).
- Packing from a directory with no template and re-extracting reproduces all
  113 source files byte for byte.

Archive rules confirmed by surveying all **6604** `.arc` files in the game:
version is always 7, the entry flag value is always 2, entries are always in
ascending offset order, and data always begins at the smallest multiple of
32768 past the entry table.

Meshes 0, 3 and 4 import without UVs — expected, their strides (12 and 28)
carry no UV channel.

**Confirmed in game:** an edited `.mod` repacked into `mnchscmn.arc` loads and
renders correctly on a running build.

## Not yet verified

- **Custom textures have not been tested in-game.** The `.tex` encoder is
  verified by round-trip (byte-identical through pack/unpack, correct on
  re-decode) but has not been shown on a running build.
- **Loose-file override is unconfirmed.** `nativePCx64/ui/chs/chs_face_a/` ships
  417 loose `.tex` files whose paths and sizes match entries also inside
  `mnchs.arc`, which strongly suggests loose files shadow archive contents —
  if so you could drop `ui/chs/chs_meku/chs_meku.mod` straight in and skip
  step 6. Worth testing by swapping one portrait texture before relying on it.
