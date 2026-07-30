"""Look for CJK text outside Scene.pck: dat/*.dbs, Gameexe.dat, the engine.

Tries the encodings a Siglus build can realistically use (UTF-16LE, Shift-JIS,
GBK, Big5) and reports which writing systems each file actually contains.

Usage:
    python legacy-siglus/probes/scan_binary_scripts.py [file ...]
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402

SIMPLIFIED_ONLY = set("们这说个儿从头关图边还进语论让时东车门问汉华应级练")
KANA = re.compile(r"[\u3041-\u309f\u30a0-\u30ff]")
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
CYR = re.compile(r"[\u0400-\u04ff]")
HANGUL = re.compile(r"[\uac00-\ud7af]")


def strings_utf16(data, minlen=2):
    out = []
    cur = []
    for i in range(0, len(data) - 1, 2):
        u = data[i] | (data[i + 1] << 8)
        ch = chr(u)
        if u == 0 or (u < 0x20 and u not in (9, 10, 13)) or 0xD800 <= u <= 0xDFFF:
            if len(cur) >= minlen:
                out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if len(cur) >= minlen:
        out.append("".join(cur))
    return out


def strings_mbcs(data, encoding, minlen=2):
    out = []
    for chunk in re.split(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]{1,}", data):
        if len(chunk) < minlen:
            continue
        try:
            s = chunk.decode(encoding)
        except UnicodeDecodeError:
            s = chunk.decode(encoding, errors="ignore")
        if len(s) >= minlen:
            out.append(s)
    return out


def summarize(label, texts):
    kana = han = cyr = hangul = 0
    simpl = Counter()
    han_chars = Counter()
    samples = []
    for s in texts:
        k = len(KANA.findall(s))
        h = len(HAN.findall(s))
        kana += k
        han += h
        cyr += len(CYR.findall(s))
        hangul += len(HANGUL.findall(s))
        if h:
            han_chars.update(HAN.findall(s))
            simpl.update(c for c in s if c in SIMPLIFIED_ONLY)
            if len(samples) < 6 and (k or h) and len(s) > 3:
                samples.append(s.strip())
    print(f"  {label:10s} kana={kana:6d} han={han:6d} cyr={cyr:5d} "
          f"hangul={hangul:4d} simplified_markers={sum(simpl.values())}")
    if simpl:
        print(f"    simplified: {dict(simpl)}")
    if han_chars:
        print("    top han: " + " ".join(
            f"{c}:{n}" for c, n in han_chars.most_common(15)))
    for s in samples:
        print(f"    sample: {s[:70]!r}")


def scan(path):
    data = path.read_bytes()
    print(f"\n{path.name}  ({len(data)} bytes)")
    summarize("utf-16le", strings_utf16(data))
    for enc in ("cp932", "gbk", "big5"):
        summarize(enc, strings_mbcs(data, enc))


def main():
    if len(sys.argv) > 1:
        targets = [Path(a) for a in sys.argv[1:]]
    else:
        targets = sorted(paths.DAT_DIR.glob("*.dbs"))
        targets += [paths.DAT_DIR / "mode.cgm", paths.DAT_DIR / "tcdata.tcr"]
        targets += [paths.GAME_DIR / "Gameexe.dat"]
    for t in targets:
        if t.exists():
            scan(t)
        else:
            print(f"\n{t}: missing")


if __name__ == "__main__":
    main()
