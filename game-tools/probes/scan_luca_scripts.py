"""Report multilingual text coverage in a LUCA System SCRIPT.PAK.

The probe reads the PAK index and compiled opcode records directly. It prints
counts only and does not expose scenario lines.

Usage:
    python game-tools/probes/scan_luca_scripts.py
    python game-tools/probes/scan_luca_scripts.py path/to/SCRIPT.PAK
"""

import argparse
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from luca import Pak, classify_source_record, iter_script_records  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAK = ROOT / "Summer Pockets REFLECTION BLUE_Steam" / "files" / "SCRIPT.PAK.orig"
SIMPLIFIED_ONLY = set("们这说个儿从头关图边还进语论让时东车门问汉华应级练")


def script_of(ch):
    code = ord(ch)
    if 0x3040 <= code <= 0x30FF:
        return "kana"
    if 0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF:
        return "han"
    if ch.isascii() and ch.isalpha():
        return "latin"
    return None


def text_groups(record, language_count=3):
    """Return known multilingual string groups from a bytecode record."""
    classified = classify_source_record(record)
    if classified.classification == "translatable":
        return (tuple(value.text for value in classified.strings),)
    if classified.classification == "unknown_candidate":
        raise ValueError(classified.error)
    return ()


def classify_slot(text, counter):
    for ch in text:
        kind = script_of(ch)
        if kind:
            counter[kind] += 1
        if ch in SIMPLIFIED_ONLY:
            counter["simplified_marker"] += 1
        if ch == "\u3001":
            counter["ja_comma"] += 1
        elif ch == "\uff0c":
            counter["zh_comma"] += 1


def infer_languages(slot_stats):
    remaining = set(range(len(slot_stats)))
    result = {}
    scorers = (
        ("ja", lambda c: c["kana"]),
        ("zh-CN", lambda c: c["simplified_marker"] + c["zh_comma"]),
        ("en", lambda c: c["latin"]),
    )
    for language, score in scorers:
        slot = max(remaining, key=lambda i: score(slot_stats[i]))
        result[slot] = language
        remaining.remove(slot)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pak", nargs="?", type=Path, default=DEFAULT_PAK)
    args = parser.parse_args()

    pak = Pak(args.pak)
    opcode_counts = Counter()
    slot_stats = [Counter() for _ in range(3)]
    slot_nonempty = Counter()
    coverage = Counter()
    scripts_ok = 0
    scripts_ending_in_25 = 0
    record_count = 0
    text_group_count = 0
    decode_errors = Counter()
    service_nontext = 0

    metadata_index = next(
        (entry.index for entry in pak.entries if entry.name == "_build_time"),
        pak.entry_count,
    )
    script_entries = list(pak.entries[:metadata_index])
    for entry in script_entries:
        try:
            records = list(iter_script_records(pak.read_entry(entry)))
        except (UnicodeDecodeError, ValueError) as exc:
            decode_errors[type(exc).__name__] += 1
            continue
        scripts_ok += 1
        if records and records[-1].opcode == 25:
            scripts_ending_in_25 += 1
        record_count += len(records)
        opcode_counts.update(record.opcode for record in records)
        for record in records:
            classified = classify_source_record(record)
            if classified.classification == "service_nontext":
                service_nontext += 1
            try:
                groups = text_groups(record)
            except (UnicodeDecodeError, ValueError):
                decode_errors[f"text:opcode-{record.opcode}"] += 1
                continue
            for strings in groups:
                text_group_count += 1
                mask = tuple(bool(text) for text in strings)
                coverage[mask] += 1
                for slot, text in enumerate(strings):
                    if text:
                        slot_nonempty[slot] += 1
                    slot_stats[slot]["characters"] += len(text)
                    classify_slot(text, slot_stats[slot])

    inferred = infer_languages(slot_stats)
    print(f"pak: {args.pak}")
    print(f"entries: {pak.entry_count}")
    print(f"script entries: {len(script_entries)}")
    print(f"scripts parsed: {scripts_ok}/{len(script_entries)}")
    print(f"scripts ending in opcode 25: {scripts_ending_in_25}/{scripts_ok}")
    print(f"opcode records: {record_count}")
    print(f"multilingual text groups: {text_group_count}")
    print(f"service/non-text candidates: {service_nontext}")
    print("\ntext slots:")
    for slot, stats in enumerate(slot_stats):
        language = inferred.get(slot, "?")
        print(
            f"  slot {slot} -> {language:5s}: nonempty={slot_nonempty[slot]:6d} "
            f"chars={stats['characters']:8d} kana={stats['kana']:7d} "
            f"han={stats['han']:7d} latin={stats['latin']:8d} "
            f"simplified={stats['simplified_marker']:6d} "
            f"U+3001={stats['ja_comma']:6d} U+FF0C={stats['zh_comma']:6d}"
        )

    print("\ncoverage masks (slot0, slot1, slot2):")
    for mask, count in coverage.most_common():
        print(f"  {mask}: {count}")

    print("\ntext opcodes:")
    print(f"  opcode 36        {opcode_counts[36]:8d}")
    print(f"  opcode 40        {opcode_counts[40]:8d}")
    if decode_errors:
        print("\ndecode errors:")
        for kind, count in decode_errors.most_common():
            print(f"  {kind:20s} {count}")


if __name__ == "__main__":
    main()
