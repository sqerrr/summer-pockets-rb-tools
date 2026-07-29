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
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ALLOWED_STATUSES = {"todo", "draft", "reviewed", "playable", "approved", "lqa"}
DEFAULT_REQUIRED = {"id", "file_id", "scene_id", "order", "source", "translation", "status"}

PROJECT_PHASES = (
    "bootstrap",
    "cataloguing",
    "reference_preparation",
    "pilot",
    "production",
    "final_lqa",
)
GATE_STATUSES = {"pending", "in_progress", "partial", "passed", "failed", "blocked"}
PROJECT_STATUS_PATH = Path("translation/project-status.yaml")
PROJECT_HISTORY_PATH = Path("translation/project-history.jsonl")

OPERATION_ALIASES = {
    "inspect_repository": "inspect-repository",
    "audit_parser": "audit-parser",
    "catalogue_sources": "catalogue-sources",
    "audit_reference_corpus": "audit-reference-corpus",
    "build_index": "build-index",
    "translate_test_lines": "translate-test-lines",
    "translate_pilot": "translate-pilot",
    "pilot_translation": "translate-pilot",
    "translate_production": "translate-production",
    "production_translation": "translate-production",
    "mass_translate": "mass-translate",
    "approve_translation": "approve-translation",
    "mark_translation_approved": "approve-translation",
    "build_pilot_context": "build-pilot-context",
    "build_production_context": "build-production-context",
    "review_pilot": "review-pilot",
    "review_production": "review-production",
    "build_game_text": "build-game-text",
    "modify_glossary": "modify-glossary",
    "modify_specifications": "modify-specifications",
    "curate_knowledge": "curate-knowledge",
    "final_lqa": "final-lqa",
    "create_documentation": "create-documentation",
    "update_glossary": "modify-glossary",
    "update_specifications": "modify-specifications",
    "update_knowledge": "curate-knowledge",
}

MACHINE_OPERATION_NAMES = {
    "translate-pilot": "pilot_translation",
    "translate-production": "production_translation",
}

OPERATION_RULES: dict[str, dict[str, Any]] = {
    "inspect-repository": {"label": "repository inspection", "phases": PROJECT_PHASES},
    "audit-parser": {"label": "parser audit", "phases": PROJECT_PHASES},
    "create-documentation": {"label": "documentation update", "phases": PROJECT_PHASES},
    "catalogue-sources": {
        "label": "source cataloguing",
        "phases": ("bootstrap", "cataloguing"),
        "gates": ("repository_audited", "parser_extraction_verified"),
    },
    "audit-reference-corpus": {
        "label": "reference corpus audit",
        "phases": ("bootstrap", "reference_preparation"),
        "gates": ("repository_audited",),
    },
    "build-index": {
        "label": "knowledge index build",
        "phases": ("cataloguing", "reference_preparation", "pilot", "production", "final_lqa"),
        "gates": ("scenario_catalogued", "stable_ids_created", "scenes_segmented"),
    },
    "translate-test-lines": {
        "label": "test-line translation",
        "phases": ("bootstrap",),
        "gates": ("parser_extraction_verified", "parser_roundtrip_verified", "cyrillic_verified"),
    },
    "build-pilot-context": {"label": "pilot context build", "phases": ("pilot",), "required_for": "pilot"},
    "translate-pilot": {"label": "pilot translation", "phases": ("pilot",), "required_for": "pilot"},
    "review-pilot": {"label": "pilot review", "phases": ("pilot",), "required_for": "pilot"},
    "build-production-context": {
        "label": "production context build",
        "phases": ("production",),
        "required_for": "production",
    },
    "translate-production": {
        "label": "production translation",
        "phases": ("production",),
        "required_for": "production",
    },
    "review-production": {
        "label": "production review",
        "phases": ("production", "final_lqa"),
        "required_for": "production",
    },
    "build-game-text": {
        "label": "game text build",
        "phases": ("pilot", "production", "final_lqa"),
        "gates": (
            "parser_roundtrip_verified",
            "cyrillic_verified",
            "technical_tags_verified",
            "choices_and_jumps_verified",
        ),
    },
    "modify-glossary": {
        "label": "glossary update",
        "phases": ("pilot", "production", "final_lqa"),
        "required_for": "pilot",
    },
    "modify-specifications": {"label": "specification update", "phases": PROJECT_PHASES},
    "curate-knowledge": {
        "label": "knowledge curation",
        "phases": ("pilot", "production", "final_lqa"),
        "required_for": "pilot",
    },
    "approve-translation": {
        "label": "translation approval",
        "phases": ("production", "final_lqa"),
        "required_for": "production",
    },
    "mass-translate": {
        "label": "mass translation",
        "phases": (),
        "policy_block": "Mass translation is forbidden; production scenes must be handled sequentially.",
    },
    "final-lqa": {"label": "final LQA", "phases": ("final_lqa",), "required_for": "production"},
}

OPERATION_PERMISSIONS = {
    "inspect-repository": "inspect_repository",
    "audit-parser": "audit_parser",
    "catalogue-sources": "catalogue_sources",
    "audit-reference-corpus": "audit_reference_corpus",
    "create-documentation": "create_documentation",
    "build-index": "build_index",
    "translate-test-lines": "translate_test_lines",
    "build-pilot-context": "translate_pilot_scene",
    "translate-pilot": "translate_pilot_scene",
    "review-pilot": "translate_pilot_scene",
    "build-production-context": "translate_production_scenes",
    "translate-production": "translate_production_scenes",
    "review-production": "translate_production_scenes",
    "mass-translate": "mass_translate",
    "approve-translation": "mark_translation_approved",
}

PHASE_TRANSITION_GATES = {
    "bootstrap": (
        "repository_audited",
        "parser_extraction_verified",
        "parser_roundtrip_verified",
        "cyrillic_verified",
        "technical_tags_verified",
        "choices_and_jumps_verified",
    ),
    "cataloguing": (
        "scenario_catalogued",
        "stable_ids_created",
        "scenes_segmented",
        "knowledge_index_built",
        "spoiler_protection_verified",
    ),
    "reference_preparation": ("reference_corpus_audited",),
    "pilot": (),  # Derived from all gates whose required_for contains production.
    "production": ("production_completed",),
}

GATE_ACTIONS = {
    "repository_audited": ("vn-bootstrap", "audit_repository", "docs/project/parser-audit.md"),
    "parser_extraction_verified": ("vn-bootstrap", "verify_parser_extraction", "docs/project/parser-audit.md"),
    "parser_roundtrip_verified": ("vn-engine-siglus", "run_extended_roundtrip", "docs/project/parser-audit.md"),
    "cyrillic_verified": ("vn-engine-siglus", "verify_cyrillic_rendering", "docs/project/evidence/russian-rendering.png"),
    "technical_tags_verified": ("vn-engine-siglus", "verify_technical_tags", "docs/project/parser-audit.md"),
    "choices_and_jumps_verified": ("vn-bootstrap", "verify_choices_and_jumps", "docs/project/parser-audit.md"),
    "layout_limits_measured": ("vn-engine-siglus", "measure_layout_limits", "docs/project/parser-audit.md"),
    "scenario_catalogued": ("vn-bootstrap", "catalogue_scenario", "translation/scenes.jsonl"),
    "stable_ids_created": ("vn-bootstrap", "create_stable_ids", "translation/segments/<scene>.jsonl"),
    "scenes_segmented": ("vn-bootstrap", "segment_logical_scenes", "translation/scenes.jsonl"),
    "reference_corpus_audited": ("vn-bootstrap", "audit_reference_corpus", "docs/reference-corpus-policy.md"),
    "knowledge_index_built": ("vn-bootstrap", "build_knowledge_index", "database/knowledge.db"),
    "spoiler_protection_verified": ("vn-context-builder", "verify_spoiler_protection", "tools/tests/test_spoiler_safety.py"),
    "pilot_completed": ("vn-context-builder", "run_pilot_workflow", "build/pilot-verification.md"),
    "production_completed": ("vn-scene-reviewer", "verify_production_completion", "docs/progress.yaml"),
}


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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_operation(operation: str) -> str:
    normalized = operation.strip().lower().replace("_", "-")
    normalized = OPERATION_ALIASES.get(normalized.replace("-", "_"), normalized)
    if normalized not in OPERATION_RULES:
        raise ValueError(f"Unknown operation: {operation}")
    return normalized


def evidence_file(root: Path, evidence: Any) -> Path | None:
    if not isinstance(evidence, str) or not evidence.strip():
        return None
    path = Path(evidence)
    return path if path.is_absolute() else root / path


def validate_project_status(root: Path, status: Any) -> dict[str, Any]:
    if not isinstance(status, dict):
        raise ValueError(f"{PROJECT_STATUS_PATH}: expected a YAML mapping")
    if status.get("schema_version") != 1:
        raise ValueError(f"{PROJECT_STATUS_PATH}: unsupported schema_version")
    phase = status.get("phase")
    if phase not in PROJECT_PHASES:
        raise ValueError(f"{PROJECT_STATUS_PATH}: unknown phase {phase!r}")
    gates = status.get("critical_gates")
    if not isinstance(gates, dict) or not gates:
        raise ValueError(f"{PROJECT_STATUS_PATH}: critical_gates must be a non-empty mapping")
    for gate, item in gates.items():
        if not isinstance(item, dict):
            raise ValueError(f"{PROJECT_STATUS_PATH}: gate {gate!r} must be a mapping")
        gate_status = item.get("status")
        if gate_status not in GATE_STATUSES:
            raise ValueError(f"{PROJECT_STATUS_PATH}: gate {gate!r} has unknown status {gate_status!r}")
        required_for = item.get("required_for", [])
        if not isinstance(required_for, list) or any(value not in PROJECT_PHASES for value in required_for):
            raise ValueError(f"{PROJECT_STATUS_PATH}: gate {gate!r} has invalid required_for")
        if gate_status == "passed":
            path = evidence_file(root, item.get("evidence"))
            if path is None or not path.is_file():
                raise ValueError(f"{PROJECT_STATUS_PATH}: passed gate {gate!r} requires an existing evidence file")
    if not isinstance(status.get("permissions", {}), dict):
        raise ValueError(f"{PROJECT_STATUS_PATH}: permissions must be a mapping")
    return status


def load_project_status(root: Path) -> dict[str, Any]:
    path = root / PROJECT_STATUS_PATH
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    return validate_project_status(root, read_yaml(path, {}))


def write_project_status(root: Path, status: dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required. Run: python -m pip install -r requirements.txt")
    validate_project_status(root, status)
    path = root / PROJECT_STATUS_PATH
    path.write_text(yaml.safe_dump(status, allow_unicode=True, sort_keys=False), encoding="utf-8")


def append_project_history(root: Path, event: dict[str, Any]) -> None:
    path = root / PROJECT_HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": now_iso(), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def gates_required_for(status: dict[str, Any], target: str) -> list[str]:
    return [
        name
        for name, item in status["critical_gates"].items()
        if target in item.get("required_for", [])
    ]


def missing_gates(status: dict[str, Any], gate_names: Iterable[str]) -> list[str]:
    gates = status["critical_gates"]
    missing: list[str] = []
    for name in gate_names:
        if name not in gates:
            raise ValueError(f"Project status does not define required gate: {name}")
        if gates[name].get("status") != "passed":
            missing.append(name)
    return missing


def operation_gate_names(status: dict[str, Any], operation: str) -> list[str]:
    rule = OPERATION_RULES[operation]
    names = list(rule.get("gates", ()))
    target = rule.get("required_for")
    if target:
        names.extend(gates_required_for(status, target))
    return list(dict.fromkeys(names))


def transition_gate_names(status: dict[str, Any]) -> list[str]:
    phase = status["phase"]
    if phase == "pilot":
        return gates_required_for(status, "production")
    return list(PHASE_TRANSITION_GATES.get(phase, ()))


def next_phase(phase: str) -> str | None:
    index = PROJECT_PHASES.index(phase)
    return PROJECT_PHASES[index + 1] if index + 1 < len(PROJECT_PHASES) else None


def action_for_gate(gate: str) -> dict[str, str]:
    skill, task, expected_evidence = GATE_ACTIONS.get(
        gate,
        ("vn-project-orchestrator", f"complete_{gate}", f"build/evidence/{gate}.md"),
    )
    return {"skill": skill, "task": task, "expected_evidence": expected_evidence}


def recommend_next_action(status: dict[str, Any]) -> dict[str, str]:
    blockers = missing_gates(status, transition_gate_names(status))
    if blockers:
        return action_for_gate(blockers[0])
    phase = status["phase"]
    following = next_phase(phase)
    if following:
        return {
            "skill": "vn-project-orchestrator",
            "task": f"advance_to_{following}",
            "expected_evidence": "translation/project-history.jsonl",
        }
    return {
        "skill": "vn-scene-reviewer",
        "task": "continue_final_lqa",
        "expected_evidence": "build/final-lqa-report.md",
    }


def operation_permission(status: dict[str, Any], operation: str) -> str | None:
    if operation == "build-game-text":
        return "translate_pilot_scene" if status["phase"] == "pilot" else "translate_production_scenes"
    if operation in {"modify-glossary", "modify-specifications", "curate-knowledge"}:
        return "create_documentation"
    return OPERATION_PERMISSIONS.get(operation)


def evaluate_operation(
    status: dict[str, Any],
    operation: str,
    check_permissions: bool = True,
) -> dict[str, Any]:
    operation = normalize_operation(operation)
    rule = OPERATION_RULES[operation]
    blockers = missing_gates(status, operation_gate_names(status, operation))
    policy_block = rule.get("policy_block")
    phase_allowed = status["phase"] in rule.get("phases", ())
    permission = operation_permission(status, operation)
    permission_allowed = (
        not check_permissions
        or permission is None
        or status.get("permissions", {}).get(permission) is True
    )
    return {
        "allowed": not blockers and phase_allowed and permission_allowed and not policy_block,
        "requested_operation": MACHINE_OPERATION_NAMES.get(operation, operation.replace("-", "_")),
        "current_phase": status["phase"],
        "blocking_gates": blockers,
        "blocking_permissions": [] if permission_allowed or permission is None else [permission],
        "phase_allowed": phase_allowed,
        "policy_block": policy_block,
        "next_required_action": recommend_next_action(status),
    }


class OperationBlockedError(RuntimeError):
    def __init__(self, result: dict[str, Any]):
        self.result = result
        super().__init__(f"{result['requested_operation'].replace('_', ' ')} is blocked")


def require_operation_allowed(operation_name: str, root: Path | None = None) -> None:
    """Guard for commands that can translate, approve, or otherwise advance content."""
    project_root = (root or Path.cwd()).resolve()
    result = evaluate_operation(load_project_status(project_root), operation_name)
    if not result["allowed"]:
        raise OperationBlockedError(result)


def permission_snapshot(status: dict[str, Any]) -> dict[str, bool]:
    def allowed(operation: str) -> bool:
        return bool(evaluate_operation(status, operation, check_permissions=False)["allowed"])

    return {
        "inspect_repository": allowed("inspect-repository"),
        "audit_parser": allowed("audit-parser"),
        "catalogue_sources": allowed("catalogue-sources"),
        "audit_reference_corpus": allowed("audit-reference-corpus"),
        "create_documentation": allowed("modify-specifications"),
        "build_index": allowed("build-index"),
        "translate_test_lines": allowed("translate-test-lines"),
        "translate_pilot_scene": allowed("translate-pilot"),
        "translate_production_scenes": allowed("translate-production"),
        "mass_translate": False,
        "mark_translation_approved": allowed("approve-translation"),
    }


def sync_permissions(root: Path, status: dict[str, Any], reason: str) -> None:
    old_permissions = status.get("permissions", {})
    new_permissions = permission_snapshot(status)
    status["permissions"] = new_permissions
    for name, value in new_permissions.items():
        old_value = old_permissions.get(name)
        if old_value != value:
            append_project_history(root, {
                "event": "permission_changed",
                "permission": name,
                "old_value": old_value,
                "new_value": value,
                "commit": None,
                "actor": "agent",
                "reason": reason,
            })


def refresh_project_summary(status: dict[str, Any]) -> None:
    blockers = missing_gates(status, transition_gate_names(status))
    status["overall_status"] = "blocked" if blockers else "ready"
    action = recommend_next_action(status)
    status["current_task"] = {
        "id": f"{status['phase'].upper()}-NEXT",
        "description": action["task"],
        "assigned_skill": action["skill"],
    }
    status["last_updated"] = now_iso()


def set_gate(root: Path, gate: str, new_status: str, evidence: str | None = None) -> int:
    status = load_project_status(root)
    gates = status["critical_gates"]
    if gate not in gates:
        raise ValueError(f"Unknown gate: {gate}")
    if new_status not in GATE_STATUSES:
        raise ValueError(f"Unknown gate status: {new_status}")
    stored_evidence: str | None = evidence
    if new_status == "passed":
        path = evidence_file(root, evidence)
        if path is None or not path.is_file():
            raise ValueError("Status 'passed' requires --evidence pointing to an existing file")
        try:
            stored_evidence = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            stored_evidence = str(path.resolve())
    elif evidence is None:
        stored_evidence = None

    item = gates[gate]
    old_status = item.get("status")
    old_evidence = item.get("evidence")
    if old_status == new_status and old_evidence == stored_evidence:
        print(f"Gate {gate} unchanged: {new_status}")
        return 0

    item["status"] = new_status
    item["evidence"] = stored_evidence
    append_project_history(root, {
        "event": "gate_status_changed",
        "gate": gate,
        "old_status": old_status,
        "new_status": new_status,
        "evidence": stored_evidence,
        "commit": None,
        "actor": "agent",
        "reason": f"Gate updated through vnctl set-gate; previous evidence: {old_evidence!r}",
    })
    sync_permissions(root, status, f"Gate {gate} changed from {old_status} to {new_status}")
    refresh_project_summary(status)
    write_project_status(root, status)
    print(f"Gate {gate}: {old_status} -> {new_status}")
    return 0


def print_gate_result(result: dict[str, Any], output_format: str = "human") -> int:
    if output_format == "yaml":
        if yaml is None:
            raise RuntimeError("PyYAML is required. Run: python -m pip install -r requirements.txt")
        print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).rstrip())
        return 0 if result["allowed"] else 1

    label = result["requested_operation"].replace("_", " ")
    if result["allowed"]:
        print(f"OK: {label} is allowed.")
        return 0
    eprint(f"ERROR: {label} is blocked.")
    if result["blocking_gates"]:
        eprint("\nMissing critical gates:")
        for gate in result["blocking_gates"]:
            eprint(f"- {gate}")
    if not result["phase_allowed"]:
        eprint(f"\nCurrent phase does not allow this operation: {result['current_phase']}")
    if result["blocking_permissions"]:
        eprint("\nDisabled permissions:")
        for permission in result["blocking_permissions"]:
            eprint(f"- {permission}")
    if result["policy_block"]:
        eprint(f"\nPolicy: {result['policy_block']}")
    return 1


def project_status_report(root: Path) -> int:
    status = load_project_status(root)
    blockers = missing_gates(status, transition_gate_names(status))
    allowed_operations = [
        name for name in OPERATION_RULES
        if evaluate_operation(status, name)["allowed"]
    ]
    action = recommend_next_action(status)
    print(f"Phase: {status['phase']}")
    print(f"Overall status: {status.get('overall_status', 'unknown')}")
    print("Allowed operations:")
    for operation in allowed_operations:
        print(f"- {operation}")
    print("Blocking gates:")
    if blockers:
        for gate in blockers:
            print(f"- {gate}")
    else:
        print("- none")
    print("Next required action:")
    print(f"- skill: {action['skill']}")
    print(f"- task: {action['task']}")
    print(f"- expected evidence: {action['expected_evidence']}")
    return 0


def advance_project(root: Path) -> int:
    status = load_project_status(root)
    phase = status["phase"]
    blockers = missing_gates(status, transition_gate_names(status))
    if blockers:
        action = action_for_gate(blockers[0])
        print(f"Current phase: {phase}")
        print(f"Recommended skill: {action['skill']}")
        print(f"Task: {action['task']}")
        print(f"Expected evidence: {action['expected_evidence']}")
        return 0

    following = next_phase(phase)
    if following is None:
        action = recommend_next_action(status)
        print(f"Current phase: {phase}")
        print(f"Recommended skill: {action['skill']}")
        print(f"Task: {action['task']}")
        print(f"Expected evidence: {action['expected_evidence']}")
        return 0

    status["phase"] = following
    append_project_history(root, {
        "event": "phase_changed",
        "old_phase": phase,
        "new_phase": following,
        "evidence": [status["critical_gates"][name]["evidence"] for name in transition_gate_names({**status, "phase": phase})],
        "commit": None,
        "actor": "agent",
        "reason": "All critical gates for the phase transition passed",
    })
    sync_permissions(root, status, f"Project advanced from {phase} to {following}")
    refresh_project_summary(status)
    write_project_status(root, status)
    action = recommend_next_action(status)
    print(f"Phase advanced: {phase} -> {following}")
    print(f"Recommended skill: {action['skill']}")
    print(f"Task: {action['task']}")
    print(f"Expected evidence: {action['expected_evidence']}")
    return 0


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
    sub.add_parser("status")
    p_gate = sub.add_parser("gate")
    p_gate.add_argument("operation")
    p_gate.add_argument("--format", choices=("human", "yaml"), default="human")
    sub.add_parser("advance")
    p_set_gate = sub.add_parser("set-gate")
    p_set_gate.add_argument("gate")
    p_set_gate.add_argument("status")
    p_set_gate.add_argument("--evidence")
    p_context = sub.add_parser("context")
    p_context.add_argument("scene_id")
    p_context.add_argument("-o", "--output", type=Path)

    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "status":
            return project_status_report(root)
        if args.command == "gate":
            result = evaluate_operation(load_project_status(root), args.operation)
            return print_gate_result(result, args.format)
        if args.command == "advance":
            return advance_project(root)
        if args.command == "set-gate":
            return set_gate(root, args.gate, args.status, args.evidence)

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
