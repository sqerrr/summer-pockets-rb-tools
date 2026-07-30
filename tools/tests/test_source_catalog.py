import hashlib
import importlib.util
import json
from pathlib import Path


def load_vnctl():
    path = Path(__file__).parents[1] / "vnctl.py"
    spec = importlib.util.spec_from_file_location("vnctl_sources", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def sha256(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def make_source_tree(tmp_path):
    archive = tmp_path / "game/SCRIPT.PAK.orig"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"archive")
    archive_hash = sha256(archive.read_bytes())
    catalog = tmp_path / "source/parsed/test/source-records.jsonl"
    catalog.parent.mkdir(parents=True)
    params_hash = sha256(b"params")
    slots = []
    for index, (language, text, encoding) in enumerate((
        ("ja", "日本語", "utf-16le"),
        ("en", "English", "utf-8"),
        ("zh-Hans", "简体中文", "utf-16le"),
    )):
        payload = text.encode(encoding)
        slots.append({
            "index": index,
            "language": language,
            "encoding": encoding,
            "payload_size": len(payload),
            "payload_sha256": sha256(payload),
            "text_sha256": sha256(text.encode("utf-8")),
            "text": text,
            "speaker": None,
            "body_text_sha256": sha256(text.encode("utf-8")),
            "body_text": text,
        })
    row = {
        "schema_version": 1,
        "source_set_id": "TEST_SET",
        "source_id": "SRC_LUCA_E000001_R000002_G00",
        "classification": "translatable",
        "script_entry": {"index": 0, "id": 1, "name_sha256": sha256(b"entry")},
        "record": {
            "ordinal": 2,
            "original_offset": 10,
            "opcode": 36,
            "flag": 3,
            "length": 20,
            "aligned_size": 20,
            "fixed_params_u16": [1, 2],
            "params_sha256": params_hash,
        },
        "layout": {"group_ordinal": 0, "name": "opcode36-multilingual-v1"},
        "slots": slots,
    }
    catalog.write_text(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "source/manifest.jsonl"
    source_slots = [
        {"index": 0, "language": "ja"},
        {"index": 1, "language": "en"},
        {"index": 2, "language": "zh-Hans"},
    ]
    manifest.write_text(json.dumps({
        "source_set_id": "TEST_SET",
        "build_id": "test_luca",
        "archive_path": "game/SCRIPT.PAK.orig",
        "archive_size": archive.stat().st_size,
        "archive_sha256": archive_hash,
        "catalog_path": "source/parsed/test/source-records.jsonl",
        "catalog_sha256": sha256(catalog.read_bytes()),
        "source_priority": ["ja", "en", "zh-Hans"],
        "working_source_language": "en",
        "build_slot": 1,
        "candidate_record_count": 1,
        "translatable_record_count": 1,
        "service_nontext_record_count": 0,
        "structural_record_count": 0,
        "record_count": 1,
        "text_opcode_counts": {"36": 1},
        "speaker_marker_counts": {
            "any_slot": 0,
            "all_slots": 0,
            "partial_slots": 0,
        },
        "slots": source_slots,
        "generator": "test",
    }) + "\n", encoding="utf-8")
    config = {
        "paths": {
            "source_manifest": "source/manifest.jsonl",
            "segments": "translation/segments",
        },
        "source_sets": {
            "test": {
                "id": "TEST_SET",
                "build_id": "test_luca",
                "archive": "game/SCRIPT.PAK.orig",
                "archive_sha256": archive_hash,
                "catalog": "source/parsed/test/source-records.jsonl",
                "source_priority": ["ja", "en", "zh-Hans"],
                "working_source_language": "en",
                "build_slot": 1,
                "slots": source_slots,
            }
        },
    }
    return row, params_hash, config


def test_source_catalog_validates_and_hydrates_segments(tmp_path):
    vnctl = load_vnctl()
    source_row, params_hash, config = make_source_tree(tmp_path)
    errors, warnings, totals = vnctl.validate_source_catalogs(tmp_path, config)
    assert errors == []
    assert warnings == []
    assert totals["candidate"] == 1

    segment_dir = tmp_path / "translation/segments"
    segment_dir.mkdir(parents=True)
    segment_dir.joinpath("test.jsonl").write_text(json.dumps({
        "id": "SEG_TEST",
        "source_set_id": "TEST_SET",
        "source_id": source_row["source_id"],
        "source_hash": params_hash,
        "file_id": "F1",
        "scene_id": "SC1",
        "order": 1,
        "translation": "",
        "status": "todo",
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = vnctl.load_segments(tmp_path, config)
    assert rows[0]["source"] == "English"
    assert rows[0]["sources"]["ja"] == "日本語"
    assert rows[0]["__catalog_source_hash"] == params_hash
