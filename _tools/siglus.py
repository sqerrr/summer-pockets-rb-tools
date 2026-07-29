"""Siglus Scene.pck reader: header parse + XOR decrypt + LZSS decompress."""
import struct

KEY = bytes.fromhex(
    "70f8a6b0a1a5284fb52f48fae1e94bdeb74f62958be00380e7cf0f6b9201ebf8"
    "a288ce630438d26d8cd28876a792718f4eb68d017988830af9e92cdb67db9114"
    "d59a4e79172308960e1d15f9a5a06f5817c8a946da22fffd871242fba9b8676c"
    "916764f9d11ee450646ff20bde40e747f103cc2aad7f3421a06426986ced69f4"
    "b523086e7d92f6eb93f07a895ef9f87aafe8a948c2ac116b2b33a7400ddc7da7"
    "5bcfc831d177528d82ac41b873a54f267c0f39da5b374adea4490b7c17a343ae"
    "77066473c043a3185a0f9f024c7e8b019f2dae725413ff96ae0b3458cfe30078"
    "bee3f561e4877cfc80afc48d463a5dd036bce5607768084fbbabe27807e873bf")


def decrypt(data: bytes) -> bytearray:
    out = bytearray(data)
    n = len(KEY)
    for i in range(len(out)):
        out[i] ^= KEY[i % n]
    return out


def decompress(src: bytes) -> bytearray:
    """Matches SiglusEngine.exe sub_71CE90: byte flag, LSB first;
    bit=1 -> literal, bit=0 -> word: off = w>>4, count = (w & 0xF) + 2,
    copied byte-by-byte from dst[dp-off] (overlapping allowed)."""
    comp_size, raw_size = struct.unpack_from("<II", src, 0)
    dst = bytearray(raw_size)
    sp, dp = 8, 0
    while dp < raw_size:
        flag = src[sp]; sp += 1
        for _ in range(8):
            if dp >= raw_size:
                break
            if flag & 1:
                dst[dp] = src[sp]; sp += 1; dp += 1
            else:
                w = src[sp] | (src[sp + 1] << 8); sp += 2
                off = w >> 4
                for _ in range((w & 0xF) + 2):
                    dst[dp] = dst[dp - off]; dp += 1
            flag >>= 1
    return dst


class ScenePack:
    def __init__(self, path):
        self.buf = open(path, "rb").read()
        h = struct.unpack_from("<23I", self.buf, 0)
        self.hdr = h
        self.pairs = [(h[1 + 2 * i], h[2 + 2 * i]) for i in range(10)]
        idx_off, cnt = self.pairs[6]
        self.count = cnt
        self.names = self._names(idx_off, idx_off + cnt * 8, cnt)
        self.data_idx = self.pairs[8][0]
        self.data_off = self.pairs[9][0]

    def _names(self, idx_off, data_off, cnt):
        out = []
        for i in range(cnt):
            o, l = struct.unpack_from("<II", self.buf, idx_off + i * 8)
            out.append(self.buf[data_off + o * 2: data_off + (o + l) * 2].decode("utf-16le"))
        return out

    def raw(self, i):
        o, s = struct.unpack_from("<II", self.buf, self.data_idx + i * 8)
        return self.buf[self.data_off + o: self.data_off + o + s]

    def scene(self, i):
        return bytes(decompress(decrypt(self.raw(i))))


STR_KEY_MUL = 0x7087


def decode_str(raw: bytes, index: int) -> str:
    """Each UTF-16 unit is XORed with (index * 0x7087) & 0xFFFF."""
    k = (index * STR_KEY_MUL) & 0xFFFF
    n = len(raw) // 2
    ws = struct.unpack("<%dH" % n, raw)
    return "".join(chr(w ^ k) for w in ws)


def encode_str(s: str, index: int) -> bytes:
    k = (index * STR_KEY_MUL) & 0xFFFF
    return struct.pack("<%dH" % len(s), *[ord(c) ^ k for c in s])


class Scene:
    """Parsed decompressed scene: header of 33 dwords = size + 16 (offset,count)."""

    def __init__(self, data: bytes):
        self.data = data
        self.hdr_size = struct.unpack_from("<I", data, 0)[0]
        n = self.hdr_size // 4
        self.dw = struct.unpack_from("<%dI" % n, data, 0)
        self.code_off, self.code_len = self.dw[1], self.dw[2]
        self.str_idx_off, self.str_count = self.dw[3], self.dw[4]
        self.str_data_off = self.dw[5]

    def strings(self):
        out = []
        for i in range(self.str_count):
            o, l = struct.unpack_from("<II", self.data, self.str_idx_off + i * 8)
            raw = self.data[self.str_data_off + o * 2: self.str_data_off + (o + l) * 2]
            out.append(decode_str(raw, i))
        return out


if __name__ == "__main__":
    import sys
    pck = ScenePack(r"A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck")
    print("scenes:", pck.count)
    i = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    raw = decrypt(pck.raw(i))
    print(f"scene {i}: {pck.names[i]!r}")
    print("  comp/raw sizes:", struct.unpack_from("<II", raw, 0))
    ss = decompress(raw)
    print("  decompressed:", len(ss))
    print("  first 0x90 bytes:")
    for r in range(0, 0x90, 16):
        print("   %04X  %s" % (r, ss[r:r + 16].hex(" ")))
    n = struct.unpack_from("<I", ss, 0)[0]
    dw = struct.unpack_from("<%dI" % (n // 4), ss, 0)
    print("  header dwords (%d):" % (n // 4))
    for j in range(1, n // 4, 2):
        if j + 1 < n // 4:
            print(f"    [{j:2d}] off=0x{dw[j]:<8X} cnt={dw[j+1]}")
