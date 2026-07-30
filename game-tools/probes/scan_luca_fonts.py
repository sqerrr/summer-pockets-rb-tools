"""Report Unicode coverage in the Steam/LUCA font mapping archives."""

import argparse
from collections import Counter
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from luca import Pak  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAME = ROOT / "Summer Pockets REFLECTION BLUE_Steam"
CODEPOINTS = (0x0020, 0x00AB, 0x00BB, 0x0410, 0x044F, 0x2014, 0x2026, 0x275D, 0x275E, 0x300A, 0x300B)


def mapping(data):
    if len(data) < 8:
        raise ValueError("font INFO member is truncated")
    glyph_count = struct.unpack_from("<H", data, 6)[0]
    offset = 8 + glyph_count * 3
    if offset + 65536 * 2 > len(data):
        raise ValueError("font INFO member has no Unicode mapping table")
    return glyph_count, offset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", type=Path, default=DEFAULT_GAME)
    args = parser.parse_args()

    archives = (
        args.game / "files" / "font_win32_1920" / "FONT__INFO.PAK",
        args.game / "files" / "font_win32_1920" / "FONT_PATCH__INFO.PAK",
        args.game / "files" / "fontzc_win32_1920" / "FONTZC__INFO.PAK",
        args.game / "files" / "fontzc_win32_1920" / "FONTZC2__INFO.PAK",
    )
    coverage = Counter()
    archive_coverage = {}
    archive_members = {}
    member_count = 0
    representative = None
    for path in archives:
        pak = Pak(path)
        current_coverage = Counter()
        archive_members[path.name] = len(pak.entries)
        for entry in pak.entries:
            data = pak.read_entry(entry)
            glyph_count, offset = mapping(data)
            member_count += 1
            values = {
                codepoint: struct.unpack_from("<H", data, offset + codepoint * 2)[0]
                for codepoint in CODEPOINTS
            }
            for codepoint, glyph in values.items():
                if glyph:
                    coverage[codepoint] += 1
                    current_coverage[codepoint] += 1
            if path.name == "FONT__INFO.PAK" and entry.name == "info40":
                russian = list(range(0x0410, 0x0450)) + [0x0401, 0x0451]
                russian_mapped = sum(
                    struct.unpack_from("<H", data, offset + codepoint * 2)[0] != 0
                    for codepoint in russian
                )
                representative = glyph_count, values, russian_mapped, len(russian)
        archive_coverage[path.name] = current_coverage

    print(f"archives: {len(archives)}")
    print(f"INFO members: {member_count}")
    for codepoint in CODEPOINTS:
        print(f"U+{codepoint:04X}: mapped={coverage[codepoint]}/{member_count}")
    print("per archive:")
    for path in archives:
        counts = archive_coverage[path.name]
        total = archive_members[path.name]
        summary = " ".join(
            f"U+{codepoint:04X}={counts[codepoint]}/{total}"
            for codepoint in (0x00AB, 0x00BB, 0x2014, 0x2026, 0x275D, 0x275E)
        )
        print(f"  {path.name}: {summary}")
    if representative is not None:
        glyph_count, values, russian_mapped, russian_count = representative
        print(f"info40 glyphs: {glyph_count}")
        for codepoint in CODEPOINTS:
            print(f"info40 U+{codepoint:04X}: glyph={values[codepoint]}")
        print(f"info40 Russian letters: mapped={russian_mapped}/{russian_count}")


if __name__ == "__main__":
    main()
