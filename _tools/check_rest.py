import sys, os, struct, re, collections
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, Scene

ROOT = r"A:\Projects\Summer Pockets REFLECTION BLUE"

# --- 1. how much of the string pool is actual Japanese text? ---
pck = ScenePack(os.path.join(ROOT, "Scene.pck"))
jp = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
counts = collections.Counter()
sample_scene = Scene(pck.scene(2))
ss = sample_scene.strings()
for s in ss:
    counts["jp" if jp.search(s) else "ascii/asset"] += 1
print("scene 2 string mix:", dict(counts), "of", len(ss))
print("scene 2 header pairs:")
dw = sample_scene.dw
for i in range(1, len(dw), 2):
    print(f"   pair{(i+1)//2:2d}: off=0x{dw[i]:<8X} cnt=0x{dw[i+1]:X} ({dw[i+1]})")

# --- 2. dbs files ---
print("\n--- dat/*.dbs ---")
for fn in sorted(os.listdir(os.path.join(ROOT, "dat"))):
    p = os.path.join(ROOT, "dat", fn)
    if not fn.lower().endswith((".dbs", ".cgm", ".tcr")):
        continue
    d = open(p, "rb").read()
    n_jp = len(jp.findall(d.decode("utf-16le", "ignore")))
    print(f"  {fn:42s} {len(d):8d}  head={d[:12].hex(' ')}  utf16-jp-chars~{n_jp}")

# --- 3. Gameexe.dat ---
g = open(os.path.join(ROOT, "Gameexe.dat"), "rb").read()
print("\nGameexe.dat:", len(g), "head:", g[:16].hex(" "))
from siglus import decrypt, decompress
try:
    dec = decrypt(g)
    print("  after 256-key xor:", bytes(dec[:16]).hex(" "))
    print("  sizes:", struct.unpack_from("<II", dec, 0))
except Exception as e:
    print("  ", e)

# --- 4. fonts: cyrillic coverage ---
print("\n--- fonts ---")
for fn in ("font01.ttf", "font02.ttf"):
    p = os.path.join(ROOT, "dat", fn)
    d = open(p, "rb").read()
    numTables = struct.unpack_from(">H", d, 4)[0]
    cmap_off = None
    name_off = None
    for i in range(numTables):
        rec = 12 + i * 16
        tag = d[rec:rec + 4]
        off, ln = struct.unpack_from(">II", d, rec + 8)
        if tag == b"cmap":
            cmap_off = off
        if tag == b"name":
            name_off = off
    chars = set()
    n = struct.unpack_from(">H", d, cmap_off + 2)[0]
    for i in range(n):
        pid, eid, sub = struct.unpack_from(">HHI", d, cmap_off + 4 + i * 8)
        fmt = struct.unpack_from(">H", d, cmap_off + sub)[0]
        if fmt == 4:
            segX2 = struct.unpack_from(">H", d, cmap_off + sub + 6)[0]
            seg = segX2 // 2
            endo = cmap_off + sub + 14
            starto = endo + segX2 + 2
            for s in range(seg):
                e = struct.unpack_from(">H", d, endo + s * 2)[0]
                st = struct.unpack_from(">H", d, starto + s * 2)[0]
                if st <= e and e != 0xFFFF:
                    chars.update(range(st, e + 1))
    cyr = sum(1 for c in chars if 0x400 <= c <= 0x4FF)
    lat = sum(1 for c in chars if 0x20 <= c <= 0x7E)
    print(f"  {fn}: glyphs mapped={len(chars)}, latin={lat}/95, cyrillic={cyr}/256")
