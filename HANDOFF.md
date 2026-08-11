# UMVC3 character-select expansion — handoff

Goal: make Community Edition's extra characters visible and selectable on the
character select screen (CSS), which vanilla limits to 50.

**Status: done. 9 rows x 16 columns = 144 slots, all 83 CloneEngine characters
selectable, cursor movement correct in every direction, verified in game.**

**There is now a Blender addon (`io_umvc3_css/`) that opens this whole screen as
an editable scene and writes it back into the game — see §11.**

---

## 1. Current working state

Installed and verified in game:

| what | where |
|---|---|
| CSS archive, 9x16 | `probe/grid16b.arc` → `nativePCx64/ui/mnchscmn.arc` **and** `mnchscmn_en.arc` |
| plugin | `asi/build/umvc3_cssslots.asi` → game root, `Stage=4` in `umvc3_cssslots.ini` |
| portraits | 83 CE `.tex` in `nativePCx64/ui/chs/chs_face_a/chs_cs_f/`, all format 19 |
| exe | untouched stock `umvc3.exe` — everything is runtime patching |

Vanilla keeps slots 0-55; CloneEngine fills 56-138 with its 83 playable
characters; 139-143 are past its roster and read UNKNOWN. Cards are 58 x 68
game units, about 42 x 49 screen px, against vanilla's 83 x 63.

Confirmed by hovering and selecting: the cursor crosses the spine correctly
(10 columns right lands on NOVA on the Marvel page), CE characters deeper in
the grid select through to assist type, and the Capcom/Marvel split holds.

Two things on this screen are owned by something other than the code you would
expect, and both cost a full debugging cycle:

- the cursor is a **separate object with its own copy of the grid dimensions**
  (§9) — that is where "directions don't match" lived;
- the grid table is **relocated a second time by CloneEngine**, after this
  plugin, so the table you relocated is not the one being read (§5) — that is
  where the missing Firebrand and Strider portraits lived.

Both are the first places to look if this screen is ever resized again.

Backups: `asi/umvc3_cssslots_16col9row_cursor_celayout.asi` (**the current
build**), and behind it `_cursor`, `_16col_nocursor`, `_18row`, `_8row`;
`backup/BUILT_mnchscmn_16col9row_installed.arc` (**the archive actually
installed** — the older `BUILT_mnchscmn_16col9row.arc` is a superseded build,
check the hash against `nativePCx64/ui/mnchscmn_en.arc` before trusting either),
`backup/BUILT_mnchscmn_18row.arc`, `backup/STOCK_mnchscmn*.arc`,
`backup/ORIGINAL_umvc3.exe`, `portraits/ce_fmt42_originals/`.

An earlier 18 rows x 8 columns build also works and is kept in the backups; it
fits the same 144 slots but gives 3.4:1 slivers instead of portrait-shaped
cards. See §6 for why the grid went wide rather than tall.

**The game loads `mnchscmn_en.arc`, not `mnchscmn.arc`.** Write both or you will
test nothing.

---

## 2. Toolchain

No standalone Python on this machine. Every script runs under Blender:

```bash
"/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" \
  --background --factory-startup --python script.py
```

Scripts take input via environment variables (`UMVC3_ARC`, `UMVC3_OUT`, ...).

**Ghidra**: a fully symbolised community database lives at `~/umvc3.rep`
(program `umvc3postDTI8.exe`, **46,797 named functions**, image base
`0x140000000`, addresses match the retail Steam build exactly). Use it — do not
hand-reverse. The GUI holds a lock, so copy the project first:

```bash
export JAVA_HOME="/c/Users/Sky/AppData/Local/Programs/Eclipse Adoptium/jdk-25.0.4.7-hotspot"
GH="/c/Users/Sky/Downloads/ghidra_12.1.2_PUBLIC_20260605/ghidra_12.1.2_PUBLIC"
"$GH/support/analyzeHeadless.bat" <copied-proj-dir> umvc3 -process umvc3postDTI8.exe \
  -noanalysis -readOnly -scriptPath ghidra_scripts -postScript DecompAt.java out.c <addr>...
```

Scripts must be **Java** (Ghidra 12 dropped Jython). Working ones in
`ghidra_scripts/`: `DumpSymbols`, `DecompAt`, `Disasm`, `ScanConstants`,
`DumpPtrStrings`, `XrefsIn` (does anything branch into a byte range — check this
before overwriting code with a detour), `ScanColumnMath` (every instruction in a
range encoding an 8-column grid), `ScanDirMask` (every d-pad direction test in
the image), `ScanVCall` (indirect calls through given vtable slots), `ScanDisp`
(every access to a given structure offset), `FindConst` (every instruction or
data word holding a given immediate), `ScanShift` (every shift by a given
amount, optionally filtered by function name — how the key-word byte was
chased).

Note `analyzeHeadless.bat` takes the **directory containing** `umvc3.gpr` as its
first argument, not the `.rep` — copy both out of `~` together.

**Scan the whole image, not a guessed range.** The cursor bug hid for a full
session because the first `ScanColumnMath` run stopped at `0x372000` and the
cursor class starts at `0x372840`. `0x140001000-0x140a60000` returns 6337 hits
and takes the same minute; filter afterwards.

**Plugin build**: `asi/build.bat` (MSVC via VS2022 `vcvars64.bat`, static CRT,
imports only `KERNEL32`).

**Driving the game** (`drive/`, PowerShell): `shot.ps1` (window screenshot),
`crop.ps1` (crop + zoom a live region), `key.ps1` (SendInput **scan codes** —
posted messages are ignored by DirectInput), `sweep.ps1`, `readmem.ps1`.
`cropng.py` crops a *saved* screenshot, so old shots can be compared against new
ones without relaunching.

Navigate to CSS: `Enter Enter` → wait → `Enter` → wait → `Esc Enter Esc Enter`
(skip prologue) → `Enter` (Offline) → `Down Down Enter` (Training). Allow ~30 s
after launch and ~10 s for the book-open animation.

---

## 3. File formats — the parts that cost real time

### ARC
v7, 8-byte header, 80-byte entries, zlib. `zlib.compress(level=6)` reproduces
shipped payloads **bit-for-bit**, so round-trips are clean.

### MOD (rModel) — vertex positions
- Mesh table stride 56. Material index = `(b[+5] >> 4) | (b[+6] << 4)`.
- Vertex layout keyed by **format id at mesh+8**, not stride.
- Mesh order in the file is unrelated to screen position.

**Positions decode with a SINGLE UNIFORM SCALE, not per axis, and the header
bounding box is inert.** This was the single most expensive mistake in the
project — every tool originally used `p = bbmin + raw/32767 * ext[axis]`, which
stretches each axis by a different factor.

```
p = origin + raw / 32767 * S          # one S for x, y and z
```

`origin` and `S` both live in the **inverse-bind matrices**, as
`invBind[j] = D . bindWorld[j]^-1` with `D = scale(S) . translate(origin)`.
Recover `D` as `invBind[0] . bindWorld[0]` — that is `M.model_dequant()`.

Proved three ways:
- Raw ranges in stock `chs_meku_face_a` are `x 0..18984, y 0..25430, z 0..2507`,
  exactly the values that make the header box tight under the uniform scale.
  Per-axis would need `0..32767` on all three. All 20 models in the archive
  agree exactly.
- Sweeping the scale against the bone lattice (explicit float matrices, so a
  fixed ruler in engine space) bottoms out near S, not near the box extents:
  mean weight error 0.22 uniform vs 0.86 per-axis.
- **In game**: shifting `bbmin.y` by -100 and growing `ext.y` by +200 in the
  header changed nothing at all, while scaling the inverse-bind rows by 0.75
  visibly shrank that page. `probe/bboxprobe.py`, `probe/invprobe.py`.

To make room, **retarget the decode** (`M.mod_retarget_dequant`): it re-encodes
every vertex and rewrites all inverse-bind matrices, so the geometry the engine
sees is unchanged (drift under half a quantisation step). Prepending the same
transform to every bone factors straight out of the skinning sum, so this is
safe. Growing the header box does nothing.

### MOD — the skinned vertex layout (fmt 57, stride 40)
```
+0  u16 x3  position       +16 u8 x8   bone indices (direct, NOT via the remap)
+6  u16     weight0/32767  +24 half x2 uv0
+8  u8 x4   normal         +28 half x2 weight5, weight6
+12 u8 x4   weight1..4/255 +32 u8 x4   colour0    +36 u8 x4 colour1
```
Weights sum to 1.000 across all 755 stock vertices. `M.read_skin` /
`M.write_skin`. The 256-byte remap table maps *bone id* (10..26) to index
(0..16); vertices index bones directly, so the remap is not involved.

### MRL (rMaterial)
```
header(40) | textures(88 each) | materials(72 each) | block data
```
Each 72-byte material entry owns **two** variable-size blocks as
`(u64 pointer, u32 size)` pairs at **+56/+12** and **+64/+52**:

| offset | meaning |
|---|---|
| +8  | name hash (`mt_hash`) |
| +12 | block 0 size |
| +28 | flags; **joint id in bits 21..28** |
| +52 | block 1 size |
| +56 | block 0 pointer (u64) |
| +64 | block 1 pointer (u64) |

`mt_hash(name)` = reflected CRC32 (`EDB88320`, init `FFFFFFFF`) **without final
XOR** = `zlib.crc32(name) ^ 0xFFFFFFFF`.

### The joint id
The CSS finds a card with `cChrTrace__findByJointId(model, i)`, which scans the
model's materials for one whose id matches. **That id is bits 21..28 of the dword
at +28 in the `.mrl` material entry.** The material *name* (`Xf<shader>__mNN_`)
mirrors it and is the readable form, but **renaming alone changes nothing**.

Numbering is `colIdx * ROWS + row`, where `colIdx` counts **inward to outward**
(colIdx 0 is nearest the screen centre). `face_a`/`face_b` legitimately have no
card at grid row 0 columns 1 and 2 — one wide banner (the CAPCOM/RANDOM plate,
348 units across) covers those cells.

### Character ids
`idnames.py` recovers the ordered name table at **rva `0xC553A0`**; portraits are
`f_<Name><colour>_BM_HQ_NOMIP.tex`. The table has three unrelated strings in
front of it, so **character id = table index - 2**: id 1 = Ryu, id 20 = Jill,
id 21 = Hiryu (**Strider**), id 22 = Vergil, id 23 = Naruhodo (Phoenix Wright),
id 24 = RedArremer (**Firebrand**), id 25 = Nemesis, id 26 = SpiderMan. That
offset is confirmed by the vanilla table: page A holds exactly ids 1-25 (Capcom)
and page B ids 26-50 (Marvel), with 53/54 the two RANDOM plates.

`vfn17` special-cases ids **0, 52 and 55** (draw the UNKNOWN plate), **53**
(RANDOM_A plate) and **54** (RANDOM_B plate) before the normal
id -> name -> portrait path — the `sub edx,0x34` / `dec` chain at `0x36E0C9`.

### TEX
Header 24 bytes. `u32 @ +8` packs mips (bits 0-5), width (6-18), height (19-31).
`u32 @ +12` bits 8-15 = **format**.

**Format 42 is not BC3.** Stock portraits are format 42; the packing has never
been worked out. A textbook DXT5 test chart came back from the game as two flat
bands. **Use format 19 (BC1)** — it round-trips correctly. Write the stock
24-byte header with the format field patched. Costs alpha, which does not matter
for opaque cards.

What *is* now known about format 42, enough to preview it: decoded as ordinary
DXT5, its **alpha channel is the entire portrait as clean greyscale luminance**,
frame included — `f_Ryu00` comes out as an unmistakable Ryu. The colour block is
chroma, but it carries only about **one degree of freedom**: sampled across the
image, `g` is essentially binary (0 or 1) and `r + b` stays near constant
(0.482/0.482 on neutral, 0.710/0.259 on skin), so it is not a plain YCoCg and
full colour cannot be reconstructed from the block data alone. The addon
therefore previews format 42 as greyscale from alpha and never writes it.

### The card frame
The white torn photo border is **part of the portrait texture**, not the card.
`frame_template.py` recovers it by comparing 30 stock portraits. Result
(`frame_data.py`): 128x128 texture, art window **(8,44)..(120,120)**.

---

## 4. Engine internals (all verified against the Ghidra DB)

Grid table at **`0x140B3E580`**, 7 rows x 8 int32 of character ids. Cannot grow
in place — live float constants follow it. The plugin relocates it and repoints
the readers.

**There are exactly two readers** — `lea` at `0x361FE5` and `0x361F52`.
Repointing only one leaves the two directions disagreeing.

> **CloneEngine relocates the table too, and it wins.** CE repoints those same
> two leas at its own table (`0x1B0000000` here) *after* this plugin runs, so a
> relocation done at startup is simply never read. Never assume the table you
> relocated to is the one in use — **read the disp32 back out of the lea** and
> follow it. `RelayoutLiveTable` in the plugin does exactly that, and
> `drive/readmem.ps1 -Address 0x140361FE8 -Count 1` shows the displacement live.
> See §5.

| address | name | role |
|---|---|---|
| `0x36DF90` | `uMenuChrSelBgMain_vfn17` | builds the cards, binds portraits per joint |
| `0x36CE80` | `uMenuChrSelBgMain_vfn28` | per-frame slot walk |
| `0x36D670` | `aChrSelect__remapSlotIndexCircular` | slot → card index |
| `0x361FA0` | `aChrSelect__charIndexToRowCol` | slot → character id |
| `0x361F50` | `aChrSelect__findCharSlotIndex` | character id → slot |
| `0x326B90` | `cChrTrace__findByJointId` | safe linear search, null if absent |
| `0x455640` | clamp `(v+d, lo, hi)` | (Ghidra names it `MtDTI__getInstanceCount` — wrong) |
| `0x4556B0` | `MtMath__wrapRange` | wrap `(v+step, lo, hi)` |
| `0x372900` | `uMenuChrSelCursor` ctor | **sets the cursor's own columns/rows** — §9 |
| `0x372E50` | `uMenuChrSelCursor__move` | per-frame; also takes a directly-picked slot |
| `0x323920` | `uUiCursor__trans` | **the actual directional movement**, fully data-driven |
| `0x372D90` | `uCursor_vfn31(col,row)` | "is this cell live" — reads the grid table |
| `0x36D6E0` | page test | `(slot & 7) > 3`, picks the hover frame |

The cursor slot itself lives at `aChrSelect + 0xbc + player*4`, mirrored from
`uUiCursor + 0x4c`; `aChrSelect__setSlotCharSlotIndex` is its only writer.

Slot arithmetic: `slot = row * COLS + col`, with `col = slot & (COLS-1)` and
`row = slot >> log2(COLS)`. Both are immediates in `charIndexToRowCol` and
`remapSlotIndexCircular`, so **the column count is extensible as long as it
stays a power of two.** 12 columns would need mod/div detours instead.

The page a slot belongs to is decided by its column, and the card column runs
the other way: `remapSlotIndexCircular` mirrors the far half
(`if (col > 7) col = 15 - col`) then indexes the card as `(7 - col) * ROWS + row`.
So joint column 0 is the one nearest the spine. `vfn17` reads the table with
`col + 8` for one page and `-1 - col + 8` (= `7 - col`) for the other, both from
the same `lea ecx,[rax + 8]` — one displacement serves both branches.

### The divisor is two immediates
`vfn17` divides in a fixed instruction shape:
```
eax = MAGIC ; mul esi ; ecx = ((((n - edx) >> 1) + edx) >> SHIFT)
```
which is exactly `q = (n + mulhi_u32(n, MAGIC)) >> (SHIFT + 1)`. So:

| divisor | MAGIC @ 0x36E091 | SHIFT @ 0x36E0A1 |
|---|---|---|
| 7 (stock) | `0x24924925` | 2 |
| 8 | `0x00000000` | 2 |
| **9** | **`0xC71C71C8`** | **3** |
| 16 | `0x00000000` | 3 |
| 18 | `0xC71C71C8` | 4 |

`magic.py` verifies these exhaustively. Note `MUL`, not `IMUL` — the magic must
be the unsigned one. /9 and /18 share a magic and differ only in the shift.

### Why five sites need detours
Four are slot bounds: they become 144 (143 for "last slot"), and `cmp r32,imm8`
sign-extends so it tops out at 127. Each is replaced by `jmp rel32` into a code
cave that redoes the compare with a 32-bit immediate and jumps back to both
original destinations.

The fifth is the grid table's row stride: `FUN_140361FD0` indexes it with
`lea r9,[rdi + rsi*8]`, and an **LEA scale can only be 1, 2, 4 or 8** — there is
no `*16` — so it is redone in the cave as `shl rsi,4 ; lea r9,[rdi+rsi]`.

| rva | bytes taken | what |
|---|---|---|
| `0x36D2DD` | 9 | `vfn28`: `while (slot < 56)` → 144, signed |
| `0x361F79` | 5 | `findCharSlotIndex`: `while (i < 56)` → 144, unsigned |
| `0x368226` | 5 | cursor walk: "on the last slot" test, 55 → 143 |
| `0x36E825` | 6 | `setSlotCharSlotIndex`: `if (value < 56)` → 144 |
| `0x361FEC` | 8 | grid table row stride 8 → 16 |

`XrefsIn.java` confirms nothing branches into any of those byte ranges.

### The grid table has to be rebuilt, not copied
A page is chosen by column and the table is linear in slot, so widening to 16
columns re-splits slots 0-55 as 32/24 between the pages instead of 28/28. Each
page needs 26 cells (25 characters + its RANDOM card) plus 2 blanks behind the
banner plate, so the narrow side is 4 short. The plugin reads the vanilla table
apart by page and writes it back in the new shape, moving the last **4 Marvel
characters onto the Capcom page**:

```
page A  cols 0-7,  rows 0-3   32 cells = RANDOM + 2 blanks + 25 Capcom + 4 Marvel
page B  cols 8-15, rows 0-2   24 cells = RANDOM + 2 blanks + 21 Marvel
```

That balances exactly. It is also why 12 columns was the alternative: at 12,
page B gets exactly 26 and nothing crosses over — but 12 is not a power of two,
so `col` and `row` would each need their own mod/div detour.

### Traps — constants that look like row counts but are not
- **`0x36E450`** `cmp esi,7 / ja` — bounds check on an **8-entry jump table** at
  `0x36E5C8`, guarding a switch over the 12 overlay models. The loop runs
  `esi = 0..11`. Raising it made `esi == 8` `jmp` to garbage — **crashed the game
  on every CSS entry**.
- **`0x36D203`** `cmp eax,7 / jg` — a slot-**state** threshold, not geometry.
- **`0x36D682`** `cmp edx,8` — the **column** clamp. Columns stay at 8.
- **`0x368240`** `mov r9d,0x37` — the *step* argument to `MtMath__wrapRange` is
  not a literal; it is computed as `lea edx,[r9-0x3F]` from the same register
  that carries the bound. Widening the bound alone silently zeroes the step and
  **the cursor stops moving**. At 143 the displacement no longer fits imm8, so
  load it outright: `6A F8 5A 90` = `push -8 ; pop rdx ; nop`, four bytes.
- `0x3610BD` / `0x36A93A` load `0x38` and `0x3B` as a pair. Left alone.

---

## 5. CloneEngine behaviour — decisive constraint

**CE claims every slot from 56 up by index. The grid table's ids are ignored
there**, so the `[NewRows]` ini setting is a no-op when CE is installed.

**CE also supplies the whole table, not just slots 56 up.** It allocates its own
copy at `0x1B0000000` and repoints both readers at it after this plugin has run.
Its layout is the **vanilla roster flattened linearly** — the 7 x 8 table read
end to end — with its own ids appended from slot 56:

```
CE slots  0-15  20  0  0 53 54  0  0 37 | 25 24 21 23 45 47 50 49
CE slots 16-31   4 11  9 22 48 46 27 39 |  5 13  1  7 40 28 33 35
CE slots 56+    60 61 62 63 ...           its own roster
```

Read 16 wide that is wrong in a way that is easy to miss, because 25 of the 50
still land plausibly: the two cells the banner plate covers move to the wrong
columns, and the four characters that vanilla kept in row 0/1 end up on the
opposite page. So the plugin **lays CE's table out in place** rather than relying
on its own relocation — `RelayoutLiveTable` follows the live reader, checks the
vanilla signature (`t[3] == 53 && t[4] == 54`, which stops it re-running), and
rewrites **slots 0-55 only**, which is exactly the vanilla roster, leaving
everything CE owns untouched. It polls for up to 10 minutes because the handover
lands a few seconds after startup while the table is not read until the screen
is built.

CE maps **slot `56+n` → the nth playable entry in `Characters.ini`** (game root,
99 sections; entries without `SoundID`/`NumColors` are child helpers, skip them).
**There are 83 playable entries**, so the last one lands on slot 138 — which is
why the grid is 18 rows and not 16.

**Consequence: vanilla must stay at slots 0-55 (rows 0-6).** New rows can only
ever go **below**.

---

## 6. Layout — what actually constrains the grid, and why the grid went wide

Three ceilings, and the tightest is not the one you would guess:

- The **bone lattice** is a 4x4 control grid spanning y = ±360.
- The **page** is tighter. The stock 7 rows span y ±304.6 and fill the drawn
  book page. An 8th row at full pitch sits at y = -351 and renders *below the
  book*, swallowed by the HUD bar — exactly what the corrected 8-row build showed.
- The **screen** is tightest of all, and it is what killed "just make the book
  taller". Measured off a screenshot (`screenroom.py`, `cropng.py`): the book
  occupies y 215..642, the bottom control bar starts at 650, and the book's top
  edge is at ~192 against the TIME readout's "∞" ending at ~197. They already
  touch. Growing the book upward means sliding it behind TIME, and buys ~1.16x.

Horizontally there is loads of room: the book uses 665 px of 1280, with ~300 px
spare either side. So **height is the scarce axis and width is the free one**,
which is why the grid became 9 x 16 rather than 18 x 8:

| layout | card, game units | card, screen px | aspect |
|---|---|---|---|
| vanilla 7 x 8 | 116 x 88 | 83 x 63 | 1.32 |
| 18 x 8 | 116 x 34 | 83 x 24 | 3.4 |
| **9 x 16** | **58 x 68** | **42 x 49** | **0.85** |

`pitch = 609.2 / ROWS` (cards are as tall as their pitch, so `ROWS * pitch` is
the whole grid height), and each source column is split into `COLS/4` narrower
ones on the **cell** grid — not on each model's card width, or the hover
overlays, which are deliberately wider than the cards they frame, slide off.

### Card depth follows the page — do not move a card in x or y alone
The open book bows, so a card's `z` depends on where it sits: within a column
`z` runs about 34 → 39 from the middle of the page to its edges, and across
columns from 36 (near the spine) to 63 (mid-page). Moving a card without
carrying its depth leaves it **behind** the page over a broad, almost-tangent
region, and the page shows through as a large soft blob that swallows three or
four cards. `buildgrid.py` fits a 2D surface over the stock card vertices —
cubic in x, quadratic in y, ~700 samples so it is well conditioned — and carries
each card along it. A *local* fit is the wrong tool: an ill-conditioned
neighbourhood can extrapolate a card clean off the page.

This cost a full debugging cycle, and every cheaper hypothesis was wrong: the
weights were fine (`checkskin.py` scored the refit *better* than stock), no card
was oversized (`cardsizes.py`), and the artifact reproduced at plugin Stage 1
with no code patches at all, which is what finally pinned it on the archive.

### Re-weighting
Cards are bent onto the page by the lattice at runtime, so a card that moves
needs the weights belonging to its new position. `buildgrid.py` refits them with
a moving-least-squares pass over the stock weight field keyed on (x, y) — a
linear basis, so a query just past the last row extrapolates along the trend
instead of flattening onto the nearest card. `checkskin.py` scores the result by
asking how far each vertex's weighted bone centroid sits from where the bilinear
lattice says it should be; the 18-row build's worst is 73 units against stock's
82.9.

**The old handoff was wrong to call the lattice the blocker.** Rigid-binding
every vertex to one bone produced output identical to the weighted attempt not
because the lattice was inescapable, but because *skinning was never the
problem* — the per-axis decode was corrupting every coordinate before skinning
ever ran.

---

## 7. Portraits

`import_portraits.py` turns supplied roster-icon PNGs into portrait `.tex`: fits
each icon into the art window (cover-fit, top-anchored), lays the recovered frame
back over the margin, writes format 19 BC1 with the stock header.

Source icons: `~/Downloads/roster icons umvc 7 30 2026/roster icons umvc 7 30 2026/`
— `Tabs/`, `CaliKing/`, `EMC/`, `Shumariachi/`, `other/` hold named art.
`default roster/` and `EX Roster/` are vanilla. `tier list/` is a tier-list icon
set, not a CSS layout.

**CloneEngine ships its own `f_<id>00` portraits tagged format 42**, which the
engine cannot decode — they render as magenta noise, which is what filled the
lower rows on the first 18-row build. Decoded as ordinary DXT5 they turn out to
be placeholder silhouettes: a flat-shaded figure in the colour block and its mask
in alpha. `fixportraits.py` composites the two over the standard backing and
rewrites them at format 19, so they read as deliberate "no art yet" placeholders
instead of noise. Originals in `portraits/ce_fmt42_originals/`.

All 83 CE portraits are now format 19. **65 have real art; 18 are still
silhouettes** and would benefit from supplied icons:

```
Jastar Thing1 Closus Onslaugh Hayto Bbmm YunLeeSF Dmitri PXavier
DudleySFTS Djinn OniHN Sea EightBall Prowler Hideo Kyoko MaDra
```

Filename → CE id needs care: ids can end in digits (`WL3`, `STR29`, `Thing1`), so
strip only the trailing colour-index group with a **lazy** prefix
(`^[bf]_(.+?)(\d{2,3})_BM`). A greedy prefix turns `Rash255` into `Rash2`+`55`.

---

## 8. Scripts

| script | does |
|---|---|
| `io_umvc3_css/` | **the Blender addon** — see §11 |
| `io_umvc3_css/mod.py` | all ARC/MOD/MRL/TEX primitives, including the uniform-decode and skin-weight helpers, plus the generic archive round-trip |
| `io_umvc3_mod.py` | compatibility shim onto `io_umvc3_css.mod`; every headless script still does `import io_umvc3_mod as M` |
| `test_css_addon.py` | headless test of the whole character-select round-trip |
| `buildgrid.py` | **the grid rebuild** — any rows x columns, splits source columns, moves/scales cards, clones missing cells, renumbers joint ids, refits weights, follows the page bow |
| `readgrid.py` | read the vanilla grid table out of the unpacked exe |
| `screenroom.py` | measure the book's screen extent against the UI overlays |
| `modelsurvey.py` | every model's bones, meshes, bounds and textures |
| `verifygrid.py` | pre-install checks: joint ids, cell occupancy, .mrl bindings, drift vs stock, weight sanity |
| `verifypatch.py` | **every patch site in the plugin vs the stock exe** — reads the tables straight out of the .cpp, so a wrong `expect` is caught before a launch instead of as a GAVE UP line in the log |
| `idnames.py` | recovers the **character id -> internal name** table from the exe (see below) |
| `cellcheck.py` | which (column, row) cells actually have a card in each grid model |
| `row0probe.py` | x extent of every row-0 mesh, stock vs rebuilt — the banner plate's row |
| `drive/writemem.ps1` | poke int32s into the running game — test a table hypothesis without a rebuild |
| `checkskin.py` | which vertices would fly off once the page curls |
| `cardsizes.py` | flags a card that is not the size its row says |
| `layout.py` | survey the grid: cell, position, depth, size |
| `decode.py` / `fitscale.py` | evidence for the uniform decode |
| `bones.py` / `boneprobe.py` | dump and compare the bone sections |
| `bboxprobe.py` / `invprobe.py` | in-game probes that proved the header box inert |
| `magic.py` | verify a replacement divide magic |
| `import_portraits.py` | roster icons → portrait `.tex` |
| `fixportraits.py` | repair CE's undecodable format-42 portraits |
| `ce_portraits.py` | decode format-42 portraits to PNG for inspection |
| `texsurvey.py` | format/size survey of installed portraits |
| `frame_template.py` | recovers the shared card frame → `frame_data.py` |
| `cropng.py` | crop a saved screenshot |
| `arc.ps1` / `arcpack.ps1` | list/extract, pack a directory |

### Verification habits that caught real bugs
Always re-verify **before** installing (`verifygrid.py` does all of this):

- **Material bindings preserved**: resolve every mesh through its name hash to an
  `.mrl` entry index, before and after; require identical. This caught a rename
  pass that silently scrambled **249** bindings.
- **Joint id field matches the name** on every material.
- **Positional check**: every card sits where its id says. Tolerance must be ~5
  units, not 2 — the `selr1` hover frames are deliberately jittered and stock
  trips a tighter bound.
- **Drift vs stock**: cards that should not have moved must match to within half
  a quantisation step. The 8-row rebuild scores 0.0134 against a 0.0268 step.
- Staged in-place edits: collect all renames first, apply in one pass over a
  snapshot. Renumber existing materials **before** appending new ones.

### Process notes
- Write the plugin `.ini` **without a BOM** — `GetPrivateProfileIntA` cannot find
  `[Config]` behind one and silently returns the default.
- PowerShell is case-insensitive: a local `$out` collides with an `-Out` parameter.
- PowerShell 5.1: no `&&`/`||`/ternary; use `[Convert]::ToUInt32('EDB88320',16)`
  for large hex.
- The game holds the `.asi` open — stop the process before copying.
- Use the plugin's **stages** to attribute a symptom to a layer. Stage 1 applies
  the archive with no code patches at all, which is how the page-depth bug was
  separated from the engine work.

---

## 9. The cursor — fixed, and why it hid for so long

**Was: directional input did not move the cursor the way it should.** Verified in
game after the fix: every direction steps exactly one cell, the spine is crossed
correctly, both wraps land on the true grid edges, all 9 rows are reachable, and
a slot-128 CloneEngine character (Dudley) selects through to assist type.

**The cursor is a separate object, and it had its own copy of the grid size.**
None of the slot math in §4 is involved in moving it. Each player owns a
`uMenuChrSelCursor` (`aChrSelect + 0x120 + player*8`) which embeds a generic
`uUiCursor` at **+0x78**, and that base class does all the navigation off two
fields handed to it at construction:

```
[+0x54] columns   [+0x58] rows   [+0x5c] columns * rows   [+0x4c] current slot
```

```
uUiCursor__trans @ 0x323920:
    row = pos / cols;  col = pos % cols
    right/left -> col +- 1        down/up -> row +- 1
    wrap col into [0,cols), row into [0,rows)
    pos = cols * row + col
```

The subclass supplies only `uCursor_vfn31(col,row)` @ `0x372D90` — "is this cell
live" — which is `FUN_140361FD0(col,row) != 0` plus "character not already
taken", so it follows the relocated table for free. **Nothing anywhere in
`uUiCursor` hard-codes a dimension**; the only 8 and 7 in the whole cursor were
the two constructor calls, so four bytes fix every direction at once:

| rva | was | now |
|---|---|---|
| `0x372965` | `mov edx,8` | `mov edx,16` — columns |
| `0x37296E` | `lea r8d,[rdx-1]` | `lea r8d,[rdx-7]` — rows, 16-7 = 9 |
| `0x3729DB` | `lea edx,[rax+8]` | `lea edx,[rax+0x10]` — default ctor |
| `0x3729DE` | `lea r8d,[rax+7]` | `lea r8d,[rax+9]` — default ctor |

Note the row count was *encoded as columns - 1*, which holds only at 8 x 7. Keep
the same LEA and change the displacement.

At 8 x 7 against a 16 x 9 grid a vertical step moves the cursor 8 slots — half a
row — so Down landed eight columns across on the same row, usually on the other
page; and the horizontal wrap fired at column 7, mid-grid, instead of column 15.
Left and Right inside a page therefore looked right while Up and Down never did,
which is exactly what "the direction only sometimes matches" looks like from the
pad. It also explains why the 18 rows x 8 columns build seemed fine: 8 was still
the true width, so `pos = cols * row + col` stayed correct and every press moved
one cell in the pressed direction. Only the row count was wrong, and a wrong row
count wraps early rather than mis-steering — the cursor just never reached rows
7-17.

Fixed alongside it, same root cause:

- **`FUN_14036d6e0` @ `0x36D6E2`** — `(slot & 7) > 3`, the page test that picks
  the hover frame (`aChsMekuSel1A..`, indexed `page + (player+4)*2`). At 16
  columns it read the wrong half: slot columns 4-7 are still the Capcom page but
  took the Marvel frame. Now `(slot & 15) > 7`.
- **Home slots 26 and 29 → 22 and 25.** 26 and 29 are the two page centres of a
  7 x 8 grid; read 16 wide they are columns 10 and 13, so *both* players opened
  on the Marvel page. 22 and 25 hold vanilla's actual position — card column 1 on
  each page — and stay mirrored (`22 & 15 = 6`, `25 & 15 = 9`, `15 - 6 = 9`).
  Row 1, because row 0 carries the banner plate's blanks and the Marvel page has
  only rows 0-2 of vanilla characters. Eight sites: `0x372986`, `0x37298F`,
  `0x36EB85`, `0x36EB8F`, and the walker's `0x3680C6`, `0x3680CE`, `0x3681D7`,
  `0x36822F`.
- **`uMenuChrSelCursor__move` @ `0x3731BA`/`0x3731CB`/`0x3731CF`** — a second
  entry point that takes a slot straight from the input mapper (picking a card
  rather than walking to it) and split it with `>> 3` / `& 7` behind a `< 56`
  bound. Now `>> 4` / `& 15` and a 144 detour.

### Why the earlier search missed it
`ScanColumnMath.java` was run over `0x360000-0x372000` and `0x200000-0x340000`.
`uMenuChrSelCursor` lives at **`0x372840-0x373200`** — a few hundred bytes past
the end of the first range — and the direction predicates it consumes are at
`0x3D59A0-0x3D5B60`. **Run range scans over the whole image**
(`0x140001000-0x140a60000`) and filter afterwards; that is only 6337 hits and
costs the same minute.

The path that did find it, for the next time something on this screen is
invisible:

1. `ScanDirMask.java` — every instruction anywhere that tests a d-pad mask
   (`b | b<<12` for `b` in 0x10/0x20/0x40/0x80). That surfaced
   `uMenuChrSel_vfn17..20` @ `0x3D5B20`/`0x3D59A0`/`0x3D5A00`/`0x3D5AC0`, which
   turn out to be per-direction predicates in the `aChrSelect` vtable at
   +0x88/+0x90/+0x98/+0xA0 (up / down / right / left).
2. `ScanDisp.java` — every access to the cursor field `aChrSelect + 0xbc`. Its
   only writer is `setSlotCharSlotIndex`, whose callers lead to
   `uMenuChrSelCursor__move` and from there to the embedded `uUiCursor`.

**Dead ends, so nobody repeats them:** `aChrSelect__slotState12_moveCharCursor`
@ `0x3643A0` reads all four direction masks but drives a *linear* index bounded
by `sGameConfigRoster__getCharCount` — not the grid.
`aChrSelect__advanceCursorToNextSelectableChar` walks *team members* (`r14+1`
against 3) after a pick. `aChrSelect__processChrSelectInputs` @ `0x41BF90`
switches mode/tab. The two non-walker `wrapRange` callers (`0x36B5AC`,
`0x36BD15`) wrap a 3-state value with `hi = 2`.

**Fallbacks:** `asi/umvc3_cssslots_16col_nocursor.asi` is the 16-column build
from immediately before this fix. `backup/BUILT_mnchscmn_18row.arc` plus
`asi/umvc3_cssslots_18row.asi` is the 18 rows x 8 columns build — but note its
cursor is 8 x 7 as well, so it only ever reached rows 0-6.

---

## 10. Known remaining rough edges

- **Slots 139-143 read UNKNOWN.** 144 cells and CE only supplies 83 characters
  from slot 56, so five cells at the end have nothing behind them. They come
  from CloneEngine, not from this work. The cursor **skips** them rather than
  stopping on them, so holding Down through column 15 jumps from row 7 to row 0
  — that is `uUiCursor` correctly refusing a dead cell, not a movement bug.
- **18 characters still show placeholder silhouettes** (list in §7) — they need
  supplied roster icons, then a re-run of `import_portraits.py`.
- **4 Marvel characters sit on the Capcom page.** Forced by the 32/24 cell split
  at 16 columns; see §4. Going to 12 columns removes it at the cost of mod/div
  detours and smaller cards.
- **Portraits are squashed horizontally by ~0.58.** The art window is 112x76
  texels (1.47:1) and the card is now 0.85:1. `import_portraits.py` has a
  `UMVC3_CARD_ASPECT` knob that pre-compensates by cropping the source to the
  card's aspect before stretching it into the window, but it is left at the
  window aspect on purpose: the 50 vanilla portraits are stock art this pipeline
  does not produce, so correcting only the CE ones would look worse than the
  present uniform squash. Fixing it properly means regenerating all 133 from
  `default roster/` + the CE sources — and the `default roster` PNGs have opaque
  **white** backgrounds, which need keying (a border flood fill, not a colour
  threshold, or Ryu's white gi gets punched through).
- **The banner plate is cramped.** It carries the RANDOM card and the
  CAPCOM/MARVEL logo as one mesh spanning 3 joint columns; at half column width
  its texture is compressed about 2x. Widening it needs more blank cells than
  the roster split leaves free.

### FIXED: row 0 rendered wrong (Firebrand and Strider had no portrait)
Row 0 is the one row that shares its page with the banner plate, and it is the
only row whose *population* changed shape rather than just size. In vanilla each
page's row 0 held **one** character (joint column 3) with the 348-unit plate
covering joint columns 0-2 — three of the four columns. At 16 columns the plate
is halved to 174 units and still covers joint columns 0-2, but that is now three
of **eight**, so row 0 has to hold **five** characters where stock had one:

```
page A row 0 slots 0..7 = Jill(20) Nemesis(25) Firebrand(24) Strider(21)
                          PhoenixWright(23) blank blank RANDOM_A(53)
joint column = 7 - slot column, so the five cards are joint columns 7..3
```

On screen that row instead renders as: Jill, **two UNKNOWN cards**, the plate,
a gap, and a stray card at the spine — so two characters lose their portrait and
two more are behind the plate. Hovering and selection are unaffected, because
those go through the grid table, which is correct.

**Ruled out — do not re-check these:**
- the grid table itself: read back live from the relocated copy, byte for byte
  what `RelocateTable` intends (`drive/readmem.ps1 -Address 0x138360000`);
- the archive: `verifygrid.py` passes all five checks at 9x16, `cellcheck.py`
  shows face_a/face_b at 70 cards with exactly joints 9 and 18 absent (the two
  banner cells, same as stock's 26 = 28 - 2), overlays at 72 (stock 28);
- geometry: `row0probe.py` puts the plate at x -199.8..-25.8 = joint columns
  0,1,2 exactly, and the five row-0 cards at joint columns 3-7, all correct;
- weights: `checkskin.py` worst 73.8 units against stock's 82.9;
- `vfn17`'s constants: `ScanConstants.java` finds no unpatched 7 / 0x1c left.

**Cause: the plugin's re-laid table was never being read — CloneEngine had
repointed the readers at its own, un-re-laid table (§5).** The screen was
running off CE's linear vanilla order, so page B row 0 held
`Nemesis, Firebrand, Strider, PhoenixWright, ...` and Firebrand and Strider fell
on page B joint columns **1 and 2 — the two cells `face_b` has no card mesh
for**. Nothing to draw on, hence no portrait; the cursor and the name plate kept
working because those go through the table, not the mesh. Nemesis at joint
column 0 sat right beside them, which is exactly how the symptom read.

**Fix:** `RelayoutLiveTable` follows whichever table the readers actually point
at and lays that one out. See §5. Verified in game: row 0 walks
`Jill -> Nemesis T-Type -> Firebrand -> Strider Hiryu -> Phoenix Wright` one cell
per press with every portrait present, the RANDOM plates sit at the spine on both
pages, no UNKNOWN cards remain, and a deep CloneEngine slot still selects through
to assist type.

**How it was found, since two plausible stories fit the screenshots for a long
time.** `drive/writemem.ps1` (added for this) pokes int32s straight into a table
in the running process, so a hypothesis can be tested without a plugin rebuild.
Overwriting the relocated table changed nothing — but so did overwriting *row 1*,
which was the control that broke the deadlock: if no row responds, the table
being written is not the table being read. Reading the disp32 back out of the lea
(`readmem.ps1 -Address 0x140361FE8 -Count 1`) then showed it pointing at
`0x1B0000000`, and dumping that address showed CE's flat vanilla roster, which
matched the screen cell for cell.

**Lesson worth keeping:** when a probe produces "nothing changed", test the
*control* before theorising about the mechanism. Three hours went into explaining
why row 0 was special when no row was special.

---

## 11. The Blender addon — `io_umvc3_css/`

Opens the character select as an editable scene and writes it back. It is a
package, not a loose file, so it installs as one thing:

```
io_umvc3_css/
  __init__.py   bl_info, addon preferences (game folder), register
  mod.py        formats + generic archive round-trip   (was io_umvc3_mod.py)
  pagefit.py    the page's real surface                (was pagefit.py)
  grid.py       cells, slots, joint ids, weight field, page bow, renumbering
  roster.py     character ids, CloneEngine's roster, portrait .tex
  scene.py      import / export / install the scene
  verify.py     the pre-install checks
  ui.py         panels and operators
```

The panels sit in the **Properties editor**, not a viewport sidebar tab: the
card's character and cell are per-object so they live in Properties > Object
(polled on the active object, so the tab stays clean for everything else), and
the grid, game folder and write options are per-scene so they live in
Properties > Scene. A sub-panel must declare the same `bl_space_type` **and**
`bl_context` as its `bl_parent_id` or it silently never draws.

`io_umvc3_mod.py` and `pagefit.py` at the top level are now **shims** that
re-export the package's namespace, underscore helpers included, so all ~20
headless scripts keep working with no edit. `buildgrid.py` and the addon now
share one copy of the weight field, the page surface and the grid maths —
`buildgrid.py` reproduces the installed 9x16 build exactly after the move
(70 cards on `face`, 72 on the overlays).

**Disable the old standalone `io_umvc3_mod.py` addon** if it is still enabled in
Blender: both register the same operators. The shim has no `bl_info`, so Blender
will not offer it as an addon any more.

### The model, and the one decision that matters

A cell of the grid is **six meshes** — the `face` card plus `sel1`, `sel2`,
`seld1`, `seld2`, `selr1` — all carrying the same joint id. Each cell gets **its
own collection** holding all six, and the count checks out exactly: 12 models x
72 cells, less the two cells per page that `face` leaves for the banner blanks,
is **860 meshes in 146 collections** (144 cards + one banner per page).

Three details make that structure actually work, and all three were learned the
hard way:

- **The card object is the `face` mesh, not a separate empty**, and the five
  overlays are parented to it. Collections group; only parenting transforms.
  Making the thing you see in the viewport the thing that carries the others
  means a click selects what you meant. (A cell `face` has no mesh for — the two
  the banner covers — falls back to whichever overlay is present.)
- **The overlays are hidden on import.** They are drawn in *front* of the cards
  and are deliberately wider, so left visible they hide the portraits and take
  every click. That is how a card gets moved with its highlights left behind:
  the diff of one damaged install showed `face_a` changed and the five overlays
  untouched. Toggle them from the Card panel.
- **Each mesh's origin is moved onto its card.** Imported meshes carry absolute
  coordinates with the origin at the world origin, so rotate and scale would
  otherwise pivot about the middle of the book.

`import_css` ends with `view_layer.update()`: origins and parenting are rewritten
wholesale, and `matrix_world` is only refreshed when the depsgraph next
evaluates, so without it the panel and the exporter read the pre-regroup scene.

**Dragging a card does not renumber it.** A card's cell is its joint id, and
`cChrTrace__findByJointId` is what binds it to a slot, so where a card is drawn
and which slot it answers to are independent. Renumbering on drag would rewire
the grid under a cosmetic edit. Use **Renumber From Position** to move a card
between cells; it refuses collisions.

Export does the two things a moved card cannot live without — carries depth
along the page bow (keeping each vertex's original clearance over the paper) and
refits skin weights through the MLS field — and only then re-encodes.

### Verified headlessly (`test_css_addon.py`, all green)

- imports the installed archive as 9 x 16, 860 meshes, 146 groups, **133
  portraits** bound onto their own cards;
- exporting untouched moves nothing: **drift 0.0000** against a 0.0241
  quantisation step, nothing renumbered, verify clean;
- moving a card 120 units writes it, keeps its joint id, follows the bow
  (-36.5 in z) with clearance preserved (4.02 -> 4.57), and refits all 30
  vertices' weights, which still sum to 1;
- the alignment check still *notices* the moved card — it is a warning, not an
  error, so a deliberately rearranged screen installs;
- adding a card into joint id 9 (one of the two cells `face_a` leaves for the
  banner) appends the mesh, its material and its `.mrl` entry, and stores the id
  in bits 21..28; `face_a` goes 70 -> 71 cards and verify stays clean.

`test_addon.py` was already stale before this work (`M.import_mod` had been
renamed away and it pointed at `extract/` rather than `extracted/`); it is fixed
and the single-`.mod` round-trip is **bit-identical** again.

### FIXED: a card dragged past the spine came out folded

Moving a card across x = 0 rendered it wildly distorted in game. **The page
surface is a quadratic MLS fit sampled only over its own half of the book**
(page A covers x -603..0), and `follow_page` evaluates it per vertex. Past the
spine that is extrapolation of a quadratic, which does not flatten out — it
takes off. One card came back with **5919 units of z spread across its own
58 x 68 face**: a fold, not a move. It also dragged the whole model's decode
with it, coarsening `face_a`'s quantisation step from 0.0241 to 0.1926 and so
degrading every other card in that model.

Joint column 0 is the column at the spine, sitting at x ~ -38, so this is one
small drag away — it is not an exotic edit.

Two fixes, both in place:

- `pagefit.Surface` **clamps queries to its sampled domain**, so past the edge
  the depth simply stops changing instead of exploding. `Surface.contains()`
  reports the overhang and the exporter warns which cards sit off the book.
- `scene.export_css` picks the surface from **where the card now is**, per card
  (never per vertex, or a card straddling the spine tears down the middle), so a
  card that crosses the gutter follows the page it is actually on.

`verify` now treats a card spanning more than 100 units in z as a hard problem —
a card is flat, so anything beyond the page's ~25-unit local tilt means its
depth came from somewhere that was extrapolating. That check would have caught
this before it ever reached the game.

**Watch the selection.** A cell is six meshes, and clicking in the viewport picks
one of them, not the card. Moving just the mesh leaves the five hover/select
overlays at the old cell — invisible until you hover it in game. The Card panel
now warns when a mesh rather than a card is active and offers **Select Whole
Card**.

### Dynamic placement — who sits where

Placement is editable in Blender and real in game. The engine has **two**
mechanisms and the addon drives both, because neither covers the whole grid:

| who | placed by | where it is written |
|---|---|---|
| the vanilla 50 (slots 0-55) | the grid table | `[Layout]` in `umvc3_cssslots.ini` |
| the 83 CloneEngine characters (56+) | CE's own index | the order of the playable sections in `Characters.ini` |

**`[Layout]` is new plugin work.** `umvc3_cssslots.cpp` now reads
`[Layout] Slot0=..` and `BuildLayout` uses it verbatim instead of dealing the
vanilla roster out by its fixed rule. It is bounded — our own relocated table
takes all 144, a table CloneEngine owns takes only the vanilla 56, so CE keeps
everything it owns. `NeedsLayout` compares against the wanted table rather than
the vanilla `53/54` signature when a layout is present, which keeps the watcher
idempotent even if a layout puts RANDOM back where vanilla had it. **The change
is inert without a `[Layout]` section**, so the new build is a safe drop-in.
Rebuild with `asi/build.bat`; `verifypatch.py` still reports 45/45 sites.

**Reordering `Characters.ini` is safe** because CE's cross-references are by
name — `BaseCharacter=VJoe`, `Child1=PsylockF` — never by index or section
number. `roster.rewrite_characters_ini` permutes the playable entries **in
place**: each playable position takes the next id, and every child-helper
section stays exactly where it was, so no helper is dragged across its parent.
Sections are renumbered `[CharacterN]` as well as physically moved, so it does
not matter whether CE walks the file or the numbering.

**Assignments are keyed by name, not index** (`cGambit`, not `c15`). Reordering
the ini is precisely what invalidates an index, so an index-keyed assignment
would silently repoint at whoever landed there. The Card panel's dropdown is an
`EnumProperty` with `get`/`set` over that string rather than a stored enum
value, for the same reason — a dynamic enum stores the chosen item's *index*.

**One character on two cards is refused, at three layers.** CE deals its roster
out one entry per slot, so a duplicate leaves someone with nowhere to go; the
rewrite's loop simply never reached the last entry and **deleted that character
from `Characters.ini`** — observed for real, Gambit lost and Iceman duplicated.
Now `plan_placement` reports it naming both slots, `install` leaves
`Characters.ini` alone while any placement problem stands, and
`rewrite_characters_ini` refuses a duplicated or wrong-length order outright and
re-checks the multiset of `CharacterID`s on the text it is about to write. A
reorder moves entries; it never adds or removes one.

`portraits.py` builds a portrait `.tex` from any image — the `import_portraits.py`
pipeline as a function — so assigning a character to a card and dropping in a
PNG creates `f_<Name>00_BM_HQ_NOMIP.tex` if it did not exist.

### FIXED: one moved card silently reset the grid to 7 x 8

`detect_rows` demanded that **every** card sit within 2 units of its row and
column. Moving a card is the entire point of this addon, so one displaced card
failed detection outright, `detect_grid` fell back to the vanilla 7 x 8, and
every slot number and character assignment in the scene was then wrong (joint
ids come from the material names, so the geometry stayed correct — this only
corrupted placement). It now scores **how many cards agree with their group's
median** and takes the best, needing 75%; it survives 8 displaced cards. Guards
against the degenerate case where a large modulus gives every card a group of
its own: every row must be occupied and hold at least two cards. Twelve models
vote and the majority wins.

Related, same session: "moved" is now judged against **half a quantisation
step**, not `1e-4`. Below half a step a vertex re-encodes to identical bytes, so
the old threshold reported the float32 noise of a round trip through Blender as
an edit — 10 phantom cards on an untouched export.

### SOLVED: where the engine draws the character card — the `.sdl` scheduler

The models the card path leaves at their local origin (`chs_card`, `chs_card_bt`,
`chs_card_tf`, `chs_card_tw_typeC`, `p_chs_hnd1`) are not placed by code. They
are placed by the **SDL resources** (ext hash `0x4C0DB839`), which were sitting
in the archive undecoded the whole time.

The trail, all from the community Ghidra DB:

* `uMenuChrSelCardPlayer__setup` @ `0x3718b1` loads
  `ui\chs\chs_meku\chs_card%dp` → `chs_card1p` / `chs_card2p`, into
  `this->field0_0x0 + 0x58`, and drives it with `MtAnim__setFrameState`.
* `uMenuChrSelCardPlayer_vfn28`/`vfn29` format node names —
  `chs_card%dp_no%d`, `..._tf`, `..._tw` — and resolve each with
  `MtAnim__helper_E580(anim, name)`, which is
  `MtAnim__updateFrame` (name → index) + `MtAnim__getFrame` (index → node),
  the node array being `anim+0x60` with the count at `anim+0x68`.
* The resolved node is handed to `sMvc3Manager__beginPhase_19A0(unit, node, ...)`,
  which is what binds the drawn unit to the animated transform.

### The SDL format

**Superseded in part — see "The SDL format, properly" below.** The reading here
was right about what the layout means and wrong about two things that only
showed up once the file had to be *written*: the record table starts at **0x20**,
not 0x50, and a value is as wide as its storage kind, not always 16 bytes.

```
+0x00 "SDL\0"        +0x04 u16 version (0x16)   +0x06 u16 record count
+0x08 u32 hash       +0x0C u32 (621, unused here)
+0x18 u64 offset of the string table
0x50: record[count], 0x30 bytes each
```
Each record:
```
+0x00 u32 flags   2 marks an OBJECT; anything else is a property
+0x04 u32         object: its class id. property: owner record index, 1-BASED
+0x08 u32         name, as an offset into the string table
+0x20 u64         key table  (u32 per key: frame in the low 16 bits)
+0x28 u64         values     (16 bytes per key; mPos/mAngle/mScale use xyz)
```
So an object owns every following property whose `+0x04` is its index + 1.
`mpParent` is a **1-based record index** of another object, `mpModel` a string
offset (the string is length-prefixed — the stray `X` before
`ui\chs\chs_meku\chs_card` in a raw dump is `0x18`, the length, not a letter).
Object 0 is `UiSdlAnimeFrame`, whose properties are the clip table:
`FrameName<i>` (string offset), `FrameStart<i>`, `FrameEnd<i>` — **floats**, not
ints. Clips here: `start` 0–60, `sel1` 60–69, `sel1_decide` 69–89, … `start_vs`.
The key frames (0, 61, 91, 101, 121, …) land exactly on those boundaries, which
is what confirms the parse.

### The SDL format, properly — and it writes now

Reading one pose out of a scheduler tolerates a lot; writing keys back into it
does not. `rScheduler__convert` @ `0x140522670`, the load-time fixup, is the
authority and settles both mistakes above.

**The record table starts at 0x20**, and record 0 is `Root`. That is the whole
explanation for the "1-based" owner index: it was a 0-based index into a table
that begins one record earlier than assumed. Starting at 0x50 also reads one
junk record past the end, which is the `type=0` record in old dumps.

**The first word is three fields**, not one:

```
+0x00 u8  storage kind - how wide a value is; 2 marks an object
+0x01 u8  MT property type - 3 bool, 6 u32, 10 s32, 12 f32, 14 string,
                             15 colour, 20 vector3, 34 float2, 128 resource
+0x02 u16 key count
```

**A value is `kind` bytes, not 16.** Measured over every key in the game: kinds
6, 9, 12 and 15 are 4 bytes, kind 8 is 16, kind 11 is 1, kinds 13 and 14 are 8,
kind 16 is a 64-byte matrix. Reading everything as 16 works for
`mPos`/`mAngle`/`mScale` — which is all the old reader looked at — and silently
misreads every multi-key scalar track (`mTransparency`, `mFrame`, `mDepth`) as
the following key's bytes.

`convert` also confirms the rest: +0x08 is a u64 name offset, +0x10 on an object
is a class DTI hash resolved through `MtDTI__findByHash`, and only kinds 6..16
have key tables to relocate. An object's +0x04 is **not** a record index (it is
some class category: 4, 8, 28, 29, 30, 31 — several hashes per value and several
values per hash), which is what makes inserting a record safe.

**Key word = `frame | interpolation << 24`.** Codes across the whole game are 0,
2, 3 and 5. Int, bool and string tracks are always 0; float and vector tracks
are 3, sometimes 5, and *sometimes 0 on single keys of a moving track* — a hold.
So 0 is CONSTANT and the rest interpolate. What separates 3 from 5, and the
curve either draws between keys, is **not decoded**; the code is preserved per
key so nothing is invented and nothing is retyped by a round trip.

**Layout, for the writer**: blocks follow the record table in order, key table
aligned to 4, values aligned to 16, then the string table aligned to 4. That
reproduces **1657 of the 1664 shipped `.sdl` files byte for byte**, and all 174
in the character-select archives. The seven that differ are `mnmain` files whose
value blocks overlap; they rebuild valid but not identical, and nothing rewrites
a resource it did not edit. Value blocks are kept verbatim, padding and all,
until a property is actually edited — which is what makes the byte-identical
rebuild survive kinds this does not decode.

Adding a *new* property to a node (rotating the cursor, which has no `mAngle`)
inserts the record with the node's other properties and moves every later record
index along — owners and `mpParent` values both. Appending at the end would
avoid the renumber, but nothing shipped is laid out that way and the engine's
binding order is not known well enough to risk it.

**Rotation order** is `uCoord`'s, from the switch in `uCoord__setEulerRotation` @
`0x140547b50`. Order 0 builds

```
[ cz cy,            cy sz,             -sy   ]
[ sx sy cz - cx sz, cx cz + sx sy sz,  cy sx ]
[ cx sy cz + sx sz, cx sy sz - sx cz,  cy cx ]
```

which is `Rz . Ry . Rx` transposed for MT's row-vector convention — exactly
Blender's `XYZ`. No `.sdl` in these archives sets a rotation order at all, so
order 0 is what they get. The earlier note that XYZ was "faithful because every
angle is dominated by one axis" is now simply correct rather than lucky.

### The numbers

Player 1's stack hangs off an anchor, `card1p_cen`, with one anchor per card:

| node | at frame 0 | settled (frame 120+) |
|---|---|---|
| `card1p_cen` | pos (−830, 0, 0) | **pos (−425, 0, 0), angle (0, 1.22, 0), scale 0.7** |
| `chs_card1p_no1` | (−20, −10, 0), angle (0, π, 0), scale (0.9, 0.9, 0.2) | rotates through the three slots |

The three cards occupy three slots relative to the anchor and rotate between
them as the carousel rolls: **(−20, −10, 0)** front and active at scale 0.85–0.9,
**(50, −300, −200)** and **(70, 270, −200)** stacked behind at 0.7. Frame 0 is
off-screen left at x = −830; the stack has flown in and settled by frame 120.
`chs_card2p` is the mirror for player 2. `_un`, `_tf`, `_tw` are children of the
card node at identity, drawing the base, the name plate and the type panel.

### `mParentFlags` is an enum, not a bitfield

From the transform compose at `0x14013cf34`, which is the only code that reads
the `u16` at `uCoord + 0x4e`:

| value | what it does to the child's basis | meaning |
|---|---|---|
| 0 | overwritten with a constant matrix | inherit the parent's **position only** |
| 1 | each basis row normalised | inherit rotation, **drop the parent's scale** |
| 2 | rows replaced by their lengths | inherit scale, drop rotation |
| 3 | left alone — falls through | **inherit the parent's matrix whole** |

Every node in the card layout is 3, `_tf` and `_tw` included. The earlier reading
that they were 0 was the float bug below, not the file.

### Two things that cost a round each

* **The key count is in the record**, high 16 bits of `+0x00`. Derived instead
  from the gap between the key table and the value block it overruns — the table
  is padded to 16 bytes while the values run right up to the *next* property's
  key table — so `mPos` read its last keys out of `mAngle`'s frame numbers and
  `mAngle` came back holding `(1, 1, 1)`, which is a scale.
* **A value is four raw bytes, not a float.** `mParentFlags`, `mpParent` and
  `mpModel` are integers; read as floats they are denormals that round to zero,
  which is how every node came out claiming to inherit nothing and owning no
  model.

Rotation order is `uCoord`'s. It was read later, and it is XYZ — see above.

### The animation is in the scene, and it goes back

`io_umvc3_css/anim.py` carries the keys into Blender and back. `mPos`, `mAngle`
and `mScale` become the empty's own location / rotation / scale curves; `Draw`
becomes keyed viewport and render visibility; every other keyed track becomes a
keyed custom property `sdl_<name>`, so colour, transparency and draw depth are
in the Graph Editor and still write back. Tracks whose values are string-table
offsets (`Texture`, `mpModel`) are left alone — their keys are file offsets, not
numbers to edit — and round-trip untouched.

Four layouts animate: `chs_card1p`, `chs_card2p` (605 frames), `chs_meku` (560)
and `chs_hnd_a` (91).

### Each clip is an Action, and the timeline is NLA strips

The first version put all 605 frames in one action per object and the clip table
on the timeline as markers. That is not how anyone edits: the unit of an edit is
`sel1_decide`, not frame 71. So **each clip is its own Action** — `chs_card1p |
sel1`, one slot per node so the whole layout's share of a clip is one datablock
— and the clips are laid back out as **NLA strips** at the frames they cover.
The strips *are* the timeline; there is no whole-timeline action to keep in sync,
and a clip edited in place is a clip the timeline plays differently. *n* clips /
Done in the Scene panel assigns one as the active action to work on and sets the
preview range to it.

Two things this needs that are easy to get wrong:

* **A clip must carry every animated channel, at both of its ends.** A strip
  that says nothing about a channel does not leave the previous strip holding
  it — the channel falls back to the object's own value and the pose jumps. The
  first build did exactly that and `card1p_cen` snapped back to the settle pose
  at frame 121, where `sel2` had no `mPos` key of its own. Each clip therefore
  gets the value sampled at its start and end for every channel that moves
  anywhere in the layout.
* **Those samples must not come back out as new keys.** On export a key is
  dropped when the file has no key at that frame *and* it holds exactly what the
  track already said there — value and interpolation code both. The code matters:
  the sample at 620 sits after `mPos`'s last key at 520, whose code is 5, so
  taking the track's usual 3 as a default left a spurious key in four nodes and
  the untouched archive stopped being byte-identical. A frame the file has no
  code for now takes the code of the segment it lands in.

Clip tables in these four are well behaved — no real overlaps, no keys outside
any clip (the cursor's layout has no clip table at all and gets one `(all)`
action), one zero-length clip (`start_wait` 61..61, an action but not a strip)
and one duplicated name (`sel_team_end` twice, so labels are made unique).
Boundary frames are shared by two clips, and the merge takes whichever copy
differs from the shipped file as the edit; both edited apart is reported.

**An animated chain has to be real parenting.** Placing one pose can compose the
node chain by hand and hand Blender a world matrix, which is what
`place_sdl_layout` did; a moving parent cannot, because the composition changes
every frame. With animation on, each empty's basis holds exactly the node's own
local transform and `matrix_parent_inverse` stays at identity, so Blender
composes `parent_world @ local` the way the engine does for `mParentFlags == 3`
— the value every node in these layouts uses. Verified against the file at nine
frames across the timeline: worst error 1.2e-7 local, 2.4e-7 composed.

One Blender artifact worth knowing: at a frame where `Draw` turns a whole
subtree off, those objects leave the depsgraph and their `matrix_world` goes
stale. `location` and the curves are still right, and export reads curves — but
a script reading `matrix_world` at such a frame is reading the last frame that
was drawn.

Export writes only tracks that actually changed, compared at float32, so an
untouched layout comes back byte-identical and the other player's card stack is
not rewritten because you touched this one. `test_css_anim.py` is the headless
proof of all of it.

### It is in the addon

`io_umvc3_css/sdl.py` parses it; the importer builds an empty per node at the
settle frame — the end of the `start` clip, frame 61, after the fly-in — parents
them as the file does, and **instances** the model onto the empty. Instanced,
not moved: one `chs_card` is drawn three times per player, and the source meshes
have to keep the coordinates the exporter writes them back from. For the same
reason the book and its card grids are **not** instanced, only recorded — they
are what the addon exists to edit, and drawing them under the layout transform
would write that transform into the geometry on the next export.

Checked against a real capture: three cards a side at the left and right edges,
strongly rotated about Y, spread vertically, P1 at x −4.30 and P2 at +4.30
mirrored to within a hundredth.

### The screen is four archives, and one resource lives in two of them

`mnchscmn` holds the book, the cards and their overlays; `mnchs` holds the team
panel and the two assist panels; `mnchsstg` holds the cursor; `mnchsea` is
textures and schedulers with no geometry at all. Everything is authored in the
same units about the same origin — the book spans ±891 × ±698, the team panel
sits at y −637 (bottom centre), the assist panels at x ±349 — so importing them
all at one scale puts each where it sits on screen. No placement data is needed
for them, and none was found in these three: their SDL resources place no models
at all. Only four layouts in the whole screen do, and all four are in
`mnchscmn` — `chs_card1p`, `chs_card2p`, `chs_meku` and `chs_hnd_a`.

**`p_chs_hnd1` is in both `mnchscmn` and `mnchsstg`, under the same entry name.**
Everything downstream of the importer keyed off that name alone, so with more
than one archive open an edit to one copy would be written into every archive
that carries the resource. Objects and images therefore record which archive
they came from (`umvc3_source_arc`), and each export pass — geometry, textures,
rebinding, baking — takes an `owns` predicate that scopes it to one archive.
**Untagged means the archive the scene was opened from**, so a `.blend` saved
before any of this still exports exactly where it used to.

An archive nothing touched is not written. That is not just tidiness: an install
that rewrites every file it can reach takes a `.bak` over each of them, and a
backup of an already-modified file is worth nothing.

Geometry, textures, materials **and the schedulers' animation** round-trip. What
positions the models the engine places at runtime — the big `chs_card`, the
cursor, the effect models, which all sit at their own local origin — is the
`.sdl`, and it is now read and written: see the two SDL sections above.

### FIXED: a portrait changed IN PLACE installed as nothing at all

Reported as "the exporter added a background and a border". It added nothing:
it wrote **no file for that character**, so the game loaded the stock portrait —
a photo on a dark background inside a torn white border. Checked before touching
anything, and the evidence was one line each way: no `f_SheHulk*.tex` had ever
been written, and `card_portrait_edits` on the real `.blend` did not list her.

A portrait is changed in place as readily as it is replaced: point the image
datablock at your own art, or paint on it. The datablock keeps `umvc3_portrait`,
which says which portrait it **stands for**, not that it still looks like it —
and the "is this still her own portrait?" test read the tag alone and skipped the
card. `unmodified_portrait` now asks whether the image is still that file: not
dirty, and still opened on the `.dds` the portrait decodes into.

**By file name, not by path**, which the first attempt got wrong and which is
worth remembering. Which cache directory a portrait is decoded into depends on
what the scene was opened from — `import_css` caches beside the *archive*
(`ui/_umvc3_cache`), Set Portrait beside the *portrait*
(`chs_cs_f/_umvc3_cache`). Comparing whole paths called **133 untouched cards
edited** against the real scene, and re-encoding those would have installed the
greyscale luminance preview of every format 42 portrait in the game. Verified
against `css.blend` both ways: 3 edits before the in-place change, 4 after, and
only those four written.

### FIXED: a transparent portrait shipped the colour hiding under the hole

BC1 was encoded with the alpha channel simply dropped, so a portrait with a
transparent margin shipped whatever RGB sat under alpha 0 — and that is
*undefined*: paint tools leave anything there, commonly a flat key colour, which
is why cut-out portraits came back green and black. Three separate leaks, all of
them fixed together, and the middle one was doing the most damage:

* **The alpha was thrown away.** BC1 has a punch-through mode — `c0 <= c1`
  selects a three-colour palette whose fourth entry is transparent black — so
  one bit of it can be carried. `encode_bc(..., cutout=True)` does, on the two
  paths that ship a user's own image into a BC1 texture (`portrait_bytes` and
  `encode_image_to_tex`). It stays **off** by default: a caller re-encoding a
  texture it just decoded has no transparency to carry, and reading alpha it did
  not put there would punch holes in a perfectly good sheet.
* **The endpoints were fitted over the hole.** A block spanning art and hole
  took its 565 pair from both, so the *visible* texels were shaded toward the
  colour under the invisible ones — the garbage bled sideways into art that was
  never transparent. Endpoints now come from the kept texels alone.
* **The resize bled it in too.** `image_pixels_topdown` scales through Blender,
  which interpolates the four channels independently, so every edge texel of a
  cut-out mixed in the hidden colour before the encoder ever saw it. It scales
  premultiplied now and divides alpha back out, which is the only way an edge
  comes out the colour of the art rather than of the hole. Measured on the test
  image: 0.40 green in the border, down to the art's own 0.14.

What the game does with the bit is the card shader's business and is not
established here — the shader disassembled for `shader.py` takes its alpha from
the vertex colour, not the texture. Where alpha is ignored a punched texel reads
**black**, which is at least defined; a margin that comes out black rather than
showing the page is that, and the answer is then to paint the margin rather than
leave it transparent.

### FIXED: a card's retargeted UVs never left Blender

`write_card` re-encoded **positions**, and skin weights when asked, and that was
all — so reframing a portrait by dragging its card's UVs left the edit in the
`.blend` and the game showing the old crop. Every other path already wrote them
(`patch_mod_bytes` for the generic exporter, `mesh_to_spec` for authored
geometry, the Add Card spec for clones), and the README has always said the
exporter writes back positions, UVs and vertex colours; the card path was the
one that did not. It now writes the uv pair at `layout_for(fmt, stride)["uv0"]`
alongside the position, and reports how many cards changed — the same silence
that made the portrait bug expensive.

Written for **every** card on every export, not only the ones that look edited:
a half read into a float32 and packed back is bit-identical, so an untouched
export still reports zero and an untouched card in an edited model stays
byte-identical. Both are checked.

### FIXED: an image put on a card's material reached nothing at all

Changing a card's Base Color to an image is the obvious way to say "this card
should look like this", and the install carried none of it — the card came back
from the game still wearing the portrait it shipped with, with nothing said
anywhere. Every export path that could have taken it declined:
`rebind_materials` binds a material to an archive texture and an image loaded
from disk is in no archive, so it `continue`d without a note; the texture
re-encode loop keys on `umvc3_entry`, which such an image does not have;
`bake_flat_materials` skips anything showing an image as "handled elsewhere";
and `write_portraits` only wrote images tagged `umvc3_portrait`, which the new
one is not. Four paths, each right to decline, and no fifth.

It is a **portrait** edit, and only a portrait edit: a card samples the shared
card sheet, and what a player sees on it is the character's own loose `.tex`,
bound per slot at runtime. Rebinding cannot express it and painting the sheet
would take every other card with it. `card_portrait_edits` now finds the cards
whose face has moved off the portrait it was imported with, and
`write_portraits` writes each one **as it is** — scaled to the `.tex` and
encoded, with nothing laid over it.

**Not** through `portraits.build`, which is what it first did: fitting the image
into the 112×76 window and laying the torn-photo frame back over the margin is
**Set Portrait**'s promise, asked for explicitly. Doing it on this path too
would leave no way at all to put an exact image on a card, and an install that
edits the art it was handed is the same class of surprise as one that drops it.
The card also keeps showing the source image rather than being re-pointed at
what was installed — it is the user's, and they may still be working on it, so
the written file is the only record of what the game has and the two are
compared byte for byte to decide whether there is anything to write. Three
things the tests pinned down:

* **Match the portrait by name, not by path.** `PORTRAIT_RE` is lazy and the
  split is genuinely ambiguous where a stem ends in a digit — `f_X2300` is X23
  colour 00 and equally parses as X2 colour 300 — so pattern-matching the stem
  read as five characters wearing somebody else's face, and rebuilt them on
  every install. `is_portrait_of` is given the stem and checks only the colour.
* **Copy a portrait, never re-encode one.** A portrait dropped on another card
  is already the right size and already a format the game reads. The stock ones
  are format 42, of which only the alpha has ever been decoded, so re-encoding
  what Blender was shown installs a greyscale card. Painted portraits are
  written first, so the file is what its pixels say by the time it is copied.
* **The `.dds` preview cache compared lengths.** Every portrait this writes is
  BC1 at the same size as the last, so a replaced one was called unchanged and
  the previous picture handed back — **Set Portrait** showed the old art however
  many times it was rewritten. It compares bytes now, and reloads the datablock
  when it rewrites.

A material this cannot bind is also reported now, on cards and anywhere else:
saying nothing is what made this cost a trip through the game to notice.

### Flattening the grid shears any card that was tilted first

`S Z 0` in Edit Mode is an orthographic **projection**, not a rotation. A card
already lying flat projects unchanged, but one that was rotated in 3D first
projects to a **parallelogram** — sheared and foreshortened. Measured on a real
install, the damage was exactly affine:

```
[1.0001  0.0001]      x' = x
[0.2643  0.7009]      y' = 0.264x + 0.701y      det 0.70
```

residual 0.149 units over the whole card, so it is affine and nothing else. No
rotation squares it, and `Ctrl+L` ▸ Link Object Data does not either: **UVs are
not uniform across cards** (jids 49-53 differ completely from jid 13), so
sharing mesh data corrupts them.

`umvc3.css_square` restores the original vertices from a reference archive,
keeping the object's position and its UVs, and holding the card on whatever
plane it is on now. **Its reference must be a clean build** — the default is the
scene's own source, which is useless once the damage has been installed, because
that archive *is* the damage. The operator measures the card's in-plane yaw
afterwards and warns when it is still skewed rather than reporting success.

Vertex ordering is **not** consistent between cards in one model (jid 13 vs
jid 22 fits as a 180-degree flip with a 45-unit residual), so a card's shape can
only be copied from the same mesh in another archive, never from a sibling.

---

## 12. The galaxy screen — replacing the comic book

Three passes, each its own script, each installable and revertible on its own.
Verified in game.

| script | does |
|---|---|
| `buildplanet.py` | moves an already-regridded archive's cards onto a spherical cap |
| `hidebook.py` | collapses chosen meshes so they stop drawing |
| `galaxy.py` | paints the full-screen backdrop |

### buildplanet — cards on a dome
A **placement pass only**: it takes the 9x16 archive `buildgrid.py` produced, so
the cells, joint ids and clone work are already done, and only moves cards. That
is what makes it cheap to iterate — change a number, rerun, reinstall.

**Rigid-bind every card vertex to bone 0.** The page's curve is not art, it is
the 4x4 lattice of 16 bones (x -639/-507/-267/-27, y +-360/+-120, middle column
at z ~70). A card placed on a dome but left weighted to that lattice gets the
book's arch applied on top and folds. Bone 0 is the root at (0, 0, -0.2),
effectively identity, and cards already reference it — binding wholly to it
lands each card exactly where authored. Confirmed in game: the dome holds still,
so bone 0 is not animated.

Overlay layering is measured per model from the source and re-applied along the
sphere normal (`selr1` runs +21 proud of `face`), or the hover frames z-fight.

**Size it to the book's footprint, not the screen.** The character body art
flanks the grid, so a dome spanning the full width covers it. The mapping is
fixed by `screenroom.py`: the stock grid is 609.2 units over 427 px, so
**1.427 units per pixel**. `UMVC3_WIDTH=900 UMVC3_HEIGHT=560` gives 670 x 436 px
against the book's 665 x 427 — the layout that demonstrably left the art clear.
At 1700 x 1000 it covered the art *and* ran off the top and bottom.

### hidebook — retiring the book
Collapses `chs_meku` meshes 2, 5, 6, 7, 8, 9, 10, 11 (six pages, two covers),
leaving 0, 1, 3, 4. It works by copying vertex 0's **whole record** over every
other vertex, not just its position: these meshes are skinned to a 69-bone rig,
so vertices sharing a position but not their weights get pulled apart again the
moment the book animates. Byte-identical vertices transform identically whatever
the rig does. It also needs no knowledge of the vertex layout, which matters —
`chs_meku` mixes strides 12/24/28/40 across formats 9, 57 and 65.

Nothing is removed and no table changes size, so it is fully reversible.

### galaxy — the backdrop
**The CSS backdrop is `meku_menu_co00_BM_NOMIP`** (1280x720, format 19), *not*
any of the `meku_chs01/02/03` atlases. Material-to-texture binding is a known
gap, so this was settled by flooding each 1280x720 candidate with a different
flat colour and launching once: the whole screen turned yellow. `chs01` is the
blue/red book pages, `chs02` the stage select, `chs03` the VERSUS page stack —
none of them appear on the character select at all once the book is collapsed.

A flat-colour BC1 payload is trivial to hand-build (`c0 = c1`, indices 0), which
makes that probe cost seconds rather than a full encode.

The art keeps the middle deliberately calm — nebula detail and star density rise
toward the edges — so the portraits have something plain to sit against, and the
planet limb is placed low enough to clear the bottom row.

### The grid lines, and the projection they need
`galaxy.py` also draws the vanilla MvC3 grid, as lines on **the same sphere the
cards sit on**, at cell *boundaries* so they fall between characters, continued
outward at the same angular pitch until they leave the frame - which is what
makes it read as infinite (+-17 columns and +-8 rows against the cards' 16 x 9).

**The projection is orthographic, 1.364 game units per pixel.** Measured, not
assumed: autocorrelating the column profile of a screenshot gives a uniform
44 px column pitch, and 15 gaps x 44 px = 660 px for 900 units. Fitting a
perspective model to the apex (z 200) and the rim (z 135) returns the same scale
for both, so there is no measurable foreshortening across the dome.

That matters for the drawing: under an orthographic projection a line of
constant latitude has a constant screen y, so the horizontals come out perfectly
straight and only the verticals curve, pinching toward the poles. That is the
vanilla look, and it falls out of the geometry rather than being faked.

### The glow around the book
`chs_meku`'s meshes 0, 1, 3 and 4 are not a backdrop panel - rendered in
isolation they are a **frame** with a hollow centre, the border decoration that
surrounded the book, and it stayed on screen after the pages went. `hidebook.py`
now collapses all twelve. Note this also proves the character-select backdrop is
drawn by the game as its own full-screen layer, not carried on `chs_meku`
geometry at all.

### Still comic-styled
The flanking UI is separate models and untouched: the "ULTIMATE MARVEL VS
CAPCOM 3" cards (`chs_card*`), the RESERVE UNIT speech balloon, and the halftone
frame. The character panels also still show silhouettes, because the vanilla 50
have no `b_<Name>255` body art in `chs_b1p/chs_body/` — unrelated to any of this.

Backups, in order: `BUILT_mnchscmn_9x16_from_vanilla.arc` (flat book grid),
`_planet.arc` (dome + book), `_planet_nobook.arc` (dome alone),
`_planet_galaxy.arc` (current).

---

### What the addon deliberately does not do

- **It cannot change rows/columns by itself.** `NEW_ROWS` and `COLS` are
  compile-time constants; only `Stage` and `[NewRows]` come from the ini. Set a
  different grid and the addon says so and prints the constants and the divide
  magic to rebuild with, rather than shipping a silent mismatch.
- **It cannot delete a card.** Blank a cell the way the game does, with
  character id 0.
