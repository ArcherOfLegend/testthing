"""Read the vanilla CSS grid table out of the unpacked exe.

The table is 7 rows x 8 int32 of character ids at RVA 0xB3E580. Columns 0-3 are
one page and 4-7 the other, so this shows how the 50 vanilla characters are
split between the Capcom and Marvel pages - which decides whether they can be
relaid out across 16 columns without mixing the two.

  UMVC3_EXE
"""
import sys, os, struct

EXE = os.environ.get("UMVC3_EXE",
                     r"C:\Users\Sky\Projects\umvc3_tools\steamless\umvc3.exe.unpacked.exe")
RVA = 0xB3E580
ROWS, COLS = 7, 8

b = open(EXE, "rb").read()
pe = struct.unpack_from("<I", b, 0x3C)[0]
if b[pe:pe + 4] != b"PE\0\0":
    raise RuntimeError("not a PE")
nsec = struct.unpack_from("<H", b, pe + 6)[0]
opt = struct.unpack_from("<H", b, pe + 20)[0]
sec = pe + 24 + opt

off = None
for i in range(nsec):
    o = sec + i * 40
    name = b[o:o + 8].split(b"\0")[0].decode()
    vsize, vaddr = struct.unpack_from("<II", b, o + 8)
    rsize, raddr = struct.unpack_from("<II", b, o + 16)
    if vaddr <= RVA < vaddr + max(vsize, rsize):
        off = raddr + (RVA - vaddr)
        print("RVA 0x%X is in %s -> file offset 0x%X" % (RVA, name, off))
if off is None:
    raise RuntimeError("RVA not in any section")

vals = struct.unpack_from("<%di" % (ROWS * COLS), b, off)
print()
print("grid table, %d rows x %d columns (col 0 is nearest the screen centre):" % (ROWS, COLS))
print("      " + "".join("%6s" % ("c%d" % c) for c in range(COLS)))
for r in range(ROWS):
    print("row %d " % r + "".join("%6d" % vals[r * COLS + c] for c in range(COLS)))

left = [vals[r * COLS + c] for r in range(ROWS) for c in range(4)]
right = [vals[r * COLS + c] for r in range(ROWS) for c in range(4, 8)]
real = lambda v: [x for x in v if x >= 0]
print()
print("page A (cols 0-3): %d cells, %d real ids, placeholders %s"
      % (len(left), len(real(left)), sorted(set(x for x in left if x < 0))))
print("page B (cols 4-7): %d cells, %d real ids, placeholders %s"
      % (len(right), len(real(right)), sorted(set(x for x in right if x < 0))))
print()
print("If the grid becomes 16 columns wide, slots 0-55 give the pages:")
print("  cols 0-7  -> slots 0-7, 16-23, 32-39, 48-55  = 32 cells")
print("  cols 8-15 -> slots 8-15, 24-31, 40-47        = 24 cells")
print("so one page can hold at most 24 of its characters below slot 56.")
