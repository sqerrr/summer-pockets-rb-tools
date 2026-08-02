#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "project.yaml"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "project.example.yaml"


class VNError(RuntimeError):
    pass


FORBIDDEN_TRACKED_KEYS = {
    "private_reason",
    "reveal_after",
    "secret",
    "api_key",
    "apikey",
    "password",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_jsonl(path: Path, *, missing_ok: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        if missing_ok:
            return []
        raise VNError(f"missing file: {path.relative_to(ROOT)}")
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise VNError(f"{path.relative_to(ROOT)}:{line_no}: {exc}") from exc
        if not isinstance(value, dict):
            raise VNError(f"{path.relative_to(ROOT)}:{line_no}: object required")
        rows.append(value)
    return rows


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def reject_forbidden_tracked_keys(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN_TRACKED_KEYS:
                raise VNError(f"{label}: forbidden private field {key!r}")
            reject_forbidden_tracked_keys(item, label)
    elif isinstance(value, list):
        for item in value:
            reject_forbidden_tracked_keys(item, label)


def validate_tracked_narrative(config: dict[str, Any], text: Any, label: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise VNError(f"{label}: nonempty text is required")
    if len(text) > 1000:
        raise VNError(f"{label}: text is too long for tracked metadata")
    private_values: list[str] = []
    for constraint in read_jsonl(cfg_path(config, "private_constraints"), missing_ok=True):
        value = constraint.get("private_reason")
        if isinstance(value, str) and value.strip():
            private_values.append(value.strip())
    for value in private_values:
        if (len(value) >= 2 and value in text) or (len(value) == 1 and text.strip() == value):
            raise VNError(f"{label}: contains private constraint text")
    for record in source_records(config, missing_ok=True):
        texts = record.get("texts", {})
        if not isinstance(texts, dict):
            continue
        for source_text in texts.values():
            if isinstance(source_text, str) and source_text.strip():
                value = source_text.strip()
                if (len(value) >= 2 and value in text) or (
                    len(value) == 1 and text.strip() == value
                ):
                    raise VNError(f"{label}: contains a complete source line")
def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise VNError("project is not initialized; run `python tools/vnctl.py init`")
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise VNError("config/project.yaml must contain a mapping")
    for key in ("project", "paths", "qa"):
        if not isinstance(data.get(key), dict):
            raise VNError(f"config/project.yaml: missing mapping {key!r}")
    languages = data["project"].get("source_languages")
    if not isinstance(languages, list) or not languages or not all(
        isinstance(item, str) and item for item in languages
    ):
        raise VNError("project.source_languages must be a nonempty string list")
    return data


def project_path(raw: str, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise VNError(f"{label} must be a nonempty relative path")
    path = Path(raw)
    if path.is_absolute():
        raise VNError(f"{label} must stay inside the project")
    candidate = (ROOT / path).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise VNError(f"{label} escapes the project root") from exc
    return candidate


def cfg_path(config: dict[str, Any], key: str) -> Path:
    raw = config["paths"].get(key)
    return project_path(raw, f"paths.{key}")


def build_path(raw: str) -> Path:
    candidate = project_path(raw, "artifact path")
    build_root = (ROOT / "build").resolve()
    try:
        candidate.relative_to(build_root)
    except ValueError as exc:
        raise VNError("agent artifacts must stay under build/") from exc
    return candidate


def source_records(config: dict[str, Any], *, missing_ok: bool = False) -> list[dict[str, Any]]:
    return read_jsonl(cfg_path(config, "source_records"), missing_ok=missing_ok)


def source_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = source_records(config)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise VNError("source record has no source_id")
        if source_id in result:
            raise VNError(f"duplicate source_id: {source_id}")
        result[source_id] = row
    return result


def scene_catalog(config: dict[str, Any], *, missing_ok: bool = False) -> list[dict[str, Any]]:
    return read_jsonl(cfg_path(config, "scenes"), missing_ok=missing_ok)


def scene_file(config: dict[str, Any], scene_id: str) -> Path:
    for scene in scene_catalog(config):
        if scene.get("scene_id") == scene_id:
            raw = scene.get("segment_file")
            if not isinstance(raw, str):
                raise VNError(f"scene {scene_id} has no segment_file")
            return project_path(raw, f"scene {scene_id} segment_file")
    raise VNError(f"unknown scene: {scene_id}")


def load_scene(config: dict[str, Any], scene_id: str) -> list[dict[str, Any]]:
    return read_jsonl(scene_file(config, scene_id))


def all_segments(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scene in scene_catalog(config, missing_ok=True):
        raw = scene.get("segment_file")
        if isinstance(raw, str):
            rows.extend(read_jsonl(project_path(raw, "scene segment_file")))
    return rows


def stored_segments(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Path]]:
    root = cfg_path(config, "segments")
    files = sorted(root.glob("*.jsonl")) if root.exists() else []
    rows: list[dict[str, Any]] = []
    for path in files:
        rows.extend(read_jsonl(path))
    return rows, files


def segment_id(source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16].upper()
    return f"SEG_{digest}"


def source_hash(record: dict[str, Any]) -> str:
    return sha256_value(record)


def scene_hash(config: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    sources = source_by_id(config)
    state = [
        {
            "id": row.get("id"),
            "source_id": row.get("source_id"),
            "source_hash": source_hash(sources[row["source_id"]]),
            "scene_id": row.get("scene_id"),
            "order": row.get("order"),
            "speaker": row.get("speaker", ""),
            "translation": row.get("translation", ""),
            "flags": sorted(row.get("flags", [])),
            "confidence": row.get("confidence"),
            "last_actor": row.get("last_actor"),
            "authors": sorted(row.get("authors", [])),
        }
        for row in sorted(rows, key=lambda item: (item.get("order", 0), item.get("id", "")))
    ]
    return sha256_value(state)


def roundtrip_state(config: dict[str, Any]) -> tuple[bool, str]:
    path = cfg_path(config, "roundtrip_receipt")
    if not path.exists():
        return False, "receipt missing"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"receipt unreadable: {exc}"
    records = source_records(config, missing_ok=True)
    checks = {
        "verified": receipt.get("verified") is True,
        "adapter": receipt.get("adapter") == config["project"].get("adapter"),
        "pristine": receipt.get("source_sha256")
        == config["project"].get("pristine_sha256"),
        "catalog": receipt.get("catalog_sha256") == sha256_value(records),
        "count": receipt.get("record_count") == len(records),
        "order": receipt.get("order_preserved") is True,
        "smoke": receipt.get("smoke_test") is True,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        return False, "receipt mismatch: " + ", ".join(failed)
    return True, "verified"


def require_roundtrip(config: dict[str, Any]) -> None:
    verified, reason = roundtrip_state(config)
    if not verified:
        raise VNError(f"translation pipeline is locked until round trip is verified: {reason}")


def safe_rules(config: dict[str, Any]) -> list[str]:
    rules: list[str] = []
    for row in read_jsonl(cfg_path(config, "private_constraints"), missing_ok=True):
        value = row.get("safe_rules", [])
        if isinstance(value, list):
            rules.extend(item for item in value if isinstance(item, str) and item)
    return rules


def configured_patterns(config: dict[str, Any]) -> list[re.Pattern[str]]:
    values = config["qa"].get("protected_patterns", [])
    if not isinstance(values, list):
        raise VNError("qa.protected_patterns must be a list")
    patterns: list[re.Pattern[str]] = []
    for raw in values:
        if not isinstance(raw, str):
            raise VNError("qa.protected_patterns entries must be strings")
        try:
            patterns.append(re.compile(raw))
        except re.error as exc:
            raise VNError(f"invalid protected pattern {raw!r}: {exc}") from exc
    return patterns


def pattern_tokens(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    found: list[tuple[int, int, str]] = []
    for index, pattern in enumerate(patterns):
        for match in pattern.finditer(text):
            found.append((match.start(), index, match.group(0)))
    return [value for _, _, value in sorted(found)]


def explicit_tokens(text: str, expected: list[str]) -> list[str]:
    if not expected:
        return []
    alternatives = sorted(set(expected), key=lambda item: (-len(item), item))
    regex = re.compile("|".join(re.escape(item) for item in alternatives))
    return [match.group(0) for match in regex.finditer(text)]


def check_protected(
    config: dict[str, Any], record: dict[str, Any], translation: str
) -> list[str]:
    errors: list[str] = []
    languages = config["project"]["source_languages"]
    texts = record.get("texts", {})
    source_text = texts.get(languages[0], "") if isinstance(texts, dict) else ""
    patterns = configured_patterns(config)
    source_pattern_tokens = pattern_tokens(source_text, patterns)
    target_pattern_tokens = pattern_tokens(translation, patterns)
    if source_pattern_tokens != target_pattern_tokens:
        errors.append(
            f"protected pattern tokens differ: source={source_pattern_tokens}, "
            f"target={target_pattern_tokens}"
        )
    expected = record.get("protected_tokens", [])
    if expected is None:
        expected = []
    if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
        errors.append("source protected_tokens must be a string list")
    elif explicit_tokens(translation, expected) != expected:
        errors.append(
            f"explicit protected tokens differ: source={expected}, "
            f"target={explicit_tokens(translation, expected)}"
        )
    return errors


def allowed_values(config: dict[str, Any], key: str) -> set[str]:
    values = config["qa"].get(key, [])
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise VNError(f"qa.{key} must be a string list")
    return set(values)


def command_init(args: argparse.Namespace) -> int:
    if CONFIG_PATH.exists() and not args.force:
        raise VNError("config/project.yaml already exists; use --force to replace it")
    data = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    if args.title:
        data["project"]["title"] = args.title
    if args.source_language:
        data["project"]["source_languages"] = args.source_language
    if args.target_language:
        data["project"]["target_language"] = args.target_language
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(
        CONFIG_PATH,
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    )
    config = load_config()
    for key in (
        "source_records",
        "scenes",
        "open_questions",
        "review_ledger",
        "private_constraints",
    ):
        path = cfg_path(config, key)
        if not path.exists():
            write_text_atomic(path, "")
    cfg_path(config, "segments").mkdir(parents=True, exist_ok=True)
    cfg_path(config, "database").parent.mkdir(parents=True, exist_ok=True)
    cfg_path(config, "roundtrip_receipt").parent.mkdir(parents=True, exist_ok=True)
    print(f"Initialized {data['project']['title']!r}")
    return 0


def scene_id_error(scene_id: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", scene_id):
        return "contains unsafe filename characters"
    stem = scene_id.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{index}" for index in range(1, 10))
    reserved.update(f"LPT{index}" for index in range(1, 10))
    if stem in reserved:
        return "is a reserved Windows filename"
    return None


def validate_source_record(
    config: dict[str, Any], row: dict[str, Any], index: int
) -> list[str]:
    errors: list[str] = []
    prefix = f"source row {index}"
    for key in ("source_id", "scene_id"):
        if not isinstance(row.get(key), str) or not row[key]:
            errors.append(f"{prefix}: {key} must be a nonempty string")
    scene_id = row.get("scene_id")
    if isinstance(scene_id, str):
        problem = scene_id_error(scene_id)
        if problem:
            errors.append(f"{prefix}: scene_id {problem}")
    if not isinstance(row.get("order"), int):
        errors.append(f"{prefix}: order must be an integer")
    texts = row.get("texts")
    if not isinstance(texts, dict):
        errors.append(f"{prefix}: texts must be an object")
    else:
        for language in config["project"]["source_languages"]:
            if not isinstance(texts.get(language), str):
                errors.append(f"{prefix}: missing text for language {language!r}")
    protected = row.get("protected_tokens", [])
    if not isinstance(protected, list) or not all(isinstance(item, str) for item in protected):
        errors.append(f"{prefix}: protected_tokens must be a string list")
    return errors


def command_ingest(args: argparse.Namespace) -> int:
    config = load_config()
    records = source_records(config)
    if not records:
        raise VNError("source catalog is empty")
    errors: list[str] = []
    source_ids: set[str] = set()
    scene_names: dict[str, str] = {}
    scene_orders: set[tuple[str, int]] = set()
    for index, row in enumerate(records, 1):
        errors.extend(validate_source_record(config, row, index))
        source_id = row.get("source_id")
        if isinstance(source_id, str):
            if source_id in source_ids:
                errors.append(f"duplicate source_id: {source_id}")
            source_ids.add(source_id)
        scene_id = row.get("scene_id")
        order = row.get("order")
        if isinstance(scene_id, str):
            folded = scene_id.casefold()
            if folded in scene_names and scene_names[folded] != scene_id:
                errors.append(
                    f"scene IDs collide on case-insensitive filesystems: "
                    f"{scene_names[folded]} and {scene_id}"
                )
            scene_names[folded] = scene_id
            if isinstance(order, int):
                order_key = (folded, order)
                if order_key in scene_orders:
                    errors.append(f"duplicate order {order} in scene {scene_id}")
                scene_orders.add(order_key)
    if errors:
        raise VNError("source validation failed:\n" + "\n".join(errors))

    stored, _ = stored_segments(config)
    existing: dict[str, dict[str, Any]] = {}
    for row in stored:
        source_id = row.get("source_id")
        if not isinstance(source_id, str):
            raise VNError("stored segment has no source_id")
        if source_id in existing:
            raise VNError(f"duplicate stored source_id: {source_id}")
        if row.get("id") != segment_id(source_id):
            raise VNError(f"stored segment has invalid stable id for {source_id}")
        existing[source_id] = row
    removed = sorted(set(existing) - source_ids)
    if removed:
        raise VNError(
            "ingest would remove existing source IDs; create an explicit migration: "
            + ", ".join(removed[:10])
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    changed_scenes: set[str] = set()
    for record in records:
        old = existing.get(record["source_id"])
        current_hash = source_hash(record)
        flags = list(old.get("flags", [])) if old else []
        status = old.get("status", "todo") if old else "todo"
        translation = old.get("translation", "") if old else ""
        confidence = old.get("confidence") if old else None
        if old and old.get("source_hash") != current_hash and translation:
            if "needs_source_check" not in flags:
                flags.append("needs_source_check")
            status = "draft"
            changed_scenes.add(record["scene_id"])
        grouped[record["scene_id"]].append(
            {
                "id": old.get("id") if old else segment_id(record["source_id"]),
                "source_id": record["source_id"],
                "scene_id": record["scene_id"],
                "order": record["order"],
                "speaker": record.get("speaker", ""),
                "source_hash": current_hash,
                "translation": translation,
                "status": status,
                "flags": flags,
                "confidence": confidence,
                "last_actor": old.get("last_actor") if old else None,
                "authors": list(old.get("authors", [])) if old else [],
            }
        )

    scenes: list[dict[str, Any]] = []
    segment_root = cfg_path(config, "segments")
    for scene_id, rows in grouped.items():
        if scene_id in changed_scenes:
            for row in rows:
                if row.get("translation"):
                    row["status"] = "draft"
        rows.sort(key=lambda item: (item["order"], item["id"]))
        path = segment_root / f"{scene_id}.jsonl"
        relative = path.relative_to(ROOT).as_posix()
        scenes.append(
            {"scene_id": scene_id, "order": rows[0]["order"], "segment_file": relative}
        )
        write_jsonl_atomic(path, rows)
    scenes.sort(key=lambda item: (item["order"], item["scene_id"]))
    write_jsonl_atomic(cfg_path(config, "scenes"), scenes)
    print(f"Ingested {len(records)} records into {len(scenes)} scenes")
    return 0


def collect_validation(config: dict[str, Any]) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    records = source_records(config, missing_ok=True)
    record_map: dict[str, dict[str, Any]] = {}
    source_scene_names: dict[str, str] = {}
    source_orders: set[tuple[str, int]] = set()
    for index, row in enumerate(records, 1):
        errors.extend(validate_source_record(config, row, index))
        source_id = row.get("source_id")
        if isinstance(source_id, str):
            if source_id in record_map:
                errors.append(f"duplicate source_id: {source_id}")
            record_map[source_id] = row
        scene_id = row.get("scene_id")
        order = row.get("order")
        if isinstance(scene_id, str):
            folded = scene_id.casefold()
            if folded in source_scene_names and source_scene_names[folded] != scene_id:
                errors.append(
                    f"scene IDs collide on case-insensitive filesystems: "
                    f"{source_scene_names[folded]} and {scene_id}"
                )
            source_scene_names[folded] = scene_id
            if isinstance(order, int):
                key = (folded, order)
                if key in source_orders:
                    errors.append(f"duplicate order {order} in scene {scene_id}")
                source_orders.add(key)

    statuses = allowed_values(config, "statuses")
    flags_allowed = allowed_values(config, "flags")
    segment_ids: set[str] = set()
    source_seen: set[str] = set()
    segment_rows, stored_files = stored_segments(config)
    for row in segment_rows:
        segment = row.get("id", "<missing>")
        if not isinstance(segment, str) or not segment:
            errors.append("segment without a valid id")
            continue
        if segment in segment_ids:
            errors.append(f"duplicate segment id: {segment}")
        segment_ids.add(segment)
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or source_id not in record_map:
            errors.append(f"{segment}: unknown source_id {source_id!r}")
            continue
        if source_id in source_seen:
            errors.append(f"duplicate segment source_id: {source_id}")
        source_seen.add(source_id)
        record = record_map[source_id]
        if segment != segment_id(source_id):
            errors.append(f"{segment}: stable id does not match source_id")
        if row.get("source_hash") != source_hash(record):
            errors.append(f"{segment}: stale source_hash")
        if row.get("scene_id") != record.get("scene_id"):
            errors.append(f"{segment}: scene_id differs from source record")
        if row.get("order") != record.get("order"):
            errors.append(f"{segment}: order differs from source record")
        if row.get("speaker", "") != record.get("speaker", ""):
            errors.append(f"{segment}: speaker differs from source record")
        status = row.get("status")
        if status not in statuses:
            errors.append(f"{segment}: invalid status {status!r}")
        if status == "approved":
            errors.append(f"{segment}: approved requires an external explicit-user mechanism")
        translation = row.get("translation")
        if not isinstance(translation, str):
            errors.append(f"{segment}: translation must be a string")
            continue
        if status == "todo" and translation:
            errors.append(f"{segment}: todo segment has translation")
        if status != "todo" and not translation:
            errors.append(f"{segment}: translated status has empty translation")
        flags = row.get("flags", [])
        if not isinstance(flags, list) or not all(isinstance(item, str) for item in flags):
            errors.append(f"{segment}: flags must be a string list")
        else:
            unknown_flags = sorted(set(flags) - flags_allowed)
            if unknown_flags:
                errors.append(f"{segment}: unknown flags {unknown_flags}")
        if translation:
            for message in check_protected(config, record, translation):
                errors.append(f"{segment}: {message}")
        confidence = row.get("confidence")
        if confidence not in {None, "low", "medium", "high"}:
            errors.append(f"{segment}: invalid confidence {confidence!r}")
        last_actor = row.get("last_actor")
        if last_actor is not None and (not isinstance(last_actor, str) or not last_actor):
            errors.append(f"{segment}: last_actor must be null or a nonempty string")
        authors = row.get("authors", [])
        if not isinstance(authors, list) or not all(
            isinstance(actor, str) and actor for actor in authors
        ):
            errors.append(f"{segment}: authors must be a nonempty-string list")
        elif len(authors) != len(set(authors)):
            errors.append(f"{segment}: authors contains duplicates")

    missing_segments = sorted(set(record_map) - source_seen)
    if missing_segments:
        warnings.append(f"{len(missing_segments)} source records have no segment; run ingest")

    scene_ids: set[str] = set()
    scene_keys: set[str] = set()
    catalog_files: set[Path] = set()
    for scene in scene_catalog(config, missing_ok=True):
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id:
            errors.append("scene catalog row has no scene_id")
            continue
        if scene_id in scene_ids:
            errors.append(f"duplicate scene_id: {scene_id}")
        scene_ids.add(scene_id)
        folded = scene_id.casefold()
        if folded in scene_keys:
            errors.append(f"case-insensitive duplicate scene_id: {scene_id}")
        scene_keys.add(folded)
        raw = scene.get("segment_file")
        if not isinstance(raw, str):
            errors.append(f"{scene_id}: missing segment_file")
            continue
        try:
            path = project_path(raw, f"scene {scene_id} segment_file")
        except VNError as exc:
            errors.append(str(exc))
            continue
        catalog_files.add(path)
        if not path.exists():
            errors.append(f"{scene_id}: missing segment_file")
    orphan_files = sorted(set(stored_files) - catalog_files)
    if orphan_files:
        errors.append(
            "segment files missing from scene catalog: "
            + ", ".join(path.name for path in orphan_files)
        )

    question_kinds = allowed_values(config, "question_kinds")
    question_ids: set[str] = set()
    for row in read_jsonl(cfg_path(config, "open_questions"), missing_ok=True):
        try:
            reject_forbidden_tracked_keys(row, "open question")
        except VNError as exc:
            errors.append(str(exc))
        unknown_question_fields = set(row) - {
            "id",
            "kind",
            "scene_id",
            "segment_ids",
            "question",
            "provisional",
            "status",
            "created_by",
        }
        if unknown_question_fields:
            errors.append(f"open question has unknown fields {sorted(unknown_question_fields)}")
        question_id = row.get("id")
        if not isinstance(question_id, str) or not question_id:
            errors.append("open question without id")
            continue
        if question_id in question_ids:
            errors.append(f"duplicate question id: {question_id}")
        question_ids.add(question_id)
        if row.get("kind") not in question_kinds:
            errors.append(f"{question_id}: invalid kind {row.get('kind')!r}")
        status = row.get("status")
        if status not in {"open", "closed"}:
            errors.append(f"{question_id}: invalid status {status!r}")
        if status == "open" and (
            not isinstance(row.get("provisional"), str) or not row["provisional"].strip()
        ):
            errors.append(f"{question_id}: open question requires provisional")
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            errors.append(f"{question_id}: question text is required")
        else:
            try:
                validate_tracked_narrative(config, row["question"], f"{question_id} question")
            except VNError as exc:
                errors.append(str(exc))
        ids = row.get("segment_ids", [])
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            errors.append(f"{question_id}: segment_ids must be a string list")
        else:
            unknown = sorted(set(ids) - segment_ids)
            if unknown:
                errors.append(f"{question_id}: unknown segment_ids {unknown}")

    try:
        ledger_rows = read_jsonl(cfg_path(config, "review_ledger"), missing_ok=True)
        runs = review_runs(config)
        known_events = {
            "review_imported",
            "review_resolved",
            "review_rechecked",
            "review_closed",
        }
        for event in ledger_rows:
            if event.get("event") not in known_events:
                errors.append(f"review ledger has unknown event {event.get('event')!r}")
        rows_by_scene: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in segment_rows:
            if isinstance(row.get("scene_id"), str):
                rows_by_scene[row["scene_id"]].append(row)
        for scene_id, rows in rows_by_scene.items():
            if not any(row.get("status") in {"reviewed", "playable", "lqa"} for row in rows):
                continue
            if any(row.get("source_id") not in record_map for row in rows):
                continue
            current_hash = scene_hash(config, rows)
            evidence = [
                run.get("closed_event", {}).get("base_sha256")
                for run in runs.values()
                if run.get("scene_id") == scene_id and run.get("closed")
            ]
            if current_hash not in evidence:
                errors.append(
                    f"{scene_id}: reviewed/playable/lqa state has no closed review for current hash"
                )
    except VNError as exc:
        errors.append(str(exc))
    verified, reason = roundtrip_state(config)
    if records or segment_rows:
        if not verified:
            errors.append(f"round-trip verification required: {reason}")
    elif cfg_path(config, "roundtrip_receipt").exists() and not verified:
        errors.append(f"round-trip receipt is stale or invalid: {reason}")
    return errors, warnings, len(segment_rows)


def command_validate(args: argparse.Namespace) -> int:
    config = load_config()
    errors, warnings, count = collect_validation(config)
    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"WARN: {message}")
    print(f"Validated {count} segments: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def command_stats(args: argparse.Namespace) -> int:
    config = load_config()
    rows = all_segments(config)
    counts = Counter(row.get("status", "invalid") for row in rows)
    translated = sum(count for status, count in counts.items() if status != "todo")
    percent = (100.0 * translated / len(rows)) if rows else 0.0
    print(f"Scenes: {len(scene_catalog(config, missing_ok=True))}")
    print(f"Segments: {len(rows)}")
    print(f"Translated: {translated}/{len(rows)} ({percent:.1f}%)")
    for status in sorted(counts):
        print(f"  {status}: {counts[status]}")
    return 0


def review_runs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for event in read_jsonl(cfg_path(config, "review_ledger"), missing_ok=True):
        review_id = event.get("review_id")
        if not isinstance(review_id, str):
            continue
        kind = event.get("event")
        if kind == "review_imported":
            runs[review_id] = {
                "review_id": review_id,
                "scene_id": event.get("scene_id"),
                "base_sha256": event.get("base_sha256"),
                "issues": event.get("issues", []),
                "imported_verdict": event.get("verdict"),
                "resolved": [],
                "rechecks": [],
                "closed": False,
                "last_event": "review_imported",
            }
        elif review_id in runs and kind == "review_resolved":
            runs[review_id]["resolved"].append(event)
            runs[review_id]["last_event"] = "review_resolved"
        elif review_id in runs and kind == "review_rechecked":
            runs[review_id]["rechecks"].append(event)
            runs[review_id]["last_event"] = "review_rechecked"
        elif review_id in runs and kind == "review_closed":
            runs[review_id]["closed"] = True
            runs[review_id]["closed_event"] = event
            runs[review_id]["last_event"] = "review_closed"
    return runs


def command_brief(args: argparse.Namespace) -> int:
    config = load_config()
    rows = all_segments(config)
    statuses = Counter(row.get("status", "invalid") for row in rows)
    questions = read_jsonl(cfg_path(config, "open_questions"), missing_ok=True)
    open_questions = sum(row.get("status") == "open" for row in questions)
    runs = review_runs(config)
    open_reviews = sum(not run.get("closed") for run in runs.values())
    verified, _ = roundtrip_state(config)
    print(f"Project: {config['project'].get('title', 'Untitled')}")
    print(f"Scenes: {len(scene_catalog(config, missing_ok=True))}")
    print(f"Segments: {len(rows)}")
    print(f"Statuses: {dict(sorted(statuses.items()))}")
    print(f"Open reviews: {open_reviews}")
    print(f"Open questions: {open_questions}")
    print(f"Round trip verified: {'yes' if verified else 'no'}")
    return 0


def command_questions(args: argparse.Namespace) -> int:
    config = load_config()
    if bool(args.import_file) != bool(args.actor):
        raise VNError("--import-file and --actor must be used together")
    if args.import_file:
        proposals = read_jsonl(build_path(args.import_file))
        reject_forbidden_tracked_keys(proposals, "question import")
        existing = read_jsonl(cfg_path(config, "open_questions"), missing_ok=True)
        known_ids = {row.get("id") for row in existing}
        segment_rows = all_segments(config)
        segment_ids = {row.get("id") for row in segment_rows}
        scene_ids = {row.get("scene_id") for row in segment_rows}
        allowed_kinds = allowed_values(config, "question_kinds")
        imported_ids: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for proposal in proposals:
            if set(proposal) - {
                "id",
                "kind",
                "scene_id",
                "segment_ids",
                "question",
                "provisional",
                "status",
            }:
                raise VNError("question proposal has unknown fields")
            question_id = proposal.get("id")
            if not isinstance(question_id, str) or not question_id:
                raise VNError("question proposal has no id")
            if question_id in known_ids or question_id in imported_ids:
                raise VNError(f"duplicate question id: {question_id}")
            imported_ids.add(question_id)
            if proposal.get("kind") not in allowed_kinds:
                raise VNError(f"{question_id}: invalid kind")
            if proposal.get("scene_id") not in scene_ids:
                raise VNError(f"{question_id}: unknown scene_id")
            ids = proposal.get("segment_ids")
            if not isinstance(ids, list) or not ids or not all(
                isinstance(item, str) and item in segment_ids for item in ids
            ):
                raise VNError(f"{question_id}: invalid segment_ids")
            if not isinstance(proposal.get("question"), str) or not proposal["question"].strip():
                raise VNError(f"{question_id}: question text is required")
            validate_tracked_narrative(
                config, proposal["question"], f"{question_id} question"
            )
            if not isinstance(proposal.get("provisional"), str) or not proposal[
                "provisional"
            ].strip():
                raise VNError(f"{question_id}: provisional is required")
            if proposal.get("status", "open") != "open":
                raise VNError(f"{question_id}: imported question must be open")
            row = dict(proposal)
            row["status"] = "open"
            row["created_by"] = args.actor
            normalized.append(row)
        write_jsonl_atomic(cfg_path(config, "open_questions"), existing + normalized)
        print(f"Imported {len(normalized)} questions")
    errors, _, _ = collect_validation(config)
    rows = read_jsonl(cfg_path(config, "open_questions"), missing_ok=True)
    question_ids = {
        row["id"] for row in rows if isinstance(row.get("id"), str) and row["id"]
    }
    question_errors = [
        message
        for message in errors
        if "question" in message.lower()
        or any(message.startswith(f"{question_id}:") for question_id in question_ids)
    ]
    open_rows = [row for row in rows if row.get("status") == "open"]
    kinds = Counter(row.get("kind", "invalid") for row in open_rows)
    for message in question_errors:
        print(f"ERROR: {message}")
    print(f"Questions: {len(rows)} total, {len(open_rows)} open, {len(question_errors)} errors")
    print(f"Kinds: {dict(sorted(kinds.items()))}")
    return 1 if question_errors else 0


def command_index(args: argparse.Namespace) -> int:
    config = load_config()
    path = cfg_path(config, "database")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "create table segments (id text primary key, scene_id text, source_id text, "
            "speaker text, source_text text, translation text, status text)"
        )
        try:
            connection.execute(
                "create virtual table segment_fts using fts5(id, scene_id, speaker, source_text, translation)"
            )
            has_fts = True
        except sqlite3.OperationalError:
            has_fts = False
        sources = source_by_id(config) if source_records(config, missing_ok=True) else {}
        languages = config["project"]["source_languages"]
        for row in all_segments(config):
            source = sources.get(row["source_id"], {})
            texts = source.get("texts", {}) if isinstance(source, dict) else {}
            source_text = "\n".join(
                texts.get(language, "") for language in languages if isinstance(texts, dict)
            )
            values = (
                row["id"],
                row["scene_id"],
                row["source_id"],
                row.get("speaker", ""),
                source_text,
                row.get("translation", ""),
                row.get("status", ""),
            )
            connection.execute("insert into segments values (?, ?, ?, ?, ?, ?, ?)", values)
            if has_fts:
                connection.execute(
                    "insert into segment_fts values (?, ?, ?, ?, ?)",
                    (values[0], values[1], values[3], values[4], values[5]),
                )
        connection.commit()
    finally:
        connection.close()
    print(f"Indexed {len(all_segments(config))} segments ({'FTS5' if has_fts else 'plain SQLite'})")
    return 0


def choose_scene(config: dict[str, Any], requested: str | None) -> str:
    scenes = scene_catalog(config)
    if requested:
        load_scene(config, requested)
        return requested
    for scene in scenes:
        scene_id = scene["scene_id"]
        if any(row.get("status") == "todo" for row in load_scene(config, scene_id)):
            return scene_id
    raise VNError("no untranslated scene is available")


def work_package(config: dict[str, Any], scene_id: str) -> str:
    rows = load_scene(config, scene_id)
    sources = source_by_id(config)
    languages = config["project"]["source_languages"]
    lines = [
        f"# Translation Work: {scene_id}",
        "",
        f"Base hash: {scene_hash(config, rows)}",
        "",
        "Translate every [EDIT] row. Read the entire scene first.",
        "Write translation_patch metadata first, then one object per editable segment.",
        "Segment rows contain only id, translation, status, flags, confidence.",
        "Status must be draft. Preserve protected tokens exactly.",
        "",
        "## Safe Constraints",
        "",
    ]
    rules = safe_rules(config)
    lines.extend(f"- {rule}" for rule in rules)
    if not rules:
        lines.append("- None configured.")
    lines.extend(["", "## Scene", ""])
    for row in rows:
        record = sources[row["source_id"]]
        mode = "EDIT" if row.get("status") in {"todo", "draft"} else "CONTEXT"
        lines.append(
            f"### [{mode}] {row['id']} | speaker={row.get('speaker', '')!r} | "
            f"status={row.get('status')} | flags={row.get('flags', [])}"
        )
        texts = record.get("texts", {})
        for language in languages:
            lines.append(f"- {language}: {texts.get(language, '')}")
        lines.append(f"- protected_tokens: {record.get('protected_tokens', [])}")
        lines.append(f"- current_target: {row.get('translation', '')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def command_work_next(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    scene_id = choose_scene(config, args.scene_id)
    output = build_path(args.output)
    write_text_atomic(output, work_package(config, scene_id))
    print(f"Wrote {output.relative_to(ROOT)} for {scene_id}")
    return 0


def patch_validation(
    config: dict[str, Any], scene_id: str, patch_path: Path
) -> tuple[list[str], list[dict[str, Any]]]:
    data = read_jsonl(patch_path)
    if not data:
        return ["patch is empty"], []
    meta, patch = data[0], data[1:]
    rows = load_scene(config, scene_id)
    sources = source_by_id(config)
    by_id = {row["id"]: row for row in rows}
    editable = {row["id"] for row in rows if row.get("status") in {"todo", "draft"}}
    errors: list[str] = []
    patch_ids: list[str] = []
    allowed_keys = {"id", "translation", "status", "flags", "confidence"}
    allowed_flags = allowed_values(config, "flags")
    if set(meta) - {"type", "scene_id", "base_sha256"}:
        errors.append("patch metadata has unknown fields")
    if meta.get("type") != "translation_patch" or meta.get("scene_id") != scene_id:
        errors.append("invalid translation patch metadata")
    if meta.get("base_sha256") != scene_hash(config, rows):
        errors.append("translation patch base hash is stale")
    for index, item in enumerate(patch, 1):
        unknown_keys = sorted(set(item) - allowed_keys)
        if unknown_keys:
            errors.append(f"patch row {index}: unknown fields {unknown_keys}")
        segment = item.get("id")
        if not isinstance(segment, str) or segment not in by_id:
            errors.append(f"patch row {index}: unknown id {segment!r}")
            continue
        patch_ids.append(segment)
        if item.get("status") != "draft":
            errors.append(f"{segment}: patch status must be draft")
        translation = item.get("translation")
        if not isinstance(translation, str) or not translation.strip():
            errors.append(f"{segment}: translation must be nonempty")
            continue
        flags = item.get("flags", [])
        if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
            errors.append(f"{segment}: flags must be a string list")
        else:
            unknown_flags = sorted(set(flags) - allowed_flags)
            if unknown_flags:
                errors.append(f"{segment}: unknown flags {unknown_flags}")
        confidence = item.get("confidence")
        if confidence not in {None, "low", "medium", "high"}:
            errors.append(f"{segment}: invalid confidence {confidence!r}")
        record = sources[by_id[segment]["source_id"]]
        for message in check_protected(config, record, translation):
            errors.append(f"{segment}: {message}")
    if len(patch_ids) != len(set(patch_ids)):
        errors.append("patch contains duplicate ids")
    if set(patch_ids) != editable:
        missing = sorted(editable - set(patch_ids))
        extra = sorted(set(patch_ids) - editable)
        errors.append(f"patch must cover exactly editable ids; missing={missing}, extra={extra}")
    return errors, patch


def command_work_check(args: argparse.Namespace) -> int:
    config = load_config()
    patch_path = build_path(args.patch)
    data = read_jsonl(patch_path)
    if not data or data[0].get("type") != "translation_patch":
        raise VNError("patch metadata is missing")
    scene_id = data[0].get("scene_id")
    if not isinstance(scene_id, str):
        raise VNError("patch metadata has no scene_id")
    errors, _ = patch_validation(config, scene_id, patch_path)
    for message in errors:
        print(f"ERROR: {message}")
    print(f"Checked {max(0, len(data) - 1)} patch rows: {len(errors)} errors")
    return 1 if errors else 0


def command_apply_translation(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    if not args.actor.strip():
        raise VNError("actor must be nonempty")
    patch_path = build_path(args.patch)
    errors, patch = patch_validation(config, args.scene_id, patch_path)
    if errors:
        raise VNError("patch rejected:\n" + "\n".join(errors))
    path = scene_file(config, args.scene_id)
    rows = load_scene(config, args.scene_id)
    changes = {item["id"]: item for item in patch}
    updated: list[dict[str, Any]] = []
    for row in rows:
        item = changes.get(row["id"])
        if item:
            row = dict(row)
            row["translation"] = item["translation"]
            row["status"] = "draft"
            row["flags"] = item.get("flags", [])
            row["confidence"] = item.get("confidence")
            row["last_actor"] = args.actor
            row["authors"] = list(dict.fromkeys([*row.get("authors", []), args.actor]))
        updated.append(row)
    write_jsonl_atomic(path, updated)
    print(f"Applied {len(changes)} translations to {args.scene_id}")
    return 0


def append_review_event(config: dict[str, Any], event: dict[str, Any]) -> None:
    path = cfg_path(config, "review_ledger")
    rows = read_jsonl(path, missing_ok=True)
    rows.append(event)
    write_jsonl_atomic(path, rows)


def review_package(config: dict[str, Any], scene_id: str) -> str:
    rows = load_scene(config, scene_id)
    if any(not row.get("translation") for row in rows):
        raise VNError(f"scene {scene_id} is not fully translated")
    sources = source_by_id(config)
    languages = config["project"]["source_languages"]
    lines = [
        f"# Source-Aware Review: {scene_id}",
        "",
        f"Base hash: {scene_hash(config, rows)}",
        "",
        "Review independently. Do not use translator reasoning.",
        "Return metadata plus one JSONL object per issue.",
        "",
        "## Safe Constraints",
        "",
    ]
    rules = safe_rules(config)
    lines.extend(f"- {rule}" for rule in rules)
    if not rules:
        lines.append("- None configured.")
    lines.extend(["", "## Scene", ""])
    for row in rows:
        source = sources[row["source_id"]]
        lines.append(
            f"### {row['id']} | speaker={row.get('speaker', '')!r} | flags={row.get('flags', [])}"
        )
        for language in languages:
            lines.append(f"- {language}: {source['texts'].get(language, '')}")
        lines.append(f"- protected_tokens: {source.get('protected_tokens', [])}")
        lines.append(f"- target: {row.get('translation', '')}")
        lines.append("")
    return "\n".join(lines) + "\n"


def command_review_package(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    output = build_path(args.output)
    write_text_atomic(output, review_package(config, args.scene_id))
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


def command_review_import(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    if not args.reviewer.strip():
        raise VNError("reviewer must be nonempty")
    rows = read_jsonl(build_path(args.issues))
    if not rows:
        raise VNError("review issue file is empty")
    reject_forbidden_tracked_keys(rows, "review import")
    meta, issues = rows[0], rows[1:]
    if set(meta) - {"type", "review_id", "scene_id", "base_sha256", "verdict"}:
        raise VNError("review metadata has unknown fields")
    review_id = meta.get("review_id")
    if meta.get("type") != "review" or not isinstance(review_id, str):
        raise VNError("first row must be review metadata")
    if meta.get("scene_id") != args.scene_id:
        raise VNError("review scene_id does not match command")
    if review_id in review_runs(config):
        raise VNError(f"review already exists: {review_id}")
    current = load_scene(config, args.scene_id)
    authors = {
        actor
        for row in current
        for actor in row.get("authors", [])
        if isinstance(actor, str) and actor
    }
    if args.reviewer in authors:
        raise VNError("reviewer must be independent from all current scene authors")
    if meta.get("base_sha256") != scene_hash(config, current):
        raise VNError("review base hash is stale")
    segment_ids = {row["id"] for row in current}
    issue_ids: set[str] = set()
    severities = {"critical", "major", "minor", "preference"}
    for issue in issues:
        if set(issue) - {
            "issue_id",
            "segment_id",
            "severity",
            "message",
            "suggested_translation",
        }:
            raise VNError("review issue has unknown fields")
        issue_id = issue.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id:
            raise VNError("review issue has no issue_id")
        if issue_id in issue_ids:
            raise VNError(f"duplicate issue_id: {issue_id}")
        issue_ids.add(issue_id)
        if issue.get("segment_id") not in segment_ids:
            raise VNError(f"{issue_id}: unknown segment_id")
        if issue.get("severity") not in severities:
            raise VNError(f"{issue_id}: invalid severity")
        if not isinstance(issue.get("message"), str) or not issue["message"]:
            raise VNError(f"{issue_id}: message is required")
        validate_tracked_narrative(config, issue["message"], f"{issue_id} message")
        suggested = issue.get("suggested_translation")
        if suggested is not None and not isinstance(suggested, str):
            raise VNError(f"{issue_id}: suggested_translation must be a string")
    verdict = meta.get("verdict")
    if verdict not in {"accept", "revise"}:
        raise VNError("review verdict must be accept or revise")
    if verdict == "accept" and issues:
        raise VNError("accept review cannot contain issues")
    append_review_event(
        config,
        {
            "event": "review_imported",
            "review_id": review_id,
            "scene_id": args.scene_id,
            "base_sha256": meta["base_sha256"],
            "verdict": verdict,
            "reviewer": args.reviewer,
            "issues": issues,
            "timestamp": now_utc(),
        },
    )
    print(f"Imported {review_id}: {len(issues)} issues")
    return 0


def get_run(config: dict[str, Any], review_id: str) -> dict[str, Any]:
    runs = review_runs(config)
    if review_id not in runs:
        raise VNError(f"unknown review: {review_id}")
    return runs[review_id]


def open_issue_ids(run: dict[str, Any]) -> set[str]:
    if run.get("closed"):
        return set()
    if run.get("last_event") == "review_rechecked":
        recheck = run.get("rechecks", [])[-1]
        if recheck.get("verdict") == "revise":
            return set(recheck.get("open_issue_ids", []))
        return set()
    if run.get("last_event") == "review_resolved":
        return set()
    return {issue["issue_id"] for issue in run.get("issues", [])}


def command_review_fix(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    run = get_run(config, args.review_id)
    if run.get("closed"):
        raise VNError("review is already closed")
    current = load_scene(config, run["scene_id"])
    by_id = {row["id"]: row for row in current}
    expected = open_issue_ids(run)
    issues = [issue for issue in run["issues"] if issue["issue_id"] in expected]
    lines = [
        f"# Review Fix: {args.review_id}",
        "",
        f"Scene: {run['scene_id']}",
        f"Base hash: {scene_hash(config, current)}",
        "",
        "Resolve every listed issue exactly once. Use applied or rejected with a reason.",
        "",
    ]
    for issue in issues:
        segment = by_id[issue["segment_id"]]
        lines.extend(
            [
                f"## {issue['issue_id']} ({issue['severity']})",
                "",
                issue["message"],
                "",
                f"- segment_id: {issue['segment_id']}",
                f"- current_target: {segment.get('translation', '')}",
                f"- current_flags: {segment.get('flags', [])}",
                f"- suggested_target: {issue.get('suggested_translation', '')}",
                "",
            ]
        )
    output = build_path(args.output)
    write_text_atomic(output, "\n".join(lines) + "\n")
    print(f"Wrote {output.relative_to(ROOT)} for {len(issues)} open issues")
    return 0


def command_review_resolve(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    if not args.actor.strip():
        raise VNError("actor must be nonempty")
    run = get_run(config, args.review_id)
    if run.get("closed"):
        raise VNError("review is already closed")
    data = read_jsonl(build_path(args.resolutions))
    if not data:
        raise VNError("resolution file is empty")
    reject_forbidden_tracked_keys(data, "review resolution")
    meta, resolutions = data[0], data[1:]
    if set(meta) - {"type", "review_id", "base_sha256"}:
        raise VNError("resolution metadata has unknown fields")
    if meta.get("type") != "resolutions" or meta.get("review_id") != args.review_id:
        raise VNError("invalid resolution metadata")
    current = load_scene(config, run["scene_id"])
    current_hash = scene_hash(config, current)
    if meta.get("base_sha256") != current_hash:
        raise VNError("resolution base hash is stale")
    expected = open_issue_ids(run)
    received = [row.get("issue_id") for row in resolutions]
    if len(received) != len(set(received)) or set(received) != expected:
        raise VNError(
            f"resolutions must cover open issues exactly; expected={sorted(expected)}, "
            f"received={sorted(item for item in received if isinstance(item, str))}"
        )
    by_id = {row["id"]: dict(row) for row in current}
    sources = source_by_id(config)
    flags_allowed = allowed_values(config, "flags")
    final_changes: dict[str, dict[str, Any]] = {}
    for resolution in resolutions:
        issue_id = resolution["issue_id"]
        if set(resolution) - {"issue_id", "disposition", "reason", "changes"}:
            raise VNError(f"{issue_id}: resolution has unknown fields")
        disposition = resolution.get("disposition")
        if disposition not in {"applied", "rejected"}:
            raise VNError(f"{issue_id}: invalid disposition")
        if not isinstance(resolution.get("reason"), str) or not resolution["reason"]:
            raise VNError(f"{issue_id}: reason is required")
        validate_tracked_narrative(config, resolution["reason"], f"{issue_id} reason")
        changes = resolution.get("changes", [])
        if not isinstance(changes, list):
            raise VNError(f"{issue_id}: changes must be a list")
        if disposition == "rejected" and changes:
            raise VNError(f"{issue_id}: rejected issue cannot contain changes")
        for change in changes:
            if not isinstance(change, dict):
                raise VNError(f"{issue_id}: change must be an object")
            if set(change) - {"id", "translation", "flags"}:
                raise VNError(f"{issue_id}: change has unknown fields")
            segment = change.get("id")
            if segment not in by_id:
                raise VNError(f"{issue_id}: unknown changed segment {segment!r}")
            translation = change.get("translation")
            flags = change.get("flags", by_id[segment].get("flags", []))
            if not isinstance(translation, str) or not translation.strip():
                raise VNError(f"{issue_id}: changed translation must be nonempty")
            if not isinstance(flags, list) or set(flags) - flags_allowed:
                raise VNError(f"{issue_id}: invalid flags")
            record = sources[by_id[segment]["source_id"]]
            protected_errors = check_protected(config, record, translation)
            if protected_errors:
                raise VNError(f"{issue_id}: {'; '.join(protected_errors)}")
            proposed = {"translation": translation, "flags": flags}
            if segment in final_changes and final_changes[segment] != proposed:
                raise VNError(f"conflicting changes for {segment}")
            final_changes[segment] = proposed
    updated: list[dict[str, Any]] = []
    for row in current:
        change = final_changes.get(row["id"])
        if change:
            row = dict(row)
            row.update(change)
            row["status"] = "draft"
            row["last_actor"] = args.actor
            row["authors"] = list(dict.fromkeys([*row.get("authors", []), args.actor]))
        updated.append(row)
    if final_changes:
        for row in updated:
            if row.get("translation") and row.get("status") != "todo":
                row["status"] = "draft"
    result_hash = scene_hash(config, updated)
    path = scene_file(config, run["scene_id"])
    write_jsonl_atomic(path, updated)
    try:
        append_review_event(
            config,
            {
                "event": "review_resolved",
                "review_id": args.review_id,
                "scene_id": run["scene_id"],
                "base_sha256": current_hash,
                "result_sha256": result_hash,
                "actor": args.actor,
                "resolutions": resolutions,
                "timestamp": now_utc(),
            },
        )
    except Exception:
        write_jsonl_atomic(path, current)
        raise
    print(f"Resolved {len(resolutions)} issues; changed {len(final_changes)} segments")
    return 0


def command_review_recheck(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    run = get_run(config, args.review_id)
    if run.get("closed"):
        raise VNError("review is already closed")
    if run.get("issues") and run.get("last_event") != "review_resolved":
        raise VNError("review has not been resolved")
    current = load_scene(config, run["scene_id"])
    package = review_package(config, run["scene_id"])
    header = [
        f"# Review Recheck: {args.review_id}",
        "",
        f"Base hash: {scene_hash(config, current)}",
        "",
        "Check every original issue and the latest resolutions against source.",
        "Return one verdict JSON object with review_id, base_sha256, verdict, open_issue_ids, notes.",
        "",
        "## Original Issues",
        "",
    ]
    for issue in run.get("issues", []):
        header.append(
            f"- {issue['issue_id']} [{issue['severity']}] {issue['segment_id']}: {issue['message']}"
        )
    header.extend(["", "## Current Scene", "", package])
    output = build_path(args.output)
    write_text_atomic(output, "\n".join(header))
    print(f"Wrote {output.relative_to(ROOT)}")
    return 0


def command_review_close(args: argparse.Namespace) -> int:
    config = load_config()
    require_roundtrip(config)
    if not args.reviewer.strip():
        raise VNError("reviewer must be nonempty")
    run = get_run(config, args.review_id)
    if run.get("closed"):
        raise VNError("review is already closed")
    verdict_rows = read_jsonl(build_path(args.verdict))
    if len(verdict_rows) != 1:
        raise VNError("verdict file must contain one JSON object")
    verdict = verdict_rows[0]
    reject_forbidden_tracked_keys(verdict, "review verdict")
    if set(verdict) - {"review_id", "base_sha256", "verdict", "open_issue_ids", "notes"}:
        raise VNError("verdict has unknown fields")
    notes = verdict.get("notes", "")
    if not isinstance(notes, str):
        raise VNError("verdict notes must be a string")
    if notes.strip():
        validate_tracked_narrative(config, notes, "verdict notes")
    if verdict.get("review_id") != args.review_id:
        raise VNError("verdict review_id does not match")
    current = load_scene(config, run["scene_id"])
    authors = {
        actor
        for row in current
        for actor in row.get("authors", [])
        if isinstance(actor, str) and actor
    }
    if args.reviewer in authors:
        raise VNError("recheck reviewer must be independent from all current scene authors")
    current_hash = scene_hash(config, current)
    if verdict.get("base_sha256") != current_hash:
        raise VNError("verdict base hash is stale")
    decision = verdict.get("verdict")
    open_ids = verdict.get("open_issue_ids", [])
    all_ids = {issue["issue_id"] for issue in run.get("issues", [])}
    if not isinstance(open_ids, list) or not all(isinstance(item, str) for item in open_ids):
        raise VNError("open_issue_ids must be a string list")
    if set(open_ids) - all_ids:
        raise VNError("verdict references unknown issue IDs")
    if run.get("issues") and run.get("last_event") != "review_resolved":
        raise VNError("open or reopened review issues must be resolved before close")
    if decision == "revise":
        if not open_ids:
            raise VNError("revise verdict requires open_issue_ids")
        append_review_event(
            config,
            {
                "event": "review_rechecked",
                "review_id": args.review_id,
                "scene_id": run["scene_id"],
                "base_sha256": current_hash,
                "verdict": "revise",
                "open_issue_ids": open_ids,
                "reviewer": args.reviewer,
                "notes": verdict.get("notes", ""),
                "timestamp": now_utc(),
            },
        )
        print(f"Recorded revision request with {len(open_ids)} open issues")
        return 0
    if decision != "accept" or open_ids:
        raise VNError("accept verdict requires an empty open_issue_ids list")
    updated: list[dict[str, Any]] = []
    for row in current:
        if row.get("status") == "draft":
            row = dict(row)
            row["status"] = "reviewed"
        updated.append(row)
    path = scene_file(config, run["scene_id"])
    write_jsonl_atomic(path, updated)
    try:
        append_review_event(
            config,
            {
                "event": "review_closed",
                "review_id": args.review_id,
                "scene_id": run["scene_id"],
                "base_sha256": current_hash,
                "reviewer": args.reviewer,
                "notes": verdict.get("notes", ""),
                "timestamp": now_utc(),
            },
        )
    except Exception:
        write_jsonl_atomic(path, current)
        raise
    print(f"Closed {args.review_id}; {len(updated)} segments are reviewed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Engine-neutral VN translation control tool")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize empty project state")
    init.add_argument("--title")
    init.add_argument("--source-language", action="append")
    init.add_argument("--target-language")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    ingest = sub.add_parser("ingest", help="build or refresh canonical segments")
    ingest.set_defaults(func=command_ingest)
    validate = sub.add_parser("validate")
    validate.set_defaults(func=command_validate)
    stats = sub.add_parser("stats")
    stats.set_defaults(func=command_stats)
    brief = sub.add_parser("brief")
    brief.set_defaults(func=command_brief)
    questions = sub.add_parser("questions")
    questions.add_argument("--import-file")
    questions.add_argument("--actor")
    questions.set_defaults(func=command_questions)
    index = sub.add_parser("index")
    index.set_defaults(func=command_index)

    work = sub.add_parser("work")
    work_sub = work.add_subparsers(dest="work_command", required=True)
    work_next = work_sub.add_parser("next")
    work_next.add_argument("scene_id", nargs="?")
    work_next.add_argument("-o", "--output", required=True)
    work_next.set_defaults(func=command_work_next)
    work_check = work_sub.add_parser("check")
    work_check.add_argument("patch")
    work_check.set_defaults(func=command_work_check)

    apply_translation = sub.add_parser("apply-translation")
    apply_translation.add_argument("scene_id")
    apply_translation.add_argument("patch")
    apply_translation.add_argument("--actor", required=True)
    apply_translation.set_defaults(func=command_apply_translation)

    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_package_parser = review_sub.add_parser("package")
    review_package_parser.add_argument("scene_id")
    review_package_parser.add_argument("-o", "--output", required=True)
    review_package_parser.set_defaults(func=command_review_package)

    review_import_parser = review_sub.add_parser("import")
    review_import_parser.add_argument("scene_id")
    review_import_parser.add_argument("issues")
    review_import_parser.add_argument("--reviewer", required=True)
    review_import_parser.set_defaults(func=command_review_import)

    review_fix_parser = review_sub.add_parser("fix")
    review_fix_parser.add_argument("review_id")
    review_fix_parser.add_argument("-o", "--output", required=True)
    review_fix_parser.set_defaults(func=command_review_fix)

    review_resolve_parser = review_sub.add_parser("resolve")
    review_resolve_parser.add_argument("review_id")
    review_resolve_parser.add_argument("resolutions")
    review_resolve_parser.add_argument("--actor", required=True)
    review_resolve_parser.set_defaults(func=command_review_resolve)

    review_recheck_parser = review_sub.add_parser("recheck")
    review_recheck_parser.add_argument("review_id")
    review_recheck_parser.add_argument("-o", "--output", required=True)
    review_recheck_parser.set_defaults(func=command_review_recheck)

    review_close_parser = review_sub.add_parser("close")
    review_close_parser.add_argument("review_id")
    review_close_parser.add_argument("verdict")
    review_close_parser.add_argument("--reviewer", required=True)
    review_close_parser.set_defaults(func=command_review_close)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        sys.stderr.reconfigure(encoding="utf-8", errors="strict")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except VNError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
