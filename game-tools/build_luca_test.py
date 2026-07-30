"""Build Russian test lines into the Steam/LUCA SCRIPT.PAK."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from luca import (  # noqa: E402
    Pak,
    classify_source_record,
    encode_luca_string,
    iter_script_records,
    relocate_script_records,
    validate_script_references,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT / "Summer Pockets REFLECTION BLUE_Steam" / "files" / "SCRIPT.PAK.orig"
)
DEFAULT_OUTPUT = ROOT / "build" / "steam" / "SCRIPT.russian-test.PAK"
TEST_CASES = (
    (
        "@Ferry Announcement@"
        "\u275dWe will be arriving at Torishiro Fishing Port shortly.\u275e",
        "@Ferry Announcement@\u275dРусский текст читается чётко.\u275e",
    ),
    (
        "The island's landscape is finally coming into focus.",
        "Русский текст читается ясно.",
    ),
)
SAVE_TESTS = {
    "natural": "Русский текст читается ясно.",
    "punctuation": "«Ёж»— съешь ещё этих булок…",
    "alphabet": "ЁёЪъЬьЫыЭэЮюЯяЩщЦцЧчЖжШшФф",
    "relocation": "Русская строка произвольной длины отображается корректно.",
}


def find_text(pak, wanted):
    metadata_index = next(
        (entry.index for entry in pak.entries if entry.name == "_build_time"),
        pak.entry_count,
    )
    for entry in pak.entries[:metadata_index]:
        data = pak.read_entry(entry)
        for record in iter_script_records(data):
            classified = classify_source_record(record)
            if classified.classification == "unknown_candidate":
                raise ValueError(classified.error)
            if classified.classification != "translatable" or record.opcode != 36:
                continue
            for slot, value in enumerate(classified.strings):
                if value.text == wanted:
                    return entry, data, record, slot, value
    raise ValueError("source test line was not found")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--save-test", choices=SAVE_TESTS, default="natural")
    args = parser.parse_args()

    pak = Pak(args.source)
    edits = {}
    expected = []
    test_cases = list(TEST_CASES)
    test_cases[1] = (test_cases[1][0], SAVE_TESTS[args.save_test])
    for source_text, test_text in test_cases:
        entry, _, record, slot, source_value = find_text(
            pak, source_text
        )
        current_value = classify_source_record(record).strings[slot]
        replacement = encode_luca_string(test_text, source_value.encoding)
        new_params = (
            record.params[:current_value.offset]
            + replacement
            + record.params[current_value.end_offset:]
        )
        edits[(entry.index, record.offset)] = new_params
        expected.append(
            (
                entry.index,
                record.offset,
                slot,
                source_value.data_size,
                len(test_text.encode(source_value.encoding)),
                test_text,
            )
        )

    relocation = relocate_script_records(pak, edits)
    pak.build(args.output, relocation.replacements)

    built = Pak(args.output)
    validation = validate_script_references(built)
    for entry_index, record_offset, slot, _, _, test_text in expected:
        _, _, readback_record, readback_slot, readback = find_text(built, test_text)
        expected_offset = relocation.offset_maps[entry_index][record_offset]
        if readback_slot != slot or readback_record.offset != expected_offset:
            raise ValueError("test line moved during read-back")

    print(f"source: {args.source}")
    print(f"output: {args.output}")
    print(f"archive_size: {args.output.stat().st_size}")
    print(
        f"validated: records={validation['records']} "
        f"references={validation['references']} labels={validation['labels']}"
    )
    for entry_index, record_offset, slot, source_size, output_size, test_text in expected:
        print(
            f"readback: entry={entry_index} "
            f"offset={relocation.offset_maps[entry_index][record_offset]} "
            f"slot={slot} bytes={source_size}->{output_size} text={ascii(test_text)}"
        )


if __name__ == "__main__":
    main()
