import struct, sys, collections

P = r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck"
buf = open(P, "rb").read()

hdr = list(struct.unpack_from("<23I", buf, 0))
print("header:", " ".join(hex(v) for v in hdr))

# pairs (offset, count) starting at dword 1
pairs = [(hdr[1 + 2 * i], hdr[2 + 2 * i]) for i in range(10)]
for i, (o, c) in enumerate(pairs):
    nxt = pairs[i + 1][0] if i + 1 < len(pairs) else len(buf)
    print(f"  region {i+1}: off=0x{o:X} count={c} span=0x{nxt-o:X} ({nxt-o} bytes) "
          f"per-entry={(nxt-o)/c:.2f}")
print("  tail dwords:", hex(hdr[21]), hex(hdr[22]))


def read_names(idx_off, data_off, cnt):
    out = []
    for i in range(cnt):
        o, l = struct.unpack_from("<II", buf, idx_off + i * 8)
        out.append(buf[data_off + o * 2: data_off + (o + l) * 2].decode("utf-16le"))
    return out


SCENE_IDX_OFF, SCENE_CNT = pairs[6]
SCENE_NAME2_OFF = pairs[7][0]
SCENE_DATA_IDX = pairs[8][0]
SCENE_DATA_OFF = pairs[9][0]

names_a = read_names(SCENE_IDX_OFF, SCENE_IDX_OFF + SCENE_CNT * 8, SCENE_CNT)
print("\nnames A[0:4]:", names_a[:4])
names_chars = sum(len(n) for n in names_a)
print("names A total chars:", names_chars, "bytes:", names_chars * 2,
      "-> ends at 0x%X" % (SCENE_IDX_OFF + SCENE_CNT * 8 + names_chars * 2))
print("region7 leftover starts 0x%X .. 0x%X" %
      (SCENE_IDX_OFF + SCENE_CNT * 8 + names_chars * 2, pairs[7][0]))

scenes = []
for i in range(SCENE_CNT):
    o, s = struct.unpack_from("<II", buf, SCENE_DATA_IDX + i * 8)
    scenes.append((i, names_a[i], o, s))
li, ln, lo, ls = scenes[-1]
print(f"\nscene data: off=0x{SCENE_DATA_OFF:X} end=0x{SCENE_DATA_OFF+lo+ls:X} filesize=0x{len(buf):X}")

# --- key recovery: assume first dword of decrypted scene == compressed size ---
cand = collections.Counter()
for (i, nm, o, s) in scenes[:40]:
    raw = buf[SCENE_DATA_OFF + o: SCENE_DATA_OFF + o + 16]
    sz = struct.pack("<I", s)
    k = bytes(raw[j] ^ sz[j] for j in range(4))
    cand[k.hex(" ")] += 1
    if i < 5:
        print(f"scene {i:3d} {nm!r} size=0x{s:X} raw={raw.hex(' ')} -> key0_3={k.hex(' ')}")
print("\nkey[0..3] candidates:", cand.most_common(5))
