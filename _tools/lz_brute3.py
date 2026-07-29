import struct, sys, itertools
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, decrypt


def lz(src, offbits, lenbits, off_high, addc, msb, ring_mode):
    comp, raw = struct.unpack_from("<II", src, 0)
    N = 1 << offbits
    lmask = (1 << lenbits) - 1
    ring = bytearray(N) if ring_mode else None
    r = 0
    dst = bytearray()
    sp, flag, nb = 8, 0, 0
    L = len(src)
    while len(dst) < raw:
        if nb == 0:
            if sp >= L: return None, sp
            flag = src[sp]; sp += 1; nb = 8
        bit = (flag & 0x80) if msb else (flag & 1)
        flag = ((flag << 1) & 0xFF) if msb else (flag >> 1)
        nb -= 1
        if bit:
            if sp >= L: return None, sp
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
            if ring_mode:
                for k in range(j):
                    c = ring[(i + k) & (N - 1)]
                    dst.append(c); ring[r] = c; r = (r + 1) & (N - 1)
            else:
                if i == 0 or i > len(dst): return None, sp
                base = len(dst) - i
                for k in range(j):
                    dst.append(dst[base + k])
    return dst, sp


pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
srcs = {i: bytes(decrypt(pck.raw(i))) for i in (1, 2, 50, 200)}

SPLITS = []
for lb in (2, 3, 4, 5, 6):
    SPLITS.append((16 - lb, lb, True))
    SPLITS.append((16 - lb, lb, False))

best = []
found = 0
for (ob, lb, hi), addc, msb, rm in itertools.product(SPLITS, (0, 1, 2, 3), (False, True), (True, False)):
    ok = True
    for i, src in srcs.items():
        comp, raw = struct.unpack_from("<II", src, 0)
        dst, sp = lz(src, ob, lb, hi, addc, msb, rm)
        if dst is None or len(dst) != raw or sp != comp:
            ok = False
            if i == 1 and dst is not None and len(dst) == raw:
                best.append((abs(sp - comp), ob, lb, hi, addc, msb, rm, sp, comp))
            break
    if ok:
        found += 1
        print(f"EXACT: off={ob}b len={lb}b off_high={hi} addc={addc} msb={msb} ring={rm}")
if not found:
    best.sort()
    print("no exact; top candidates by src consumption (scene1):")
    for d, ob, lb, hi, addc, msb, rm, sp, comp in best[:10]:
        print(f"  off={ob}b len={lb}b hi={hi} addc={addc} msb={msb} ring={rm} sp={sp}/{comp}")
