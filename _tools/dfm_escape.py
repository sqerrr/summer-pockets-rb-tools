"""Converts a UTF-8 .dfm to the ASCII form Delphi expects:
non-ASCII characters inside string literals become #NNNN escapes."""
import re, sys, io

path = sys.argv[1]
src = io.open(path, encoding="utf-8").read()


def conv_literal(text):
    """text = raw contents between the outer quotes"""
    parts = []
    buf = []
    for ch in text:
        if ord(ch) < 128:
            buf.append(ch)
        else:
            if buf:
                parts.append("'" + "".join(buf) + "'")
                buf = []
            parts.append("#%d" % ord(ch))
    if buf:
        parts.append("'" + "".join(buf) + "'")
    return "".join(parts) if parts else "''"


def repl(m):
    inner = m.group(1)
    if all(ord(c) < 128 for c in inner):
        return m.group(0)
    return conv_literal(inner)


# match single-quoted literals (doubled '' = escaped quote inside)
out = re.sub(r"'((?:[^']|'')*)'", repl, src)

if any(ord(c) > 127 for c in out):
    bad = {c for c in out if ord(c) > 127}
    print("WARNING: non-ASCII left outside literals:", bad)

io.open(path, "w", encoding="ascii", newline="\r\n").write(out)
print("ok:", path, len(out), "bytes")
