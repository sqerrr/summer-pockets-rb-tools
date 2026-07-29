import struct, sys, collections
sys.path.insert(0, r"A:\Projects\_tools")
from siglus import ScenePack

pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
ss = pck.scene(1)
dw = struct.unpack_from("<33I", ss, 0)
IDX, CNT = dw[3], dw[4]
DAT = dw[5]
print("msg index=0x%X count=%d data=0x%X sceneLen=0x%X" % (IDX, CNT, DAT, len(ss)))

ents = [struct.unpack_from("<II", ss, IDX + i * 8) for i in range(CNT)]
print("first entries (charOff, charLen):", ents[:6])
print("last entry:", ents[-1], "-> end 0x%X" % (DAT + (ents[-1][0] + ents[-1][1]) * 2))

# raw words of first few strings
for k in range(4):
    o, l = ents[k]
    raw = ss[DAT + o * 2: DAT + (o + l) * 2]
    ws = struct.unpack("<%dH" % l, raw)
    print(f"  str{k}: len={l} words={[hex(w) for w in ws[:12]]}")

# hypothesis: xor with a per-position value. Collect deltas assuming plain ASCII/kana
# check the classic Siglus scheme: c ^= ((i*0x7087) + 0x??) style -> test constant xor first
o, l = ents[0]
ws = struct.unpack_from("<%dH" % l, ss, DAT + o * 2)
for cand in range(0, 0x10000, 1):
    dec = [w ^ cand for w in ws]
    if all(0x20 <= d <= 0x7E or 0x3000 <= d <= 0x30FF or 0x4E00 <= d <= 0x9FFF for d in dec):
        print("constant xor 0x%04X works for str0:" % cand, "".join(chr(d) for d in dec)[:40])
        break
else:
    print("no single constant xor for str0")

# try position-dependent: key(i) = ws[i] ^ expected ; look at differences between strings
print("\nword[0] of first 20 strings:", [hex(struct.unpack_from('<H', ss, DAT + ents[i][0]*2)[0]) for i in range(20)])
