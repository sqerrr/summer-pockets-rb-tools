import sys, struct
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack, Scene

pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
bad_tail = []
bad_order = []
bad_contig = []
max_cp = 0
for i in range(pck.count):
    data = pck.scene(i)
    sc = Scene(data)
    idx_off, cnt, dat_off = sc.str_idx_off, sc.str_count, sc.str_data_off
    # 1) index immediately followed by data?
    if idx_off + cnt * 8 != dat_off:
        bad_contig.append(i)
    # 2) data region ends exactly at scene end?
    if cnt:
        o, l = struct.unpack_from("<II", data, idx_off + (cnt - 1) * 8)
        if dat_off + (o + l) * 2 != len(data):
            bad_tail.append((i, dat_off + (o + l) * 2, len(data)))
    # 3) any other header region located after the string index?
    for k in range(1, len(sc.dw), 2):
        if k in (3, 5):
            continue
        if sc.dw[k] > idx_off:
            bad_order.append((i, k, sc.dw[k], idx_off))
            break
    # 4) char offsets strictly sequential?
    prev = 0
    for j in range(cnt):
        o, l = struct.unpack_from("<II", data, idx_off + j * 8)
        if o != prev:
            bad_order.append((i, "gap", j, o, prev)); break
        prev = o + l

print("scenes:", pck.count)
print("index not directly followed by data:", len(bad_contig), bad_contig[:5])
print("string data not ending at scene end:", len(bad_tail), bad_tail[:5])
print("regions after string index / non-sequential offsets:", len(bad_order), bad_order[:5])
