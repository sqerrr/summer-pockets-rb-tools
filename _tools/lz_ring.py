import struct, sys
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, decrypt


def ring_lzss(src, N=4096, F=18, THR=2, init_r=None, fill=0):
    comp, raw = struct.unpack_from("<II", src, 0)
    ring = bytearray([fill]) * N
    r = (N - F) if init_r is None else init_r
    dst = bytearray()
    sp, flags = 8, 0
    while len(dst) < raw and sp < len(src):
        flags >>= 1
        if not (flags & 0x100):
            flags = src[sp] | 0xFF00; sp += 1
        if flags & 1:
            c = src[sp]; sp += 1
            dst.append(c); ring[r] = c; r = (r + 1) & (N - 1)
        else:
            if sp + 1 >= len(src): break
            b1, b2 = src[sp], src[sp + 1]; sp += 2
            i = b1 | ((b2 & 0xF0) << 4)
            j = (b2 & 0x0F) + THR
            for k in range(j + 1):
                c = ring[(i + k) & (N - 1)]
                dst.append(c); ring[r] = c; r = (r + 1) & (N - 1)
    return dst, sp, comp


def score(dst):
    tot = cur = best = 0
    for p in range(0, len(dst) - 1, 2):
        cp = dst[p] | (dst[p + 1] << 8)
        if (0x20 <= cp <= 0x7E) or (0x3040 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FAF):
            cur += 1
        else:
            if cur >= 10:
                tot += cur; best = max(best, cur)
            cur = 0
    return tot, best


pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
for i in (1, 2, 50):
    src = bytes(decrypt(pck.raw(i)))
    comp, raw = struct.unpack_from("<II", src, 0)
    print(f"\n=== scene {i} comp={comp} raw={raw}")
    print("  decrypted head:", src[:40].hex(" "))
    for N, F, THR, ir in ((4096, 18, 2, None), (4096, 18, 2, 0), (4096, 17, 2, None), (2048, 18, 2, None)):
        dst, sp, _ = ring_lzss(src, N, F, THR, ir)
        t, b = score(dst)
        print(f"  N={N} F={F} THR={THR} init_r={ir}: out={len(dst)}/{raw} sp={sp}/{comp} "
              f"head={bytes(dst[:12]).hex(' ')} text={t} longest={b}")
