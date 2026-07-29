import sys, re

pat = bytes.fromhex("70f8a6b0")
for p in [r"A:\Projects\Summer Pockets REFLECTION BLUE\SiglusEngine.exe",
          r"A:\Projects\Summer Pockets REFLECTION BLUE\SiglusEngine.exe.org"]:
    data = open(p, "rb").read()
    print("==", p, len(data))
    for m in re.finditer(re.escape(pat), data):
        o = m.start()
        print(f"  @0x{o:X}: {data[o:o+32].hex(' ')}")
