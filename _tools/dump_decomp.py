import pefile, capstone

EXE = r"A:\Projects\Summer Pockets REFLECTION BLUE\SiglusEngine.exe"
pe = pefile.PE(EXE, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
data = open(EXE, "rb").read()

key = data[0x6D9DB0:0x6D9DB0 + 256]
print("KEY (256 bytes):")
print(key.hex())

VA = 0x71CE90
foff = pe.get_offset_from_rva(VA - base)
print("\n=== decompress func VA 0x%X foff 0x%X ===" % (VA, foff))
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
code = data[foff:foff + 0x300]
rets = 0
for ins in md.disasm(code, VA):
    print("  0x%08X  %-8s %s" % (ins.address, ins.mnemonic, ins.op_str))
    if ins.mnemonic == "ret":
        rets += 1
        if rets >= 3:
            break
