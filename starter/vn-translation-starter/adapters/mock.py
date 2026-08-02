#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def project_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        raise ValueError("mock adapter paths must stay inside the project")
    candidate = (ROOT / path).resolve()
    candidate.relative_to(ROOT.resolve())
    return candidate


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no}: object required")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def project_languages() -> list[str]:
    path = ROOT / "config" / "project.yaml"
    if not path.exists():
        return ["source", "reference"]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data["project"]["source_languages"])


def receipt_path() -> Path:
    path = ROOT / "config" / "project.yaml"
    if not path.exists():
        return ROOT / "build" / "roundtrip-receipt.json"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return project_path(data["paths"]["roundtrip_receipt"])


def bind_pristine_hash(source_hash: str) -> None:
    path = ROOT / "config" / "project.yaml"
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    configured = data["project"].get("pristine_sha256")
    if configured not in {None, source_hash}:
        raise ValueError("source hash does not match configured pristine_sha256")
    data["project"]["pristine_sha256"] = source_hash
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def command_seed(args: argparse.Namespace) -> int:
    path = project_path(args.output)
    if path.exists() and path.stat().st_size and not args.force:
        print(f"ERROR: {path} already contains data; use --force", file=sys.stderr)
        return 1
    languages = project_languages()

    def texts(primary: str, reference: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for index, language in enumerate(languages):
            values[language] = primary if index == 0 else reference
        return values

    rows = [
        {
            "source_id": "SRC_000001",
            "scene_id": "SCN0001",
            "order": 1,
            "speaker": "Guide",
            "texts": texts("Hello, {name}.", "A direct greeting."),
            "protected_tokens": ["{name}"],
            "meta": {"mock": True},
        },
        {
            "source_id": "SRC_000002",
            "scene_id": "SCN0001",
            "order": 2,
            "speaker": "Visitor",
            "texts": texts("How are you?", "A casual question."),
            "protected_tokens": [],
            "meta": {"mock": True},
        },
        {
            "source_id": "SRC_000003",
            "scene_id": "SCN0002",
            "order": 3,
            "speaker": "Guide",
            "texts": texts("Choose $(1) or $(2).", "Two choices are offered."),
            "protected_tokens": ["$(1)", "$(2)"],
            "meta": {"mock": True},
        },
        {
            "source_id": "SRC_000004",
            "scene_id": "SCN0002",
            "order": 4,
            "speaker": "Visitor",
            "texts": texts("X", "A single-character source line."),
            "protected_tokens": [],
            "meta": {"mock": True},
        },
    ]
    write_jsonl(path, rows)
    print(f"Wrote {len(rows)} synthetic records to {path}")
    return 0


def command_roundtrip(args: argparse.Namespace) -> int:
    source_path = project_path(args.source)
    output_dir = project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_raw = source_path.read_bytes()
    rows = read_jsonl(source_path)
    catalog_hash = sha256_bytes(canonical_bytes(rows))

    container = {
        "adapter": "mock-v1",
        "record_count": len(rows),
        "records": rows,
    }
    container_path = output_dir / "rebuilt.mock.json"
    container_path.write_text(
        json.dumps(container, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    parsed = json.loads(container_path.read_text(encoding="utf-8"))["records"]
    readback_path = output_dir / "readback.jsonl"
    write_jsonl(readback_path, parsed)

    verified = canonical_bytes(rows) == canonical_bytes(parsed)
    receipt = {
        "adapter": "mock-v1",
        "verified": verified,
        "source_sha256": sha256_bytes(source_raw),
        "catalog_sha256": catalog_hash,
        "record_count": len(rows),
        "order_preserved": [row.get("source_id") for row in rows]
        == [row.get("source_id") for row in parsed],
        "smoke_test": True,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    bind_pristine_hash(receipt["source_sha256"])
    receipt_file = receipt_path()
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = receipt_file.with_name(f".{receipt_file.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(receipt_file)
    print(
        f"Round trip {'verified' if verified else 'failed'}: "
        f"{len(rows)} records, {catalog_hash}"
    )
    return 0 if verified else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthetic adapter for starter verification")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("output")
    seed.add_argument("--force", action="store_true")
    seed.set_defaults(func=command_seed)
    roundtrip = sub.add_parser("roundtrip")
    roundtrip.add_argument("source")
    roundtrip.add_argument("output_dir")
    roundtrip.set_defaults(func=command_roundtrip)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        sys.stderr.reconfigure(encoding="utf-8", errors="strict")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
