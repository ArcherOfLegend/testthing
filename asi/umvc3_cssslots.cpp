// umvc3_cssslots.asi - reshape the character-select grid from 7 rows x 8
// columns to 9 rows x 16 columns.
//
// Function names below come from the community Ghidra database (umvc3postDTI8),
// which is the same binary layout as the Steam build.
//
// ---------------------------------------------------------------------------
// How the CSS grid is defined in the game
// ---------------------------------------------------------------------------
// A slot index is split into a column and a row, then looked up in a table:
//
//   uMenuChrSelBgMain_vfn17 @ 0x36DF90 (builds the cards):
//       col = i / 7                          ; magic multiply, 0x24924925
//       row = i - col*7                      ; imul ecx,ecx,7
//       id  = FUN_140361FD0(col+4, row)
//       ... assign portrait per card, loop while i < 0x1C (28 = 4 cols x 7 rows)
//
//   FUN_140361FD0(col,row):
//       return gGridTable[col + row*8]       ; int32, ROW STRIDE ALREADY 8
//
//   uMenuChrSelBgMain_vfn28 @ 0x36CE80 (per-frame): slots while slot < 0x38 (56)
//
//   aChrSelect__remapSlotIndexCircular @ 0x36D670 (slot -> card index):
//       col = slot & 7; row = slot >> 3;
//       if (row > 6) row = 0;                ; <- clamps away any extra row
//       if (col > 3) col = 7 - col;          ; mirror the right-hand side
//       return (3 - col) * 7 + row;          ; <- row stride 7
//
// The table's row stride is already 8 int32s, so extra rows are just more bytes
// - but the bytes after it are live float constants (two xrefs at 0x140360914 /
// 0x140360C76), so the table is copied somewhere new instead and every lea that
// reads it is repointed. There are exactly two such leas; an earlier build
// repointed only one, leaving the two readers disagreeing about where the roster
// lived.
//
// Why 144 slots: CloneEngine claims every slot from 56 upward by index and maps
// slot 56+n to the nth playable entry in Characters.ini. There are 83 of those,
// so the last one needs slot 138, and 139 slots rounds up to 9 rows x 16.
//
// Why 16 columns rather than 8 rows more: the drawn book already fills its
// vertical band - its top edge touches the TIME readout and its bottom sits on
// the control bar - while ~300 px of screen width either side goes unused. So
// height is the scarce axis and width is the free one, and 9x16 gives cards of
// roughly vanilla proportions where 18x8 gave 3.4:1 slivers.
//
// ---------------------------------------------------------------------------
// The Capcom/Marvel split, and why 4 characters cross over
// ---------------------------------------------------------------------------
// A page is chosen by column, and the grid table is linear in slot, so at 16
// columns slots 0-55 divide 32/24 between the pages instead of 28/28. Each page
// needs 26 cells (25 characters + its RANDOM card) plus 2 blanks behind the
// banner plate, so the narrow side is 4 short. The table below therefore moves
// the last 4 Marvel characters onto the Capcom page, which balances exactly:
//       page A  32 cells = RANDOM + 2 blanks + 25 Capcom + 4 Marvel
//       page B  24 cells = RANDOM + 2 blanks + 21 Marvel
//
// ---------------------------------------------------------------------------
// The divisor
// ---------------------------------------------------------------------------
// The /7 is a magic multiply in a fixed instruction shape:
//       eax = MAGIC; edx:eax = eax*n; ecx = ((((n - edx) >> 1) + edx) >> SHIFT)
// which is exactly  q = (n + mulhi_u32(n, MAGIC)) >> (SHIFT + 1).
// So the divisor is two immediates and needs no code rewrite:
//       /7   MAGIC 0x24924925  SHIFT 2      (stock)
//       /8   MAGIC 0x00000000  SHIFT 2
//       /9   MAGIC 0xC71C71C8  SHIFT 3      <- verified exact over all u32
//       /16  MAGIC 0x00000000  SHIFT 3
//       /18  MAGIC 0xC71C71C8  SHIFT 4
//
// ---------------------------------------------------------------------------
// Why five sites need detours
// ---------------------------------------------------------------------------
// Four are slot bounds: they become 144 (143 for "last slot"), and `cmp r32,imm8`
// sign-extends so it tops out at 127. Each is replaced by a `jmp rel32` into a
// code cave that does the widened compare and jumps back to both original
// destinations.
//
// The fifth is the grid table's row stride. FUN_140361FD0 indexes it with
// `lea r9,[rdi + rsi*8]`, and an LEA scale can only be 1, 2, 4 or 8 - there is
// no *16 - so that one is redone in the cave as a shift plus an add.
//
// Ghidra confirms nothing branches into any of the bytes being taken over.
//
// ---------------------------------------------------------------------------
// The cursor is a separate object and has its own copy of the grid size
// ---------------------------------------------------------------------------
// Directional input does not go through any of the slot math above. The screen
// owns a uMenuChrSelCursor per player (aChrSelect + 0x120 + player*8), which
// embeds a generic uUiCursor at +0x78, and that base class does all the
// navigation off two fields it is handed at construction:
//
//     [+0x54] columns   [+0x58] rows   [+0x5c] columns * rows
//     [+0x4c] the current slot
//
//   uUiCursor__trans @ 0x323920:
//       row = pos / cols; col = pos % cols;
//       right/left -> col +- 1;  down/up -> row +- 1;
//       wrap col into [0,cols), row into [0,rows);
//       pos = cols * row + col
//
// The subclass only supplies uCursor_vfn31(col,row) - "is this cell live" -
// which is FUN_140361FD0(col,row) != 0 and the character not already taken, so
// it follows the relocated table for free. Nothing in uUiCursor hard-codes a
// dimension; the only 8 and 7 in the entire cursor are the two constructor
// calls, at 0x372965/0x37296E and 0x3729DB/0x3729DE.
//
// Left at 8 x 7 against a 16 x 9 grid, a vertical step moves the cursor by 8
// slots - half a row - so Down lands eight columns across on the same row,
// usually on the other page, rather than one row down; and the horizontal wrap
// fires at column 7, in the middle of the grid, instead of at column 15. Left
// and Right inside a page therefore behave while Up and Down never do, which is
// what "the direction only sometimes matches" looks like from the pad.
//
// It also explains why the earlier 18 rows x 8 columns build looked fine: 8
// columns was still the true width, so `pos = cols * row + col` stayed correct
// and every press moved the cursor exactly one cell in the pressed direction.
// Only the row count was wrong, and a wrong row count wraps early rather than
// mis-steering - the cursor simply never reached rows 7-17.
//
// ---------------------------------------------------------------------------
// Constants that look like row counts but are NOT - do not patch them
// ---------------------------------------------------------------------------
//   0x36E450  cmp esi,7 / ja  - the bounds check on an EIGHT-ENTRY JUMP TABLE
//                               at 0x36E5C8, guarding a switch over the 12
//                               overlay models. Raising it to 8 lets the loop
//                               index one past the table and `jmp` to garbage.
//                               This crashed the game on every CSS entry.
//   0x36D203  cmp eax,7 / jg  - a uMenuChrSel slot-STATE threshold ("state < 8"),
//                               unrelated to grid geometry.
//   0x36D682  cmp edx,8       - the COLUMN clamp. Columns stay at 8.
//
// Likewise 0x3610BD / 0x36A93A load 0x38 and 0x3B as a pair; 56 and 59 are not
// valid indices into a 56-slot grid, so they are something else and are left be.
//
// Timing: Steam's DRM decrypts .text at the entry point, which runs after
// imported DLLs load, so nothing is patched blind - the plugin polls until the
// expected bytes are present and verifies every site before writing.

#include <windows.h>
#include <cstdio>
#include <cstdint>

namespace {

// ---------------------------------------------------------------- config ---
// Character ids written into the added rows. CloneEngine overrides every slot
// from 56 up by index, so these are only ever seen if CE is absent.
int g_newRow[8] = { 16, 19, 18, 12, 36, 29, 31, 32 };

const DWORD RVA_GRID_TABLE   = 0xB3E580;   // 7 rows x 8 int32
const int   VANILLA_ROWS     = 7;
const int   VANILLA_COLS     = 8;
const int   NEW_ROWS         = 9;
const int   COLS             = 16;
const int   SLOTS            = NEW_ROWS * COLS;         // 144
const int   VANILLA_SLOTS    = VANILLA_ROWS * VANILLA_COLS;  // 56, all CE leaves us
const int   LAST_SLOT        = SLOTS - 1;               // 143
const int   CARDS_PER_SIDE   = NEW_ROWS * (COLS / 2);   // 72
const int   BANNER_BLANKS    = 2;          // cells the banner plate covers
const int   ID_RANDOM_A      = 53;
const int   ID_RANDOM_B      = 54;

// An explicit slot -> character id table from [Layout] in the ini, which the
// Blender addon writes out of the scene. -1 means "not specified, work it out".
// This is what makes placement dynamic: without it the vanilla 50 are dealt into
// the grid by BuildLayout's fixed rule and cannot be moved at all.
//
// It only decides slots 0-55. CloneEngine claims every slot from 56 up BY INDEX
// and ignores the table there, so moving a CE character means reordering the
// playable sections of Characters.ini instead - the addon does that too.
int  g_layout[SLOTS];
bool g_hasLayout = false;

// Every instruction that loads the address of the grid table. Both are 7-byte
// `lea r64,[rip+disp32]`, so the displacement always sits at +3.
struct TableRef { DWORD rva; BYTE opcode[3]; const char* where; };
const TableRef g_tableRefs[] = {
    { 0x361FE5, {0x48,0x8D,0x05}, "FUN_140361FD0 (slot -> character id)" },
    { 0x361F52, {0x4C,0x8D,0x0D}, "aChrSelect__findCharSlotIndex (character id -> slot)" },
};

struct BytePatch {
    DWORD  rva;
    BYTE   expect[6];
    BYTE   value[6];
    int    len;
    int    stage;          // lowest stage that applies this patch
    const char* name;
};

BytePatch g_patches[] = {
    // -- stage 2: walk the grid as 9 rows of 16 instead of 7 of 8 -----------
    { 0x36E091, {0x25,0x49,0x92,0x24}, {0xC8,0x71,0x1C,0xC7}, 4, 2, "vfn17: /7 magic -> /9 magic" },
    { 0x36E0A1, {0x02},                {0x03},                1, 2, "vfn17: divide shift 2 -> 3" },
    // imul ecx,ecx,7 -> 9  (row = i % 9)
    { 0x36E0B0, {0x6B,0xC9,0x07},      {0x6B,0xC9,0x09},      3, 2, "vfn17: i%7 -> i%9" },
    // the second page starts at column 4 -> column 8
    { 0x36E0B7, {0x8D,0x48,0x04},      {0x8D,0x48,0x08},      3, 2, "vfn17: page B column base 4 -> 8" },
    // per-side card counts 28 -> 72  (8 columns x 9 rows)
    { 0x36E1F9, {0x83,0xFE,0x1C},      {0x83,0xFE,0x48},      3, 2, "vfn17: face loop 28 -> 72" },
    { 0x36E2B2, {0x83,0xFB,0x1C},      {0x83,0xFB,0x48},      3, 2, "vfn17: overlay init 28 -> 72" },
    { 0x36E4B9, {0x83,0xFF,0x1C},      {0x83,0xFF,0x48},      3, 2, "vfn17: overlay texture 28 -> 72" },
    // charIndexToRowCol splits a slot into column and row
    { 0x361FAA, {0x83,0xE2,0x07},      {0x83,0xE2,0x0F},      3, 2, "charIndexToRowCol: sign fixup mask 7 -> 15" },
    { 0x361FB1, {0x83,0xE0,0x07},      {0x83,0xE0,0x0F},      3, 2, "charIndexToRowCol: col = slot & 15" },
    { 0x361FB4, {0xC1,0xF9,0x03},      {0xC1,0xF9,0x04},      3, 2, "charIndexToRowCol: row = slot >> 4" },

    // -- stage 3: map the new slots onto their own cards --------------------
    // remapSlotIndexCircular: col = slot & 7, row = slot >> 3, fold anything
    // past the last row onto row 0, mirror the far half of the columns, then
    // index the card by (3 - col) * ROWS + row.
    { 0x36D673, {0x83,0xE2,0x07},      {0x83,0xE2,0x0F},      3, 3, "remap: col = slot & 15" },
    { 0x36D676, {0x41,0xC1,0xE8,0x03}, {0x41,0xC1,0xE8,0x04}, 4, 3, "remap: row = slot >> 4" },
    { 0x36D682, {0x83,0xFA,0x08},      {0x83,0xFA,0x10},      3, 3, "remap: col bound 8 -> 16" },
    { 0x36D688, {0x41,0x83,0xF8,0x07}, {0x41,0x83,0xF8,0x09}, 4, 3, "remap: row clamp 7 -> 9" },
    { 0x36D690, {0x83,0xFA,0x04},      {0x83,0xFA,0x08},      3, 3, "remap: mirror threshold 4 -> 8" },
    { 0x36D695, {0xB8,0x07,0,0,0},     {0xB8,0x0F,0,0,0},     5, 3, "remap: mirror 7-col -> 15-col" },
    { 0x36D69E, {0xB8,0x03,0,0,0},     {0xB8,0x07,0,0,0},     5, 3, "remap: card column 3-col -> 7-col" },
    { 0x36D6A5, {0x6B,0xC0,0x07},      {0x6B,0xC0,0x09},      3, 3, "remap: row stride *7 -> *9" },
    // Which page a slot sits on, as `(slot & 7) > 3`. It picks the hover frame
    // (aChsMekuSel1A..) and is indexed page + (player + 4) * 2. At 16 columns it
    // reads the wrong half: slot columns 4-7 are still the Capcom page but would
    // take the Marvel frame, and 8-11 the reverse.
    { 0x36D6E2, {0x80,0xE2,0x07},      {0x80,0xE2,0x0F},      3, 3, "page test: slot & 7 -> slot & 15" },
    { 0x36D6E5, {0x80,0xFA,0x04},      {0x80,0xFA,0x08},      3, 3, "page test: page B starts at column 4 -> 8" },

    // -- stage 4: let the cursor actually reach the new slots ----------------
    // advanceCursorToNextSelectableChar walks slots with
    //     MtMath__wrapRange(slot, step, 0, last)
    // where `step` is not a literal - it is computed as `lea edx,[r9-0x3F]`
    // from the same register that carries `last`, giving 0x37-0x3F = -8, i.e.
    // one row of eight. Widening `last` alone silently zeroes the step and the
    // cursor stops moving, and a row is now sixteen, so load it outright:
    //     push -16 ; pop rdx ; nop   == edx = -16, in the same four bytes.
    { 0x368240, {0x41,0xB9,0x37,0,0,0},    {0x41,0xB9,0x8F,0,0,0},    6, 4, "cursor walk: last slot 55 -> 143" },
    { 0x36824B, {0x41,0x8D,0x51,0xC1},     {0x6A,0xF0,0x5A,0x90},     4, 4, "cursor walk: row step -16" },
    // clamp(slot, 0, 0x37) feeding the player card plate
    { 0x36F856, {0x41,0xB9,0x37,0,0,0},    {0x41,0xB9,0x8F,0,0,0},    6, 4, "CardPlayer: clamp slot 55 -> 143" },

    // -- stage 4: the cursor object's own idea of the grid -------------------
    // This is what actually moves the cursor, and it is a separate object from
    // everything above. uMenuChrSelCursor owns a generic uUiCursor at +0x78 and
    // that base class does all the navigation, entirely off two fields:
    //     [+0x54] columns   [+0x58] rows   [+0x5c] columns * rows
    // uUiCursor__trans @ 0x323920 is
    //     row = pos / cols; col = pos % cols;
    //     right/left: col +- 1     down/up: row +- 1
    //     wrap col into [0,cols) and row into [0,rows)
    //     pos = cols * row + col
    // with `pos` the slot index, the same one the rest of the screen reads.
    // Nothing in uUiCursor hard-codes a dimension - the only 8 and 7 in the
    // whole cursor are the two constructor calls below - so getting these two
    // numbers right fixes every direction at once.
    //
    // Left at 8 x 7 against a 16 x 9 grid: a vertical step moves the cursor by
    // 8 slots, which is half a row, so Down lands eight columns across on the
    // same row (usually on the other page) instead of one row down; and the
    // horizontal wrap fires at column 7, in the middle of the grid, instead of
    // at column 15. Horizontal presses inside a page therefore look right while
    // vertical ones never do - "only sometimes corresponds".
    { 0x372965, {0xBA,0x08,0,0,0},          {0xBA,0x10,0,0,0},         5, 4, "cursor grid: columns 8 -> 16" },
    // rows were encoded as `lea r8d,[rdx-1]`, i.e. columns - 1, which is only
    // true at 8 x 7. Same instruction, displacement -7, so 16 - 7 = 9.
    { 0x37296E, {0x44,0x8D,0x42,0xFF},      {0x44,0x8D,0x42,0xF9},     4, 4, "cursor grid: rows = cols-1 -> cols-7 (9)" },
    // the default constructor builds the same 8 x 7 out of a zeroed register
    { 0x3729DB, {0x8D,0x50,0x08},           {0x8D,0x50,0x10},          3, 4, "cursor grid (default ctor): columns 8 -> 16" },
    { 0x3729DE, {0x44,0x8D,0x40,0x07},      {0x44,0x8D,0x40,0x09},     4, 4, "cursor grid (default ctor): rows 7 -> 9" },

    // Where each player's cursor starts. 26 and 29 are the two page centres of
    // a 7 x 8 grid; read 16 wide they are columns 10 and 13, so both players
    // would open on the Marvel page. 22 and 25 are the mirrored pair holding
    // vanilla's position - card column 1 on each page - in the new layout:
    // 22 & 15 = 6 (Capcom), 25 & 15 = 9 (Marvel), and 15 - 6 = 9 so the two
    // sides stay symmetric. Row 1, because row 0 carries the banner plate's
    // blank cells and the Marvel page only has rows 0-2 of vanilla characters.
    { 0x372986, {0xBA,0x1A,0,0,0},          {0xBA,0x16,0,0,0},         5, 4, "cursor home 1P: 26 -> 22" },
    { 0x37298F, {0xBA,0x1D,0,0,0},          {0xBA,0x19,0,0,0},         5, 4, "cursor home 2P: 29 -> 25" },
    // the same two seeds again, in BgMain's setup and in the post-pick walker
    { 0x36EB85, {0x1A,0,0,0},               {0x16,0,0,0},              4, 4, "BgMain setup home 1P: 26 -> 22" },
    { 0x36EB8F, {0x1D,0,0,0},               {0x19,0,0,0},              4, 4, "BgMain setup home 2P: 29 -> 25" },
    { 0x3680C6, {0x44,0x8D,0x7E,0x1D},      {0x44,0x8D,0x7E,0x19},     4, 4, "cursor walk home 2P: 29 -> 25" },
    { 0x3680CE, {0x8D,0x5E,0x1A},           {0x8D,0x5E,0x16},          3, 4, "cursor walk home 1P: 26 -> 22" },
    { 0x3681D7, {0x41,0xBF,0x1D,0,0,0},     {0x41,0xBF,0x19,0,0,0},    6, 4, "cursor walk home 2P (retry): 29 -> 25" },
    { 0x36822F, {0x8D,0x5D,0x1A},           {0x8D,0x5D,0x16},          3, 4, "cursor walk home 1P (retry): 26 -> 22" },

    // uMenuChrSelCursor__move also takes a slot straight from the input mapper
    // - picking a card directly rather than walking to it - and splits that one
    // with the 8-column constants too.
    { 0x3731CB, {0x41,0xC1,0xE8,0x03},      {0x41,0xC1,0xE8,0x04},     4, 4, "cursor direct pick: row = slot >> 4" },
    { 0x3731CF, {0x83,0xE2,0x07},           {0x83,0xE2,0x0F},          3, 4, "cursor direct pick: col = slot & 15" },
};

// ------------------------------------------------------------- detours ------
// Each takes over a `cmp r32,imm8` plus the conditional branch that follows,
// and re-does both in a cave with a 32-bit immediate.
struct Detour {
    DWORD  rva;            // first byte taken over
    BYTE   expect[12];
    int    len;            // bytes taken over, always >= 5
    int    stage;
    BYTE   body[16];       // replacement instructions run in the cave
    int    bodyLen;
    BYTE   cc;             // second byte of the 0F 8x long conditional form,
                           // or 0 for a straight-line replacement
    DWORD  taken;          // rva the conditional branch goes to (cc != 0)
    DWORD  fall;           // rva to continue at
    const char* name;
    BYTE*  stub;           // filled in at runtime
};

Detour g_detours[] = {
    // uMenuChrSelBgMain_vfn28: while (slot < 56) -> while (slot < 144), signed
    { 0x36D2DD, {0x83,0xFE,0x38, 0x0F,0x8C,0x2A,0xFE,0xFF,0xFF}, 9, 2,
      {0x81,0xFE,0x90,0x00,0x00,0x00}, 6, 0x8C, 0x36D110, 0x36D2E6,
      "vfn28: 56 -> 144 slots", nullptr },

    // aChrSelect__findCharSlotIndex: while (i < 56) -> while (i < 144), unsigned
    { 0x361F79, {0x83,0xF8,0x38, 0x72,0xE2}, 5, 3,
      {0x3D,0x90,0x00,0x00,0x00}, 5, 0x82, 0x361F60, 0x361F7E,
      "findCharSlotIndex: 56 -> 144", nullptr },

    // advanceCursorToNextSelectableChar: the "cursor is on the last slot" test
    { 0x368226, {0x83,0xFB,0x37, 0x75,0x15}, 5, 4,
      {0x81,0xFB,0x8F,0x00,0x00,0x00}, 6, 0x85, 0x368240, 0x36822B,
      "cursor walk: end of grid 55 -> 143", nullptr },

    // setSlotCharSlotIndex: if (value < 56) store -> if (value < 144) store
    { 0x36E825, {0x41,0x83,0xF8,0x38, 0x73,0x0A}, 6, 4,
      {0x41,0x81,0xF8,0x90,0x00,0x00,0x00}, 7, 0x83, 0x36E835, 0x36E82B,
      "setSlotCharSlotIndex: 56 -> 144", nullptr },

    // uMenuChrSelCursor__move: reject a directly-picked slot that is past the
    // end of the grid, `if (slot >= 56) ignore` -> 144, unsigned. The compare
    // and its branch are exactly 5 bytes together.
    { 0x3731BA, {0x83,0xF8,0x38, 0x73,0x2B}, 5, 4,
      {0x3D,0x90,0x00,0x00,0x00}, 5, 0x83, 0x3731EA, 0x3731BF,
      "cursor direct pick: 56 -> 144", nullptr },

    // FUN_140361FD0 reads gGridTable[col + row*8] as `lea r9,[rdi + rsi*8]`.
    // An LEA scale is only 1, 2, 4 or 8, so a 16-column stride cannot be
    // written in place; shift the row instead and add. Takes over the LEA and
    // the load that follows it.
    //     shl rsi,4 ; lea r9,[rdi+rsi] ; mov ebx,[rax+r9*4]
    { 0x361FEC, {0x4C,0x8D,0x0C,0xF7, 0x42,0x8B,0x1C,0x88}, 8, 1,
      {0x48,0xC1,0xE6,0x04, 0x4C,0x8D,0x0C,0x37, 0x42,0x8B,0x1C,0x88}, 12,
      0x00, 0x000000, 0x361FF4,
      "grid table row stride 8 -> 16", nullptr },
};

const int kMaxTries = 600;
const int kPollMs   = 50;
// The handover to CloneEngine happens during startup, but the table is not read
// until character select is built, so watch generously and cheaply.
const int kWatchTries = 2400;
const int kWatchMs    = 250;
char g_log[MAX_PATH] = {0};

void Log(const char* fmt, ...) {
    FILE* f = nullptr;
    if (fopen_s(&f, g_log, "a") != 0 || !f) return;
    SYSTEMTIME st; GetLocalTime(&st);
    fprintf(f, "[%02d:%02d:%02d] ", st.wHour, st.wMinute, st.wSecond);
    va_list ap; va_start(ap, fmt);
    vfprintf(f, fmt, ap); va_end(ap);
    fprintf(f, "\n"); fclose(f);
}

bool Readable(void* p, SIZE_T n) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery(p, &mbi, sizeof(mbi))) return false;
    if (mbi.State != MEM_COMMIT) return false;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    return (SIZE_T)((BYTE*)mbi.BaseAddress + mbi.RegionSize - (BYTE*)p) >= n;
}

bool Write(void* dst, const void* src, SIZE_T n) {
    DWORD old = 0;
    if (!VirtualProtect(dst, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(dst, src, n);
    VirtualProtect(dst, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), dst, n);
    return true;
}

// A RIP-relative disp32 only reaches +-2GB, so both the replacement table and
// the code cave must live near the module. But they must NOT land flush against
// the image: the first attempt grabbed 0x13FFF0000, exactly one allocation block
// below the base, and the game crashed during startup before any CSS code ran -
// consistent with colliding with something the DRM or allocator wanted there.
//
// So: start well clear of the image and search upward first, staying inside the
// +-2GB the displacement can reach.
const SIZE_T kMinDistance = 0x08000000;   // 128 MB clear of the module
const SIZE_T kMaxDistance = 0x60000000;   // comfortably inside 2 GB

void* AllocNear(BYTE* anchor, SIZE_T size, DWORD protect) {
    SYSTEM_INFO si; GetSystemInfo(&si);
    const SIZE_T gran = si.dwAllocationGranularity;
    for (SIZE_T delta = kMinDistance; delta < kMaxDistance; delta += gran) {
        for (int dir = 0; dir < 2; ++dir) {
            BYTE* probe = dir ? anchor + delta : anchor - delta;
            if (probe < (BYTE*)si.lpMinimumApplicationAddress) continue;
            if (probe > (BYTE*)si.lpMaximumApplicationAddress) continue;
            void* p = VirtualAlloc(probe, size, MEM_COMMIT | MEM_RESERVE, protect);
            if (p) return p;
        }
    }
    return nullptr;
}

bool Rel32(BYTE* from_end, BYTE* to, int32_t* out) {
    int64_t d = (int64_t)(to - from_end);
    if (d > INT32_MAX || d < INT32_MIN) return false;
    *out = (int32_t)d;
    return true;
}

BYTE* g_cave = nullptr;
SIZE_T g_caveUsed = 0;
const SIZE_T kCaveSize = 0x1000;

// The table this plugin relocated to, so the watcher can tell "still ours" from
// "someone else took the readers over".
int32_t* g_ourTable = nullptr;

// Build the stub, then redirect the site to it. The stub is written first, so a
// half-finished detour can never be reachable.
bool ApplyDetour(BYTE* base, Detour& d) {
    BYTE* at = base + d.rva;
    if (!Readable(at, d.len)) return false;
    if (memcmp(at, d.expect, d.len) != 0) return false;
    if (!g_cave) {
        g_cave = (BYTE*)AllocNear(base, kCaveSize, PAGE_EXECUTE_READWRITE);
        if (!g_cave) { Log("  cave allocation failed"); return false; }
        Log("  code cave at %p", g_cave);
    }

    const SIZE_T need = (SIZE_T)d.bodyLen + (d.cc ? 6 : 0) + 5;
    if (g_caveUsed + need > kCaveSize) { Log("  code cave full"); return false; }
    BYTE* stub = g_cave + g_caveUsed;

    BYTE buf[40];
    int n = 0;
    memcpy(buf + n, d.body, d.bodyLen); n += d.bodyLen;
    int32_t r = 0;
    if (d.cc) {
        buf[n++] = 0x0F; buf[n++] = d.cc;
        if (!Rel32(stub + n + 4, base + d.taken, &r)) { Log("  taken branch out of reach"); return false; }
        memcpy(buf + n, &r, 4); n += 4;
    }
    buf[n++] = 0xE9;
    if (!Rel32(stub + n + 4, base + d.fall, &r)) { Log("  fallthrough out of reach"); return false; }
    memcpy(buf + n, &r, 4); n += 4;

    int32_t toStub = 0;
    if (!Rel32(at + 5, stub, &toStub)) { Log("  cave out of reach of rva 0x%06X", d.rva); return false; }

    if (!Write(stub, buf, n)) { Log("  failed writing stub for rva 0x%06X", d.rva); return false; }

    BYTE site[16];
    site[0] = 0xE9;
    memcpy(site + 1, &toStub, 4);
    for (int i = 5; i < d.len; ++i) site[i] = 0x90;
    if (!Write(at, site, d.len)) { Log("  failed writing jmp at rva 0x%06X", d.rva); return false; }

    d.stub = stub;
    g_caveUsed += need;
    Log("  detoured rva 0x%06X -> %p  %s", d.rva, stub, d.name);
    return true;
}

// ------------------------------------------------------- the grid layout ---
// Re-lay the vanilla 56 across 16 columns, reading `src` as the vanilla
// 7 rows x 8 columns table and writing slots 0-55 of a 9 x 16 one. Those are
// exactly the cells this touches - page A rows 0-3 columns 0-7 and page B
// rows 0-2 columns 8-15 - so anything CloneEngine owns from slot 56 up is left
// alone.
//
// A page is chosen by column and the source is linear in slot, so at this width
// slots 0-55 divide 32/24 between the pages instead of 28/28; the last four
// Marvel characters move to the Capcom page to balance it.
// `limit` bounds how far into dst this may write. Our own relocated table takes
// all SLOTS; a table CloneEngine owns takes only the vanilla 56, because
// everything above that is CE's and must not be touched.
bool BuildLayout(const int32_t* src, int32_t* dst, int limit) {
    int a[64], b[64], na = 0, nb = 0;
    for (int r = 0; r < VANILLA_ROWS; ++r) {
        for (int c = 0; c < VANILLA_COLS; ++c) {
            int32_t v = src[r * VANILLA_COLS + c];
            if (v == 0) continue;                       // blank behind the banner
            if (c < VANILLA_COLS / 2) {
                if (v == ID_RANDOM_A) continue;
                a[na++] = v;
            } else {
                if (v == ID_RANDOM_B) continue;
                b[nb++] = v;
            }
        }
    }

    const int half = COLS / 2;                          // 8 columns per page
    const int rowsA = 4, rowsB = 3;                     // rows of each page below slot 56
    const int capA = rowsA * half, capB = rowsB * half; // 32 and 24
    const int needA = capA - 1 - BANNER_BLANKS;         // characters page A holds
    const int spill = nb - (capB - 1 - BANNER_BLANKS);  // Marvel that will not fit
    // A [Layout] that names every slot stands on its own, so an unrecognisable
    // source is only fatal when there is nothing to fall back to.
    bool computed = !(spill < 0 || na + spill != needA);
    if (!computed) {
        Log("  grid layout: unexpected vanilla roster (%d + %d, spill %d)", na, nb, spill);
        if (!g_hasLayout) return false;
    }
    if (computed) {

    // Page A is columns 0..7 and page B is 8..15; within a page the card column
    // runs the other way (joint col = 7 - slot col on A, slot col - 8 on B), and
    // the banner plate sits over joint columns 0..2 - the RANDOM card and the
    // two blanks. So on A the row-0 tail is blanks+RANDOM, on B the head is.
    // Getting this wrong is not cosmetic: joint columns 1 and 2 of row 0 have no
    // card mesh at all, so any character landing there renders nothing while
    // staying hoverable and selectable.
    int ia = 0, ib = 0;
    for (int r = 0; r < rowsA; ++r) {
        for (int c = 0; c < half; ++c) {
            int32_t v;
            if (r == 0 && c == half - 1)            v = ID_RANDOM_A;
            else if (r == 0 && c >= half - 1 - BANNER_BLANKS) v = 0;
            else if (ia < na)                       v = a[ia++];
            else                                    v = b[nb - spill + (ia++ - na)];
            dst[r * COLS + c] = v;
        }
    }
    for (int r = 0; r < rowsB; ++r) {
        for (int c = 0; c < half; ++c) {
            int32_t v;
            if (r == 0 && c == 0)                   v = ID_RANDOM_B;
            else if (r == 0 && c <= BANNER_BLANKS)  v = 0;
            else                                    v = b[ib++];
            dst[r * COLS + half + c] = v;
        }
    }
    Log("  grid layout: %d Capcom + %d Marvel, %d Marvel moved to the Capcom page",
        na, nb, spill);
    }   // computed

    // Explicit slots go on TOP of the computed layout, never instead of it: a
    // [Layout] naming only some slots would otherwise leave the rest holding
    // whatever was in the buffer - placeholder ids in our own table, or
    // CloneEngine's un-re-laid vanilla order in its one.
    if (g_hasLayout) {
        int n = 0;
        for (int i = 0; i < limit && i < SLOTS; ++i) {
            if (g_layout[i] >= 0) { dst[i] = g_layout[i]; ++n; }
        }
        Log("  [Layout] set %d slot(s) explicitly over the computed layout", n);
    }
    return true;
}

// A table still in vanilla order has RANDOM_A at flat index 3 and RANDOM_B at
// 4; once BuildLayout has run they sit at 7 and 8. That makes the rewrite
// idempotent, so the watcher below can be run as often as it likes.
bool NeedsLayout(const int32_t* t) {
    // With an explicit table the signature test does not apply - a layout is
    // free to put RANDOM anywhere, including back where vanilla had it. Compare
    // against what we actually want instead, which is exact and still idempotent.
    if (g_hasLayout) {
        for (int i = 0; i < VANILLA_SLOTS; ++i)
            if (g_layout[i] >= 0 && t[i] != g_layout[i]) return true;
        // A PARTIAL layout leaves the rest to the computed pass, so the vanilla
        // signature still has to be honoured - otherwise a table that happens to
        // already match the named slots is never re-laid at all.
    }
    return t[3] == ID_RANDOM_A && t[4] == ID_RANDOM_B;
}

// Where a reader currently points, or null if it is not the lea we know.
int32_t* ReaderTarget(BYTE* base, const TableRef& ref) {
    BYTE* p = base + ref.rva;
    if (!Readable(p, 7)) return nullptr;
    if (memcmp(p, ref.opcode, 3) != 0) return nullptr;
    return (int32_t*)(p + 7 + *(int32_t*)(p + 3));
}

// Every reader must be repointed together, or the two directions of the
// slot <-> character-id mapping disagree.
bool RelocateTable(BYTE* base) {
    const int nrefs = _countof(g_tableRefs);
    BYTE* lea[_countof(g_tableRefs)] = { nullptr };

    for (int i = 0; i < nrefs; ++i) {
        BYTE* p = base + g_tableRefs[i].rva;
        if (!Readable(p, 7)) return false;
        if (memcmp(p, g_tableRefs[i].opcode, 3) != 0) {
            Log("  lea at rva 0x%06X not where expected (%02X %02X %02X)",
                g_tableRefs[i].rva, p[0], p[1], p[2]);
            return false;
        }
        if (p + 7 + *(int32_t*)(p + 3) != base + RVA_GRID_TABLE) {
            Log("  lea at rva 0x%06X does not point at the grid table - already relocated?",
                g_tableRefs[i].rva);
            return false;
        }
        lea[i] = p;
    }

    BYTE* cur = base + RVA_GRID_TABLE;
    const SIZE_T bytes = (SIZE_T)NEW_ROWS * COLS * sizeof(int32_t);
    int32_t* fresh = (int32_t*)AllocNear(lea[0], 0x1000, PAGE_READWRITE);
    if (!fresh) { Log("  AllocNear failed"); return false; }

    // Vanilla must keep slots 0-55, because CloneEngine claims every slot from
    // 56 up by index and would overwrite them. Everything past 55 is a
    // placeholder: those ids are never read, CE substitutes its own roster
    // there (verified by writing 1..8 into a new row and watching the screen
    // keep showing Rashid, Ken, Guile, Charlie...).
    for (int i = 0; i < SLOTS; ++i) fresh[i] = g_newRow[i % 8];

    if (!BuildLayout((const int32_t*)cur, fresh, SLOTS)) return false;

    // Check reach for every site before writing any of them, so a failure
    // cannot leave half the readers repointed.
    int32_t d32[_countof(g_tableRefs)];
    for (int i = 0; i < nrefs; ++i) {
        if (!Rel32(lea[i] + 7, (BYTE*)fresh, &d32[i])) {
            Log("  relocated table out of rip range from rva 0x%06X", g_tableRefs[i].rva);
            return false;
        }
    }
    for (int i = 0; i < nrefs; ++i) {
        if (!Write(lea[i] + 3, &d32[i], 4)) {
            Log("  failed to write table disp at rva 0x%06X", g_tableRefs[i].rva);
            return false;
        }
        Log("  repointed rva 0x%06X -> %p  [%s]",
            g_tableRefs[i].rva, fresh, g_tableRefs[i].where);
    }

    Log("  grid table relocated %p -> %p (%d rows x %d cols, %zu bytes)",
        cur, fresh, NEW_ROWS, COLS, bytes);
    Log("  slots 56-%d are placeholders (CloneEngine substitutes its roster there)",
        LAST_SLOT);
    g_ourTable = fresh;
    return true;
}

// ---------------------------------------------------------------------------
// CloneEngine relocates the grid table too, and it wins
// ---------------------------------------------------------------------------
// CE repoints the same two leas at its own table - 0x1B0000000 in the builds
// seen here - and it does so after this plugin has run, so the table relocated
// above is simply never read. CE's table is the vanilla roster in flat linear
// order followed by its own ids from slot 56, and it is never re-laid out for a
// wider grid. Read 16 wide that puts the two cells the banner plate covers on
// the wrong columns:
//
//   CE slots 0-7   20  0  0 53 54  0  0 37   page A row 0
//   CE slots 8-15  25 24 21 23 45 47 50 49   page B row 0
//
// so Firebrand (24) and Strider (21) land on page B joint columns 1 and 2 -
// the two cells `face_b` has no card mesh for at all. They stay hoverable and
// selectable, because that goes through the table, but nothing is ever drawn
// for them. Nemesis (25) sits at joint column 0 right beside them, which is
// exactly how the symptom reads on screen.
//
// So: follow whichever table the readers actually point at and lay that one out
// in place. Only slots 0-55 are touched, which is precisely the vanilla roster,
// so CE keeps everything it owns. `NeedsLayout` makes it idempotent, and the
// watcher stops as soon as it has laid out a table that is not ours.
bool RelayoutLiveTable(BYTE* base) {
    int32_t* t = ReaderTarget(base, g_tableRefs[0]);
    if (!t) return false;
    int32_t* t2 = ReaderTarget(base, g_tableRefs[1]);
    if (t2 != t) {
        Log("  readers disagree (%p vs %p) - leaving the table alone", t, t2);
        return false;
    }
    if (t == g_ourTable) return false;              // still ours; nothing took it over
    if (!Readable(t, SLOTS * sizeof(int32_t))) return false;
    if (!NeedsLayout(t)) return false;              // already laid out, or not a roster

    int32_t src[VANILLA_ROWS * VANILLA_COLS];
    memcpy(src, t, sizeof(src));                    // BuildLayout reads and writes the same 56

    DWORD old = 0;
    if (!VirtualProtect(t, SLOTS * sizeof(int32_t), PAGE_READWRITE, &old)) return false;
    bool ok = BuildLayout(src, t, VANILLA_SLOTS);
    VirtualProtect(t, SLOTS * sizeof(int32_t), old, &old);
    if (!ok) return false;

    Log("  another plugin (CloneEngine) had repointed the readers to %p;"
        " re-laid its table for %d columns in place", t, COLS);
    Log("  slots 0-55 rewritten, 56-%d left to CloneEngine", LAST_SLOT);
    return true;
}

bool ApplyPatch(BYTE* base, const BytePatch& p) {
    BYTE* at = base + p.rva;
    if (!Readable(at, p.len)) return false;
    if (memcmp(at, p.expect, p.len) != 0) return false;
    if (!Write(at, p.value, p.len)) { Log("  write failed at rva 0x%06X", p.rva); return false; }
    Log("  patched rva 0x%06X  %s", p.rva, p.name);
    return true;
}

// Stage selector, read from umvc3_cssslots.ini next to the plugin. Each stage
// includes the ones below it, so a failure names the layer that introduced it:
//   [Config] Stage=0  loaded but inert - confirms the plugin is innocent
//            Stage=1  relocate the grid table (both readers), no code patches
//            Stage=2  + walk the grid as 9 rows of 16: cards and portraits appear
//            Stage=3  + give the new cells their own cards instead of row 0's
//            Stage=4  + tell the cursor the grid is 9 x 16 and let it move
//                       onto the new cells
//
// The added rows' character ids can be overridden without a rebuild:
//   [NewRows] Slot0=16 ... Slot7=32
int g_stage = 4;

void LoadConfig(HMODULE h) {
    char ini[MAX_PATH];
    GetModuleFileNameA(h, ini, MAX_PATH);
    char* dot = strrchr(ini, '.');
    if (dot) strcpy_s(dot, sizeof(ini) - (dot - ini), ".ini");
    g_stage = (int)GetPrivateProfileIntA("Config", "Stage", 4, ini);
    for (int c = 0; c < (int)_countof(g_newRow); ++c) {
        char key[16];
        sprintf_s(key, "Slot%d", c);
        g_newRow[c] = (int)GetPrivateProfileIntA("NewRows", key, g_newRow[c], ini);
    }
    int placed = 0;
    for (int i = 0; i < SLOTS; ++i) {
        char key[16];
        sprintf_s(key, "Slot%d", i);
        g_layout[i] = (int)GetPrivateProfileIntA("Layout", key, -1, ini);
        if (g_layout[i] >= 0) ++placed;
    }
    g_hasLayout = placed > 0;
    if (g_hasLayout)
        Log("config: [Layout] gives %d slot(s) explicitly", placed);
}

DWORD WINAPI Worker(LPVOID) {
    BYTE* base = (BYTE*)GetModuleHandleW(nullptr);
    if (!base) { Log("GetModuleHandleW(NULL) failed"); return 0; }
    Log("module base %p; stage %d; target %d rows x %d columns (%d slots)",
        base, g_stage, NEW_ROWS, COLS, SLOTS);
    if (g_stage == 0) { Log("stage 0 - doing nothing"); return 0; }

    const int n = _countof(g_patches);
    const int nd = _countof(g_detours);
    bool done[_countof(g_patches)] = { false };
    bool ddone[_countof(g_detours)] = { false };
    bool tableDone = false;
    int remaining = 1;                       // the table relocation
    for (int i = 0; i < n; ++i) {
        if (g_patches[i].stage > g_stage) done[i] = true;   // not part of this stage
        else ++remaining;
    }
    for (int i = 0; i < nd; ++i) {
        if (g_detours[i].stage > g_stage) ddone[i] = true;
        else ++remaining;
    }

    for (int t = 0; t < kMaxTries && remaining > 0; ++t) {
        for (int i = 0; i < n; ++i)
            if (!done[i] && ApplyPatch(base, g_patches[i])) { done[i] = true; --remaining; }
        for (int i = 0; i < nd; ++i)
            if (!ddone[i] && ApplyDetour(base, g_detours[i])) { ddone[i] = true; --remaining; }
        if (!tableDone && RelocateTable(base)) { tableDone = true; --remaining; }
        if (remaining) Sleep(kPollMs);
    }

    if (remaining == 0) {
        Log("stage %d applied cleanly", g_stage);
        if (g_stage >= 2)
            Log("grid is now %d rows x %d columns (%d slots); CloneEngine fills 56..%d",
                NEW_ROWS, COLS, SLOTS, LAST_SLOT);
    } else {
        for (int i = 0; i < n; ++i)
            if (!done[i]) Log("GAVE UP rva 0x%06X (%s)", g_patches[i].rva, g_patches[i].name);
        for (int i = 0; i < nd; ++i)
            if (!ddone[i]) Log("GAVE UP detour rva 0x%06X (%s)",
                               g_detours[i].rva, g_detours[i].name);
        if (!tableDone) Log("GAVE UP relocating the grid table");
        Log("NOTE: a partial patch set leaves the grid inconsistent; "
            "remove this plugin if the screen misbehaves.");
    }

    // CloneEngine repoints the same readers at its own table, and it does it
    // after us, so watch for the handover and lay that table out instead. The
    // screen only reads the table when it is built, so catching this any time
    // before the player reaches character select is enough.
    //
    // This runs whether or not the relocation above succeeded: if CE got there
    // first, RelocateTable fails ("already relocated?") and re-laying CE's table
    // in place is the only thing that will make the grid right.
    if (g_stage >= 1) {
        for (int t = 0; t < kWatchTries; ++t) {
            if (RelayoutLiveTable(base)) break;
            Sleep(kWatchMs);
        }
    }
    return 0;
}

} // namespace

BOOL APIENTRY DllMain(HMODULE h, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        GetModuleFileNameA(h, g_log, MAX_PATH);
        char* dot = strrchr(g_log, '.');
        if (dot) strcpy_s(dot, sizeof(g_log) - (dot - g_log), ".log");
        FILE* f = nullptr; if (fopen_s(&f, g_log, "w") == 0 && f) fclose(f);
        LoadConfig(h);
        Log("umvc3_cssslots loaded");
        CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
    }
    return TRUE;
}
