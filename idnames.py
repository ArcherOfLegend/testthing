"""Recover the character id -> internal name table from the exe.

Portrait textures are named f_<Name><colour>_BM_HQ_NOMIP, so the engine holds an
ordered table of those names; the index into it is the character id the grid
table stores. Anchor on a run of pointers to known portrait names, then walk
outward for as long as each qword still points at a plausible identifier, so the
table's true start - and therefore the true id of every entry - is recovered
rather than guessed.

  UMVC3_EXE, UMVC3_NAMES (directory of portrait .tex to take the anchor names from)
"""
import os, re, struct

EXE = os.environ.get("UMVC3_EXE",
                     r"C:\Users\Sky\Projects\umvc3_tools\steamless\umvc3.exe.unpacked.exe")
NAMES_DIR = os.environ.get(
    "UMVC3_NAMES",
    r"C:\Program Files (x86)\Steam\steamapps\common\ULTIMATE MARVEL VS. CAPCOM 3"
    r"\nativePCx64\ui\chs\chs_face_a\chs_cs_f")

known = set()
for fn in os.listdir(NAMES_DIR):
    m = re.match(r"^f_(.+?)(\d{2,3})_BM", fn)
    if m:
        known.add(m.group(1))

b = open(EXE, "rb").read()
pe = struct.unpack_from("<I", b, 0x3C)[0]
base = struct.unpack_from("<Q", b, pe + 24 + 24)[0]
nsec = struct.unpack_from("<H", b, pe + 6)[0]
sec = pe + 24 + struct.unpack_from("<H", b, pe + 20)[0]
SEC = []
for i in range(nsec):
    o = sec + i * 40
    vsize, vaddr = struct.unpack_from("<II", b, o + 8)
    rsize, raddr = struct.unpack_from("<II", b, o + 16)
    SEC.append((vaddr, max(vsize, rsize), raddr, rsize))

IDENT = re.compile(rb"^[A-Za-z][A-Za-z0-9_]{1,23}$")


def read_str(va):
    """The NUL-terminated identifier at a virtual address, or None."""
    rva = va - base
    for vaddr, vsize, raddr, rsize in SEC:
        if vaddr <= rva < vaddr + rsize:
            o = raddr + (rva - vaddr)
            e = b.find(b"\x00", o, o + 32)
            if e < 0:
                return None
            s = b[o:e]
            return s.decode("ascii") if IDENT.match(s) else None
    return None


def off_of(rva):
    for vaddr, vsize, raddr, rsize in SEC:
        if vaddr <= rva < vaddr + rsize:
            return raddr + (rva - vaddr)
    return None


# anchor: longest run of qwords pointing at names we know are portrait names
best, best_rva = [], None
for vaddr, vsize, raddr, rsize in SEC:
    p = raddr
    end = raddr + rsize
    while p + 8 <= end:
        q = struct.unpack_from("<Q", b, p)[0]
        s = read_str(q) if q > base else None
        if s in known:
            start = p
            run = []
            while p + 8 <= end:
                q = struct.unpack_from("<Q", b, p)[0]
                s = read_str(q) if q > base else None
                if s not in known:
                    break
                run.append(s)
                p += 8
            if len(run) > len(best):
                best, best_rva = run, vaddr + (start - raddr)
        else:
            p += 8

anchor_off = off_of(best_rva)
print("anchor: %d known names at rva 0x%X" % (len(best), best_rva))

# walk outward while the qwords keep resolving to identifiers
lo = anchor_off
while lo - 8 >= 0:
    q = struct.unpack_from("<Q", b, lo - 8)[0]
    if q <= base or read_str(q) is None:
        break
    lo -= 8
hi = anchor_off + len(best) * 8
while True:
    q = struct.unpack_from("<Q", b, hi)[0]
    if q <= base or read_str(q) is None:
        break
    hi += 8

table = [read_str(struct.unpack_from("<Q", b, p)[0]) for p in range(lo, hi, 8)]
start_rva = best_rva - (anchor_off - lo)
print("full table: %d entries at rva 0x%X\n" % (len(table), start_rva))
for i, n in enumerate(table):
    mark = "" if n in known else "   (no portrait file)"
    print("  %3d  %-14s%s" % (i, n, mark))
