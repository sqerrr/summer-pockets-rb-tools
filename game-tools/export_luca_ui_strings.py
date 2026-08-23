"""Export candidate non-gameplay UI strings from the active LUCA executable."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pefile


ROOT = Path(__file__).resolve().parents[1]
EXE_PATH = ROOT / "Summer Pockets REFLECTION BLUE_Steam/SummerPocketsRB.exe"
OUTPUT_PATH = ROOT / "build/steam/ui-exe-strings.jsonl"
DEFAULT_START = 0x6E0000
DEFAULT_END = 0x700000


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def iter_cstrings(data: bytes, start: int, end: int):
    previous_nul = data.rfind(b"\0", 0, start)
    offset = start if previous_nul < 0 else previous_nul + 1
    while offset < end:
        terminator = data.find(b"\0", offset, end)
        if terminator < 0:
            break
        raw = data[offset:terminator]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if (
            offset >= start
            and len(raw) >= 2
            and text
            and any(character.isalnum() for character in text)
            and all(character.isprintable() or character in "\r\n\t" for character in text)
        ):
            yield offset, raw
        offset = terminator + 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=EXE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--start", type=lambda value: int(value, 0), default=DEFAULT_START)
    parser.add_argument("--end", type=lambda value: int(value, 0), default=DEFAULT_END)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exe_path = args.exe if args.exe.is_absolute() else ROOT / args.exe
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    data = exe_path.read_bytes()
    if not 0 <= args.start < args.end <= len(data):
        raise SystemExit("invalid executable scan range")

    pe = pefile.PE(str(exe_path), fast_load=True)
    image_base = pe.OPTIONAL_HEADER.ImageBase
    rows = []
    for offset, raw in iter_cstrings(data, args.start, args.end):
        rva = pe.get_rva_from_offset(offset)
        rows.append({
            "file_offset": offset,
            "file_offset_hex": f"0x{offset:X}",
            "rva": rva,
            "rva_hex": f"0x{rva:X}",
            "virtual_address_hex": f"0x{image_base + rva:X}",
            "byte_length": len(raw),
            "slot_size": len(raw) + 1,
            "text_en": raw.decode("utf-8"),
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps({
        "exe": str(exe_path),
        "exe_sha256": "sha256:" + digest_file(exe_path),
        "start": f"0x{args.start:X}",
        "end": f"0x{args.end:X}",
        "string_count": len(rows),
        "output": str(output_path),
    }, indent=2))


if __name__ == "__main__":
    main()
