import struct, re, sys
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack

pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
i = int(sys.argv[1]) if len(sys.argv) > 1 else 1
ss = pck.scene(i)
print(f"scene {i} {pck.names[i]!r} len={len(ss)}")

# find runs of UTF-16LE chars in BMP Japanese/latin range
runs = []
p, start = 0, None
while p + 1 < len(ss):
    cp = ss[p] | (ss[p + 1] << 8)
    ok = (0x20 <= cp <= 0x7E) or (0x3000 <= cp <= 0x30FF) or (0x4E00 <= cp <= 0x9FFF) or (0xFF00 <= cp <= 0xFF60)
    if ok:
        if start is None:
            start = p
    else:
        if start is not None and (p - start) >= 8:
            runs.append((start, p))
        start = None
    p += 2
print("utf16 runs:", len(runs))
for (a, b) in runs[:3]:
    print(f"  0x{a:X}..0x{b:X} len={(b-a)//2}")
if runs:
    a, b = runs[0]
    print("  first run head:", ss[a:min(b, a + 60)].decode("utf-16le"))
    lo = min(r[0] for r in runs); hi = max(r[1] for r in runs)
    print(f"text area approx 0x{lo:X}..0x{hi:X} of 0x{len(ss):X}")

n = struct.unpack_from("<I", ss, 0)[0]
print("header size:", n)
dw = struct.unpack_from("<%dI" % (n // 4), ss, 0)
print("dwords:", " ".join("%d:0x%X" % (j, v) for j, v in enumerate(dw)))
