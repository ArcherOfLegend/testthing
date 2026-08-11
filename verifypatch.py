"""Check every patch site in umvc3_cssslots.cpp against the unpacked exe.

The plugin verifies its own `expect` bytes at runtime and silently skips any
site that does not match, so a wrong expectation shows up only as a GAVE UP
line in the log after a full game launch. This reads the patch and detour
tables straight out of the .cpp and compares them against the stock bytes, so a
typo is caught before the game is ever started.

  UMVC3_EXE   unpacked exe (default: steamless/umvc3.exe.unpacked.exe)
  UMVC3_CPP   plugin source (default: asi/umvc3_cssslots.cpp)
"""
import os, re, struct, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
EXE = os.environ.get("UMVC3_EXE", os.path.join(ROOT, "steamless", "umvc3.exe.unpacked.exe"))
CPP = os.environ.get("UMVC3_CPP", os.path.join(ROOT, "asi", "umvc3_cssslots.cpp"))

b = open(EXE, "rb").read()
pe = struct.unpack_from("<I", b, 0x3C)[0]
if b[pe:pe + 4] != b"PE\0\0":
    raise RuntimeError("not a PE")
nsec = struct.unpack_from("<H", b, pe + 6)[0]
sec = pe + 24 + struct.unpack_from("<H", b, pe + 20)[0]
SECTIONS = []
for i in range(nsec):
    o = sec + i * 40
    vsize, vaddr = struct.unpack_from("<II", b, o + 8)
    rsize, raddr = struct.unpack_from("<II", b, o + 16)
    SECTIONS.append((vaddr, max(vsize, rsize), raddr))


def at(rva, n):
    for vaddr, vsize, raddr in SECTIONS:
        if vaddr <= rva < vaddr + vsize:
            off = raddr + (rva - vaddr)
            return b[off:off + n]
    raise RuntimeError("RVA 0x%X is in no section" % rva)


src = open(CPP, "r", encoding="utf-8", errors="replace").read()


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return "\n".join(re.sub(r"//.*", "", ln) for ln in s.split("\n"))


def table(name):
    i = src.index(name + "[] = {")
    depth, j = 0, src.index("{", i + len(name))
    start = j
    while True:
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return strip_comments(src[start + 1:j])


def rows(body):
    """Split a brace-initialiser list into its top-level { ... } entries."""
    out, depth, cur = [], 0, ""
    for ch in body:
        if ch == "{":
            depth += 1
            if depth == 1:
                cur = ""
                continue
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append(cur)
                continue
        if depth >= 1:
            cur += ch
    return out


def fields(entry):
    """Top-level comma-separated fields, keeping nested { ... } together."""
    out, depth, cur = [], 0, ""
    for ch in entry:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def bytelist(s):
    return [int(x, 0) for x in s.strip().strip("{}").split(",") if x.strip()]


bad = 0
checked = 0
for label, body in (("patch", table("g_patches")), ("detour", table("g_detours"))):
    for entry in rows(body):
        f = fields(entry)
        if len(f) < 4:
            continue
        rva = int(f[0], 0)
        expect = bytelist(f[1])
        # BytePatch: rva, expect, value, len, stage, name
        # Detour:    rva, expect, len, stage, body, bodyLen, cc, taken, fall, name
        n = int(f[3], 0) if label == "patch" else int(f[2], 0)
        name = f[-2].strip().strip('"') if label == "patch" else f[-2].strip().strip('"')
        want = bytes(expect[:n])
        got = at(rva, n)
        checked += 1
        if got != want:
            bad += 1
            print("MISMATCH %s rva 0x%06X  %s" % (label, rva, name))
            print("    expect %s" % " ".join("%02X" % c for c in want))
            print("    actual %s" % " ".join("%02X" % c for c in got))

# Both grid-table readers must still point at the vanilla table.
for rva, opcode in ((0x361FE5, (0x48, 0x8D, 0x05)), (0x361F52, (0x4C, 0x8D, 0x0D))):
    lea = at(rva, 7)
    checked += 1
    disp = struct.unpack_from("<i", lea, 3)[0]
    target = rva + 7 + disp
    if tuple(lea[:3]) != opcode or target != 0xB3E580:
        bad += 1
        print("MISMATCH table ref rva 0x%06X -> 0x%X (want lea to 0xB3E580)" % (rva, target))

print()
print("%d sites checked, %d mismatched" % (checked, bad))
sys.exit(1 if bad else 0)
