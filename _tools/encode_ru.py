"""Cyrillic <-> carrier codepoints, mirrors EncodeRussian in uSiglus.pas."""

BASE, YO_U, LOW, YO_L = 0x100, 0x120, 0x121, 0x141


def encode(s: str) -> str:
    out = []
    for ch in s:
        c = ord(ch)
        if 0x410 <= c <= 0x42F:
            out.append(chr(BASE + c - 0x410))
        elif c == 0x401:
            out.append(chr(YO_U))
        elif 0x430 <= c <= 0x44F:
            out.append(chr(LOW + c - 0x430))
        elif c == 0x451:
            out.append(chr(YO_L))
        else:
            out.append(ch)
    return "".join(out)


def decode(s: str) -> str:
    out = []
    for ch in s:
        c = ord(ch)
        if BASE <= c <= BASE + 31:
            out.append(chr(0x410 + c - BASE))
        elif c == YO_U:
            out.append(chr(0x401))
        elif LOW <= c <= LOW + 31:
            out.append(chr(0x430 + c - LOW))
        elif c == YO_L:
            out.append(chr(0x451))
        else:
            out.append(ch)
    return "".join(out)


if __name__ == "__main__":
    import sys
    from PIL import Image, ImageDraw, ImageFont

    text = "Вдали начали проступать очертания острова."
    enc = encode(text)
    assert decode(enc) == text, "round trip failed"
    print("plain  :", text)
    print("carrier:", " ".join("%04X" % ord(c) for c in enc[:12]), "...")
    print("round trip ok")

    fp = r"A:\Projects\Summer Pockets REFLECTION BLUE\dat\font01.ttf"
    fnt = ImageFont.truetype(fp, 44)
    im = Image.new("RGB", (1180, 150), (18, 60, 100))
    d = ImageDraw.Draw(im)
    d.text((14, 12), text, font=fnt, fill=(255, 255, 255))
    d.text((14, 78), enc, font=fnt, fill=(180, 255, 180))
    im.save(r"A:\Projects\_tools\shots\carrier_check.png")
    print("rendered: top = real cyrillic, bottom = carriers")
