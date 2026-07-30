"""Classify the writing system of every string in Scene.pck.orig.

Answers a technical question: which languages actually ship inside the scene
pack, and where they live. Caches the decoded strings so the LZSS pass runs
once.

Usage:
    python game-tools/probes/scan_scripts.py            # scan + report
    python game-tools/probes/scan_scripts.py --samples  # add example lines
"""
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paths  # noqa: E402

paths.ensure_importable()
import siglus  # noqa: E402

CACHE = paths.ROOT / "reports" / "tmp" / "scene_strings.jsonl"

# Simplified forms that no Japanese shinjitai uses; a hit means Chinese.
SIMPLIFIED_ONLY = set("们这说个儿从头关图边还进语论让时东车门问长汉华应级练纟")
# Traditional forms Japanese replaced with shinjitai; a hit means Chinese too.
TRADITIONAL_ONLY = set("們這說個兒從關圖邊還進語論讓東車門問長漢華應麼沒學實變體")


def load_strings():
    if CACHE.exists():
        with open(CACHE, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                yield rec["scene"], rec["name"], rec["strings"]
        return
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pck = siglus.ScenePack(paths.SCENE_PCK_ORIG)
    with open(CACHE, "w", encoding="utf-8") as fh:
        for i in range(pck.count):
            strings = siglus.Scene(pck.scene(i)).strings()
            fh.write(json.dumps(
                {"scene": i, "name": pck.names[i], "strings": strings},
                ensure_ascii=False) + "\n")
            yield i, pck.names[i], strings


def script_of(ch):
    o = ord(ch)
    if 0x3041 <= o <= 0x309F:
        return "hiragana"
    if 0x30A0 <= o <= 0x30FF:
        return "katakana"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
        return "han"
    if 0x0400 <= o <= 0x04FF:
        return "cyrillic"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
        return "hangul"
    if ch.isascii() and ch.isalpha():
        return "latin"
    if 0xFF21 <= o <= 0xFF5A or 0xFF10 <= o <= 0xFF19:
        return "fullwidth_alnum"
    return None


def classify(s):
    kinds = Counter(k for k in map(script_of, s) if k)
    kana = kinds["hiragana"] + kinds["katakana"]
    if kana:
        return "japanese", kinds
    if kinds["han"]:
        return "han_only", kinds
    if kinds["hangul"]:
        return "korean", kinds
    if kinds["latin"]:
        return "latin", kinds
    if kinds["cyrillic"]:
        return "cyrillic", kinds
    return "other", kinds


def main():
    want_samples = "--samples" in sys.argv
    totals = Counter()
    per_scene = {}
    han_only_chars = Counter()
    kana_line_chars = Counter()
    comma_ja = comma_zh = 0
    samples = {"han_only": [], "japanese": [], "korean": []}
    scenes = 0

    for idx, name, strings in load_strings():
        scenes += 1
        local = Counter()
        for s in strings:
            kind, kinds = classify(s)
            totals[kind] += 1
            local[kind] += 1
            comma_ja += s.count("\u3001")
            comma_zh += s.count("\uff0c")
            if kind == "han_only":
                han_only_chars.update(c for c in s if script_of(c) == "han")
                if want_samples and len(samples["han_only"]) < 40 and len(s) > 3:
                    samples["han_only"].append((name, s))
            elif kind == "japanese":
                kana_line_chars.update(c for c in s if script_of(c) == "han")
                if want_samples and len(samples["japanese"]) < 15 and len(s) > 6:
                    samples["japanese"].append((name, s))
            elif kind == "korean" and want_samples and len(samples["korean"]) < 10:
                samples["korean"].append((name, s))
        per_scene[name] = local

    print(f"scenes: {scenes}")
    print(f"strings: {sum(totals.values())}")
    for kind, n in totals.most_common():
        print(f"  {kind:16s} {n:8d}")

    print(f"\nideographic comma U+3001 (ja): {comma_ja}")
    print(f"fullwidth comma   U+FF0C (zh): {comma_zh}")

    zh_simpl = {c: n for c, n in han_only_chars.items() if c in SIMPLIFIED_ONLY}
    zh_trad = {c: n for c, n in han_only_chars.items() if c in TRADITIONAL_ONLY}
    print(f"\nhan-only distinct chars: {len(han_only_chars)}")
    print(f"  simplified-only markers: {sum(zh_simpl.values())} {zh_simpl}")
    print(f"  traditional-only markers: {sum(zh_trad.values())} {zh_trad}")
    exclusive = set(han_only_chars) - set(kana_line_chars)
    print(f"  chars never seen in kana lines: {len(exclusive)}")
    print("  top han-only chars: " + " ".join(
        f"{c}:{n}" for c, n in han_only_chars.most_common(30)))

    top = sorted(per_scene.items(),
                 key=lambda kv: kv[1]["japanese"] + kv[1]["han_only"],
                 reverse=True)[:15]
    print("\nscenes with most CJK strings:")
    for name, c in top:
        print(f"  {name:32s} ja={c['japanese']:5d} han={c['han_only']:5d} "
              f"latin={c['latin']:5d}")

    if want_samples:
        for key, rows in samples.items():
            if not rows:
                continue
            print(f"\n--- {key} samples ---")
            for name, s in rows:
                print(f"  [{name}] {s[:90]!r}")


if __name__ == "__main__":
    main()
