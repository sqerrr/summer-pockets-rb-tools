import pefile, capstone, re, struct, collections

EXE = r"A:\Projects\Summer Pockets REFLECTION BLUE\SiglusEngine.exe"
pe = pefile.PE(EXE, fast_load=True)
pe.parse_data_directories()
base = pe.OPTIONAL_HEADER.ImageBase
data = open(EXE, "rb").read()

iat = {}
for e in pe.DIRECTORY_ENTRY_IMPORT:
    for i in e.imports:
        if i.name:
            iat[i.address] = i.name.decode()

gdi = {a: n for a, n in iat.items() if n in (
    "GetGlyphOutlineW", "GetTextExtentPoint32W", "GetCharWidth32W",
    "GetCharABCWidthsW", "CreateFontIndirectW", "GetOutlineTextMetricsW",
    "GetTextMetricsW", "GetCharABCWidthsFloatW")}
print("font/text APIs imported:", sorted(set(gdi.values())))

text_secs = [s for s in pe.sections if s.Characteristics & 0x20000000]
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

# call sites of those APIs
print("\n--- call sites ---")
sites = collections.defaultdict(list)
for s in text_secs:
    raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
    for a, n in gdi.items():
        for m in re.finditer(re.escape(b"\xff\x15" + struct.pack("<I", a)), raw):
            va = base + s.VirtualAddress + m.start()
            sites[n].append(va)
for n in sorted(sites):
    print(f"  {n}: {[hex(v) for v in sites[n]]}")

# signature of a half/full width classifier: halfwidth katakana range constants
print("\n--- half/full width range constants in code ---")
for const in (0xFF61, 0xFF9F, 0xFF00, 0x3000, 0x2E80):
    pat = struct.pack("<I", const)
    hits = []
    for s in text_secs:
        raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        for m in re.finditer(re.escape(pat), raw):
            hits.append(base + s.VirtualAddress + m.start())
    if hits:
        print(f"  0x{const:04X}: {[hex(v) for v in hits[:12]]}")
