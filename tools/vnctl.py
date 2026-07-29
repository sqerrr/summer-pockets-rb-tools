#!/usr/bin/env python3
"""Minimal project CLI for a VN translation repository.

The canonical data stays in JSONL/YAML/Markdown. SQLite is rebuilt as an index.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ALLOWED_STATUSES = {"todo", "draft", "reviewed", "playable", "approved", "lqa"}
DEFAULT_REQUIRED = {"id", "file_id", "scene_id", "order", "source", "translation", "status"}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    if yaml is None:
        raise RuntimeError("PyYAML is required. Run: python -m pip install -r requirements.txt")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return default if data is None else data


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            item["__source_file"] = str(path)
            item["__source_line"] = line_no
            rows.append(item)
    return rows


def iter_segment_files(root: Path, config: dict[str, Any]) -> list[Path]:
    rel = config.get("paths", {}).get("segments", "translation/segments")
    base = root / rel
    return sorted(base.glob("**/*.jsonl")) if base.exists() else []


def load_segments(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in iter_segment_files(root, config):
        rows.extend(read_jsonl(path))
    return rows


def load_config(root: Path) -> dict[str, Any]:
    path = root / "config/project.yaml"
    if not path.exists():
        example = root / "config/project.example.yaml"
        raise FileNotFoundError(
            f"Missing {path}. Copy and edit {example.name}: "
            f"cp config/project.example.yaml config/project.yaml"
        )
    return read_yaml(path, {})


def clean_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("__")}


def validate(root: Path, config: dict[str, Any]) -> int:
    qa = read_yaml(root / "config/qa-rules.yaml", {}) or {}
    required = set(qa.get("required_segment_fields", DEFAULT_REQUIRED))
    allowed_statuses = set(qa.get("allowed_statuses", ALLOWED_STATUSES))
    allowed_flags = set(qa.get("allowed_flags", []))
    patterns = [re.compile(p) for p in qa.get("protected_patterns", [])]

    errors: list[str] = []
    warnings: list[str] = []
    segments = load_segments(root, config)
    seen: dict[str, tuple[str, int]] = {}
    by_scene: dict[str, list[dict[str, Any]]] = defaultdict(list)

    if not segments:
        warnings.append("No segment JSONL files found.")

    for row in segments:
        loc = f"{row.get('__source_file')}:{row.get('__source_line')}"
        missing = sorted(required - row.keys())
        if missing:
            errors.append(f"{loc}: missing fields: {', '.join(missing)}")
            continue
        sid = str(row["id"])
        if sid in seen:
            errors.append(f"{loc}: duplicate id {sid}; first at {seen[sid]}")
        else:
            seen[sid] = (str(row["__source_file"]), int(row["__source_line"]))
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            errors.append(f"{loc}: non-portable id: {sid}")
        if row["status"] not in allowed_statuses:
            errors.append(f"{loc}: invalid status {row['status']!r}")
        flags = row.get("flags", []) or []
        if not isinstance(flags, list):
            errors.append(f"{loc}: flags must be a list")
        elif allowed_flags:
            unknown = sorted(set(flags) - allowed_flags)
            if unknown:
                errors.append(f"{loc}: unknown flags: {', '.join(unknown)}")
        if row["status"] != "todo" and not str(row.get("translation", "")).strip():
            errors.append(f"{loc}: status {row['status']} but translation is empty")
        if row["status"] == "todo" and str(row.get("translation", "")).strip():
            warnings.append(f"{loc}: translation exists but status is todo")
        if not isinstance(row.get("order"), int):
            errors.append(f"{loc}: order must be integer")
        by_scene[str(row["scene_id"])].append(row)

        # Generic protected-token check only when translated.
        if str(row.get("translation", "")).strip():
            src = str(row.get("source", ""))
            dst = str(row.get("translation", ""))
            for pattern in patterns:
                src_tokens = pattern.findall(src)
                dst_tokens = pattern.findall(dst)
                if src_tokens != dst_tokens:
                    warnings.append(
                        f"{loc}: protected-token mismatch for {pattern.pattern}: "
                        f"source={src_tokens!r} target={dst_tokens!r}"
                    )

    for scene_id, rows in by_scene.items():
        orders = [r["order"] for r in rows if isinstance(r.get("order"), int)]
        if len(orders) != len(set(orders)):
            errors.append(f"scene {scene_id}: duplicate order values")

    for msg in errors:
        eprint("ERROR:", msg)
    for msg in warnings:
        eprint("WARN:", msg)
    print(f"Validated {len(segments)} segments: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def db_path(root: Path, config: dict[str, Any]) -> Path:
    return root / config.get("paths", {}).get("database", "database/knowledge.db")


def index_project(root: Path, config: dict[str, Any]) -> int:
    dest = db_path(root, config)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    con = sqlite3.connect(dest)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE segments (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
            ord INTEGER NOT NULL,
            speaker TEXT,
            source TEXT NOT NULL,
            translation TEXT NOT NULL,
            status TEXT NOT NULL,
            flags_json TEXT NOT NULL,
            decision_ids_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE INDEX idx_segments_scene ON segments(scene_id, ord);
        CREATE INDEX idx_segments_speaker ON segments(speaker);
        CREATE INDEX idx_segments_status ON segments(status);
        CREATE VIRTUAL TABLE segments_fts USING fts5(
            id UNINDEXED,
            scene_id UNINDEXED,
            speaker,
            source,
            translation,
            tokenize='unicode61'
        );
        CREATE TABLE documents (
            path TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE documents_fts USING fts5(
            path UNINDEXED,
            kind UNINDEXED,
            content,
            tokenize='unicode61'
        );
        CREATE TABLE glossary (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            preferred_ru TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE decisions (
            id TEXT PRIMARY KEY,
            type TEXT,
            status TEXT,
            decision TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE summaries (
            scene_id TEXT PRIMARY KEY,
            safe_summary TEXT,
            payload_json TEXT NOT NULL
        );
        """
    )

    segments = load_segments(root, config)
    for row in segments:
        r = clean_meta(row)
        cur.execute(
            "INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["id"], r["file_id"], r["scene_id"], r["order"], r.get("speaker"),
                r.get("source", ""), r.get("translation", ""), r.get("status", "todo"),
                json.dumps(r.get("flags", []), ensure_ascii=False),
                json.dumps(r.get("decision_ids", []), ensure_ascii=False),
                json.dumps(r.get("metadata", {}), ensure_ascii=False),
            ),
        )
        cur.execute(
            "INSERT INTO segments_fts VALUES (?,?,?,?,?)",
            (r["id"], r["scene_id"], r.get("speaker") or "", r.get("source", ""), r.get("translation", "")),
        )

    docs_root = root / "docs"
    if docs_root.exists():
        for path in sorted(docs_root.glob("**/*.md")):
            content = path.read_text(encoding="utf-8-sig")
            rel = path.relative_to(root).as_posix()
            kind = "character" if "/characters/" in f"/{rel}" else "documentation"
            cur.execute("INSERT INTO documents VALUES (?,?,?)", (rel, kind, content))
            cur.execute("INSERT INTO documents_fts VALUES (?,?,?)", (rel, kind, content))

    glossary_path = root / config.get("paths", {}).get("glossary", "docs/glossary.yaml")
    glossary = read_yaml(glossary_path, []) or []
    if not isinstance(glossary, list):
        raise ValueError(f"{glossary_path}: expected a YAML list")
    for item in glossary:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        cur.execute(
            "INSERT INTO glossary VALUES (?,?,?,?,?)",
            (
                item["id"], str(item.get("source", "")), str(item.get("preferred_ru", "")),
                str(item.get("status", "proposed")), json.dumps(item, ensure_ascii=False),
            ),
        )

    decisions_path = root / config.get("paths", {}).get("decisions", "docs/decisions.jsonl")
    for item in read_jsonl(decisions_path):
        item = clean_meta(item)
        if not item.get("id"):
            continue
        cur.execute(
            "INSERT INTO decisions VALUES (?,?,?,?,?)",
            (
                item["id"], item.get("type"), item.get("status"), item.get("decision"),
                json.dumps(item, ensure_ascii=False),
            ),
        )

    summaries_path = root / config.get("paths", {}).get("summaries", "docs/scene-summaries.jsonl")
    for item in read_jsonl(summaries_path):
        item = clean_meta(item)
        if not item.get("scene_id"):
            continue
        cur.execute(
            "INSERT INTO summaries VALUES (?,?,?)",
            (item["scene_id"], item.get("safe_summary", ""), json.dumps(item, ensure_ascii=False)),
        )

    con.commit()
    con.close()
    print(f"Indexed {len(segments)} segments into {dest}")
    return 0


def stats(root: Path, config: dict[str, Any]) -> int:
    segments = load_segments(root, config)
    by_status = Counter(str(r.get("status", "missing")) for r in segments)
    by_scene = Counter(str(r.get("scene_id", "missing")) for r in segments)
    speakers = Counter(str(r.get("speaker")) for r in segments if r.get("speaker"))
    translated = sum(1 for r in segments if str(r.get("translation", "")).strip())
    total = len(segments)
    pct = 100.0 * translated / total if total else 0.0
    print(f"Segments: {total}")
    print(f"Scenes: {len(by_scene)}")
    print(f"Translated: {translated} ({pct:.1f}%)")
    print("Statuses:")
    for key, value in sorted(by_status.items()):
        print(f"  {key}: {value}")
    print("Top speakers:")
    for key, value in speakers.most_common(15):
        print(f"  {key}: {value}")
    return 0



def load_scenes(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    rel = config.get("paths", {}).get("scenes", "translation/scenes.jsonl")
    return [clean_meta(x) for x in read_jsonl(root / rel)]


def linked_decisions(db: Path, segment_ids: set[str]) -> list[dict[str, Any]]:
    if not segment_ids:
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    out: list[dict[str, Any]] = []
    try:
        for row in con.execute("SELECT payload_json FROM decisions"):
            item = json.loads(row["payload_json"])
            linked = set(map(str, item.get("segment_ids", item.get("segments", []))))
            if linked & segment_ids:
                safe = {k: v for k, v in item.items() if k not in {"private_reason", "reason_private"}}
                out.append(safe)
    finally:
        con.close()
    return out


def approved_examples(db: Path, speakers: list[str], excluded_scene: str, limit_total: int) -> list[dict[str, Any]]:
    if not speakers or limit_total <= 0:
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    out: list[dict[str, Any]] = []
    try:
        per_speaker = max(1, limit_total // len(speakers))
        for speaker in speakers:
            rows = con.execute(
                """SELECT id, scene_id, speaker, source, translation, status
                   FROM segments
                   WHERE speaker=? AND scene_id<>? AND status IN ('approved','lqa')
                     AND translation<>''
                   ORDER BY rowid DESC LIMIT ?""",
                (speaker, excluded_scene, per_speaker),
            ).fetchall()
            out.extend(dict(r) for r in rows)
    finally:
        con.close()
    return out[:limit_total]


def character_doc(root: Path, config: dict[str, Any], speaker: str) -> str | None:
    base = root / config.get("paths", {}).get("characters", "docs/characters")
    if not base.exists():
        return None
    normalized = speaker.lower().replace("_", "-")
    candidates = [base / f"{normalized}.md", base / f"{speaker}.md", base / f"{speaker.lower()}.md"]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8-sig")
    # Conservative frontmatter scan.
    for path in base.glob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        if re.search(rf"(?mi)^id:\s*{re.escape(speaker)}\s*$", text):
            return text
    return None


def glossary_for_scene(root: Path, config: dict[str, Any], source_text: str) -> list[dict[str, Any]]:
    path = root / config.get("paths", {}).get("glossary", "docs/glossary.yaml")
    items = read_yaml(path, []) or []
    result = []
    for item in items if isinstance(items, list) else []:
        src = str(item.get("source", "")) if isinstance(item, dict) else ""
        if src and src in source_text:
            result.append(item)
    return result


def safe_constraints(root: Path, config: dict[str, Any], segment_ids: set[str]) -> list[dict[str, Any]]:
    path = root / config.get("paths", {}).get("private_constraints", "private/constraints.jsonl")
    out = []
    for row in read_jsonl(path):
        linked = set(map(str, row.get("segment_ids", [])))
        if linked & segment_ids and row.get("status", "active") == "active":
            out.append({
                "id": row.get("id"),
                "segment_ids": sorted(linked & segment_ids),
                "safe_rules": row.get("safe_rules", []),
            })
    return out


def build_context(root: Path, config: dict[str, Any], scene_id: str) -> str:
    db = db_path(root, config)
    if not db.exists():
        raise FileNotFoundError(f"Index not found: {db}. Run: python tools/vnctl.py index")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM segments WHERE scene_id=? ORDER BY ord", (scene_id,)).fetchall()
    if not rows:
        raise ValueError(f"Unknown or empty scene: {scene_id}")

    prev_n = int(config.get("workflow", {}).get("context_previous_segments", 20))
    next_n = int(config.get("workflow", {}).get("context_next_segments", 10))
    scene_items = load_scenes(root, config)
    scene_entry = next((x for x in scene_items if x.get("scene_id") == scene_id), {})
    previous_scene_id = scene_entry.get("previous_scene")
    next_scene_id = scene_entry.get("next_scene")

    if previous_scene_id:
        previous = con.execute(
            "SELECT * FROM segments WHERE scene_id=? ORDER BY ord DESC LIMIT ?",
            (previous_scene_id, prev_n),
        ).fetchall()[::-1]
    else:
        previous = []
    if next_scene_id:
        following = con.execute(
            "SELECT * FROM segments WHERE scene_id=? ORDER BY ord LIMIT ?",
            (next_scene_id, next_n),
        ).fetchall()
    else:
        following = []
    previous_summary = (
        con.execute("SELECT safe_summary FROM summaries WHERE scene_id=?", (previous_scene_id,)).fetchone()
        if previous_scene_id else None
    )
    con.close()

    source_text = "\n".join(str(r["source"]) for r in rows)
    speakers = sorted({str(r["speaker"]) for r in rows if r["speaker"]})
    seg_ids = {str(r["id"]) for r in rows}
    glossary = glossary_for_scene(root, config, source_text)
    constraints = safe_constraints(root, config, seg_ids)
    decisions = linked_decisions(db, seg_ids)
    example_limit = int(config.get("workflow", {}).get("similar_examples_limit", 20))
    examples = approved_examples(db, speakers, scene_id, example_limit)

    spec = (root / "docs/translation-spec.md").read_text(encoding="utf-8-sig")
    progress = read_yaml(root / "docs/progress.yaml", {}) or {}

    parts: list[str] = []
    parts.append(f"# Контекст сцены {scene_id}\n")
    parts.append("## Задача\nПеревести или проверить текущую сцену по правилам проекта. Не выводить будущие сюжетные сведения.\n")
    parts.append("## Текущий прогресс\n```yaml\n" + (yaml.safe_dump(progress, allow_unicode=True, sort_keys=False) if yaml else json.dumps(progress, ensure_ascii=False, indent=2)) + "```\n")
    parts.append("## Глобальная спецификация\n" + spec + "\n")
    parts.append("## Участники\n" + (", ".join(speakers) if speakers else "Повествование / неизвестно") + "\n")

    for speaker in speakers:
        doc = character_doc(root, config, speaker)
        if doc:
            parts.append(f"## Карточка персонажа: {speaker}\n{doc}\n")

    parts.append("## Релевантный глоссарий\n")
    if glossary:
        parts.append("```yaml\n" + (yaml.safe_dump(glossary, allow_unicode=True, sort_keys=False) if yaml else json.dumps(glossary, ensure_ascii=False, indent=2)) + "```\n")
    else:
        parts.append("Нет совпадений.\n")

    parts.append("## Безопасные сюжетные ограничения\n")
    if constraints:
        for item in constraints:
            parts.append(f"- {item['id']}: " + "; ".join(map(str, item.get("safe_rules", []))))
        parts.append("")
    else:
        parts.append("Нет.\n")

    parts.append("## Связанные утверждённые решения\n")
    if decisions:
        parts.append("```json\n" + json.dumps(decisions, ensure_ascii=False, indent=2) + "\n```\n")
    else:
        parts.append("Нет.\n")

    parts.append("## Утверждённые примеры речи\n")
    if examples:
        parts.append("```jsonl")
        for item in examples:
            parts.append(json.dumps(item, ensure_ascii=False))
        parts.append("```\n")
    else:
        parts.append("Пока нет.\n")

    if previous_summary and previous_summary["safe_summary"]:
        parts.append("## Безопасное резюме предыдущей сцены\n" + str(previous_summary["safe_summary"]) + "\n")

    def render_segments(title: str, segment_rows: Iterable[sqlite3.Row]) -> None:
        parts.append(f"## {title}\n```jsonl")
        for r in segment_rows:
            item = {
                "id": r["id"], "speaker": r["speaker"], "source": r["source"],
                "translation": r["translation"], "status": r["status"]
            }
            parts.append(json.dumps(item, ensure_ascii=False))
        parts.append("```\n")

    render_segments("Предыдущие сегменты", previous)
    render_segments("Текущая сцена", rows)
    render_segments("Следующие сегменты", following)

    output = "\n".join(parts)
    if "private_reason" in output:
        raise RuntimeError("Spoiler safety failure: private_reason leaked into context")
    return output


FINDING_AREAS = {"scene-pack", "engine", "font", "encoding", "tooling", "content"}
FINDING_KINDS = {"fact", "decision", "limitation"}
FINDING_STATUSES = {"verified", "assumed", "refuted"}
FINDING_REQUIRED = ("id", "date", "area", "kind", "title", "statement", "status")


def findings(root: Path, config: dict[str, Any]) -> int:
    """Validate the technical findings journal (docs/project/findings.jsonl)."""
    rel = config.get("paths", {}).get("findings", "docs/project/findings.jsonl")
    path = root / rel
    if not path.exists():
        eprint(f"ERROR: {rel} not found")
        return 2

    rows = read_jsonl(path)
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for line_no, row in enumerate(rows, start=1):
        tag = row.get("id") or f"line {line_no}"
        for field in FINDING_REQUIRED:
            if not row.get(field):
                errors.append(f"{tag}: missing field '{field}'")
        fid = row.get("id", "")
        if fid in seen:
            errors.append(f"{tag}: duplicate id")
        seen.add(fid)
        if row.get("area") not in FINDING_AREAS:
            errors.append(f"{tag}: unknown area '{row.get('area')}'")
        if row.get("kind") not in FINDING_KINDS:
            errors.append(f"{tag}: unknown kind '{row.get('kind')}'")
        if row.get("status") not in FINDING_STATUSES:
            errors.append(f"{tag}: unknown status '{row.get('status')}'")
        if row.get("status") == "verified" and not row.get("method"):
            errors.append(f"{tag}: status 'verified' requires a 'method'")
        if row.get("status") == "assumed" and not row.get("evidence"):
            warnings.append(f"{tag}: status 'assumed' without 'evidence'")

    for row in rows:
        sup = row.get("supersedes")
        if sup and sup not in seen:
            errors.append(f"{row.get('id')}: supersedes unknown id '{sup}'")

    for message in warnings:
        eprint(f"WARN: {message}")
    for message in errors:
        eprint(f"ERROR: {message}")
    print(f"Validated {len(rows)} findings: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("index")
    sub.add_parser("stats")
    sub.add_parser("findings")
    p_context = sub.add_parser("context")
    p_context.add_argument("scene_id")
    p_context.add_argument("-o", "--output", type=Path)

    args = parser.parse_args()
    root = args.root.resolve()
    try:
        config = load_config(root)
        if args.command == "validate":
            return validate(root, config)
        if args.command == "index":
            return index_project(root, config)
        if args.command == "stats":
            return stats(root, config)
        if args.command == "findings":
            return findings(root, config)
        if args.command == "context":
            content = build_context(root, config, args.scene_id)
            if args.output:
                out = args.output if args.output.is_absolute() else root / args.output
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(content, encoding="utf-8")
                print(out)
            else:
                print(content)
            return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        eprint(f"ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
