import pefile, struct, capstone, re

EXE = r"A:\Projects\Summer Pockets REFLECTION BLUE\SiglusEngine.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
data = open(EXE, "rb").read()

KEY_FOFF = 0x6D9DB0
key_rva = None
for s in pe.sections:
    if s.PointerToRawData <= KEY_FOFF < s.PointerToRawData + s.SizeOfRawData:
        key_rva = s.VirtualAddress + (KEY_FOFF - s.PointerToRawData)
        print("key section:", s.Name.rstrip(b"\0").decode(), "rva=0x%X va=0x%X" % (key_rva, base + key_rva))
key_va = base + key_rva

# find references to key VA inside code sections
text = [s for s in pe.sections if s.Characteristics & 0x20000000]
pat = struct.pack("<I", key_va)
refs = []
for s in text:
    raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
    for m in re.finditer(re.escape(pat), raw):
        foff = s.PointerToRawData + m.start()
        va = base + s.VirtualAddress + m.start()
        refs.append((foff, va, s.Name.rstrip(b"\0").decode()))
print("refs to key VA:", [(hex(a), hex(b), c) for a, b, c in refs])

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = False


def sec_of(foff):
    for s in pe.sections:
        if s.PointerToRawData <= foff < s.PointerToRawData + s.SizeOfRawData:
            return s
    return None


for foff, va, nm in refs:
    start = foff - 0x60
    s = sec_of(foff)
    code = data[start:start + 0x180]
    addr = base + s.VirtualAddress + (start - s.PointerToRawData)
    print("\n===== around ref @0x%X (VA 0x%X) =====" % (foff, va))
    for ins in md.disasm(code, addr):
        print("  0x%08X  %-8s %s" % (ins.address, ins.mnemonic, ins.op_str))
