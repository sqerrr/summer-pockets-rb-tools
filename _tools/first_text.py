import sys, re
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, Scene

pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")

print("=== first 12 scenes ===")
for i in range(12):
    print(f"  {i:3d}  {pck.names[i]}")

print("\n=== scenes that look like entry points ===")
for i, n in enumerate(pck.names):
    if re.search(r"title|system|init|start|logo|menu", n, re.I):
        print(f"  {i:3d}  {n}")

# prologue scene: show the beginning of the pool
idx = 1
sc = Scene(pck.scene(idx))
ss = sc.strings()
print(f"\n=== scene {idx} '{pck.names[idx]}' : {len(ss)} strings ===")
print("first 14 entries (truncated to 45 chars):")
for k in range(14):
    s = ss[k].replace("\n", "\\n")
    print(f"  [{k:3d}] {s[:45]!r}")
