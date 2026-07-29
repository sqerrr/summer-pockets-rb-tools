import sys, struct, collections
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, Scene

pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
ok = bad = 0
total_strings = 0
total_chars = 0
hdr_sizes = collections.Counter()
bad_scenes = []

for i in range(pck.count):
    try:
        sc = Scene(pck.scene(i))
        hdr_sizes[sc.hdr_size] += 1
        ss = sc.strings()
        # sanity: characters must be printable-ish
        n_bad = 0
        for s in ss:
            for ch in s:
                c = ord(ch)
                if not (0x20 <= c <= 0x7E or 0x3000 <= c <= 0x30FF or
                        0x4E00 <= c <= 0x9FFF or 0xFF00 <= c <= 0xFFEF or
                        c in (0x0A, 0x09) or 0xA0 <= c <= 0x2FFF or 0xE000 <= c <= 0xF8FF):
                    n_bad += 1
        total_strings += len(ss)
        total_chars += sum(len(s) for s in ss)
        if n_bad > 0:
            bad_scenes.append((i, pck.names[i], n_bad))
        ok += 1
    except Exception as e:
        bad += 1
        bad_scenes.append((i, pck.names[i], repr(e)))

print(f"scenes decoded OK: {ok}/{pck.count}, failures: {bad}")
print("header sizes:", dict(hdr_sizes))
print(f"total strings: {total_strings}, total chars: {total_chars}")
print("scenes with suspicious chars:", len(bad_scenes))
for x in bad_scenes[:10]:
    print("   ", x)
