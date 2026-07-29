tests = [("q", 0x71), ("a-grave", 0xE0), ("A-macron", 0x100), ("b-bar", 0x180),
         ("alpha", 0x3B1), ("A-cyr", 0x410), ("hiragana", 0x3042)]

print("%-10s %-9s %-14s %-10s" % ("char", "code", "shift-jis", "predicted"))
for name, cp in tests:
    try:
        b = chr(cp).encode("cp932")
        n, s = len(b), b.hex(" ")
    except UnicodeEncodeError:
        n, s = 0, "not encodable"
    print("%-10s U+%04X    %-14s %-10s" % (name, cp, s, "full" if n == 2 else "half"))


def sjis_len(cp):
    try:
        return len(chr(cp).encode("cp932"))
    except UnicodeEncodeError:
        return 0


ext_a = [cp for cp in range(0x100, 0x180) if sjis_len(cp) == 2]
print("\nLatin Extended-A codepoints present in Shift-JIS:", len(ext_a), "of 128")
lat1 = [cp for cp in range(0xA0, 0x100) if sjis_len(cp) == 2]
print("Latin-1 Supplement codepoints present in Shift-JIS:", len(lat1), "of 96")
print("  ->", " ".join(chr(c) for c in lat1))
