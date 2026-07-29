import pefile, capstone, struct

EXE = r"A:\Projects\Summer Pockets REFLECTION BLUE\SiglusEngine.exe"
pe = pefile.PE(EXE, fast_load=True)
pe.parse_data_directories()
base = pe.OPTIONAL_HEADER.ImageBase
data = open(EXE, "rb").read()

iat = {}
for entry in pe.DIRECTORY_ENTRY_IMPORT:
    for imp in entry.imports:
        if imp.name:
            iat[imp.address] = imp.name.decode()

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

for va, before, after in ((0x62ABF1, 0x30, 0xC0), (0x65DD63, 0x30, 0xC0)):
    start = va - before
    foff = pe.get_offset_from_rva(start - base)
    print("\n===== around VA 0x%X =====" % va)
    for ins in md.disasm(data[foff:foff + before + after], start):
        note = ""
        if ins.mnemonic == "call" and "dword ptr [0x" in ins.op_str:
            try:
                tgt = int(ins.op_str.split("[")[1].rstrip("]"), 16)
                if tgt in iat:
                    note = "   <-- " + iat[tgt]
            except Exception:
                pass
        print("  0x%08X  %-9s %s%s" % (ins.address, ins.mnemonic, ins.op_str, note))
