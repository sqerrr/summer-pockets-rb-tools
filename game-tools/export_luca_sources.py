"""Export a deterministic local multilingual source catalogue from SCRIPT.PAK."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from luca import (  # noqa: E402
    Pak,
    SOURCE_LANGUAGES,
    classify_source_record,
    iter_script_records,
    make_source_id,
)


ROOT = Path(__file__).resolve().parents[1]
SPEAKER_MARKER = re.compile(r"^@([^@\r\n]+)@")


def digest_bytes(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest_file(path):
    value = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def write_jsonl_atomic(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def source_row(source_set_id, entry, record, ordinal, classified):
    base = {
        "schema_version": 1,
        "source_set_id": source_set_id,
        "source_id": make_source_id(entry.entry_id, ordinal),
        "classification": classified.classification,
        "script_entry": {
            "index": entry.index,
            "id": entry.entry_id,
            "name_sha256": digest_bytes((entry.name or "").encode("utf-8")),
        },
        "record": {
            "ordinal": ordinal,
            "original_offset": record.offset,
            "opcode": record.opcode,
            "flag": record.flag,
            "length": record.length,
            "aligned_size": (record.length + 1) & ~1,
            "fixed_params_u16": list(record.fixed_params),
            "params_sha256": digest_bytes(record.params),
        },
        "layout": {
            "group_ordinal": 0,
            "name": classified.layout,
        },
        "slots": [],
    }
    if classified.classification == "service_nontext":
        base["layout"]["params_size"] = len(record.params)
        return base

    base["layout"].update({
        "prefix_size": len(classified.prefix),
        "prefix_hex": classified.prefix.hex(),
        "tail_size": len(classified.tail),
        "tail_sha256": digest_bytes(classified.tail),
    })
    for index, (language, value) in enumerate(zip(SOURCE_LANGUAGES, classified.strings)):
        payload = record.params[value.data_offset:value.data_offset + value.data_size]
        marker = SPEAKER_MARKER.match(value.text)
        speaker = marker.group(1) if marker else None
        body_text = value.text[marker.end():] if marker else value.text
        base["slots"].append({
            "index": index,
            "language": language,
            "encoding": value.encoding,
            "payload_size": value.data_size,
            "payload_sha256": digest_bytes(payload),
            "text_sha256": digest_bytes(value.text.encode("utf-8")),
            "text": value.text,
            "speaker": speaker,
            "body_text_sha256": digest_bytes(body_text.encode("utf-8")),
            "body_text": body_text,
        })
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "project.yaml")
    parser.add_argument("--source-set", default="steam_luca")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    source_config = config["source_sets"][args.source_set]
    source_set_id = source_config["id"]
    archive = ROOT / source_config["archive"]
    catalog = ROOT / source_config["catalog"]
    manifest_path = ROOT / config.get("paths", {}).get(
        "source_manifest", "source/manifest.jsonl"
    )

    actual_hash = digest_file(archive)
    expected_hash = source_config["archive_sha256"].lower()
    if actual_hash != expected_hash:
        raise ValueError(f"source archive hash mismatch: {actual_hash}")

    pak = Pak(archive)
    metadata_index = next(
        (entry.index for entry in pak.entries if entry.name == "_build_time"),
        pak.entry_count,
    )
    counts = {
        "records": 0,
        "translatable": 0,
        "service_nontext": 0,
        "structural": 0,
        "opcode36": 0,
        "opcode40": 0,
        "speaker_any": 0,
        "speaker_all": 0,
        "speaker_partial": 0,
    }

    def rows():
        for entry in pak.entries[:metadata_index]:
            records = list(iter_script_records(pak.read_entry(entry)))
            counts["records"] += len(records)
            for ordinal, record in enumerate(records):
                classified = classify_source_record(record)
                if classified.classification == "structural":
                    counts["structural"] += 1
                    continue
                if classified.classification == "unknown_candidate":
                    raise ValueError(
                        f"unknown candidate at entry_id={entry.entry_id} "
                        f"record_ordinal={ordinal} opcode={record.opcode} "
                        f"offset={record.offset}: {classified.error}"
                    )
                counts[classified.classification] += 1
                if classified.classification == "translatable":
                    counts[f"opcode{record.opcode}"] += 1
                row = source_row(source_set_id, entry, record, ordinal, classified)
                if classified.classification == "translatable":
                    marker_count = sum(slot["speaker"] is not None for slot in row["slots"])
                    counts["speaker_any"] += marker_count > 0
                    counts["speaker_all"] += marker_count == len(row["slots"])
                    counts["speaker_partial"] += 0 < marker_count < len(row["slots"])
                yield row

    write_jsonl_atomic(catalog, rows())
    catalog_hash = digest_file(catalog)
    candidate_count = counts["translatable"] + counts["service_nontext"]
    if counts != {
        "records": 287663,
        "translatable": 96806,
        "service_nontext": 155,
        "structural": 190702,
        "opcode36": 96621,
        "opcode40": 185,
        "speaker_any": 69383,
        "speaker_all": 69342,
        "speaker_partial": 41,
    }:
        raise ValueError(f"unexpected source counts: {counts}")

    manifest = {
        "schema_version": 1,
        "source_set_id": source_set_id,
        "build_id": source_config["build_id"],
        "format": "luca-script-pak",
        "archive_path": source_config["archive"],
        "archive_size": archive.stat().st_size,
        "archive_sha256": actual_hash,
        "catalog_path": source_config["catalog"],
        "catalog_sha256": catalog_hash,
        "script_entry_count": metadata_index,
        "record_count": counts["records"],
        "candidate_record_count": candidate_count,
        "translatable_record_count": counts["translatable"],
        "service_nontext_record_count": counts["service_nontext"],
        "structural_record_count": counts["structural"],
        "text_opcode_counts": {"36": counts["opcode36"], "40": counts["opcode40"]},
        "speaker_marker_counts": {
            "any_slot": counts["speaker_any"],
            "all_slots": counts["speaker_all"],
            "partial_slots": counts["speaker_partial"],
        },
        "source_priority": source_config["source_priority"],
        "working_source_language": source_config["working_source_language"],
        "build_slot": source_config["build_slot"],
        "slots": source_config["slots"],
        "generator": "game-tools/export_luca_sources.py",
    }
    manifests = []
    if manifest_path.exists():
        for raw in manifest_path.read_text(encoding="utf-8-sig").splitlines():
            if raw.strip() and not raw.lstrip().startswith("#"):
                item = json.loads(raw)
                if item.get("source_set_id") != source_set_id:
                    manifests.append(item)
    manifests.append(manifest)
    manifests.sort(key=lambda item: str(item.get("source_set_id", "")))
    write_jsonl_atomic(manifest_path, manifests)
    print(f"source set: {source_set_id}")
    print(f"archive: {archive}")
    print(f"catalog: {catalog}")
    print(f"catalog sha256: {catalog_hash}")
    print(
        f"records: {counts['records']} candidate={candidate_count} "
        f"translatable={counts['translatable']} service={counts['service_nontext']}"
    )


if __name__ == "__main__":
    main()
