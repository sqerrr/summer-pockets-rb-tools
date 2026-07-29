import struct, sys
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, decrypt

VARIANTS = {
    "A off=w>>4 cnt=(w&15)+2": lambda w: (w >> 4, (w & 0xF) + 2),
    "B off=w>>4 cnt=(w&15)+3": lambda w: (w >> 4, (w & 0xF) + 3),
    "C off=w&0xFFF cnt=(w>>12)+2": lambda w: (w & 0xFFF, (w >> 12) + 2),
    "D off=w&0xFFF cnt=(w>>12)+3": lambda w: (w & 0xFFF, (w >> 12) + 3),
    "E off=w>>5 cnt=(w&31)+2": lambda w: (w >> 5, (w & 0x1F) + 2),
    "F off=w>>3 cnt=(w&7)+2": lambda w: (w >> 3, (w & 0x7) + 2),
}


def run(src, split, msb=False):
    comp, raw = struct.unpack_from("<II", src, 0)
    dst = bytearray(raw)
    sp, dp, flag, nb = 8, 0, 0, 0
    try:
        while dp < raw:
            if nb == 0:
                flag = src[sp]; sp += 1; nb = 8
            bit = (flag & 0x80) if msb else (flag & 1)
            if bit:
                dst[dp] = src[sp]; sp += 1; dp += 1
            else:
                w = src[sp] | (src[sp + 1] << 8); sp += 2
                off, cnt = split(w)
                if off == 0 or off > dp:
                    return None, sp, "bad off %d at dp=%d" % (off, dp)
                for _ in range(cnt):
                    if dp >= raw: break
                    dst[dp] = dst[dp - off]; dp += 1
            flag = ((flag << 1) & 0xFF) if msb else (flag >> 1)
            nb -= 1
    except IndexError as e:
        return None, sp, "index error"
    return dst, sp, "ok"


def score_text(dst):
    """count utf16le chars that look like Japanese/ascii in long runs"""
    best = 0; cur = 0; total = 0
    for p in range(0, len(dst) - 1, 2):
        cp = dst[p] | (dst[p + 1] << 8)
        if (0x20 <= cp <= 0x7E) or (0x3040 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FAF) or cp == 0x3001 or cp == 0x3002:
            cur += 1
        else:
            if cur >= 10: total += cur; best = max(best, cur)
            cur = 0
    return total, best


pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
for i in (1, 2, 50):
    src = bytes(decrypt(pck.raw(i)))
    comp, raw = struct.unpack_from("<II", src, 0)
    print(f"\n=== scene {i} comp={comp} raw={raw} bloblen={len(src)}")
    for msb in (False, True):
        for name, split in VARIANTS.items():
            dst, sp, st = run(src, split, msb)
            tag = "MSB" if msb else "LSB"
            if dst is None:
                print(f"  {tag} {name:32s} FAIL sp={sp} ({st})")
            else:
                tot, best = score_text(dst)
                mark = "  <== SRC EXACT" if sp == comp else ""
                print(f"  {tag} {name:32s} sp={sp} (comp={comp}) textchars={tot} longest={best}{mark}")
