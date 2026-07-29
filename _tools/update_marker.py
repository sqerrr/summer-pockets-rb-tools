import io, re, sys

marker = io.open(r"A:\Projects\_tools\marker.txt", encoding="utf-8").read()
path = r"A:\Projects\_tools\MakeTestPck.dpr"
src = io.open(path, encoding="utf-8-sig").read()

esc = marker.replace("'", "''")
new = re.sub(r"MARKER = '.*?';", "MARKER = '%s';" % esc, src, count=1, flags=re.S)
if new == src:
    sys.exit("MARKER не найден в .dpr")
io.open(path, "w", encoding="utf-8-sig", newline="\r\n").write(new)
print("MARKER =", esc)
