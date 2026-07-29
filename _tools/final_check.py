import sys, os, struct, re, collections
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, Scene

ROOT = r"A:\Projects\Summer Pockets REFLECTION BLUE"
pck = ScenePack(os.path.join(ROOT, "Scene.pck"))

jp = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
lat = re.compile(r"[A-Za-z]{3,}")

tot = collections.Counter()
for i in range(0, pck.count, 25):
    for s in Scene(pck.scene(i)).strings():
        if jp.search(s):
            tot["japanese"] += 1
        elif lat.search(s):
            tot["latin"] += 1
        else:
            tot["other/short"] += 1
print("language mix (every 25th scene):", dict(tot))

sc = Scene(pck.scene(1))
ss = sc.strings()
print("\nscene 1 sample (first 20 chars of a few entries):")
for k in (0, 1, 2, 4, 5):
    print(f"  [{k}] {ss[k][:20]!r}")

# cyrillic coverage detail
d = open(os.path.join(ROOT, "dat", "font01.ttf"), "rb").read()
numTables = struct.unpack_from(">H", d, 4)[0]
cmap_off = next(struct.unpack_from(">II", d, 12 + i * 16 + 8)[0]
                for i in range(numTables) if d[12 + i * 16:12 + i * 16 + 4] == b"cmap")
chars = set()
n = struct.unpack_from(">H", d, cmap_off + 2)[0]
for i in range(n):
    pid, eid, sub = struct.unpack_from(">HHI", d, cmap_off + 4 + i * 8)
    if struct.unpack_from(">H", d, cmap_off + sub)[0] == 4:
        segX2 = struct.unpack_from(">H", d, cmap_off + sub + 6)[0]
        endo = cmap_off + sub + 14
        starto = endo + segX2 + 2
        for s2 in range(segX2 // 2):
            e = struct.unpack_from(">H", d, endo + s2 * 2)[0]
            st = struct.unpack_from(">H", d, starto + s2 * 2)[0]
            if st <= e and e != 0xFFFF:
                chars.update(range(st, e + 1))
cyr = sorted(c for c in chars if 0x400 <= c <= 0x4FF)
print("\nfont01 cyrillic codepoints:", "".join(chr(c) for c in cyr))
need = set(range(0x410, 0x450)) | {0x401, 0x451}
print("russian alphabet fully covered:", need.issubset(chars))
print("missing:", "".join(chr(c) for c in sorted(need - chars)) or "none")

# dbs: is it encrypted?
p = os.path.join(ROOT, "dat", "cg_info.dbs")
b = open(p, "rb").read()
print("\ncg_info.dbs first 64:", b[:64].hex(" "))
ent = struct.unpack_from("<I", b, 0)[0]
print("  dword0 =", ent)
