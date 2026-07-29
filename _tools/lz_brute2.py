import struct, sys, itertools
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, decrypt

# (name, offbits) -> offset uses high bits (w>>lenbits) or low bits (w & mask)
SPLITS = []
for lenbits in (2, 3, 4, 5, 6):
    offbits = 16 - lenbits
    SPLITS.append(("hi%d/lo%d" % (offbits, lenbits), offbits, lenbits, True))
    SPLITS.append(("lo%d/hi%d" % (offbits, lenbits), offbits, lenbits, False))


def lz(src, offbits, lenbits, off_high, addc, mult, ring_mode):
    comp, raw = struct.unpack_from("<II", src, 0)
    N = 1 << offbits
    lmask = (1 << lenbits) - 1
    ring = bytearray(N) if ring_mode else None
    r = 0
    dst = bytearray()
    sp, flags = 8, 0
    L = len(src)
    while len(dst) < raw:
        if sp >= L:
            return None, sp
        flags >>= 1
        if not (flags & 0x100):
            flags = src[sp] | 0xFF00; sp += 1
            if sp >= L: return None, sp
        if flags & 1:
            c = src[sp]; sp += 1
            dst.append(c)
            if ring_mode:
                ring[r] = c; r = (r + 1) & (N - 1)
        else:
            if sp + 1 >= L: return None, sp
            w = src[sp] | (src[sp + 1] << 8); sp += 2
            if off_high:
                i, j = w >> lenbits, (w & lmask) + addc
            else:
                i, j = w & (N - 1), (w >> offbits) + addc
            n = j * mult
            if ring_mode:
                for k in range(n):
                    c = ring[(i + k) & (N - 1)]
                    dst.append(c); ring[r] = c; r = (r + 1) & (N - 1)
            else:
                if i == 0 or i > len(dst):
                    return None, sp
                base = len(dst) - i
                for k in range(n):
                    dst.append(dst[base + k])
    return dst, sp


pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
srcs = {i: bytes(decrypt(pck.raw(i))) for i in (1, 2, 50, 200)}
found = []
for (nm, ob, lb, hi), addc, mult, rm in itertools.product(SPLITS, (0, 1, 2, 3), (1, 2), (True, False)):
    ok = True
    for i, src in srcs.items():
        comp, raw = struct.unpack_from("<II", src, 0)
        dst, sp = lz(src, ob, lb, hi, addc, mult, rm)
        if dst is None or len(dst) != raw or sp != comp:
            ok = False; break
    if ok:
        found.append((nm, addc, mult, rm))
        print(f"EXACT: split={nm} addc={addc} mult={mult} ring={rm}")
if not found:
    print("none exact. Best src-consumption ratios on scene 1:")
    src = srcs[1]; comp, raw = struct.unpack_from("<II", src, 0)
    rows = []
    for (nm, ob, lb, hi), addc, mult, rm in itertools.product(SPLITS, (0, 1, 2, 3), (1, 2), (True,)):
        dst, sp = lz(src, ob, lb, hi, addc, mult, rm)
        if dst is not None and len(dst) == raw:
            rows.append((abs(sp - comp), nm, addc, mult, rm, sp))
    rows.sort()
    for d, nm, addc, mult, rm, sp in rows[:12]:
        print(f"  split={nm:10s} addc={addc} mult={mult} ring={rm} sp={sp}/{comp} diff={d}")
