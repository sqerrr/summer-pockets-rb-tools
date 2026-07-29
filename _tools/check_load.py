import pefile, capstone, re, struct

EXE = r"A:\Projects\Summer Pockets REFLECTION BLUE\SiglusEngine.exe"
pe = pefile.PE(EXE, fast_load=True)
pe.parse_data_directories()
base = pe.OPTIONAL_HEADER.ImageBase
data = open(EXE, "rb").read()

# imports of interest
want = {b"CreateFileW", b"ReadFile", b"SetFilePointer", b"SetFilePointerEx",
        b"CreateFileMappingW", b"MapViewOfFile", b"GetFileSize", b"GetFileSizeEx"}
iat = {}
for entry in pe.DIRECTORY_ENTRY_IMPORT:
    for imp in entry.imports:
        if imp.name in want:
            iat[imp.address] = imp.name.decode()
print("imports found:", sorted(set(iat.values())))

# locate wide string "Scene.pck"
needle = "Scene.pck".encode("utf-16le")
hits = [m.start() for m in re.finditer(re.escape(needle), data)]
print("\n'Scene.pck' (utf-16) at file offsets:", [hex(h) for h in hits])

for h in hits:
    sec = next(s for s in pe.sections
               if s.PointerToRawData <= h < s.PointerToRawData + s.SizeOfRawData)
    va = base + sec.VirtualAddress + (h - sec.PointerToRawData)
    print("  VA 0x%X in %s" % (va, sec.Name.rstrip(b'\0').decode()))
    pat = struct.pack("<I", va)
    for s in pe.sections:
        if not (s.Characteristics & 0x20000000):
            continue
        raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        for m in re.finditer(re.escape(pat), raw):
            cva = base + s.VirtualAddress + m.start()
            print("    referenced from code VA 0x%X" % cva)

# how big is the buffer read? look for the reader that uses GetFileSize + ReadFile
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
print("\n--- scanning for ReadFile call sites ---")
rf = [a for a, n in iat.items() if n == "ReadFile"]
mv = [a for a, n in iat.items() if n in ("MapViewOfFile", "CreateFileMappingW")]
for s in pe.sections:
    if not (s.Characteristics & 0x20000000):
        continue
    raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
    for tgt, label in [(rf, "ReadFile"), (mv, "FileMapping")]:
        for a in tgt:
            pat = b"\xff\x15" + struct.pack("<I", a)
            n = len(re.findall(re.escape(pat), raw))
            if n:
                print(f"  call [{label}] indirect call sites: {n}")
