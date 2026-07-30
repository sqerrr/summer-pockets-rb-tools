"""Stress-test LUCA script relocation without exposing scenario text."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from luca import (  # noqa: E402
    Pak,
    classify_source_record,
    encode_luca_string,
    iter_script_records,
    relocate_script_records,
    validate_script_references,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = (
    ROOT / "Summer Pockets REFLECTION BLUE_Steam" / "files" / "SCRIPT.PAK.orig"
)
DEFAULT_OUTPUT = ROOT / "build" / "steam" / "SCRIPT.relocation-stress.PAK"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = Pak(args.source)
    before = validate_script_references(source)
    metadata_index = next(
        (entry.index for entry in source.entries if entry.name == "_build_time"),
        source.entry_count,
    )
    edits = {}
    text_records = 0
    for entry in source.entries[:metadata_index]:
        for record in iter_script_records(source.read_entry(entry)):
            classified = classify_source_record(record)
            if classified.classification == "unknown_candidate":
                raise ValueError(classified.error)
            if classified.classification != "translatable":
                continue
            english = classified.strings[1]
            replacement = encode_luca_string(english.text + " ", english.encoding)
            edits[(entry.index, record.offset)] = (
                record.params[:english.offset]
                + replacement
                + record.params[english.end_offset:]
            )
            text_records += 1

    relocation = relocate_script_records(source, edits)
    source.build(args.output, relocation.replacements)
    built = Pak(args.output)
    after = validate_script_references(built)
    if before != after:
        raise ValueError(f"structural counts changed: {before!r} -> {after!r}")

    print(f"source: {args.source}")
    print(f"output: {args.output}")
    print(f"text records changed: {text_records}")
    print(f"archive size: {source.file_size}->{built.file_size}")
    print(
        f"validated: scripts={after['script_entries']} records={after['records']} "
        f"references={after['references']} labels={after['labels']}"
    )


if __name__ == "__main__":
    main()
