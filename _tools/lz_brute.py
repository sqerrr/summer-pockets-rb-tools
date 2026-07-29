import struct, sys, itertools
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, decrypt


def lz(src, mode, addc, extra, r0, N=4096):
    comp, raw = struct.unpack_from("<II", src, 0)
    ring = bytearray(N)
    r = r0
    dst = bytearray()
    sp, flags = 8, 0
    L = len(src)
    while len(dst) < raw:
        if sp >= L:
            return None, sp
        flags >>= 1
        if not (flags & 0x100):
            flags = src[sp] | 0xFF00; sp += 1
            if sp > L: return None, sp
        if flags & 1:
            c = src[sp]; sp += 1
            dst.append(c); ring[r] = c; r = (r + 1) & (N - 1)
        else:
            if sp + 1 >= L: return None, sp
            b1, b2 = src[sp], src[sp + 1]; sp += 2
            w = b1 | (b2 << 8)
            if mode == 0:      # offset = high 12 bits
                i, j = w >> 4, (w & 0xF) + addc
            else:              # okumura split
                i, j = b1 | ((b2 & 0xF0) << 4), (b2 & 0xF) + addc
            for k in range(j + extra):
                c = ring[(i + k) & (N - 1)]
                dst.append(c); ring[r] = c; r = (r + 1) & (N - 1)
    return dst, sp


pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
srcs = {i: bytes(decrypt(pck.raw(i))) for i in (1, 2, 50, 200)}

results = []
for mode, addc, extra, r0 in itertools.product((0, 1), (2, 3), (0, 1), (0, 4078, 4079, 4080)):
    ok = True
    for i, src in srcs.items():
        comp, raw = struct.unpack_from("<II", src, 0)
        dst, sp = lz(src, mode, addc, extra, r0)
        if dst is None or len(dst) != raw or sp != comp:
            ok = False
            break
    if ok:
        results.append((mode, addc, extra, r0))
        print("EXACT MATCH:", "mode=%d addc=%d extra=%d r0=%d" % (mode, addc, extra, r0))

if not results:
    print("no exact combo; closest by src consumption:")
    src = srcs[1]; comp, raw = struct.unpack_from("<II", src, 0)
    for mode, addc, extra, r0 in itertools.product((0, 1), (2, 3), (0, 1), (0, 4078)):
        dst, sp = lz(src, mode, addc, extra, r0)
        print("  mode=%d addc=%d extra=%d r0=%-4d -> out=%s/%d sp=%d/%d" %
              (mode, addc, extra, r0, len(dst) if dst else "FAIL", raw, sp, comp))
