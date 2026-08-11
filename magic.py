"""Verify the replacement divide-by-18 magic.

vfn17 divides with a fixed instruction shape:
    eax = MAGIC ; mul esi ; ecx = (((n - hi) >> 1) + hi) >> SHIFT
which is exactly  q = (n + mulhi_u32(n, MAGIC)) >> (SHIFT + 1).

Stock is MAGIC 0x24924925 / SHIFT 2, i.e. /7. Only the two immediates change.
"""
MASK = 0xFFFFFFFF


def q(n, magic, shift):
    hi = (n * magic) >> 32
    return (((((n - hi) & MASK) >> 1) + hi) & MASK) >> shift


def check(d, magic, shift, limit):
    for n in range(limit):
        if q(n, magic, shift) != n // d:
            return n
    for n in (0xFFFF, 0x10000, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF,
              1 << 20, (1 << 24) - 1, (1 << 28) + 17):
        if q(n, magic, shift) != n // d:
            return n
    return None


for d, magic, shift in ((7, 0x24924925, 2), (8, 0x00000000, 2),
                        (9, 0xC71C71C8, 3), (16, 0x00000000, 3),
                        (18, 0xC71C71C8, 4)):
    bad = check(d, magic, shift, 100000)
    print("d=%-3d magic=0x%08X shift=%d  ->  %s"
          % (d, magic, shift, "exact" if bad is None else "WRONG at n=%d" % bad))

print()
print("bytes to write: magic immediate %s   final shift %02X"
      % (" ".join("%02X" % b for b in (0xC71C71C8).to_bytes(4, "little")), 4))
