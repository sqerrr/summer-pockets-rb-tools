#!/usr/bin/env python3
"""Minimal project CLI for a VN translation repository.

The canonical data stays in JSONL/YAML/Markdown. SQLite is rebuilt as an index.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ALLOWED_STATUSES = {"todo", "draft", "reviewed", "playable", "approved", "lqa"}
DEFAULT_REQUIRED = {
    "id", "source_set_id", "source_id", "source_hash", "file_id", "scene_id",
    "order", "translation", "status",
}

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
    "batch_translate": "batch-translate",
    "batch_translation": "batch-translate",
    "mass_translate": "mass-translate",
    "approve_translation": "approve-translation",
    "mark_translation_approved": "approve-translation",
    "build_pilot_context": "build-pilot-context",
    "build_production_context": "build-production-context",
    "review_pilot": "review-pilot",
    "review_production": "review-production",
    "build_game_text": "build-game-text",
    "verify_engine": "verify-engine",
    "build_test_pack": "verify-engine",
    "verify_engine_build": "verify-engine",
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
    "batch-translate": "batch_translation",
}

OPERATION_RULES: dict[str, dict[str, Any]] = {
    "inspect-repository": {"label": "repository inspection", "phases": PROJECT_PHASES},
    "audit-parser": {"label": "parser audit", "phases": PROJECT_PHASES},
    "create-documentation": {"label": "documentation update", "phases": PROJECT_PHASES},
    "catalogue-sources": {
        "label": "source cataloguing",
        "phases": PROJECT_PHASES,
        "gates": ("repository_audited", "parser_extraction_verified"),
    },
    "audit-reference-corpus": {
        "label": "reference corpus audit",
        "phases": PROJECT_PHASES,
    },
    "build-index": {
        "label": "knowledge index build",
        "phases": PROJECT_PHASES,
    },
    "translate-test-lines": {
        "label": "test-line translation",
        "phases": PROJECT_PHASES,
        "gates": ("parser_extraction_verified",),
    },
    "build-pilot-context": {
        "label": "pilot context build",
        "phases": PROJECT_PHASES,
        "gates": (
            "scenario_catalogued",
            "stable_ids_created",
            "scenes_segmented",
            "knowledge_index_built",
            "spoiler_protection_verified",
        ),
    },
    "translate-pilot": {
        "label": "pilot translation",
        "phases": PROJECT_PHASES,
        "gates": (
            "parser_extraction_verified",
            "scenario_catalogued",
            "stable_ids_created",
            "scenes_segmented",
            "knowledge_index_built",
            "spoiler_protection_verified",
        ),
    },
    "review-pilot": {
        "label": "pilot review",
        "phases": PROJECT_PHASES,
        "gates": (
            "scenario_catalogued",
            "stable_ids_created",
            "scenes_segmented",
            "knowledge_index_built",
            "spoiler_protection_verified",
        ),
    },
    "build-production-context": {
        "label": "production context build",
        "phases": PROJECT_PHASES,
        "gates": (
            "scenario_catalogued",
            "stable_ids_created",
            "scenes_segmented",
            "knowledge_index_built",
            "spoiler_protection_verified",
            "pilot_completed",
        ),
    },
    "translate-production": {
        "label": "production translation",
        "phases": PROJECT_PHASES,
        "gates": (
            "parser_extraction_verified",
            "scenario_catalogued",
            "stable_ids_created",
            "scenes_segmented",
            "knowledge_index_built",
            "spoiler_protection_verified",
            "pilot_completed",
        ),
    },
    "review-production": {
        "label": "production review",
        "phases": PROJECT_PHASES,
        "gates": (
            "scenario_catalogued",
            "stable_ids_created",
            "scenes_segmented",
            "knowledge_index_built",
            "spoiler_protection_verified",
            "pilot_completed",
        ),
    },
    "batch-translate": {
        "label": "checkpointed scene-batch translation",
        "phases": PROJECT_PHASES,
        "gates": (
            "parser_extraction_verified",
            "scenario_catalogued",
            "stable_ids_created",
            "scenes_segmented",
            "knowledge_index_built",
            "spoiler_protection_verified",
            "pilot_completed",
        ),
    },
    "verify-engine": {
        # Verification builds are how evidence for the roundtrip, Cyrillic,
        # tag and layout gates is produced, so they must stay possible in every
        # phase. Only extraction has to be proven first: you cannot sensibly
        # write a format you cannot read. Requiring the roundtrip gate here
        # would be circular, because the roundtrip is itself this operation.
        "label": "engine verification build",
        "phases": PROJECT_PHASES,
        "gates": ("parser_extraction_verified",),
    },
    "build-game-text": {
        "label": "game text build",
        "phases": PROJECT_PHASES,
        "gates": (
            "parser_roundtrip_verified",
            "cyrillic_verified",
            "technical_tags_verified",
            "choices_and_jumps_verified",
        ),
    },
    "modify-glossary": {
        "label": "glossary update",
        "phases": PROJECT_PHASES,
    },
    "modify-specifications": {"label": "specification update", "phases": PROJECT_PHASES},
    "curate-knowledge": {
        "label": "knowledge curation",
        "phases": PROJECT_PHASES,
    },
    "approve-translation": {
        "label": "translation approval",
        "phases": ("final_lqa",),
        "gates": ("production_completed",),
    },
    "mass-translate": {
        "label": "mass translation",
        "phases": (),
        "policy_block": "One-shot route translation is forbidden; use checkpointed batch-translate instead.",
    },
    "final-lqa": {
        "label": "final LQA",
        "phases": ("final_lqa",),
        "gates": (
            "production_completed",
            "technical_tags_verified",
            "choices_and_jumps_verified",
            "layout_limits_measured",
        ),
    },
}

PHASE_TRANSITION_GATES = {
    "bootstrap": (
        "repository_audited",
        "parser_extraction_verified",
        "parser_roundtrip_verified",
        "cyrillic_verified",
    ),
    "cataloguing": (
        "scenario_catalogued",
        "stable_ids_created",
        "scenes_segmented",
        "knowledge_index_built",
        "spoiler_protection_verified",
    ),
    # External references are optional. This phase is a progress marker, not a
    # prerequisite for pilot translation.
    "reference_preparation": (),
    "pilot": ("pilot_completed",),
    "production": (
        "production_completed",
        "technical_tags_verified",
        "choices_and_jumps_verified",
        "layout_limits_measured",
    ),
}

GATE_ACTIONS = {
    "repository_audited": ("vn-bootstrap", "audit_repository", "docs/project/parser-audit.md"),
    "parser_extraction_verified": ("vn-bootstrap", "verify_parser_extraction", "docs/project/parser-audit.md"),
    "parser_roundtrip_verified": ("vn-engine-luca", "run_extended_roundtrip", "docs/project/evidence/steam-luca-verification.md"),
    "cyrillic_verified": ("vn-engine-luca", "verify_cyrillic_rendering", "docs/project/evidence/steam-luca-cyrillic.png"),
    "technical_tags_verified": ("vn-engine-luca", "verify_technical_tags", "docs/project/parser-audit.md"),
    "choices_and_jumps_verified": ("vn-bootstrap", "verify_choices_and_jumps", "docs/project/parser-audit.md"),
    "layout_limits_measured": ("vn-engine-luca", "measure_layout_limits", "docs/project/parser-audit.md"),
    "scenario_catalogued": ("vn-bootstrap", "catalogue_scenario", "translation/scenes.jsonl"),
    "stable_ids_created": ("vn-bootstrap", "create_stable_ids", "translation/segments/<scene>.jsonl"),
    "scenes_segmented": ("vn-bootstrap", "segment_logical_scenes", "translation/scenes.jsonl"),
    "reference_corpus_audited": ("vn-reference-curator", "audit_reference_corpus", "docs/reference-audit.md"),
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
    return list(dict.fromkeys(rule.get("gates", ())))


def transition_gate_names(status: dict[str, Any]) -> list[str]:
    phase = status["phase"]
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


def evaluate_operation(
    status: dict[str, Any],
    operation: str,
) -> dict[str, Any]:
    operation = normalize_operation(operation)
    rule = OPERATION_RULES[operation]
    blockers = missing_gates(status, operation_gate_names(status, operation))
    policy_block = rule.get("policy_block")
    phase_allowed = status["phase"] in rule.get("phases", PROJECT_PHASES)
    return {
        "allowed": not blockers and phase_allowed and not policy_block,
        "requested_operation": MACHINE_OPERATION_NAMES.get(operation, operation.replace("-", "_")),
        "current_phase": status["phase"],
        "blocking_gates": blockers,
        "blocking_permissions": [],
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


def refresh_project_summary(status: dict[str, Any]) -> None:
    blockers = missing_gates(status, transition_gate_names(status))
    status["overall_status"] = "in_progress" if blockers else "ready_to_advance"
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
    print("Gates for the next milestone:")
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


def index_freshness(root: Path, config: dict[str, Any]) -> str:
    dest = db_path(root, config)
    if not dest.is_file():
        return "missing"
    inputs = list(iter_segment_files(root, config))
    for rel in (
        "translation/scenes.jsonl",
        "source/manifest.jsonl",
        "config/project.yaml",
        "config/qa-rules.yaml",
    ):
        path = root / rel
        if path.is_file():
            inputs.append(path)
    for item in read_jsonl(source_manifest_path(root, config)):
        catalog = root / str(item.get("catalog_path", ""))
        if catalog.is_file():
            inputs.append(catalog)
    docs_root = root / "docs"
    if docs_root.exists():
        inputs.extend(docs_root.glob("**/*.md"))
    for key, default in (
        ("glossary", "docs/glossary.yaml"),
        ("decisions", "docs/decisions.jsonl"),
        ("summaries", "docs/scene-summaries.jsonl"),
    ):
        path = root / config.get("paths", {}).get(key, default)
        if path.is_file():
            inputs.append(path)
    latest_input = max((path.stat().st_mtime for path in inputs), default=0.0)
    return "stale" if latest_input > dest.stat().st_mtime else "current"


def project_resume_report(root: Path) -> int:
    status = load_project_status(root)
    config = load_config(root)
    segments = load_segments(root, config)
    scenes = load_scenes(root, config)
    by_status = Counter(str(row.get("status", "missing")) for row in segments)
    translated = sum(1 for row in segments if str(row.get("translation", "")).strip())
    source_manifest = read_jsonl(source_manifest_path(root, config))
    source_candidates = sum(int(row.get("candidate_record_count", 0)) for row in source_manifest)
    source_translatable = sum(int(row.get("translatable_record_count", 0)) for row in source_manifest)
    glossary_path = root / config.get("paths", {}).get("glossary", "docs/glossary.yaml")
    glossary = read_yaml(glossary_path, []) or []
    characters_path = root / config.get("paths", {}).get("characters", "docs/characters")
    character_cards = [
        path for path in characters_path.glob("*.md")
        if path.name != "_template.md"
    ] if characters_path.exists() else []
    decisions_path = root / config.get("paths", {}).get("decisions", "docs/decisions.jsonl")
    decisions = read_jsonl(decisions_path)
    decision_statuses = Counter(str(row.get("status", "missing")) for row in decisions)
    references_root = root / "references/local"
    reference_corpora = [path for path in references_root.iterdir() if path.is_dir()] if references_root.exists() else []
    action = recommend_next_action(status)

    print(f"Фаза: {status['phase']}")
    print(f"Состояние этапа: {status.get('overall_status', 'unknown')}")
    print("Фактический прогресс:")
    print(f"- наборов источников: {len(source_manifest)}")
    print(f"- записей исходного каталога: {source_candidates}")
    print(f"- переводимых трёхъязычных записей: {source_translatable}")
    print(f"- сцен в каталоге: {len(scenes)}")
    print(f"- сегментов: {len(segments)}")
    print(f"- переведено: {translated}")
    for name in ("todo", "draft", "reviewed", "playable", "lqa", "approved"):
        if by_status[name]:
            print(f"- статус {name}: {by_status[name]}")
    print("Знания и референсы:")
    print(f"- терминов в глоссарии: {len(glossary) if isinstance(glossary, list) else 0}")
    print(f"- карточек персонажей: {len(character_cards)}")
    print(f"- переводческих решений: {len(decisions)}")
    for name, count in sorted(decision_statuses.items()):
        print(f"- решений {name}: {count}")
    print(f"- локальных референсных корпусов: {len(reference_corpora)}")
    print(f"- индекс: {index_freshness(root, config)}")
    print("Следующий рабочий блок:")
    print(f"- skill: {action['skill']}")
    print(f"- задача: {action['task']}")
    print(f"- ожидаемый результат: {action['expected_evidence']}")
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
        return 1

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


def iter_jsonl(path: Path):
    if not path.exists():
        return
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
            yield line_no, item


def sha256_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_manifest_path(root: Path, config: dict[str, Any]) -> Path:
    return root / config.get("paths", {}).get("source_manifest", "source/manifest.jsonl")


def source_configs_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for item in (config.get("source_sets", {}) or {}).values():
        if isinstance(item, dict) and item.get("id"):
            result[str(item["id"])] = item
    return result


def validate_source_catalogs(root: Path, config: dict[str, Any]):
    errors: list[str] = []
    warnings: list[str] = []
    manifest_rows = [clean_meta(row) for row in read_jsonl(source_manifest_path(root, config))]
    configured = source_configs_by_id(config)
    seen_sets: set[str] = set()
    totals = Counter()

    if not manifest_rows:
        warnings.append("No source manifest entries found.")
        return errors, warnings, totals

    for manifest in manifest_rows:
        source_set_id = str(manifest.get("source_set_id", ""))
        if not source_set_id:
            errors.append("source manifest: missing source_set_id")
            continue
        if source_set_id in seen_sets:
            errors.append(f"source manifest: duplicate source_set_id {source_set_id}")
            continue
        seen_sets.add(source_set_id)
        if source_set_id not in configured:
            errors.append(f"source manifest: unconfigured source set {source_set_id}")
        source_config = configured.get(source_set_id, {})
        archive_rel = str(manifest.get("archive_path", ""))
        archive = root / archive_rel
        if archive.is_file():
            if archive.stat().st_size != int(manifest.get("archive_size", -1)):
                errors.append(f"source set {source_set_id}: archive size mismatch")
            if sha256_file(archive) != str(manifest.get("archive_sha256", "")):
                errors.append(f"source set {source_set_id}: archive hash mismatch")
        else:
            warnings.append(f"source set {source_set_id}: source archive is absent locally")
        if source_config and str(source_config.get("archive_sha256", "")) != str(
            manifest.get("archive_sha256", "")
        ):
            errors.append(f"source set {source_set_id}: configured archive hash mismatch")
        for field in (
            "build_id", "archive", "catalog", "source_priority",
            "working_source_language", "build_slot", "slots",
        ):
            manifest_field = {
                "archive": "archive_path",
                "catalog": "catalog_path",
            }.get(field, field)
            if source_config and source_config.get(field) != manifest.get(manifest_field):
                errors.append(
                    f"source set {source_set_id}: configured {field} does not match manifest"
                )
        catalog_rel = str(manifest.get("catalog_path", ""))
        catalog = root / catalog_rel
        if not catalog.is_file():
            warnings.append(
                f"source set {source_set_id}: local catalog is absent; regenerate with "
                f"{manifest.get('generator', 'the configured exporter')}"
            )
            continue
        expected_digest = str(manifest.get("catalog_sha256", ""))
        actual_digest = sha256_file(catalog)
        if actual_digest != expected_digest:
            errors.append(
                f"source set {source_set_id}: catalog hash mismatch "
                f"{actual_digest} != {expected_digest}"
            )

        expected_languages = [
            str(slot.get("language")) for slot in manifest.get("slots", [])
            if isinstance(slot, dict)
        ]
        seen_ids: set[str] = set()
        previous_key = None
        counts = Counter()
        for line_no, row in iter_jsonl(catalog):
            loc = f"{catalog_rel}:{line_no}"
            source_id = str(row.get("source_id", ""))
            if not re.fullmatch(r"SRC_LUCA_E\d{6}_R\d{6}_G\d{2}", source_id):
                errors.append(f"{loc}: invalid source_id {source_id!r}")
            elif source_id in seen_ids:
                errors.append(f"{loc}: duplicate source_id {source_id}")
            seen_ids.add(source_id)
            if row.get("source_set_id") != source_set_id:
                errors.append(f"{loc}: source_set_id mismatch")
            script_entry = row.get("script_entry", {})
            record = row.get("record", {})
            layout = row.get("layout", {})
            if "name" in script_entry:
                errors.append(f"{loc}: raw script entry names are forbidden")
            key = (
                int(script_entry.get("index", -1)),
                int(record.get("ordinal", -1)),
                int(layout.get("group_ordinal", -1)),
            )
            expected_source_id = (
                f"SRC_LUCA_E{int(script_entry.get('id', -1)):06d}_"
                f"R{key[1]:06d}_G{key[2]:02d}"
            )
            if source_id != expected_source_id:
                errors.append(f"{loc}: source_id does not match entry ID and ordinals")
            if previous_key is not None and key <= previous_key:
                errors.append(f"{loc}: source rows are not in deterministic order")
            previous_key = key

            classification = row.get("classification")
            counts["candidate"] += 1
            counts[str(classification)] += 1
            slots = row.get("slots", [])
            if classification == "translatable":
                counts[f"opcode:{record.get('opcode')}"] += 1
                languages = [str(slot.get("language")) for slot in slots]
                indices = [slot.get("index") for slot in slots]
                if languages != expected_languages or indices != list(range(len(expected_languages))):
                    errors.append(f"{loc}: language slots do not match the manifest")
                for slot in slots:
                    text = slot.get("text")
                    if not isinstance(text, str) or not text:
                        errors.append(f"{loc}: source slot text is empty")
                    elif slot.get("text_sha256") != sha256_text(text):
                        errors.append(f"{loc}: source slot text hash mismatch")
                    else:
                        try:
                            payload = text.encode(str(slot.get("encoding", "")))
                        except (LookupError, UnicodeEncodeError):
                            errors.append(f"{loc}: invalid source slot encoding")
                        else:
                            payload_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
                            if slot.get("payload_size") != len(payload):
                                errors.append(f"{loc}: source slot payload size mismatch")
                            if slot.get("payload_sha256") != payload_hash:
                                errors.append(f"{loc}: source slot payload hash mismatch")
                    speaker = slot.get("speaker")
                    body_text = slot.get("body_text")
                    if not isinstance(body_text, str) or not body_text:
                        errors.append(f"{loc}: source slot body text is empty")
                    elif slot.get("body_text_sha256") != sha256_text(body_text):
                        errors.append(f"{loc}: source slot body hash mismatch")
                    elif speaker is None:
                        if body_text != text:
                            errors.append(f"{loc}: unmarked source slot body differs from text")
                    elif not isinstance(speaker, str) or not speaker or text != f"@{speaker}@{body_text}":
                        errors.append(f"{loc}: source speaker marker is inconsistent")
                marked_slots = sum(slot.get("speaker") is not None for slot in slots)
                counts["speaker:any_slot"] += marked_slots > 0
                counts["speaker:all_slots"] += marked_slots == len(slots)
                counts["speaker:partial_slots"] += 0 < marked_slots < len(slots)
            elif classification == "service_nontext":
                if slots:
                    errors.append(f"{loc}: service_nontext record has language slots")
            else:
                errors.append(f"{loc}: unknown classification {classification!r}")

        expected_counts = {
            "candidate": int(manifest.get("candidate_record_count", -1)),
            "translatable": int(manifest.get("translatable_record_count", -1)),
            "service_nontext": int(manifest.get("service_nontext_record_count", -1)),
        }
        for name, expected in expected_counts.items():
            if counts[name] != expected:
                errors.append(
                    f"source set {source_set_id}: {name} count {counts[name]} != {expected}"
                )
        for opcode, expected in (manifest.get("text_opcode_counts", {}) or {}).items():
            actual = counts[f"opcode:{opcode}"]
            if actual != int(expected):
                errors.append(
                    f"source set {source_set_id}: opcode {opcode} text count "
                    f"{actual} != {expected}"
                )
        for name, expected in (manifest.get("speaker_marker_counts", {}) or {}).items():
            actual = counts[f"speaker:{name}"]
            if actual != int(expected):
                errors.append(
                    f"source set {source_set_id}: speaker marker count {name} "
                    f"{actual} != {expected}"
                )
        if int(manifest.get("candidate_record_count", -1)) + int(
            manifest.get("structural_record_count", -1)
        ) != int(manifest.get("record_count", -1)):
            errors.append(f"source set {source_set_id}: manifest record counts are inconsistent")
        totals.update(counts)
    return errors, warnings, totals


def load_source_records(root: Path, config: dict[str, Any], keys):
    needed = set(keys)
    if not needed:
        return {}
    manifests = {
        str(row.get("source_set_id")): clean_meta(row)
        for row in read_jsonl(source_manifest_path(root, config))
    }
    result = {}
    by_set = defaultdict(set)
    for source_set_id, source_id in needed:
        by_set[source_set_id].add(source_id)
    for source_set_id, source_ids in by_set.items():
        manifest = manifests.get(source_set_id)
        if not manifest:
            raise ValueError(f"missing source manifest for {source_set_id}")
        catalog = root / str(manifest.get("catalog_path", ""))
        if not catalog.is_file():
            raise ValueError(f"local source catalog is missing: {catalog}")
        for _, item in iter_jsonl(catalog):
            source_id = str(item.get("source_id", ""))
            if source_id in source_ids:
                result[(source_set_id, source_id)] = item
    missing = sorted(needed - result.keys())
    if missing:
        raise ValueError(f"unknown source references: {missing[:5]!r}")
    return result


def iter_segment_files(root: Path, config: dict[str, Any]) -> list[Path]:
    rel = config.get("paths", {}).get("segments", "translation/segments")
    base = root / rel
    return sorted(base.glob("**/*.jsonl")) if base.exists() else []


def load_segments(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in iter_segment_files(root, config):
        rows.extend(read_jsonl(path))
    configured = source_configs_by_id(config)
    keys = {
        (str(row.get("source_set_id")), str(row.get("source_id")))
        for row in rows
        if row.get("source_set_id")
        and row.get("source_id")
        and (
            str(row.get("source_set_id")) in configured
            or not isinstance(row.get("source"), str)
        )
    }
    source_records = load_source_records(root, config, keys)
    for row in rows:
        key = (str(row.get("source_set_id")), str(row.get("source_id")))
        item = source_records.get(key)
        if not item:
            continue
        sources = {
            str(slot["language"]): str(slot.get("body_text", slot["text"]))
            for slot in item.get("slots", [])
        }
        working_language = str(
            configured.get(key[0], {}).get(
                "working_source_language",
                config.get("project", {}).get("working_source_language", "en"),
            )
        )
        row["sources"] = sources
        row.setdefault("source", sources.get(working_language, next(iter(sources.values()), "")))
        row["__catalog_source_hash"] = item.get("record", {}).get("params_sha256")
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


def segment_rule_exceptions(root: Path) -> dict[str, set[str]]:
    """Approved per-segment exceptions to otherwise global text rules."""
    exceptions: dict[str, set[str]] = defaultdict(set)
    for row in read_jsonl(root / "docs" / "decisions.jsonl"):
        if row.get("status") != "approved" or row.get("scope") != "segment":
            continue
        decision_id = str(row.get("exception_to", "")).strip()
        if not decision_id:
            continue
        for segment_id in row.get("segment_ids", []) or []:
            exceptions[str(segment_id)].add(decision_id)
    return exceptions


def allowed_line_findings(root: Path, segment_id: str,
                          findings: list[Finding]) -> list[Finding]:
    allowed = segment_rule_exceptions(root).get(segment_id, set())
    return [finding for finding in findings if finding.decision not in allowed]


def validate(root: Path, config: dict[str, Any]) -> int:
    qa = read_yaml(root / "config/qa-rules.yaml", {}) or {}
    required = set(qa.get("required_segment_fields", DEFAULT_REQUIRED))
    allowed_statuses = set(qa.get("allowed_statuses", ALLOWED_STATUSES))
    allowed_flags = set(qa.get("allowed_flags", []))
    patterns = [re.compile(p) for p in qa.get("protected_patterns", [])]

    errors: list[str] = []
    warnings: list[str] = []
    source_errors, source_warnings, source_totals = validate_source_catalogs(root, config)
    errors.extend(source_errors)
    warnings.extend(source_warnings)
    name_map = approved_names(root, config)
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
        catalog_hash = row.get("__catalog_source_hash")
        if catalog_hash and row.get("source_hash") != catalog_hash:
            errors.append(f"{loc}: source_hash does not match the source catalogue")

        # Правила русского текста. Проверяются только заполненные переводы:
        # пустой сегмент ещё не является нарушением чего-либо.
        translation = str(row.get("translation", ""))
        if translation.strip():
            checks = allowed_line_findings(
                root, str(row["id"]),
                check_line(translation, is_dialogue=bool(row.get("speaker"))))
            sources = row.get("sources") or {}
            # Построчная проверка имён снята: она срабатывала на отсутствие
            # имени в переводе, а замена имени местоимением - обычный перевод,
            # не ошибка. Точность оказалась низкой, а единообразие написания
            # ловится аудитором поперёк сцен, где оно и имеет смысл.
            checks += check_markup(str(sources.get("ja", "")), translation)
            for finding in checks:
                message = f"{loc}: {finding.decision} {finding.message}"
                (errors if finding.severity == "error" else warnings).append(message)
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
            # Ruby is source-only reading metadata. Its removal is validated by
            # check_markup(), so generic token comparison must not demand it.
            generic_src = strip_ruby(src)
            generic_dst = strip_ruby(dst)
            for pattern in patterns:
                src_tokens = pattern.findall(generic_src)
                dst_tokens = pattern.findall(generic_dst)
                if src_tokens != dst_tokens:
                    warnings.append(
                        f"{loc}: protected-token mismatch for {pattern.pattern}: "
                        f"source={src_tokens!r} target={dst_tokens!r}"
                    )

    for scene_id, rows in by_scene.items():
        orders = [r["order"] for r in rows if isinstance(r.get("order"), int)]
        if len(orders) != len(set(orders)):
            errors.append(f"scene {scene_id}: duplicate order values")

    scenes_rel = config.get("paths", {}).get("scenes", "translation/scenes.jsonl")
    scenes_path = root / scenes_rel
    if scenes_path.exists():
        scene_catalogue = load_scenes(root, config)
        catalogue_ids = {str(scene.get("scene_id")) for scene in scene_catalogue}
        if catalogue_ids != set(by_scene):
            missing = sorted(set(by_scene) - catalogue_ids)
            extra = sorted(catalogue_ids - set(by_scene))
            errors.append(f"scene catalogue mismatch: missing={missing[:5]} extra={extra[:5]}")
        for scene in scene_catalogue:
            route = str(scene.get("route", ""))
            if not re.fullmatch(r"BLK[0-9]{4}", route):
                errors.append(f"scene {scene.get('scene_id')}: invalid or missing opaque route")
    style_errors, style_warnings = validate_style_ledger(root, config)
    errors.extend(style_errors)
    warnings.extend(style_warnings)
    review_errors, review_warnings = validate_review_ledger(root, config)
    errors.extend(review_errors)
    warnings.extend(review_warnings)

    for msg in errors:
        eprint("ERROR:", msg)
    for msg in warnings:
        eprint("WARN:", msg)
    print(
        f"Validated {len(segments)} segments and {source_totals['candidate']} source records: "
        f"{len(errors)} errors, {len(warnings)} warnings"
    )
    return 1 if errors else 0


def db_path(root: Path, config: dict[str, Any]) -> Path:
    return root / config.get("paths", {}).get("database", "database/knowledge.db")


def populate_index_database(root: Path, config: dict[str, Any],
                            con: sqlite3.Connection) -> int:
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE segments (
            id TEXT PRIMARY KEY,
            source_set_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            file_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
            route TEXT NOT NULL,
            ord INTEGER NOT NULL,
            speaker TEXT,
            source TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            translation TEXT NOT NULL,
            status TEXT NOT NULL,
            flags_json TEXT NOT NULL,
            decision_ids_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE INDEX idx_segments_scene ON segments(scene_id, ord);
        CREATE INDEX idx_segments_route ON segments(route, scene_id, ord);
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
    route_by_scene = {
        str(scene["scene_id"]): str(scene.get("route", ""))
        for scene in load_scenes(root, config)
    }
    for row in segments:
        r = clean_meta(row)
        cur.execute(
            "INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["id"], r.get("source_set_id", ""), r.get("source_id", ""),
                r.get("source_hash", ""), r["file_id"], r["scene_id"],
                route_by_scene.get(str(r["scene_id"]), ""), r["order"],
                r.get("speaker"), r.get("source", ""),
                json.dumps(r.get("sources", {}), ensure_ascii=False),
                r.get("translation", ""), r.get("status", "todo"),
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
    return len(segments)


def build_index_database(root: Path, config: dict[str, Any], dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(dest)
    try:
        return populate_index_database(root, config, con)
    finally:
        con.close()


def index_project(root: Path, config: dict[str, Any]) -> int:
    dest = db_path(root, config)
    temp = dest.with_name(f"{dest.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        count = build_index_database(root, config, temp)
        temp.replace(dest)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    print(f"Indexed {count} segments into {dest}")
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
        items = [json.loads(row["payload_json"])
                 for row in con.execute("SELECT payload_json FROM decisions")]
        superseded = {str(item.get("supersedes")) for item in items
                      if item.get("supersedes")}
        for item in items:
            linked = set(map(str, item.get("segment_ids", item.get("segments", []))))
            if (linked & segment_ids and item.get("status") == "approved"
                    and str(item.get("id")) not in superseded):
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
    found = character_doc_path(root, config, speaker)
    return found[0].read_text(encoding="utf-8-sig") if found else None


def character_doc_path(root: Path, config: dict[str, Any],
                       speaker: str) -> tuple[Path, str] | None:
    """Путь к карточке и её текст.

    Путь нужен затем, что карточка целиком в пакет больше не вклеивается:
    шестьдесят строк доказательств на персонажа вытесняли собой сам текст.
    В пакете остаётся манера, а за обоснованием агент ходит по ссылке.
    """
    base = root / config.get("paths", {}).get("characters", "docs/characters")
    if not base.exists():
        return None
    normalized = speaker.lower().replace("_", "-")
    candidates = [base / f"{normalized}.md", base / f"{speaker}.md", base / f"{speaker.lower()}.md"]
    for path in candidates:
        if path.exists():
            return path, path.read_text(encoding="utf-8-sig")
    # Ярлык говорящего в сегменте - японская строка (羽依里, しろは), а карточки
    # названы латиницей. Поэтому совпадение по имени файла и по id не срабатывает
    # никогда, и карточки не доходили до переводчика вовсе (FND-0048).
    # Ищем по японскому имени, объявленному в самой карточке.
    escaped = re.escape(speaker)
    patterns = [
        rf"(?mi)^id:\s*{escaped}\s*$",
        rf"(?mi)^name_ja:\s*\"?{escaped}\"?\s*$",
        rf"(?mi)^\s+ja:\s*\"?{escaped}\"?\s*$",
    ]
    for path in base.glob("*.md"):
        text = path.read_text(encoding="utf-8-sig")
        head = text.split("---", 2)[1] if text.startswith("---") else text[:800]
        if any(re.search(p, head) for p in patterns):
            return path, text
    return None


def voice_digest(doc: str, limit: int = 6) -> str:
    """Только манера речи: первые пункты раздела о ней.

    Остальное в карточке - подсчёты, проверки чужих утверждений и оговорки о
    методе. Это доказательства, нужные при разборе трудного места, а не при
    каждой реплике, поэтому они остаются за ссылкой.
    """
    lines = doc.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("## ") and "речевая манера" in line.lower()), None)
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("- ") or line.startswith("  "):
            if line.startswith("- "):
                if len(out) >= limit:
                    break
                out.append(line)
            elif out:
                out[-1] += " " + line.strip()
    return "\n".join(out)


def glossary_for_scene(root: Path, config: dict[str, Any], source_text: str) -> list[dict[str, Any]]:
    path = root / config.get("paths", {}).get("glossary", "docs/glossary.yaml")
    items = read_yaml(path, []) or []
    result = []
    for item in items if isinstance(items, list) else []:
        src = str(item.get("source", "")) if isinstance(item, dict) else ""
        if src and src in source_text:
            result.append(item)
    return result


def glossary_note(item: dict[str, Any]) -> str:
    values: list[str] = []
    for field in ("note", "notes"):
        value = item.get(field)
        if isinstance(value, list):
            values.extend(str(part).strip() for part in value if str(part).strip())
        elif value is not None and str(value).strip():
            values.append(str(value).strip())
    return " ".join(values)


def related_questions(root: Path, config: dict[str, Any], scene_ids: set[str],
                      segment_ids: set[str], glossary: list[dict[str, Any]] | None = None,
                      source_text: str = "", *, open_only: bool = True) -> list[dict[str, Any]]:
    linked_question_ids = {
        str(question_id)
        for item in (glossary or [])
        for question_id in (item.get("open_questions") or [])
    }
    path = root / config.get("paths", {}).get(
        "questions", "translation/open-questions.jsonl")
    result: list[dict[str, Any]] = []
    for raw in read_jsonl(path):
        row = clean_meta(raw)
        if open_only and row.get("status") != "open":
            continue
        linked_segments = set(map(str, row.get("segment_ids", [])))
        raw_source_terms = row.get("source_terms")
        source_terms = ([str(term) for term in raw_source_terms if str(term)]
                        if isinstance(raw_source_terms, list) else [])
        if (str(row.get("scene_id", "")) in scene_ids
                or bool(linked_segments & segment_ids)
                or str(row.get("id", "")) in linked_question_ids
                or row.get("kind") == "policy"
                or any(term in source_text for term in source_terms)):
            result.append(row)
    return result


def active_findings_for_package(root: Path, config: dict[str, Any], *, role: str,
                                russian_only: bool = False) -> list[dict[str, Any]]:
    path = root / config.get("paths", {}).get(
        "findings", "docs/project/findings.jsonl")
    result: list[dict[str, Any]] = []
    for raw in read_jsonl(path):
        row = clean_meta(raw)
        if findings_relevance(row) != "current":
            continue
        if role in {"translator", "review", "review-fix", "review-recheck", "reviewer"}:
            if row.get("area") not in {"content", "font"}:
                continue
        elif role in {"stylist", "auditor"} and row.get("area") != "content":
            continue
        statement = " ".join(str(row.get("statement", "")).split())
        item = {
            "id": row.get("id"),
            "status": row.get("status"),
            "area": row.get("area"),
            "kind": row.get("kind"),
            "title": row.get("title"),
            "statement": statement[:320],
        }
        if russian_only:
            item = {
                key: CJK_RE.sub("", str(value)).strip() if isinstance(value, str) else value
                for key, value in item.items()
            }
        result.append(item)
    return result


def markdown_section(doc: str, heading: str) -> str:
    lines = doc.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.strip().lower() == f"## {heading}".lower()), None)
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out).strip()


def voice_contract(doc: str, *, russian_only: bool = False) -> str:
    status = "unknown"
    body = doc
    if doc.startswith("---"):
        pieces = doc.split("---", 2)
        if len(pieces) == 3:
            meta = yaml.safe_load(pieces[1]) if yaml else {}
            if isinstance(meta, dict):
                status = str(meta.get("status", "unknown"))
            body = pieces[2]
    sections = []
    for heading in ("Базовая письменная речевая манера", "Обращения", "Не использовать"):
        text = markdown_section(body, heading)
        if text:
            sections.append(f"### {heading}\n{text}")
    result = f"Статус карточки: {status}.\n" + ("\n\n".join(sections) or "Манера не описана.")
    if russian_only:
        result = re.sub(r"「[^」]*」|『[^』]*』", "", result)
        result = CJK_RE.sub("", result)
        result = re.sub(r"[ \t]+", " ", result)
    return result.strip()


MARKUP_TOKEN = re.compile(
    r"\$\[\$b|\$\]|\$\([0-9]+\)|\$C\[[0-9a-fA-F]*\]|\$[dw]|"
    r"\$S(?:\([^)]*\)|[0-9]+)?"
)


def markup_contract(source: str) -> dict[str, Any]:
    tokens = MARKUP_TOKEN.findall(strip_ruby(source))
    ruby_bases = [match.group(1) for match in RUBY.finditer(source)]
    return {
        "preserve_exact": tokens,
        "remove_ruby_keep_base": ruby_bases,
    }


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


def approved_names(root: Path, config: dict[str, Any]) -> dict[str, str]:
    """Утверждённые русские формы имён: справочник говорящих плюс глоссарий."""
    names: dict[str, str] = {}
    roles: set[str] = set()
    speakers = root / "translation/speakers.jsonl"
    if speakers.exists():
        for row in read_jsonl(speakers):
            if row.get("kind") == "person" and row.get("preferred_ru"):
                names[str(row["source"])] = str(row["preferred_ru"])
            elif row.get("kind") in ("role", "unknown"):
                roles.add(str(row["source"]))
    glossary = read_yaml(root / config.get("paths", {}).get(
        "glossary", "docs/glossary.yaml"), []) or []
    # Ярлык говорящего выводится движком отдельным полем, внутри строки его быть
    # не должно: проверять его там - гарантированное ложное срабатывание.
    skip = {"speaker_label", "role", "address"}
    for row in glossary:
        source = str(row.get("source", ""))
        if row.get("kind") in skip or source in roles:
            continue
        if source and row.get("preferred_ru"):
            names.setdefault(source, str(row["preferred_ru"]))
    return names


def findings_relevance(row: dict[str, Any]) -> str:
    """Актуальна ли находка для текущей работы.

    Опровергнутое и отозванное не удаляется - ложный след экономит время
    следующему, - но и не должно занимать контекст наравне с действующим.
    Правило выводится из уже записанных полей, а не назначается вручную.
    """
    if row.get("status") in ("refuted", "deprecated"):
        return "archive"
    if row.get("applies_to_build") == "siglus":
        return "archive"
    return "current"


def rules_checklist(root: Path, config: dict[str, Any]) -> list[str]:
    """Короткий чек-лист из утверждённых решений.

    Он порождается из `decisions.jsonl`, а не пишется отдельно: иначе список
    правил и список решений разъезжаются, и агент получает вчерашнюю политику.
    """
    path = root / config.get("paths", {}).get("decisions", "docs/decisions.jsonl")
    rows = read_jsonl(path)
    # Отменённое решение не должно доходить до переводчика: оно противоречит
    # тому, которое его отменило, и агент не обязан догадываться, какое новее.
    superseded = {str(r.get("supersedes")) for r in rows if r.get("supersedes")}
    # Решения о сборке и организации проекта переводчику не нужны.
    relevant = {"style", "punctuation", "naming", "voice", "terminology", "humour"}
    out: list[str] = []
    for row in rows:
        if row.get("status") != "approved" or row.get("scope") != "global":
            continue
        if str(row.get("id")) in superseded or row.get("type") not in relevant:
            continue
        text = " ".join(str(row.get("decision", "")).split())
        out.append(f"[{row['id']}] {text}")
    return out


def brief(root: Path, config: dict[str, Any]) -> int:
    """Сводка для входа в проект: что решено, что открыто, что установлено.

    Существует потому, что записать знание есть куда, а прочитать его никто не
    обязан. Правило «прочитай docs/project/» не работает: свежий агент читает
    то, что успеет, и предлагает как новинку решение, принятое неделю назад.
    Здесь действует тот же принцип, что в work next - знание вкладывают, а не
    сообщают, где оно лежит.
    """
    print("=" * 70)
    print("СОСТОЯНИЕ ПРОЕКТА")
    print("=" * 70)

    scenes = load_scenes(root, config)
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    total = done = 0
    for path in sorted(seg_dir.glob("*.jsonl")):
        for row in read_jsonl(path):
            total += 1
            if str(row.get("translation", "")).strip():
                done += 1
    print(f"Сцен: {len(scenes)} | сегментов: {total} | переведено: {done} "
          f"({done / total * 100:.3f}%)" if total else "Сегментов нет")

    integration = config.get("integration", {})
    slot = config.get("source_sets", {}).get("steam_luca", {}).get("build_slot")
    print(f"Языковой слот сборки: {slot} | build_command: "
          f"{integration.get('build_command') or 'НЕ ЗАДАН'}")

    print("\n" + "=" * 70)
    print("УТВЕРЖДЁННЫЕ РЕШЕНИЯ")
    print("=" * 70)
    rows = read_jsonl(root / config.get("paths", {}).get(
        "decisions", "docs/decisions.jsonl"))
    superseded = {str(r.get("supersedes")) for r in rows if r.get("supersedes")}
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") != "approved" or str(row.get("id")) in superseded:
            continue
        groups.setdefault(str(row.get("type", "прочее")), []).append(row)
    for kind in sorted(groups):
        print(f"\n[{kind}]")
        for row in groups[kind]:
            text = " ".join(str(row.get("decision", "")).split())
            print(f"  {row['id']}: {text}")

    print("\n" + "=" * 70)
    print("УСТАНОВЛЕНО О ДВИЖКЕ И ТЕКСТЕ")
    print("=" * 70)
    fpath = root / config.get("paths", {}).get("findings", "docs/project/findings.jsonl")
    for row in read_jsonl(fpath):
        if findings_relevance(row) == "current":
            print(f"  {row['id']} [{row.get('status')}/{row['kind']}] {row['title']}")

    print("\n" + "=" * 70)
    print("ОЧЕРЕДЬ ВОПРОСОВ")
    print("=" * 70)
    qpath = root / config.get("paths", {}).get(
        "questions", "translation/open-questions.jsonl")
    if qpath.exists():
        open_rows = [r for r in read_jsonl(qpath) if r.get("status") == "open"]
        counts = Counter(str(row.get("kind", "other")) for row in open_rows)
        print(f"  открыто: {len(open_rows)} {dict(sorted(counts.items()))}")
        policy_rows = [row for row in open_rows if row.get("kind") == "policy"]
        for row in policy_rows:
            print(f"  {row['id']} [{row.get('kind')}] "
                  f"{' '.join(str(row.get('question','')).split())[:90]}")
            print(f"      рабочий вариант: "
                  f"{' '.join(str(row.get('provisional','')).split())[:80]}")
        if not open_rows:
            print("  нет")
        elif not policy_rows:
            print("  глобальных policy-вопросов нет")
        print("  Сценовые вопросы подставляются только в связанные рабочие пакеты.")

    print("\nПодробности: docs/project/luca-format.md — как устроен формат;")
    print("docs/translation-spec.md — переводческая политика;")
    print("docs/project/findings-archive.jsonl — опровергнутое и legacy.")
    return 0


def next_unfinished_scene(root: Path, config: dict[str, Any]) -> str | None:
    """Следующая сцена для перевода.

    Без этого сцену выбирает человек, и нигде не записано, где остановились.
    Порядок берём из каталога сцен, а не из имён файлов: он отражает ход игры.

    Два правила поверх порядка, оба выведены из наблюдённой ошибки:

    - начатая сцена важнее новой. Иначе очередь уводит с недоделанной сцены на
      более раннюю по номеру, и брошенный хвост не находит никто;
    - сцены из ``workflow.deferred_scenes`` уходят в конец. Первый номер файла
      занимает отладочный скрипт с именами звуков и служебными сообщениями:
      без этого правила перевод начинается именно с него.
    """
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    deferred = set(config.get("workflow", {}).get("deferred_scenes") or [])
    buckets: dict[tuple[bool, bool], list[str]] = {}
    for scene in load_scenes(root, config):
        scene_id = str(scene["scene_id"])
        path = seg_dir / f"{scene_id}.jsonl"
        if not path.exists():
            continue
        rows = read_jsonl(path)
        translated = [bool(str(r.get("translation", "")).strip()) for r in rows]
        if all(translated):
            continue
        buckets.setdefault((scene_id in deferred, not any(translated)), []).append(scene_id)
    for key in ((False, False), (False, True), (True, False), (True, True)):
        if buckets.get(key):
            return buckets[key][0]
    return None


def next_unfinished_scenes(root: Path, config: dict[str, Any], limit: int,
                           max_segments: int) -> list[str]:
    if limit < 1:
        raise ValueError("scene selection size must be at least 1")
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    deferred = set(config.get("workflow", {}).get("deferred_scenes") or [])
    buckets: dict[tuple[bool, bool], list[tuple[str, str, int]]] = defaultdict(list)
    for scene in load_scenes(root, config):
        scene_id = str(scene["scene_id"])
        path = seg_dir / f"{scene_id}.jsonl"
        if not path.exists():
            continue
        rows = read_jsonl(path)
        pending = [index for index, row in enumerate(rows)
                   if not str(row.get("translation", "")).strip()]
        if not pending:
            continue
        first = pending[0]
        buckets[(scene_id in deferred, first == 0)].append(
            (scene_id, str(scene.get("route", "")), len(rows) - first))
    candidates: list[tuple[str, str, int]] = []
    for key in ((False, False), (False, True), (True, False), (True, True)):
        candidates.extend(buckets.get(key, []))
    if not candidates:
        return []
    route = candidates[0][1]
    selected: list[str] = []
    total = 0
    for scene_id, scene_route, count in candidates:
        if scene_route != route:
            continue
        if selected and (len(selected) >= limit
                         or (max_segments > 0 and total + count > max_segments)):
            break
        selected.append(scene_id)
        total += count
        if len(selected) >= limit:
            break
    return selected


STAGE_ORDER = (
    "переводить", "review initial", "review fix", "review recheck", "review finalize",
    "review wait", "смешанная",
)
STYLE_READY_STATUSES = {"reviewed", "playable", "lqa", "approved"}
STYLE_EVENTS = {
    "ledger_initialized", "run_started", "window_applied",
    "window_revised", "window_accepted", "route_audited", "build_readback",
}
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
CJK_RUN_RE = re.compile(CJK_RE.pattern + "+")


def russian_only_projection(text: str) -> str:
    return CJK_RUN_RE.sub("[иероглиф]", text)


def scene_stage(statuses: Counter) -> str:
    """Ступень конвейера, на которой сцена ждёт работы.

    Ступень выводится из статусов сегментов, а не хранится отдельно: отдельное
    поле пришлось бы обновлять вручную, и оно разошлось бы с текстом.
    """
    if statuses.get("todo"):
        return "переводить"
    only = set(statuses)
    if only == {"draft"}:
        return "ревью"
    if only <= STYLE_READY_STATUSES:
        return ""
    return "смешанная"


def style_ledger_path(root: Path, config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get("style_ledger", "translation/style-ledger.jsonl")
    return root / rel


def load_style_events(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    return [clean_meta(row) for row in read_jsonl(style_ledger_path(root, config))]


def append_style_event(root: Path, config: dict[str, Any], event: dict[str, Any]) -> None:
    path = style_ledger_path(root, config)
    with exclusive_file_lock(path):
        rows = load_style_events(root, config)
        rows.append(event)
        write_jsonl_atomic(path, rows)


def style_runs(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for event in events:
        run_id = str(event.get("run_id", ""))
        kind = event.get("event")
        if kind == "run_started":
            runs[run_id] = {
                **event,
                "applied": {},
                "revisions": {},
                "accepted": {},
                "reopened": set(),
                "audit": None,
                "builds": [],
            }
        elif run_id in runs and kind == "window_applied":
            runs[run_id]["applied"][str(event["window_id"])] = event
        elif run_id in runs and kind == "window_revised":
            window_id = str(event["window_id"])
            runs[run_id]["revisions"].setdefault(window_id, []).append(event)
            if window_id in runs[run_id]["accepted"]:
                runs[run_id]["reopened"].add(window_id)
            runs[run_id]["accepted"].pop(window_id, None)
            runs[run_id]["audit"] = None
        elif run_id in runs and kind == "window_accepted":
            window_id = str(event["window_id"])
            runs[run_id]["accepted"][window_id] = event
            runs[run_id]["reopened"].discard(window_id)
        elif run_id in runs and kind == "route_audited":
            runs[run_id]["audit"] = event
        elif run_id in runs and kind == "build_readback":
            runs[run_id]["builds"].append(event)
    return runs


def style_effective_changes(run: dict[str, Any], window_id: str) -> list[dict[str, Any]]:
    applied = run.get("applied", {}).get(window_id)
    if not applied:
        return []
    order = [str(change["id"]) for change in applied.get("changes", [])]
    by_id = {str(change["id"]): dict(change) for change in applied.get("changes", [])}
    for event in run.get("revisions", {}).get(window_id, []):
        for revision in event.get("changes", []):
            sid = str(revision["id"])
            if sid not in by_id:
                by_id[sid] = dict(revision)
                order.append(sid)
                continue
            by_id[sid]["after"] = revision.get("after", by_id[sid].get("after"))
            by_id[sid]["flags_after"] = revision.get(
                "flags_after", by_id[sid].get("flags_after", []))
            by_id[sid]["reason"] = revision.get("reason", by_id[sid].get("reason"))
    return [by_id[sid] for sid in order]


def route_scenes(root: Path, config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scene in load_scenes(root, config):
        route = str(scene.get("route", ""))
        if route:
            out[route].append(scene)
    return dict(out)


def style_route_rows(root: Path, config: dict[str, Any], route: str) -> list[dict[str, Any]]:
    scenes = route_scenes(root, config).get(route)
    if not scenes:
        raise ValueError(f"Unknown style block: {route}")
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    rows: list[dict[str, Any]] = []
    for scene in scenes:
        path = seg_dir / f"{scene['scene_id']}.jsonl"
        if not path.exists():
            raise ValueError(f"Missing segment file for {scene['scene_id']}")
        rows.extend(clean_meta(row) for row in read_jsonl(path))
    return rows


def style_text_hash(rows: list[dict[str, Any]]) -> str:
    payload = [{"id": row["id"], "translation": row.get("translation", "")} for row in rows]
    return sha256_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def style_slice_hash(rows: list[dict[str, Any]], *,
                     status_ids: set[str] | None = None) -> str:
    protected_status_ids = (
        {str(row["id"]) for row in rows} if status_ids is None else status_ids)
    payload = [{
        "id": row["id"],
        "translation": row.get("translation", ""),
        "status": row.get("status") if str(row["id"]) in protected_status_ids else None,
        "flags": row.get("flags", []),
    } for row in rows]
    return sha256_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def style_package_hash(rows: list[dict[str, Any]],
                       editable: list[dict[str, Any]]) -> str:
    status_ids = {
        str(row["id"]) for row in editable
        if not CJK_RE.search(str(row.get("translation", "")))
    }
    return style_slice_hash(rows, status_ids=status_ids)


def plan_style_windows(rows: list[dict[str, Any]], minimum: int, maximum: int,
                       context: int) -> list[dict[str, Any]]:
    total = len(rows)
    if not total:
        return []
    if minimum <= 0 or maximum < minimum or context < 0:
        raise ValueError("Invalid style window configuration")
    if total <= maximum:
        count = 1
    else:
        count = math.ceil(total / maximum)
        if total // count < minimum:
            count -= 1
        if count <= 0 or math.ceil(total / count) > maximum or total // count < minimum:
            raise ValueError(
                f"Cannot split {total} segments into windows of {minimum}-{maximum}")
    base, extra = divmod(total, count)
    windows: list[dict[str, Any]] = []
    first = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        last = first + size
        windows.append({
            "window_id": f"W{index + 1:03d}",
            "editable_first": str(rows[first]["id"]),
            "editable_last": str(rows[last - 1]["id"]),
            "editable_count": size,
            "context_before": min(context, first),
            "context_after": min(context, total - last),
        })
        first = last
    return windows


def style_window_rows(rows: list[dict[str, Any]], window: dict[str, Any]) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {str(row["id"]): index for index, row in enumerate(rows)}
    try:
        first = by_id[str(window["editable_first"])]
        last = by_id[str(window["editable_last"])] + 1
    except KeyError as exc:
        raise ValueError(f"Style window boundary is absent: {exc}") from exc
    editable = rows[first:last]
    if len(editable) != int(window["editable_count"]):
        raise ValueError(f"Style window {window['window_id']} changed size")
    start = max(0, first - int(window["context_before"]))
    end = min(len(rows), last + int(window["context_after"]))
    return rows[start:end], editable


def current_style_run(root: Path, config: dict[str, Any], route: str) -> dict[str, Any] | None:
    runs = style_runs(load_style_events(root, config))
    candidates = [run for run in runs.values() if run.get("route") == route]
    return candidates[-1] if candidates else None


def style_run_complete(root: Path, config: dict[str, Any], route: str) -> bool:
    run = current_style_run(root, config, route)
    if not run or not run.get("audit"):
        return False
    rows = style_route_rows(root, config, route)
    return run["audit"].get("route_sha256") == style_text_hash(rows)


def work_queue(root: Path, config: dict[str, Any]) -> int:
    """Что готово к работе на каждой ступени.

    Без этого очередь отвечала только на вопрос «что переводить», и остальные
    ступени приходилось искать глазами. Залп из нескольких агентов собирается
    именно отсюда: каждая ступень идёт на своей сцене, параллельно остальным.
    """
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    deferred = set(config.get("workflow", {}).get("deferred_scenes") or [])
    buckets: dict[str, list[tuple[str, int, bool, str]]] = defaultdict(list)
    active_style_routes = {
        str(run.get("route")) for run in style_runs(load_style_events(root, config)).values()
        if run.get("route") and not run.get("audit")
    }
    done = 0
    total_segments = 0
    translated_segments = 0
    all_statuses: Counter = Counter()
    for scene in load_scenes(root, config):
        scene_id = str(scene["scene_id"])
        path = seg_dir / f"{scene_id}.jsonl"
        if not path.exists():
            continue
        rows = read_jsonl(path)
        total_segments += len(rows)
        translated_segments += sum(
            1 for row in rows if str(row.get("translation", "")).strip())
        statuses = Counter(str(r.get("status")) for r in rows)
        all_statuses.update(statuses)
        stage = scene_stage(statuses)
        route = str(scene.get("route", ""))
        if route in active_style_routes and stage == "смешанная":
            continue
        if not stage:
            if route in set(config.get("workflow", {}).get("style_service_routes") or []):
                done += 1
            elif style_run_complete(root, config, route) and set(statuses) <= {
                    "playable", "lqa", "approved"}:
                done += 1
            continue
        note = ""
        queue_stage = stage
        if stage == "ревью":
            run = latest_review_for_scene(root, config, scene_id)
            if not run:
                queue_stage = "review initial"
            elif run.get("accepted"):
                queue_stage = "review wait"
                note = "принято, обновить статусы"
            else:
                open_ids = review_open_issue_ids(run)
                escalations = sum(1 for item in effective_review_resolutions(run)
                                  if item.get("escalation"))
                if run.get("finalization_blocked"):
                    queue_stage = "review wait"
                    note = "конфликт финальной правки"
                elif escalations:
                    queue_stage = "review wait"
                    note = f"решение пользователя: {escalations}"
                elif run.get("resolution") and open_ids:
                    queue_stage = "review fix"
                    note = f"дельта: {len(open_ids)}"
                elif run.get("resolution"):
                    if run.get("rechecks"):
                        queue_stage = "review finalize"
                        note = "после единственной перепроверки"
                    else:
                        queue_stage = "review recheck"
                else:
                    queue_stage = "review fix"
                    counts = Counter(
                        str(issue.get("severity")) for issue in run.get("issues", []))
                    note = "/".join(
                        f"{key}:{counts[key]}" for key in
                        ("critical", "major", "minor", "preference") if counts[key])
        buckets[queue_stage].append((scene_id, len(rows), scene_id in deferred, note))

    for stage in STAGE_ORDER:
        items = buckets.get(stage) or []
        if not items:
            continue
        items.sort(key=lambda item: (item[2], item[0]))
        shown = ", ".join(
            f"{scene_id} ({count}{', отложена' if is_deferred else ''}"
            f"{', ' + note if note else ''})"
            for scene_id, count, is_deferred, note in items[:8])
        tail = f" … ещё {len(items) - 8}" if len(items) > 8 else ""
        print(f"{stage:12} {shown}{tail}")

    service = set(config.get("workflow", {}).get("style_service_routes") or [])
    style_items: list[str] = []
    build_items: list[str] = []
    for route, scenes in sorted(route_scenes(root, config).items()):
        if route in service:
            continue
        rows = style_route_rows(root, config, route)
        statuses = {str(row.get("status")) for row in rows}
        run = current_style_run(root, config, route)
        if run and not run.get("audit"):
            accepted = len(run["accepted"])
            style_items.append(f"{route} ({accepted}/{len(run['windows'])} окон принято)")
        elif statuses <= STYLE_READY_STATUSES and not style_run_complete(root, config, route):
            style_items.append(f"{route} ({len(rows)}, начать)")
        elif style_run_complete(root, config, route) and "reviewed" in statuses:
            build_items.append(f"{route} ({len(rows)})")
    if style_items:
        print(f"{'вычитка':12} " + ", ".join(style_items[:8]))
    if build_items:
        print(f"{'собирать':12} " + ", ".join(build_items[:8]))
    print(f"{'готово':12} {done} сцен")
    percent = 100.0 * translated_segments / total_segments if total_segments else 0.0
    status_text = ", ".join(f"{key}={value}" for key, value in sorted(all_statuses.items()))
    print(f"{'статус':12} {translated_segments}/{total_segments} ({percent:.1f}%); {status_text}")
    return 0


SILENCE_ONLY = re.compile(r"^[\s\u3000…\u2026「」『』]*$")
# Только явный обрыв: запятая, многоточие или っ на конце. Голая падежная
# частица сюда не входит намеренно - 「俺が」 это законченное эллиптическое
# высказывание, и запрет на нём заморозил бы ровно те строки, которые надо
# чинить: «Я.» вместо «Это я.», «Сердце.» вместо «В сердце».
DANGLING_TAIL = re.compile(r"(?:[、,]|\u2026|っ)\s*[」』]?\s*$")


def style_start(root: Path, config: dict[str, Any], route: str) -> int:
    service = set(config.get("workflow", {}).get("style_service_routes") or [])
    if route in service:
        raise ValueError(f"Service block {route} is not a literary style run")
    rows = style_route_rows(root, config, route)
    bad = Counter(str(row.get("status")) for row in rows
                  if str(row.get("status")) not in STYLE_READY_STATUSES)
    if bad:
        raise ValueError(f"Style block {route} is not reviewed completely: {dict(bad)}")
    current = current_style_run(root, config, route)
    if current and not current.get("audit"):
        raise ValueError(f"Style run already active: {current['run_id']}")
    if style_run_complete(root, config, route):
        print(f"{route}: current text already passed style audit")
        return 0
    events = load_style_events(root, config)
    serial = 1 + sum(1 for event in events
                     if event.get("event") == "run_started" and event.get("route") == route)
    run_id = f"STYLE-{route}-{serial:02d}"
    workflow = config.get("workflow", {})
    windows = plan_style_windows(
        rows,
        int(workflow.get("style_window_min", 600)),
        int(workflow.get("style_window_max", 1000)),
        int(workflow.get("style_context_segments", 75)),
    )
    append_style_event(root, config, {
        "schema_version": 1,
        "event": "run_started",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "route": route,
        "route_sha256": style_text_hash(rows),
        "segment_count": len(rows),
        "windows": windows,
    })
    print(f"{run_id}: {len(rows)} segments, {len(windows)} windows")
    return 0


def speaker_labels(root: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in read_jsonl(root / "translation/speakers.jsonl"):
        labels[str(row.get("source"))] = str(row.get("preferred_ru") or row.get("id"))
    return labels


def russian_voice_digest(doc: str, limit: int = 3) -> str:
    text = voice_digest(doc, limit=limit)
    text = re.sub(r"「[^」]*」|『[^』]*』", "", text)
    text = CJK_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.;:])", r"\1", text)
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


def source_text_by_segment(root: Path, config: dict[str, Any],
                           rows: list[dict[str, Any]]) -> dict[str, str]:
    keys = {(str(row["source_set_id"]), str(row["source_id"])) for row in rows}
    records = load_source_records(root, config, keys)
    out: dict[str, str] = {}
    for row in rows:
        item = records[(str(row["source_set_id"]), str(row["source_id"]))]
        slots = {str(slot["language"]): str(slot.get("body_text", slot.get("text", "")))
                 for slot in item.get("slots", [])}
        out[str(row["id"])] = slots.get("ja", "")
    return out


def style_package(root: Path, config: dict[str, Any], run_id: str,
                  window_id: str | None = None) -> str:
    runs = style_runs(load_style_events(root, config))
    run = runs.get(run_id)
    if not run:
        raise ValueError(f"Unknown style run: {run_id}")
    if window_id:
        window = next((w for w in run["windows"]
                       if str(w["window_id"]) == window_id), None)
        if not window:
            raise ValueError(f"Unknown style window: {run_id}/{window_id}")
        if window_id in run["applied"]:
            raise ValueError(f"Style window already applied: {run_id}/{window_id}")
    else:
        window = next((w for w in run["windows"]
                       if str(w["window_id"]) not in run["applied"]), None)
    if not window:
        return f"# {run_id}\n\nВсе окна применены; ожидается проверка дельты и аудит.\n"
    rows = style_route_rows(root, config, str(run["route"]))
    package_rows, editable = style_window_rows(rows, window)
    cjk_locked_ids = {
        str(row["id"]) for row in editable
        if CJK_RE.search(str(row.get("translation", "")))
    }
    editable_ids = {str(row["id"]) for row in editable} - cjk_locked_ids
    all_ids = {str(row["id"]) for row in package_rows}
    labels = speaker_labels(root)
    source_texts = source_text_by_segment(root, config, package_rows)
    constraints: list[str] = []
    for item in safe_constraints(root, config, all_ids):
        for rule in item.get("safe_rules", []):
            safe_rule = russian_only_projection(str(rule)).strip()
            if safe_rule:
                constraints.append(f"- {', '.join(item['segment_ids'])}: {safe_rule}")
    for sid in sorted(cjk_locked_ids):
        constraints.append(
            f"- {sid}: строка содержит намеренное иероглифическое написание; не редактировать")
    for row in package_rows:
        sid = str(row["id"])
        source = source_texts[sid]
        if SILENCE_ONLY.fullmatch(source):
            constraints.append(f"- {sid}: строка молчания, словами не заполнять")
        elif DANGLING_TAIL.search(source):
            constraints.append(
                f"- {sid}: мысль оборвана; переформулировать можно, договаривать нельзя")

    source_text = "\n".join(source_texts.values())
    glossary = glossary_for_scene(root, config, source_text)

    base_sha = style_package_hash(package_rows, editable)
    parts = [
        f"# Русская вычитка {run_id} / {window['window_id']}",
        "",
        f"Редактируемо: {len(editable_ids)} сегментов. Контекст по краям неизменяем.",
        f"base_sha256: `{base_sha}`",
        "",
        "Оригинала и переводов-посредников в пакете нет намеренно. Судить нужно "
        "русский текст как самостоятельный.",
        "Смысловой инвентарь `before` заблокирован: конкретные существа, предметы, "
        "места, числа, элементы списка и оба участника сравнения нельзя удалять, "
        "обобщать или заменять отрицательной формулой. Если без этого фраза не "
        "чинится, оставь текст и добавь needs_source_check.",
    ]
    if constraints:
        parts.extend(["", "## Ограничения", "", *sorted(set(constraints))])
    parts.extend(["", render_required_knowledge(
        root, config, package_rows, glossary, role="stylist", russian_only=True)])
    parts.extend(["", "## Текст", "", "```jsonl"])
    for row in package_rows:
        parts.append(json.dumps({
            "id": row["id"],
            "scene": row["scene_id"],
            "scope": "editable" if str(row["id"]) in editable_ids else "context",
            "speaker": labels.get(str(row.get("speaker")), None) if row.get("speaker") else None,
            "ru": russian_only_projection(str(row.get("translation", ""))),
            "flags": row.get("flags", []),
            "markup": markup_contract(str(row.get("translation", ""))),
        }, ensure_ascii=False))
    parts.extend([
        "```", "", "## Сдать", "",
        f"Патч: `build/style-{run_id}-{window['window_id']}.jsonl`.",
        "Первая строка:",
        "```json",
        json.dumps({"__style_window__": {
            "run_id": run_id,
            "window_id": window["window_id"],
            "base_sha256": base_sha,
        }}, ensure_ascii=False),
        "```",
        "Дальше только реально изменённые editable-записи:",
        '```json\n{"id":"...","before":"...","translation":"...","reason":"..."}\n```',
        "При риске смыслового изменения текст не переписывай: оставь `translation` "
        "равным `before` и добавь `\"flags\":[\"needs_source_check\"]`.",
        "Статус в патче не указывается: его назначает инструмент.",
        "",
        f"Проверка: `python tools/vnctl.py style check {run_id} "
        f"{window['window_id']} build/style-{run_id}-{window['window_id']}.jsonl`",
        f"Применение: `python tools/vnctl.py style apply {run_id} "
        f"{window['window_id']} build/style-{run_id}-{window['window_id']}.jsonl`",
    ])
    output = "\n".join(parts)
    if CJK_RE.search(output):
        raise RuntimeError("Russian-only style package contains CJK")
    return output


def style_run_window(root: Path, config: dict[str, Any], run_id: str,
                     window_id: str) -> tuple[dict[str, Any], dict[str, Any],
                                               list[dict[str, Any]], list[dict[str, Any]],
                                               list[dict[str, Any]]]:
    run = style_runs(load_style_events(root, config)).get(run_id)
    if not run:
        raise ValueError(f"Unknown style run: {run_id}")
    window = next((item for item in run["windows"]
                   if str(item["window_id"]) == window_id), None)
    if not window:
        raise ValueError(f"Unknown style window: {run_id}/{window_id}")
    rows = style_route_rows(root, config, str(run["route"]))
    package_rows, editable = style_window_rows(rows, window)
    return run, window, rows, package_rows, editable


def validate_style_patch(root: Path, config: dict[str, Any], run_id: str,
                         window_id: str, patch_path: Path) -> tuple[
                             list[str], list[dict[str, Any]], dict[str, Any]]:
    patch_file = patch_path if patch_path.is_absolute() else root / patch_path
    if not patch_file.exists():
        return [f"patch not found: {patch_file}"], [], {}
    run, window, _, package_rows, editable = style_run_window(
        root, config, run_id, window_id)
    if window_id in run["applied"]:
        return [f"window already applied: {run_id}/{window_id}"], [], {}
    raw_rows = read_jsonl(patch_file)
    headers = [row.get("__style_window__") for row in raw_rows if row.get("__style_window__")]
    if len(headers) != 1 or not isinstance(headers[0], dict):
        return ["patch must contain exactly one __style_window__ header"], [], {}
    header = headers[0]
    errors: list[str] = []
    if header.get("run_id") != run_id or header.get("window_id") != window_id:
        errors.append("patch header does not match requested run/window")
    current_hash = style_package_hash(package_rows, editable)
    if header.get("base_sha256") != current_hash:
        errors.append(
            f"stale style package: header={header.get('base_sha256')} current={current_hash}")

    editable_by_id = {
        str(row["id"]): row for row in editable
        if not CJK_RE.search(str(row.get("translation", "")))
    }
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_texts = source_text_by_segment(root, config, editable)
    qa = read_yaml(root / "config/qa-rules.yaml", {}) or {}
    allowed_flags = set(qa.get("allowed_flags", []))
    allowed_fields = {"id", "before", "translation", "reason", "flags"}
    for index, raw in enumerate(raw_rows, start=1):
        if raw.get("__style_window__"):
            continue
        entry = clean_meta(raw)
        unknown = set(entry) - allowed_fields
        sid = str(entry.get("id", ""))
        if unknown:
            errors.append(f"line {index}: unknown fields {sorted(unknown)}")
            continue
        if sid in seen:
            errors.append(f"line {index}: duplicate id {sid}")
            continue
        seen.add(sid)
        current = editable_by_id.get(sid)
        if not current:
            errors.append(f"line {index}: {sid!r} is not editable in this window")
            continue
        before = str(entry.get("before", ""))
        after = str(entry.get("translation", ""))
        reason = str(entry.get("reason", "")).strip()
        if before != str(current.get("translation", "")):
            errors.append(f"line {index}: before text does not match canonical text for {sid}")
        if not after.strip():
            errors.append(f"line {index}: empty translation for {sid}")
        if not reason:
            errors.append(f"line {index}: missing reason for {sid}")
        old_flags = list(current.get("flags", []) or [])
        new_flags = list(entry.get("flags", old_flags) or [])
        if not set(old_flags) <= set(new_flags):
            errors.append(f"line {index}: style patch may not remove flags from {sid}")
        if set(new_flags) - set(old_flags) - {"needs_source_check"}:
            errors.append(f"line {index}: style patch may add only needs_source_check to {sid}")
        if set(new_flags) - allowed_flags:
            errors.append(f"line {index}: unknown flags for {sid}")
        if after == before and new_flags == old_flags:
            errors.append(f"line {index}: no-op entry for {sid}")
        findings = allowed_line_findings(
            root, sid, check_line(after, is_dialogue=bool(current.get("speaker"))))
        findings += check_markup(source_texts[sid], after)
        for finding in findings:
            errors.append(f"line {index}: {sid} {finding.decision} {finding.message}")
        entry["flags"] = new_flags
        entries.append(entry)
    return errors, entries, header


def style_check(root: Path, config: dict[str, Any], run_id: str,
                window_id: str, patch_path: Path) -> int:
    errors, entries, _ = validate_style_patch(root, config, run_id, window_id, patch_path)
    for message in errors:
        eprint(f"ERROR: {message}")
    print(f"Style patch {run_id}/{window_id}: {len(entries)} changes, {len(errors)} errors")
    return 1 if errors else 0


def write_scene_transaction(root: Path, config: dict[str, Any],
                            scene_rows: dict[str, list[dict[str, Any]]]) -> None:
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    originals: dict[Path, bytes] = {}
    written: list[Path] = []
    try:
        for scene_id, rows in scene_rows.items():
            path = seg_dir / f"{scene_id}.jsonl"
            originals[path] = path.read_bytes()
            write_jsonl_atomic(path, rows)
            written.append(path)
    except Exception:
        for path in written:
            path.write_bytes(originals[path])
        raise


def style_apply(root: Path, config: dict[str, Any], run_id: str,
                window_id: str, patch_path: Path) -> int:
    errors, entries, header = validate_style_patch(
        root, config, run_id, window_id, patch_path)
    if errors:
        for message in errors:
            eprint(f"ERROR: {message}")
        return 1
    _, _, _, _, editable = style_run_window(root, config, run_id, window_id)
    editable_by_id = {str(row["id"]): row for row in editable}
    affected = sorted({str(editable_by_id[str(entry["id"])]["scene_id"]) for entry in entries})
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    scene_rows = {
        scene_id: [clean_meta(row) for row in read_jsonl(seg_dir / f"{scene_id}.jsonl")]
        for scene_id in affected
    }
    canonical = {str(row["id"]): row for rows in scene_rows.values() for row in rows}
    changes: list[dict[str, Any]] = []
    for entry in entries:
        sid = str(entry["id"])
        row = canonical[sid]
        changes.append({
            "id": sid,
            "scene_id": row["scene_id"],
            "before": row.get("translation", ""),
            "after": entry["translation"],
            "before_status": row.get("status"),
            "flags_before": row.get("flags", []),
            "flags_after": entry["flags"],
            "reason": entry["reason"],
        })
        row["translation"] = entry["translation"]
        row["flags"] = entry["flags"]
        row["status"] = "draft"
    if scene_rows:
        write_scene_transaction(root, config, scene_rows)
    patch_file = patch_path if patch_path.is_absolute() else root / patch_path
    append_style_event(root, config, {
        "schema_version": 1,
        "event": "window_applied",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "window_id": window_id,
        "input_sha256": header["base_sha256"],
        "patch_sha256": sha256_file(patch_file),
        "changes": changes,
    })
    print(f"{run_id}/{window_id}: applied {len(changes)} changes; changed rows are draft")
    return 0


STYLE_SEGMENT_ID_RE = re.compile(r"\bSEG[A-Za-z0-9_]+\b")


def style_revision_report(path: Path) -> tuple[str, set[str]]:
    text = path.read_text(encoding="utf-8-sig")
    if report_verdict(path) != "REVISE":
        raise ValueError("Style revision requires a report with VERDICT: REVISE")
    return text, set(STYLE_SEGMENT_ID_RE.findall(text))


def validate_style_revision(root: Path, config: dict[str, Any], run_id: str,
                            window_id: str, patch_path: Path,
                            report_path: Path) -> tuple[
                                list[str], list[dict[str, Any]], dict[str, Any]]:
    patch_file = patch_path if patch_path.is_absolute() else root / patch_path
    if not patch_file.exists():
        return [f"patch not found: {patch_file}"], [], {}
    report_file = report_path if report_path.is_absolute() else root / report_path
    if not report_file.exists():
        return [f"review report not found: {report_file}"], [], {}
    try:
        _, report_ids = style_revision_report(report_file)
    except ValueError as exc:
        return [str(exc)], [], {}
    run, _, route_rows, _, editable = style_run_window(root, config, run_id, window_id)
    if window_id not in run["applied"]:
        return [f"window is not applied: {run_id}/{window_id}"], [], {}
    editable_ids = {str(row["id"]) for row in editable
                    if not CJK_RE.search(str(row.get("translation", "")))}
    allowed_ids = report_ids & editable_ids
    by_id = {str(row["id"]): row for row in route_rows if str(row["id"]) in allowed_ids}
    current_rows = [row for row in route_rows if str(row["id"]) in allowed_ids]
    raw_rows = read_jsonl(patch_file)
    headers = [row.get("__style_revision__") for row in raw_rows
               if row.get("__style_revision__")]
    if len(headers) != 1 or not isinstance(headers[0], dict):
        return ["patch must contain exactly one __style_revision__ header"], [], {}
    header = headers[0]
    errors: list[str] = []
    if header.get("run_id") != run_id or header.get("window_id") != window_id:
        errors.append("revision header does not match requested run/window")
    if report_ids - editable_ids:
        errors.append(
            "review report references IDs outside editable scope: "
            + ", ".join(sorted(report_ids - editable_ids)))
    if header.get("report_sha256") != sha256_file(report_file):
        errors.append("revision header report hash does not match review report")
    if header.get("allowed_ids") != sorted(allowed_ids):
        errors.append("revision header allowed_ids do not match review report")
    current_hash = style_slice_hash(current_rows)
    if header.get("base_sha256") != current_hash:
        errors.append(
            f"stale style revision: header={header.get('base_sha256')} current={current_hash}")

    source_texts = source_text_by_segment(root, config, current_rows)
    qa = read_yaml(root / "config/qa-rules.yaml", {}) or {}
    allowed_flags = set(qa.get("allowed_flags", []))
    allowed_fields = {"id", "before", "translation", "reason", "flags"}
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rows, start=1):
        if raw.get("__style_revision__"):
            continue
        entry = clean_meta(raw)
        unknown = set(entry) - allowed_fields
        sid = str(entry.get("id", ""))
        if unknown:
            errors.append(f"line {index}: unknown fields {sorted(unknown)}")
            continue
        if sid in seen:
            errors.append(f"line {index}: duplicate id {sid}")
            continue
        seen.add(sid)
        current = by_id.get(sid)
        if not current:
            errors.append(f"line {index}: {sid!r} is not named by the review report")
            continue
        if str(current.get("status")) not in ({"draft"} | STYLE_READY_STATUSES):
            errors.append(f"line {index}: {sid} is not eligible for style revision")
        before = str(entry.get("before", ""))
        after = str(entry.get("translation", ""))
        reason = str(entry.get("reason", "")).strip()
        if before != str(current.get("translation", "")):
            errors.append(f"line {index}: before text does not match canonical text for {sid}")
        if not after.strip():
            errors.append(f"line {index}: empty translation for {sid}")
        if not reason:
            errors.append(f"line {index}: missing reason for {sid}")
        old_flags = list(current.get("flags", []) or [])
        new_flags = list(entry.get("flags", old_flags) or [])
        if not set(old_flags) <= set(new_flags):
            errors.append(f"line {index}: style revision may not remove flags from {sid}")
        # A source-aware review may require any configured follow-up flag.
        # Russian-only style patches remain limited to needs_source_check.
        if set(new_flags) - allowed_flags:
            errors.append(f"line {index}: unknown flags for {sid}")
        if after == before and new_flags == old_flags:
            errors.append(f"line {index}: no-op entry for {sid}")
        findings = allowed_line_findings(
            root, sid, check_line(after, is_dialogue=bool(current.get("speaker"))))
        findings += check_markup(source_texts[sid], after)
        for finding in findings:
            errors.append(f"line {index}: {sid} {finding.decision} {finding.message}")
        entry["flags"] = new_flags
        entries.append(entry)
    if not entries:
        errors.append("style revision must contain at least one changed entry")
    return errors, entries, header


def style_revise(root: Path, config: dict[str, Any], run_id: str, window_id: str,
                 patch_path: Path, report_path: Path, actor: str) -> int:
    errors, entries, header = validate_style_revision(
        root, config, run_id, window_id, patch_path, report_path)
    if errors:
        for message in errors:
            eprint(f"ERROR: {message}")
        return 1
    _, _, route_rows, _, _ = style_run_window(root, config, run_id, window_id)
    route_by_id = {str(row["id"]): row for row in route_rows}
    affected = sorted({str(route_by_id[str(entry["id"])]["scene_id"]) for entry in entries})
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    scene_rows = {
        scene_id: [clean_meta(row) for row in read_jsonl(seg_dir / f"{scene_id}.jsonl")]
        for scene_id in affected
    }
    original_rows = {scene_id: [dict(row) for row in rows]
                     for scene_id, rows in scene_rows.items()}
    canonical = {str(row["id"]): row for rows in scene_rows.values() for row in rows}
    changes: list[dict[str, Any]] = []
    for entry in entries:
        sid = str(entry["id"])
        row = canonical[sid]
        changes.append({
            "id": sid,
            "scene_id": row["scene_id"],
            "before": row.get("translation", ""),
            "after": entry["translation"],
            "before_status": row.get("status"),
            "flags_before": row.get("flags", []),
            "flags_after": entry["flags"],
            "reason": entry["reason"],
        })
        row["translation"] = entry["translation"]
        row["flags"] = entry["flags"]
        row["status"] = "draft"
    write_scene_transaction(root, config, scene_rows)
    patch_file = patch_path if patch_path.is_absolute() else root / patch_path
    event = {
        "schema_version": 1,
        "event": "window_revised",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "window_id": window_id,
        "actor": actor,
        "report_sha256": header["report_sha256"],
        "input_sha256": header["base_sha256"],
        "patch_sha256": sha256_file(patch_file),
        "changes": changes,
    }
    try:
        append_style_event(root, config, event)
    except Exception:
        revisions = style_runs(load_style_events(root, config)).get(
            run_id, {}).get("revisions", {}).get(window_id, [])
        if any(item.get("patch_sha256") == event["patch_sha256"] for item in revisions):
            print(f"{run_id}/{window_id}: revised {len(changes)} changes")
            return 0
        write_scene_transaction(root, config, original_rows)
        raise
    print(f"{run_id}/{window_id}: revised {len(changes)} changes")
    return 0


def style_review_package(root: Path, config: dict[str, Any], run_id: str,
                         window_id: str) -> str:
    run, _, route_rows, _, _ = style_run_window(root, config, run_id, window_id)
    applied = run["applied"].get(window_id)
    if not applied:
        raise ValueError(f"Style window is not applied: {run_id}/{window_id}")
    effective = style_effective_changes(run, window_id)
    changed_ids = [str(item["id"]) for item in effective]
    by_id = {str(row["id"]): row for row in route_rows}
    changed_rows = [by_id[sid] for sid in changed_ids]
    keys = {(str(row["source_set_id"]), str(row["source_id"])) for row in changed_rows}
    records = load_source_records(root, config, keys)
    labels = speaker_labels(root)
    positions = {str(row["id"]): i for i, row in enumerate(route_rows)}
    knowledge_rows: list[dict[str, Any]] = []
    for row in changed_rows:
        key = (str(row["source_set_id"]), str(row["source_id"]))
        slots = {str(slot["language"]): str(slot.get("body_text", slot.get("text", "")))
                 for slot in records[key].get("slots", [])}
        knowledge_rows.append({**row, "sources": slots})
    glossary = glossary_for_scene(
        root, config, "\n".join(
            "\n".join(item.get("sources", {}).values()) for item in knowledge_rows))
    parts = [
        f"# Проверка стилевой дельты {run_id} / {window_id}", "",
        "Проверяй только изменённые записи. Соседи даны как неизменяемый контекст.",
        "Задача: убедиться, что улучшение русского не изменило смысл, степень "
        "выразительности, обрыв, двусмысленность, повтор или роль реплики.", "",
        "Отдельно сверь конкретные сущности и предметы, оба участника и направление "
        "каждого сравнения, элементы перечней, числа, отрицание, модальность и "
        "причинность. Обобщение конкретного образа означает VERDICT: REVISE.", "",
        render_required_knowledge(
            root, config, knowledge_rows, glossary, role="reviewer"), "",
        "## Изменения", "", "```jsonl",
    ]
    before_by_id = {str(item["id"]): item for item in effective}
    for row in changed_rows:
        key = (str(row["source_set_id"]), str(row["source_id"]))
        slots = {str(slot["language"]): str(slot.get("body_text", slot.get("text", "")))
                 for slot in records[key].get("slots", [])}
        index = positions[str(row["id"])]
        neighbors = route_rows[max(0, index - 2):index] + route_rows[index + 1:index + 3]
        parts.append(json.dumps({
            "id": row["id"],
            "speaker": row.get("speaker"),
            "sources": slots,
            "before": before_by_id[str(row["id"])]["before"],
            "after": row.get("translation", ""),
            "reason": before_by_id[str(row["id"])].get("reason"),
            "flags": row.get("flags", []),
            "markup": markup_contract(slots.get("ja", "")),
            "neighbors_ru": [{"id": n["id"], "ru": n.get("translation", "")}
                             for n in neighbors],
        }, ensure_ascii=False))
    parts.extend([
        "```", "", "## Вердикт", "",
        "Запиши отчёт в `build/style-review-" + run_id + "-" + window_id + ".md`.",
        "Первая непустая строка после заголовка должна быть одной из двух:",
        "`VERDICT: ACCEPT` — смысл не снесён; `VERDICT: REVISE` — есть правки.",
        "При REVISE перечисли ID, severity, причину и окончательный русский вариант.",
        "Canonical files не правь.",
    ])
    return "\n".join(parts)


def style_revision_package(root: Path, config: dict[str, Any], run_id: str,
                           window_id: str, report_path: Path) -> str:
    report = report_path if report_path.is_absolute() else root / report_path
    if not report.exists():
        raise ValueError(f"Style review report not found: {report}")
    review_text, report_ids = style_revision_report(report)
    run, _, route_rows, _, editable = style_run_window(root, config, run_id, window_id)
    if window_id not in run["applied"]:
        raise ValueError(f"Style window is not applied: {run_id}/{window_id}")
    editable_ids = {str(row["id"]) for row in editable
                    if not CJK_RE.search(str(row.get("translation", "")))}
    outside = report_ids - editable_ids
    if outside:
        raise ValueError(
            "Style review references IDs outside editable scope: "
            + ", ".join(sorted(outside)))
    allowed_ids = report_ids & editable_ids
    current_rows = [row for row in route_rows if str(row["id"]) in allowed_ids]
    if not current_rows:
        raise ValueError("Style review does not name any editable segment ID")
    base_sha = style_slice_hash(current_rows)
    context = style_review_package(root, config, run_id, window_id)
    context = context.split("\n## Вердикт", 1)[0]
    patch_name = f"build/style-revision-{run_id}-{window_id}.jsonl"
    parts = [
        f"# Исправление стилевой дельты {run_id} / {window_id}", "",
        "Режим vn-stylist: source-aware исправление замечаний delta-review. "
        "Не проводи новое независимое ревью; исправь только перечисленные ниже ID.", "",
        context, "", "## Строки из замечаний", "", "```jsonl",
    ]
    records = load_source_records(
        root, config, {(str(row["source_set_id"]), str(row["source_id"]))
                       for row in current_rows})
    for row in current_rows:
        record = records[(str(row["source_set_id"]), str(row["source_id"]))]
        slots = {str(slot["language"]): str(slot.get("body_text", slot.get("text", "")))
                 for slot in record.get("slots", [])}
        parts.append(json.dumps({
            "id": row["id"],
            "speaker": row.get("speaker"),
            "sources": slots,
            "current": row.get("translation", ""),
            "flags": row.get("flags", []),
            "markup": markup_contract(slots.get("ja", "")),
        }, ensure_ascii=False))
    parts.extend([
        "```", "", "## Замечания рецензента", "", review_text.strip(), "",
        "## Сдать", "", f"Патч: `{patch_name}`.", "Первая строка:", "```json",
        json.dumps({"__style_revision__": {
            "run_id": run_id,
            "window_id": window_id,
            "base_sha256": base_sha,
            "report_sha256": sha256_file(report),
            "allowed_ids": sorted(allowed_ids),
        }}, ensure_ascii=False),
        "```",
        "Дальше только реально исправленные записи с полями `id`, `before`, "
        "`translation`, `reason` и при необходимости `flags`.",
        f"Применение: `python tools/vnctl.py style revise {run_id} {window_id} "
        f"{patch_name} --report {report_path} --actor vn-stylist`.",
    ])
    return "\n".join(parts)


def report_verdict(path: Path) -> str | None:
    verdicts = re.findall(
        r"(?m)^VERDICT:\s*(ACCEPT|REVISE)\s*$",
        path.read_text(encoding="utf-8-sig"),
    )
    return verdicts[0] if len(verdicts) == 1 else None


def report_accepts(path: Path) -> bool:
    return report_verdict(path) == "ACCEPT"


def style_accept(root: Path, config: dict[str, Any], run_id: str,
                 window_id: str, report_path: Path, reviewer: str) -> int:
    report = report_path if report_path.is_absolute() else root / report_path
    if not report.exists():
        raise ValueError(f"Review report not found: {report}")
    if not report_accepts(report):
        raise ValueError("Style delta review did not say VERDICT: ACCEPT")
    run, _, _, _, _ = style_run_window(root, config, run_id, window_id)
    applied = run["applied"].get(window_id)
    if not applied:
        raise ValueError(f"Style window is not applied: {run_id}/{window_id}")
    if window_id in run["accepted"]:
        raise ValueError(f"Style window already accepted: {run_id}/{window_id}")
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    effective = style_effective_changes(run, window_id)
    affected = sorted({str(change["scene_id"]) for change in effective})
    scene_rows = {
        scene_id: [clean_meta(row) for row in read_jsonl(seg_dir / f"{scene_id}.jsonl")]
        for scene_id in affected
    }
    canonical = {str(row["id"]): row for rows in scene_rows.values() for row in rows}
    final = []
    allowed_statuses = {"draft", "reviewed"} if window_id in run["reopened"] else {"draft"}
    for change in effective:
        row = canonical[str(change["id"])]
        if row.get("status") not in allowed_statuses:
            raise ValueError(f"Changed segment is not awaiting delta review: {row['id']}")
        row["status"] = "reviewed"
        final.append({"id": row["id"], "translation": row.get("translation", "")})
    if scene_rows:
        write_scene_transaction(root, config, scene_rows)
    append_style_event(root, config, {
        "schema_version": 1,
        "event": "window_accepted",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "window_id": window_id,
        "reviewer": reviewer,
        "report_sha256": sha256_file(report),
        "final_delta_sha256": sha256_text(json.dumps(final, ensure_ascii=False)),
    })
    print(f"{run_id}/{window_id}: delta accepted, {len(final)} rows reviewed")
    return 0


def style_sibling_anchors(root: Path, config: dict[str, Any], run: dict[str, Any],
                          segment_ids: set[str]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    review_events = load_review_events(root, config)
    review_states = review_runs(review_events)
    for event in review_events:
        if event.get("event") != "review_resolved":
            continue
        review_id = str(event.get("review_id", ""))
        state = review_states.get(review_id, {})
        if not state.get("accepted"):
            continue
        superseded = state.get("superseded_issues", {})
        effective = state.get("effective_resolutions", {})
        for resolution in event.get("resolutions", []) or []:
            issue_id = str(resolution.get("issue_id", ""))
            if (effective.get(issue_id, {}).get("disposition") != "applied"
                    or issue_id in superseded):
                continue
            for change in resolution.get("changes", []) or []:
                sid = str(change.get("id", ""))
                before = str(change.get("before", ""))
                after = str(change.get("translation", ""))
                if sid in segment_ids and before != after:
                    latest[sid] = {
                        "anchor": sid,
                        "provenance": issue_id,
                        "before": before,
                        "after": after,
                    }

    for window in run.get("windows", []):
        window_id = str(window.get("window_id", ""))
        if window_id not in run.get("accepted", {}):
            continue
        events = [run.get("applied", {}).get(window_id)]
        events.extend(run.get("revisions", {}).get(window_id, []))
        for event in events:
            if not event:
                continue
            for change in event.get("changes", []) or []:
                sid = str(change.get("id", ""))
                before = str(change.get("before", ""))
                after = str(change.get("after", ""))
                if sid in segment_ids and before != after:
                    latest[sid] = {
                        "anchor": sid,
                        "provenance": f"{run['run_id']}/{window_id}",
                        "before": before,
                        "after": after,
                    }
    return latest


def style_exact_source_sibling_blockers(
        root: Path, config: dict[str, Any], run: dict[str, Any],
        rows: list[dict[str, Any]], source_texts: dict[str, str]) -> list[dict[str, str]]:
    segment_ids = {str(row["id"]) for row in rows}
    anchors = style_sibling_anchors(root, config, run, segment_ids)
    if not anchors:
        return []

    def source_signature(row: dict[str, Any]) -> tuple[str, str, str]:
        source = source_texts[str(row["id"])]
        contract = json.dumps(
            markup_contract(source), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))
        return source, str(row.get("speaker") or ""), contract

    fingerprints: dict[str, tuple[tuple[str, str, str], ...]] = {}
    by_scene: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_scene[str(row["scene_id"])].append(row)
    for scene_rows in by_scene.values():
        for index in range(2, len(scene_rows) - 2):
            context = scene_rows[index - 2:index] + scene_rows[index + 1:index + 3]
            fingerprints[str(scene_rows[index]["id"])] = tuple(
                source_signature(item) for item in context)

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sid = str(row["id"])
        fingerprint = fingerprints.get(sid)
        if fingerprint is not None:
            groups[(*source_signature(row), fingerprint)].append(row)

    blockers: list[dict[str, str]] = []
    by_id = {str(row["id"]): row for row in rows}
    for anchor_id, anchor in anchors.items():
        anchor_row = by_id.get(anchor_id)
        fingerprint = fingerprints.get(anchor_id)
        if (not anchor_row or fingerprint is None
                or str(anchor_row.get("translation", "")) != anchor["after"]):
            continue
        key = (*source_signature(anchor_row), fingerprint)
        for sibling in groups.get(key, []):
            sibling_id = str(sibling["id"])
            if (sibling_id != anchor_id
                    and str(sibling.get("translation", "")) == anchor["before"]):
                blockers.append({
                    "anchor": anchor_id,
                    "sibling": sibling_id,
                    "provenance": anchor["provenance"],
                    "before": anchor["before"],
                    "after": anchor["after"],
                })
    return sorted(blockers, key=lambda item: (
        item["anchor"], item["sibling"], item["provenance"],
        item["before"], item["after"]))


def style_audit_package(root: Path, config: dict[str, Any], run_id: str) -> str:
    run = style_runs(load_style_events(root, config)).get(run_id)
    if not run:
        raise ValueError(f"Unknown style run: {run_id}")
    if len(run["accepted"]) != len(run["windows"]):
        raise ValueError(f"Not all style windows are accepted: {len(run['accepted'])}/{len(run['windows'])}")
    rows = style_route_rows(root, config, str(run["route"]))
    source_texts = source_text_by_segment(root, config, rows)
    blockers = style_exact_source_sibling_blockers(
        root, config, run, rows, source_texts)
    if blockers:
        diagnostics = "\n".join(
            json.dumps(item, ensure_ascii=False) for item in blockers)
        raise ValueError(
            f"Exact-source sibling preflight blocked style audit: {len(blockers)} blocker(s)\n"
            + diagnostics)
    labels = speaker_labels(root)
    changed = [change for window in run["windows"]
               for change in style_effective_changes(run, str(window["window_id"]))]
    glossary = glossary_for_scene(root, config, "\n".join(source_texts.values()))
    parts = [
        f"# Сквозной аудит {run_id}", "",
        f"Блок: {run['route']}; сегментов: {len(rows)}; стилевых правок: {len(changed)}.",
        "Проверь весь русский блок на дрейф голосов, разошедшиеся повторы, "
        "термины, обращения и неравномерность вычитки. Это аудит блока, не новое "
        "переписывание строк.", "",
        render_required_knowledge(
            root, config, rows, glossary, role="auditor", russian_only=True), "",
        "## Стилевые изменения", "", "```jsonl",
    ]
    for change in changed:
        parts.append(json.dumps({
            "id": change.get("id"),
            "scene": change.get("scene_id"),
            "before": russian_only_projection(str(change.get("before", ""))),
            "after": russian_only_projection(str(change.get("after", ""))),
            "reason": russian_only_projection(str(change.get("reason", ""))),
            "flags_before": change.get("flags_before", []),
            "flags_after": change.get("flags_after", []),
        }, ensure_ascii=False))
    parts.extend(["```", "", "## Текст", "", "```jsonl"])
    for row in rows:
        parts.append(json.dumps({
            "id": row["id"],
            "scene": row["scene_id"],
            "speaker": labels.get(str(row.get("speaker"))) if row.get("speaker") else None,
            "ru": russian_only_projection(str(row.get("translation", ""))),
            "flags": row.get("flags", []),
            "markup": markup_contract(str(row.get("translation", ""))),
        }, ensure_ascii=False))
    parts.extend([
        "```", "", "## Вердикт", "",
        f"Отчёт: `build/style-audit-{run_id}.md`.",
        "После заголовка: `VERDICT: ACCEPT` либо `VERDICT: REVISE`.",
        "REVISE означает, что конкретный дефект надо исправить и повторить аудит.",
    ])
    output = "\n".join(parts)
    if CJK_RE.search(output):
        raise RuntimeError("Russian-only audit package contains CJK")
    return output


def style_accept_audit(root: Path, config: dict[str, Any], run_id: str,
                       report_path: Path, auditor: str) -> int:
    report = report_path if report_path.is_absolute() else root / report_path
    if not report.exists() or not report_accepts(report):
        raise ValueError("Route audit report is absent or did not say VERDICT: ACCEPT")
    run = style_runs(load_style_events(root, config)).get(run_id)
    if not run:
        raise ValueError(f"Unknown style run: {run_id}")
    if len(run["accepted"]) != len(run["windows"]):
        raise ValueError("Route audit cannot pass before every window is accepted")
    rows = style_route_rows(root, config, str(run["route"]))
    append_style_event(root, config, {
        "schema_version": 1,
        "event": "route_audited",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "route": run["route"],
        "route_sha256": style_text_hash(rows),
        "auditor": auditor,
        "report_sha256": sha256_file(report),
    })
    print(f"{run_id}: route audit accepted; build is allowed for current text hash")
    return 0


def style_status(root: Path, config: dict[str, Any]) -> int:
    runs = style_runs(load_style_events(root, config))
    if not runs:
        print("Style runs: 0")
        return 0
    for run in runs.values():
        audit = "audited" if run.get("audit") else "pending audit"
        print(f"{run['run_id']}: {run['route']}, "
              f"applied={len(run['applied'])}/{len(run['windows'])}, "
              f"accepted={len(run['accepted'])}/{len(run['windows'])}, {audit}")
    return 0


def validate_style_ledger(root: Path, config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    events = load_style_events(root, config)
    known_routes = set(route_scenes(root, config))
    runs: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(events, start=1):
        kind = event.get("event")
        if event.get("schema_version") != 1:
            errors.append(f"style ledger line {index}: unsupported schema_version")
        if kind not in STYLE_EVENTS:
            errors.append(f"style ledger line {index}: unknown event {kind!r}")
            continue
        if kind == "run_started":
            run_id = str(event.get("run_id", ""))
            if run_id in runs:
                errors.append(f"style ledger line {index}: duplicate run {run_id}")
            if event.get("route") not in known_routes:
                errors.append(f"style ledger line {index}: unknown route {event.get('route')}")
            windows = event.get("windows")
            if not isinstance(windows, list) or not windows:
                errors.append(f"style ledger line {index}: run without windows")
            runs[run_id] = {"windows": {str(w.get('window_id')) for w in windows or []},
                            "applied": set(), "accepted": set(), "audited": False}
        elif kind != "ledger_initialized":
            run_id = str(event.get("run_id", ""))
            run = runs.get(run_id)
            if not run:
                errors.append(f"style ledger line {index}: event references unknown run {run_id}")
                continue
            window_id = str(event.get("window_id", ""))
            if kind == "window_applied":
                if window_id not in run["windows"]:
                    errors.append(f"style ledger line {index}: unknown window {window_id}")
                if window_id in run["applied"]:
                    errors.append(f"style ledger line {index}: window applied twice {window_id}")
                run["applied"].add(window_id)
            elif kind == "window_revised":
                if window_id not in run["applied"]:
                    errors.append(f"style ledger line {index}: window revised before apply {window_id}")
                run["accepted"].discard(window_id)
                run["audited"] = False
            elif kind == "window_accepted":
                if window_id not in run["applied"]:
                    errors.append(f"style ledger line {index}: window accepted before apply {window_id}")
                if window_id in run["accepted"]:
                    errors.append(f"style ledger line {index}: window accepted twice {window_id}")
                run["accepted"].add(window_id)
            elif kind == "route_audited":
                if run["accepted"] != run["windows"]:
                    errors.append(f"style ledger line {index}: route audited before all windows")
                if run["audited"]:
                    errors.append(f"style ledger line {index}: route audited twice")
                run["audited"] = True
            elif kind == "build_readback" and not run["audited"]:
                errors.append(f"style ledger line {index}: build before route audit")
    return errors, warnings


REVIEW_EVENTS = {
    "ledger_initialized", "review_imported", "review_resolved", "review_rechecked",
    "review_accepted", "review_issue_superseded", "review_invalidated",
    "review_finalization_blocked",
}
REVIEW_SEVERITIES = {"critical", "major", "minor", "preference"}
REVIEW_DISPOSITIONS = {"applied", "rejected"}
REVIEW_VERDICTS = {"accept", "revise"}


def review_ledger_path(root: Path, config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get("review_ledger", "translation/review-ledger.jsonl")
    return root / rel


def load_review_events(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    return [clean_meta(row) for row in read_jsonl(review_ledger_path(root, config))]


def append_review_event(root: Path, config: dict[str, Any], event: dict[str, Any]) -> None:
    path = review_ledger_path(root, config)
    with exclusive_file_lock(path):
        rows = load_review_events(root, config)
        rows.append(event)
        write_jsonl_atomic(path, rows)


def review_runs(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for event in events:
        review_id = str(event.get("review_id", ""))
        kind = event.get("event")
        if kind == "review_imported":
            runs[review_id] = {
                **event, "resolution": None, "resolution_events": [],
                "effective_resolutions": {}, "recheck": None, "rechecks": [],
                "accepted": None, "invalidated": None,
                "finalization_blocked": None,
                "superseded_issues": {},
            }
        elif review_id in runs and runs[review_id].get("invalidated"):
            continue
        elif review_id in runs and kind == "review_resolved":
            run = runs[review_id]
            run["resolution"] = event
            run["resolution_events"].append(event)
            for item in event.get("resolutions", []) or []:
                run["effective_resolutions"][str(item.get("issue_id", ""))] = item
            run["recheck"] = None
            run["finalization_blocked"] = None
        elif review_id in runs and kind == "review_rechecked":
            runs[review_id]["recheck"] = event
            runs[review_id]["rechecks"].append(event)
        elif review_id in runs and kind == "review_accepted":
            runs[review_id]["accepted"] = event
        elif review_id in runs and kind == "review_issue_superseded":
            issue_id = str(event.get("issue_id", ""))
            runs[review_id]["superseded_issues"][issue_id] = event
        elif review_id in runs and kind == "review_invalidated":
            runs[review_id]["invalidated"] = event
        elif review_id in runs and kind == "review_finalization_blocked":
            runs[review_id]["finalization_blocked"] = event
    return runs


def effective_review_resolutions(run: dict[str, Any]) -> list[dict[str, Any]]:
    effective = run.get("effective_resolutions", {})
    return [effective[issue_id] for issue_id in (
        str(issue.get("issue_id", "")) for issue in run.get("issues", [])
    ) if issue_id in effective]


def review_open_issue_ids(run: dict[str, Any]) -> set[str]:
    if run.get("accepted") or run.get("invalidated"):
        return set()
    if run.get("finalization_blocked"):
        return set(map(str, run["finalization_blocked"].get("issue_ids", []) or []))
    all_ids = {str(issue.get("issue_id", "")) for issue in run.get("issues", [])}
    if not run.get("resolution"):
        return all_ids
    recheck = run.get("recheck")
    if recheck and recheck.get("verdict") == "revise":
        return set(map(str, recheck.get("open_issue_ids", []) or []))
    return {
        str(item.get("issue_id", ""))
        for item in effective_review_resolutions(run)
        if item.get("escalation")
    }


def scene_review_hash(rows: list[dict[str, Any]]) -> str:
    payload = [{
        "id": str(row.get("id")),
        "translation": str(row.get("translation", "")),
        "flags": list(row.get("flags", []) or []),
    } for row in rows]
    return sha256_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def indexed_scene_review_hash(root: Path, config: dict[str, Any], scene_id: str) -> str:
    db = db_path(root, config)
    if not db.exists():
        raise FileNotFoundError(f"Index not found: {db}. Run: python tools/vnctl.py index")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    indexed = con.execute(
        "SELECT id, translation, flags_json FROM segments WHERE scene_id=? ORDER BY ord",
        (scene_id,),
    ).fetchall()
    con.close()
    return scene_review_hash([{
        "id": row["id"], "translation": row["translation"],
        "flags": json.loads(row["flags_json"] or "[]"),
    } for row in indexed])


def ensure_fresh_scene_index(root: Path, config: dict[str, Any], scene_id: str,
                             expected_hash: str) -> None:
    try:
        current_hash = indexed_scene_review_hash(root, config, scene_id)
    except FileNotFoundError:
        current_hash = ""
    if current_hash == expected_hash:
        return
    index_project(root, config)
    if indexed_scene_review_hash(root, config, scene_id) != expected_hash:
        raise ValueError("knowledge index is stale; run python tools/vnctl.py index")


def next_review_id(root: Path, config: dict[str, Any], scene_id: str) -> str:
    serial = 1 + sum(
        1 for run in review_runs(load_review_events(root, config)).values()
        if run.get("scene_id") == scene_id
    )
    return f"REV-{scene_id}-{serial:02d}"


def latest_review_for_scene(root: Path, config: dict[str, Any],
                            scene_id: str) -> dict[str, Any] | None:
    items = [run for run in review_runs(load_review_events(root, config)).values()
             if run.get("scene_id") == scene_id and not run.get("invalidated")]
    return items[-1] if items else None


def review_package(root: Path, config: dict[str, Any], scene_id: str) -> str:
    seg_file = root / config.get("paths", {}).get(
        "segments", "translation/segments") / f"{scene_id}.jsonl"
    rows = [clean_meta(row) for row in read_jsonl(seg_file)]
    if not rows:
        raise ValueError(f"Unknown or empty scene: {scene_id}")
    if {str(row.get("status")) for row in rows} != {"draft"}:
        raise ValueError(f"Scene {scene_id} is not a complete draft")
    review_id = next_review_id(root, config, scene_id)
    base_hash = scene_review_hash(rows)
    ensure_fresh_scene_index(root, config, scene_id, base_hash)
    context = build_context(root, config, scene_id, purpose="review")
    parts = [
        f"# Двуязычное ревью {review_id}", "",
        context, "",
        "## Машинный отчёт", "",
        "Пользователь этот текст не читает. Ты находишь проблемы, а оркестратор "
        "применяет или явно отклоняет каждую из них. Источник истины — JSONL, "
        "не свободный Markdown.", "",
        f"Замечания и suggested_changes разрешены только для segment_id сцены {scene_id}. "
        "Строки других сцен могут присутствовать ниже только как контекст; не выпускай "
        "по ним issues в этом review-файле.", "",
        f"Запиши `build/review-{review_id}.jsonl`. Первая строка:", "",
        "```json",
        json.dumps({"__review__": {
            "review_id": review_id,
            "scene_id": scene_id,
            "base_sha256": base_hash,
        }}, ensure_ascii=False),
        "```", "",
        "Дальше одна строка на каждое замечание, включая preference:", "",
        "```json",
        json.dumps({
            "issue_id": f"{review_id}-I001",
            "severity": "major",
            "category": "accuracy",
            "segment_ids": ["SEG_..."],
            "problem": "Что именно сломано.",
            "suggested_changes": [{"id": "SEG_...", "translation": "Окончательный вариант."}],
        }, ensure_ascii=False),
        "```", "",
        "Если замечаний нет, файл содержит только заголовок. Итоговые счётчики "
        "выводятся из JSONL, вручную их не объявляй.",
    ]
    return "\n".join(parts)


def review_import(root: Path, config: dict[str, Any], scene_id: str,
                  report_path: Path, reviewer: str) -> int:
    report = report_path if report_path.is_absolute() else root / report_path
    raw_rows = read_jsonl(report)
    headers = [row.get("__review__") for row in raw_rows if row.get("__review__")]
    if len(headers) != 1 or not isinstance(headers[0], dict):
        raise ValueError("review report must contain exactly one __review__ header")
    header = headers[0]
    review_id = str(header.get("review_id", ""))
    if not re.fullmatch(rf"REV-{re.escape(scene_id)}-[0-9]{{2}}", review_id):
        raise ValueError("review_id does not match scene")
    if review_id in review_runs(load_review_events(root, config)):
        raise ValueError(f"Review already imported: {review_id}")
    seg_file = root / config.get("paths", {}).get(
        "segments", "translation/segments") / f"{scene_id}.jsonl"
    scene_rows = [clean_meta(row) for row in read_jsonl(seg_file)]
    current_hash = scene_review_hash(scene_rows)
    if header.get("scene_id") != scene_id or header.get("base_sha256") != current_hash:
        raise ValueError("review report is for another or stale scene version")
    by_id = {str(row["id"]): row for row in scene_rows}
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if raw.get("__review__"):
            continue
        issue = clean_meta(raw)
        issue_id = str(issue.get("issue_id", ""))
        if not re.fullmatch(rf"{re.escape(review_id)}-I[0-9]{{3}}", issue_id):
            raise ValueError(f"invalid issue_id: {issue_id!r}")
        if issue_id in seen:
            raise ValueError(f"duplicate issue_id: {issue_id}")
        seen.add(issue_id)
        if issue.get("severity") not in REVIEW_SEVERITIES:
            raise ValueError(f"{issue_id}: invalid severity")
        if not str(issue.get("category", "")).strip() or not str(issue.get("problem", "")).strip():
            raise ValueError(f"{issue_id}: category and problem are required")
        segment_ids = list(map(str, issue.get("segment_ids", [])))
        if not segment_ids or any(sid not in by_id for sid in segment_ids):
            raise ValueError(f"{issue_id}: segment_ids must belong to {scene_id}")
        changes = issue.get("suggested_changes", []) or []
        if not isinstance(changes, list):
            raise ValueError(f"{issue_id}: suggested_changes must be a list")
        for change in changes:
            if str(change.get("id", "")) not in segment_ids:
                raise ValueError(f"{issue_id}: suggested change outside issue segment_ids")
            if not str(change.get("translation", "")).strip():
                raise ValueError(f"{issue_id}: suggested translation is empty")
        issues.append(issue)
    agent_file = root / ".opencode" / "agent" / f"{reviewer}.md"
    append_review_event(root, config, {
        "schema_version": 1,
        "event": "review_imported",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_id": review_id,
        "scene_id": scene_id,
        "base_sha256": current_hash,
        "reviewer": reviewer,
        "reviewer_prompt_sha256": sha256_file(agent_file) if agent_file.exists() else None,
        "report_sha256": sha256_file(report),
        "issues": issues,
    })
    counts = Counter(str(issue["severity"]) for issue in issues)
    print(f"{review_id}: imported {len(issues)} issues {dict(counts)}")
    return 0


def review_resolution_package(root: Path, config: dict[str, Any], review_id: str) -> str:
    run = review_runs(load_review_events(root, config)).get(review_id)
    if not run:
        raise ValueError(f"Unknown review: {review_id}")
    if run.get("invalidated"):
        raise ValueError(f"Review is invalidated: {review_id}")
    if run.get("accepted"):
        raise ValueError(f"Review already accepted: {review_id}")
    open_issue_ids = review_open_issue_ids(run)
    if not open_issue_ids:
        raise ValueError(f"Review has no issues awaiting resolution: {review_id}")
    scene_id = str(run["scene_id"])
    seg_file = root / config.get("paths", {}).get(
        "segments", "translation/segments") / f"{scene_id}.jsonl"
    rows = [clean_meta(row) for row in read_jsonl(seg_file)]
    expected_hash = (run.get("resolution") or {}).get("result_sha256", run["base_sha256"])
    current_hash = scene_review_hash(rows)
    if current_hash != expected_hash:
        raise ValueError("canonical scene changed after review; create a new review")
    ensure_fresh_scene_index(root, config, scene_id, current_hash)
    by_id = {str(row["id"]): row for row in rows}
    issues = [issue for issue in run.get("issues", [])
              if str(issue.get("issue_id", "")) in open_issue_ids]
    focus_ids = {
        str(segment_id) for issue in issues for segment_id in issue.get("segment_ids", [])
    }
    repeated_resolution = bool(run.get("resolution_events"))
    context = build_context(
        root, config, scene_id, purpose="review-fix",
        focus_segment_ids=focus_ids if repeated_resolution else None)
    templates = []
    for issue in issues:
        changes = []
        for suggestion in issue.get("suggested_changes", []) or []:
            sid = str(suggestion.get("id"))
            changes.append({
                "id": sid,
                "before": by_id[sid].get("translation", ""),
                "translation": suggestion.get("translation", ""),
                "flags": by_id[sid].get("flags", []),
            })
        templates.append({
            "issue_id": issue.get("issue_id"),
            "disposition": "rejected" if issue.get("severity") == "preference" else "applied",
            "reason": "Краткое обоснование решения.",
            "changes": changes,
        })
    parts = [
        f"# Применение замечаний ревью {review_id}", "", context, "",
        "## Замечания", "", "```json",
        json.dumps(issues, ensure_ascii=False, indent=2),
        "```", "",
        "Приоритет этого режима: точный и естественный русский. Не проводи новое "
        "ревью вместо рецензента, но и не вставляй его формулировку механически, "
        "если она по-русски хуже: исправь названный дефект минимальным вариантом.",
        "Формы из глоссария и утверждённых решений заблокированы. Японские бытовые "
        "реалии и родственные обращения не заменяй функциональным русским эквивалентом, "
        "если пакет закрепляет транслитерированную форму.", "",
        f"Запиши `build/resolutions-{review_id}.jsonl`: ровно одна строка на каждый "
        "issue_id из этого дельтового пакета, без пропусков. Уже закрытые замечания "
        "повторно не разрешай. Начальная заготовка:", "", "```jsonl",
    ]
    parts.extend(json.dumps(item, ensure_ascii=False) for item in templates)
    parts.extend([
        "```", "",
        "`critical`, `major` и подтверждённый `minor` обычно `applied`; preference "
        "обычно `rejected`. Любое отклонение требует конкретной причины. Глобальную "
        "развилку не угадывай: оставь рабочий вариант, сохрани/добавь нужный `needs_*` "
        "и добавь `escalation` с полями `question` и `provisional` — оркестратор "
        "соберёт такие вопросы для пользователя пачкой. Пока escalation не снят "
        "новым resolution, review close заблокирован.", "",
        f"Применение: `python tools/vnctl.py review resolve {review_id} "
        f"build/resolutions-{review_id}.jsonl --actor vn-stylist`",
    ])
    return "\n".join(parts)


def review_resolve(root: Path, config: dict[str, Any], review_id: str,
                   resolutions_path: Path, actor: str) -> int:
    run = review_runs(load_review_events(root, config)).get(review_id)
    if not run:
        raise ValueError(f"Unknown review: {review_id}")
    if run.get("invalidated"):
        raise ValueError(f"Review is invalidated: {review_id}")
    if run.get("accepted"):
        raise ValueError(f"Review already accepted: {review_id}")
    expected_issue_ids = review_open_issue_ids(run)
    if not expected_issue_ids:
        raise ValueError(f"Review has no issues awaiting resolution: {review_id}")
    scene_id = str(run["scene_id"])
    seg_file = root / config.get("paths", {}).get(
        "segments", "translation/segments") / f"{scene_id}.jsonl"
    rows = [clean_meta(row) for row in read_jsonl(seg_file)]
    expected_hash = (run.get("resolution") or {}).get("result_sha256", run["base_sha256"])
    if scene_review_hash(rows) != expected_hash:
        raise ValueError("canonical scene changed after review; create a new review")
    issues = {str(issue["issue_id"]): issue for issue in run.get("issues", [])}
    path = resolutions_path if resolutions_path.is_absolute() else root / resolutions_path
    resolutions = [clean_meta(row) for row in read_jsonl(path)]
    by_resolution = {str(row.get("issue_id", "")): row for row in resolutions}
    if len(by_resolution) != len(resolutions):
        raise ValueError("duplicate issue_id in resolutions")
    if set(by_resolution) != expected_issue_ids:
        missing = sorted(expected_issue_ids - set(by_resolution))
        extra = sorted(set(by_resolution) - expected_issue_ids)
        raise ValueError(
            f"every open issue needs a disposition: missing={missing}, extra={extra}")
    qa = read_yaml(root / "config/qa-rules.yaml", {}) or {}
    allowed_flags = set(qa.get("allowed_flags", []))
    by_id = {str(row["id"]): row for row in rows}
    changed: dict[str, dict[str, Any]] = {}
    normalized: list[dict[str, Any]] = []
    for issue_id, resolution in by_resolution.items():
        disposition = resolution.get("disposition")
        reason = str(resolution.get("reason", "")).strip()
        if disposition not in REVIEW_DISPOSITIONS or not reason:
            raise ValueError(f"{issue_id}: disposition and reason are required")
        issue_ids = set(map(str, issues[issue_id].get("segment_ids", [])))
        changes = resolution.get("changes", []) or []
        escalation = resolution.get("escalation")
        if escalation is not None:
            if (not isinstance(escalation, dict)
                    or not str(escalation.get("question", "")).strip()
                    or not str(escalation.get("provisional", "")).strip()):
                raise ValueError(
                    f"{issue_id}: escalation requires question and provisional")
        if disposition == "rejected" and changes:
            raise ValueError(f"{issue_id}: rejected issue may not carry changes")
        normalized_changes: list[dict[str, Any]] = []
        for change in changes:
            sid = str(change.get("id", ""))
            if sid not in issue_ids:
                raise ValueError(f"{issue_id}: change outside issue segment_ids")
            current = by_id[sid]
            before = str(change.get("before", ""))
            after = str(change.get("translation", ""))
            if before != str(current.get("translation", "")):
                raise ValueError(f"{issue_id}: stale before text for {sid}")
            if not after.strip():
                raise ValueError(f"{issue_id}: empty translation for {sid}")
            flags = list(change.get("flags", current.get("flags", [])) or [])
            if set(flags) - allowed_flags:
                raise ValueError(f"{issue_id}: unknown flags for {sid}")
            candidate = {"translation": after, "flags": flags}
            if sid in changed and changed[sid] != candidate:
                raise ValueError(f"conflicting resolutions for {sid}")
            source = source_text_by_segment(root, config, [current])[sid]
            findings = allowed_line_findings(
                root, sid, check_line(after, is_dialogue=bool(current.get("speaker"))))
            findings += check_markup(source, after)
            if findings:
                detail = "; ".join(f"{item.decision}: {item.message}" for item in findings)
                raise ValueError(f"{issue_id}: invalid change for {sid}: {detail}")
            changed[sid] = candidate
            normalized_changes.append({
                "id": sid,
                "before": before,
                "translation": after,
                "flags": flags,
            })
        normalized.append({
            "issue_id": issue_id,
            "disposition": disposition,
            "reason": reason,
            "changes": normalized_changes,
            **({"escalation": {
                "question": str(escalation["question"]).strip(),
                "provisional": str(escalation["provisional"]).strip(),
            }} if escalation is not None else {}),
        })
    for sid, change in changed.items():
        by_id[sid]["translation"] = change["translation"]
        by_id[sid]["flags"] = change["flags"]
        by_id[sid]["status"] = "draft"
    if changed:
        write_jsonl_atomic(seg_file, rows)
    result_hash = scene_review_hash(rows)
    append_review_event(root, config, {
        "schema_version": 1,
        "event": "review_resolved",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_id": review_id,
        "scene_id": scene_id,
        "actor": actor,
        "input_sha256": expected_hash,
        "resolutions_sha256": sha256_file(path),
        "result_sha256": result_hash,
        "resolutions": normalized,
    })
    counts = Counter(str(item["disposition"]) for item in normalized)
    print(f"{review_id}: resolved {len(normalized)} issues {dict(counts)}; "
          f"changed {len(changed)} segments")
    return 0


def review_recheck_package(root: Path, config: dict[str, Any], review_id: str) -> str:
    run = review_runs(load_review_events(root, config)).get(review_id)
    if run and run.get("invalidated"):
        raise ValueError(f"Review is invalidated: {review_id}")
    if not run or not run.get("resolution"):
        raise ValueError(f"Review has no complete resolution: {review_id}")
    if run.get("rechecks"):
        raise ValueError(
            f"Review already used its single recheck: {review_id}; "
            "apply final corrections, then use review finalize or review block")
    open_issue_ids = review_open_issue_ids(run)
    if open_issue_ids:
        raise ValueError(
            f"Review still has issues awaiting resolution: {', '.join(sorted(open_issue_ids))}")
    scene_id = str(run["scene_id"])
    seg_file = root / config.get("paths", {}).get(
        "segments", "translation/segments") / f"{scene_id}.jsonl"
    rows = [clean_meta(row) for row in read_jsonl(seg_file)]
    result_hash = str(run["resolution"]["result_sha256"])
    if scene_review_hash(rows) != result_hash:
        raise ValueError("canonical scene changed after resolution")
    ensure_fresh_scene_index(root, config, scene_id, result_hash)
    latest_recheck = (run.get("rechecks") or [])[-1] if run.get("rechecks") else None
    checked_issue_ids = (
        set(map(str, latest_recheck.get("open_issue_ids", []) or []))
        if latest_recheck and latest_recheck.get("verdict") == "revise"
        else {str(issue.get("issue_id", "")) for issue in run.get("issues", [])}
    )
    issues = [issue for issue in run.get("issues", [])
              if str(issue.get("issue_id", "")) in checked_issue_ids]
    resolutions = [item for item in effective_review_resolutions(run)
                   if str(item.get("issue_id", "")) in checked_issue_ids]
    focus_ids = {
        str(segment_id) for issue in issues for segment_id in issue.get("segment_ids", [])
    }
    repeated_recheck = bool(latest_recheck and latest_recheck.get("verdict") == "revise")
    context = build_context(
        root, config, scene_id, purpose="review-recheck",
        focus_segment_ids=focus_ids if repeated_recheck else None)
    parts = [
        f"# Перепроверка применённых замечаний {review_id}", "", context, "",
        "## Замечания и решения оркестратора", "", "```json",
        json.dumps({
            "issues": issues,
            "resolutions": resolutions,
        }, ensure_ascii=False, indent=2),
        "```", "",
        "Проверь, что каждое applied действительно исправлено, каждый rejected "
        "обоснован, а правки не внесли новую ошибку. Пользователь текст не читает.", "",
        f"Запиши `build/verdict-{review_id}.jsonl` одной строкой:", "", "```json",
        json.dumps({
            "review_id": review_id,
            "scene_sha256": result_hash,
            "verdict": "accept",
            "open_issue_ids": [],
        }, ensure_ascii=False),
        "```", "",
        "При `revise` перечисли в `open_issue_ids` все незакрытые issue_id и "
        "опиши исправления в отдельном Markdown-отчёте.",
    ]
    return "\n".join(parts)


def review_close(root: Path, config: dict[str, Any], review_id: str,
                 verdict_path: Path, reviewer: str) -> int:
    run = review_runs(load_review_events(root, config)).get(review_id)
    if run and run.get("invalidated"):
        raise ValueError(f"Review is invalidated: {review_id}")
    zero_issue_initial = bool(run is not None and not run.get("issues"))
    if not run or (not run.get("resolution") and not zero_issue_initial):
        raise ValueError(f"Review has no complete resolution: {review_id}")
    if run.get("accepted"):
        raise ValueError(f"Review already accepted: {review_id}")
    verdict_file = verdict_path if verdict_path.is_absolute() else root / verdict_path
    verdict_rows = [clean_meta(row) for row in read_jsonl(verdict_file)]
    if len(verdict_rows) != 1:
        raise ValueError("review verdict must contain exactly one JSON object")
    verdict = verdict_rows[0]
    scene_id = str(run["scene_id"])
    seg_file = root / config.get("paths", {}).get(
        "segments", "translation/segments") / f"{scene_id}.jsonl"
    rows = [clean_meta(row) for row in read_jsonl(seg_file)]
    current_hash = scene_review_hash(rows)
    verdict_name = str(verdict.get("verdict", ""))
    open_issue_ids = list(map(str, verdict.get("open_issue_ids", []) or []))
    known_issue_ids = {
        str(issue.get("issue_id", "")) for issue in run.get("issues", [])
    }
    if (verdict.get("review_id") != review_id
            or verdict.get("scene_sha256") != current_hash
            or verdict_name not in REVIEW_VERDICTS
            or len(open_issue_ids) != len(set(open_issue_ids))
            or set(open_issue_ids) - known_issue_ids
            or (verdict_name == "accept" and open_issue_ids)
            or (verdict_name == "revise" and not open_issue_ids)):
        raise ValueError("invalid review verdict for the current scene hash")
    expected_hash = (run["base_sha256"] if zero_issue_initial
                     else run["resolution"].get("result_sha256"))
    if current_hash != expected_hash:
        raise ValueError("scene changed after resolution")
    escalations = [item.get("issue_id") for item in effective_review_resolutions(run)
                   if item.get("escalation")]
    if escalations:
        raise ValueError(
            f"review has unresolved user escalations: {', '.join(map(str, escalations))}")
    if verdict_name == "revise":
        append_review_event(root, config, {
            "schema_version": 1,
            "event": "review_rechecked",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "review_id": review_id,
            "scene_id": scene_id,
            "scene_sha256": current_hash,
            "verdict": "revise",
            "open_issue_ids": open_issue_ids,
            "reviewer": reviewer,
            "verdict_sha256": sha256_file(verdict_file),
        })
        print(f"{review_id}: revise; {len(open_issue_ids)} issues reopened")
        return 0
    unresolved = review_open_issue_ids(run)
    if unresolved:
        raise ValueError(
            f"review has unresolved recheck issues: {', '.join(sorted(unresolved))}")
    statuses = {str(row.get("status")) for row in rows}
    if statuses not in ({"draft"}, {"reviewed"}):
        raise ValueError(f"scene is not awaiting review close: {dict(Counter(statuses))}")
    recovering = statuses == {"reviewed"}
    original_rows = [dict(row) for row in rows]
    if not recovering:
        for row in rows:
            row["status"] = "reviewed"
        write_jsonl_atomic(seg_file, rows)
    event = {
        "schema_version": 1,
        "event": "review_accepted",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_id": review_id,
        "scene_id": scene_id,
        "scene_sha256": current_hash,
        "reviewer": reviewer,
        "verdict_sha256": sha256_file(verdict_file),
    }
    try:
        append_review_event(root, config, event)
    except Exception:
        accepted = review_runs(load_review_events(root, config)).get(review_id, {}).get("accepted")
        if accepted:
            print(f"{review_id}: accepted; {len(rows)} segments are reviewed")
            return 0
        if not recovering:
            write_jsonl_atomic(seg_file, original_rows)
        raise
    print(f"{review_id}: accepted; {len(rows)} segments are reviewed")
    return 0


def review_finalize(root: Path, config: dict[str, Any], review_id: str,
                    actor: str) -> int:
    actor = actor.strip()
    if not actor:
        raise ValueError("actor is required")
    run = review_runs(load_review_events(root, config)).get(review_id)
    if not run:
        raise ValueError(f"Unknown review: {review_id}")
    if run.get("invalidated"):
        raise ValueError(f"Review is invalidated: {review_id}")
    if run.get("accepted"):
        raise ValueError(f"Review already accepted: {review_id}")
    rechecks = run.get("rechecks") or []
    if len(rechecks) != 1 or rechecks[0].get("verdict") != "revise":
        raise ValueError(f"Review finalize requires exactly one revise recheck: {review_id}")
    if run.get("recheck") is not None:
        raise ValueError(f"Review still needs final corrections: {review_id}")
    if run.get("finalization_blocked"):
        raise ValueError(f"Review finalization is blocked: {review_id}")
    unresolved = review_open_issue_ids(run)
    if unresolved:
        raise ValueError(
            f"Review has unresolved final issues: {', '.join(sorted(unresolved))}")
    scene_id = str(run["scene_id"])
    seg_file = root / config.get("paths", {}).get(
        "segments", "translation/segments") / f"{scene_id}.jsonl"
    rows = [clean_meta(row) for row in read_jsonl(seg_file)]
    current_hash = scene_review_hash(rows)
    if current_hash != run["resolution"].get("result_sha256"):
        raise ValueError("scene changed after final resolution")
    verdict_file = root / "build" / f"verdict-finalize-{review_id}.jsonl"
    verdict_file.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(verdict_file, [{
        "review_id": review_id,
        "scene_sha256": current_hash,
        "verdict": "accept",
        "open_issue_ids": [],
        "finalized_after_single_recheck": True,
    }])
    return review_close(root, config, review_id, verdict_file, actor)


def review_block(root: Path, config: dict[str, Any], review_id: str,
                 issue_ids: list[str], actor: str, reason: str) -> int:
    actor = actor.strip()
    reason = reason.strip()
    issue_ids = list(map(str, issue_ids))
    if not actor or not reason:
        raise ValueError("actor and reason are required")
    if not issue_ids or len(issue_ids) != len(set(issue_ids)):
        raise ValueError("review block requires unique issue IDs")
    run = review_runs(load_review_events(root, config)).get(review_id)
    if not run:
        raise ValueError(f"Unknown review: {review_id}")
    if run.get("invalidated") or run.get("accepted"):
        raise ValueError(f"Review cannot be blocked: {review_id}")
    rechecks = run.get("rechecks") or []
    if len(rechecks) != 1 or rechecks[0].get("verdict") != "revise":
        raise ValueError(f"Review block requires exactly one revise recheck: {review_id}")
    if run.get("recheck") is not None:
        raise ValueError(f"Review still needs final corrections: {review_id}")
    if run.get("finalization_blocked"):
        raise ValueError(f"Review finalization already blocked: {review_id}")
    allowed = set(map(str, rechecks[0].get("open_issue_ids", []) or []))
    if set(issue_ids) - allowed:
        raise ValueError("review block references issues outside the revise verdict")
    append_review_event(root, config, {
        "schema_version": 1,
        "event": "review_finalization_blocked",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_id": review_id,
        "scene_id": run["scene_id"],
        "issue_ids": issue_ids,
        "actor": actor,
        "reason": reason,
    })
    print(f"{review_id}: finalization blocked for {len(issue_ids)} issues")
    return 0


def review_issue_supersede(root: Path, config: dict[str, Any], issue_id: str,
                           question_id: str, actor: str, reason: str) -> int:
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("actor and reason are required")
    runs = review_runs(load_review_events(root, config))
    matches = [
        (review_id, run)
        for review_id, run in runs.items()
        if issue_id in {str(issue.get("issue_id", "")) for issue in run.get("issues", [])}
    ]
    if len(matches) != 1:
        raise ValueError(f"review issue must exist exactly once: {issue_id}")
    review_id, run = matches[0]
    if not run.get("accepted"):
        raise ValueError(f"review issue is not accepted: {issue_id}")
    if issue_id in run.get("superseded_issues", {}):
        raise ValueError(f"review issue already superseded: {issue_id}")
    questions_path = root / config.get("paths", {}).get(
        "questions", "translation/open-questions.jsonl")
    questions = {
        str(row.get("id", "")): clean_meta(row) for row in read_jsonl(questions_path)
    }
    question = questions.get(question_id)
    if not question:
        raise ValueError(f"unknown question: {question_id}")
    if question.get("status") != "open":
        raise ValueError(f"superseding question is not open: {question_id}")
    append_review_event(root, config, {
        "schema_version": 1,
        "event": "review_issue_superseded",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_id": review_id,
        "issue_id": issue_id,
        "question_id": question_id,
        "actor": actor,
        "reason": reason,
    })
    print(f"{issue_id}: superseded by {question_id}")
    return 0


def review_invalidate(root: Path, config: dict[str, Any], review_id: str,
                      actor: str, reason: str) -> int:
    actor = actor.strip()
    reason = reason.strip()
    if not actor or not reason:
        raise ValueError("actor and reason are required")
    run = review_runs(load_review_events(root, config)).get(review_id)
    if not run:
        raise ValueError(f"Unknown review: {review_id}")
    if run.get("invalidated"):
        raise ValueError(f"Review already invalidated: {review_id}")
    if (run.get("accepted") or run.get("resolution_events") or run.get("rechecks")
            or run.get("superseded_issues")):
        raise ValueError(
            "only an untouched imported review may be invalidated; "
            "later events require an explicit migration")
    append_review_event(root, config, {
        "schema_version": 1,
        "event": "review_invalidated",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_id": review_id,
        "scene_id": str(run["scene_id"]),
        "actor": actor,
        "reason": reason,
    })
    print(f"{review_id}: invalidated by {actor}")
    return 0


def review_status(root: Path, config: dict[str, Any]) -> int:
    runs = review_runs(load_review_events(root, config))
    if not runs:
        print("Review runs: 0")
        return 0
    for run in runs.values():
        issues = run.get("issues", [])
        open_ids = review_open_issue_ids(run)
        state = "invalidated" if run.get("invalidated") else (
            "accepted" if run.get("accepted") else (
                f"open:{len(open_ids)}" if open_ids else
                "awaiting recheck" if run.get("resolution") else "open"))
        counts = Counter(str(issue.get("severity")) for issue in issues)
        escalations = sum(1 for item in effective_review_resolutions(run)
                          if item.get("escalation"))
        suffix = f", escalations={escalations}" if escalations else ""
        print(f"{run['review_id']}: {run['scene_id']}, {state}, {dict(counts)}{suffix}")
    return 0


def validate_review_ledger(root: Path, config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    known_scenes = {str(scene["scene_id"]) for scene in load_scenes(root, config)}
    questions_path = root / config.get("paths", {}).get(
        "questions", "translation/open-questions.jsonl")
    question_statuses = {
        str(row.get("id", "")): row.get("status") for row in read_jsonl(questions_path)
    }
    runs: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(load_review_events(root, config), start=1):
        kind = event.get("event")
        if event.get("schema_version") != 1:
            errors.append(f"review ledger line {index}: unsupported schema_version")
        if kind not in REVIEW_EVENTS:
            errors.append(f"review ledger line {index}: unknown event {kind!r}")
            continue
        if kind == "ledger_initialized":
            continue
        review_id = str(event.get("review_id", ""))
        if kind == "review_imported":
            if review_id in runs:
                errors.append(f"review ledger line {index}: duplicate review {review_id}")
                continue
            scene_id = str(event.get("scene_id", ""))
            if scene_id not in known_scenes:
                errors.append(f"review ledger line {index}: unknown scene {scene_id}")
            issues = event.get("issues", []) or []
            issue_ids = [str(issue.get("issue_id", "")) for issue in issues]
            if len(issue_ids) != len(set(issue_ids)):
                errors.append(f"review ledger line {index}: duplicate issue IDs")
            if any(issue.get("severity") not in REVIEW_SEVERITIES for issue in issues):
                errors.append(f"review ledger line {index}: invalid issue severity")
            runs[review_id] = {
                "issues": set(issue_ids), "expected": set(issue_ids),
                "effective": {}, "resolved": not issue_ids, "accepted": False,
                "superseded": set(), "invalidated": False,
                "rechecks": 0, "blocked": False,
            }
            continue
        run = runs.get(review_id)
        if not run:
            errors.append(f"review ledger line {index}: event before import {review_id}")
            continue
        if kind == "review_invalidated":
            if run["invalidated"]:
                errors.append(f"review ledger line {index}: review invalidated twice")
            if (run["effective"] or run["resolved"] or run["accepted"]
                    or run["superseded"]):
                errors.append(
                    f"review ledger line {index}: only untouched import may be invalidated")
            if not str(event.get("actor", "")).strip() or not str(event.get("reason", "")).strip():
                errors.append(f"review ledger line {index}: invalidation actor and reason required")
            run["invalidated"] = True
        elif run["invalidated"]:
            errors.append(f"review ledger line {index}: event after invalidation {review_id}")
        elif kind == "review_resolved":
            resolution_ids = {str(item.get("issue_id", ""))
                              for item in event.get("resolutions", []) or []}
            if resolution_ids not in (run["expected"], run["issues"]):
                errors.append(f"review ledger line {index}: incomplete issue dispositions")
            for item in event.get("resolutions", []) or []:
                run["effective"][str(item.get("issue_id", ""))] = item
            escalations = {
                issue_id for issue_id, item in run["effective"].items()
                if item.get("escalation")
            }
            run["expected"] = escalations
            run["resolved"] = not escalations
            run["blocked"] = False
        elif kind == "review_rechecked":
            verdict = event.get("verdict")
            open_ids = list(map(str, event.get("open_issue_ids", []) or []))
            if not run["resolved"]:
                errors.append(f"review ledger line {index}: rechecked before resolution")
            if verdict != "revise" or not open_ids or len(open_ids) != len(set(open_ids)):
                errors.append(f"review ledger line {index}: invalid revise verdict")
            if set(open_ids) - run["issues"]:
                errors.append(f"review ledger line {index}: revise references unknown issues")
            if run["rechecks"]:
                errors.append(f"review ledger line {index}: review rechecked more than once")
            run["rechecks"] += 1
            run["expected"] = set(open_ids)
            run["resolved"] = False
        elif kind == "review_finalization_blocked":
            issue_ids = list(map(str, event.get("issue_ids", []) or []))
            if run["rechecks"] != 1 or not run["resolved"]:
                errors.append(
                    f"review ledger line {index}: finalization blocked outside final stage")
            if (not issue_ids or len(issue_ids) != len(set(issue_ids))
                    or set(issue_ids) - run["issues"]):
                errors.append(f"review ledger line {index}: invalid blocked issue IDs")
            if not str(event.get("actor", "")).strip() or not str(event.get("reason", "")).strip():
                errors.append(f"review ledger line {index}: block actor and reason required")
            if run["blocked"]:
                errors.append(f"review ledger line {index}: finalization blocked twice")
            run["blocked"] = True
            run["expected"] = set(issue_ids)
            run["resolved"] = False
        elif kind == "review_accepted":
            if not run["resolved"]:
                errors.append(f"review ledger line {index}: accepted before resolution")
            if run["accepted"]:
                errors.append(f"review ledger line {index}: accepted twice")
            run["accepted"] = True
        elif kind == "review_issue_superseded":
            issue_id = str(event.get("issue_id", ""))
            question_id = str(event.get("question_id", ""))
            if not run["accepted"]:
                errors.append(f"review ledger line {index}: issue superseded before accept")
            if issue_id not in run["issues"]:
                errors.append(f"review ledger line {index}: unknown issue {issue_id}")
            if question_statuses.get(question_id) != "open":
                errors.append(
                    f"review ledger line {index}: superseding question is not open {question_id}")
            if not str(event.get("actor", "")).strip() or not str(event.get("reason", "")).strip():
                errors.append(f"review ledger line {index}: supersession actor and reason required")
            if issue_id in run["superseded"]:
                errors.append(f"review ledger line {index}: issue superseded twice {issue_id}")
            run["superseded"].add(issue_id)
    return errors, warnings


def prior_review_issues(root: Path, config: dict[str, Any],
                        segment_ids: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for run in review_runs(load_review_events(root, config)).values():
        if not run.get("accepted"):
            continue
        resolutions = run.get("effective_resolutions", {})
        superseded = run.get("superseded_issues", {})
        for issue in run.get("issues", []):
            linked = set(map(str, issue.get("segment_ids", [])))
            if not linked & segment_ids:
                continue
            issue_id = str(issue.get("issue_id"))
            resolution = resolutions.get(issue_id, {})
            supersession = superseded.get(issue_id)
            item = {
                "issue_id": issue.get("issue_id"),
                "severity": issue.get("severity"),
                "category": issue.get("category"),
                "segment_ids": sorted(linked & segment_ids),
                "problem": issue.get("problem"),
                "disposition": resolution.get("disposition"),
                "reason": resolution.get("reason"),
                "state": "superseded" if supersession else "active",
            }
            if supersession:
                item.update({
                    "superseded_by_question": supersession.get("question_id"),
                    "supersession_reason": supersession.get("reason"),
                    "superseded_by_actor": supersession.get("actor"),
                })
            result.append(item)
    return result


def render_required_knowledge(root: Path, config: dict[str, Any],
                              rows: list[dict[str, Any]], glossary: list[dict[str, Any]],
                              *, role: str, russian_only: bool = False) -> str:
    scene_ids = {str(row.get("scene_id", "")) for row in rows}
    segment_ids = {str(row.get("id", "")) for row in rows}
    source_text = "\n".join(
        str((row.get("sources") or {}).get("ja", row.get("source", "")))
        for row in rows
    )
    questions_rows = related_questions(
        root, config, scene_ids, segment_ids, glossary, source_text)
    findings_rows = active_findings_for_package(
        root, config, role=role, russian_only=russian_only)
    reviews = prior_review_issues(root, config, segment_ids)
    labels = speaker_labels(root)
    parts = ["## ОБЯЗАТЕЛЬНЫЕ ЗНАНИЯ", ""]

    parts.extend(["### Утверждённые решения", ""])
    decisions = rules_checklist(root, config)
    decision_lines = [CJK_RE.sub("", item).strip() if russian_only else item
                      for item in decisions]
    parts.extend([f"- {item}" for item in decision_lines] or ["Нет."])

    parts.extend(["", "### Решения по этим строкам", ""])
    db = db_path(root, config)
    linked = linked_decisions(db, segment_ids) if db.exists() else []
    linked_lines = []
    for item in linked:
        text = str(item.get("decision", ""))
        if russian_only:
            text = CJK_RE.sub("", text).strip()
        linked_lines.append(f"- [{item.get('id')}] {text}")
    parts.extend(linked_lines or ["Нет."])

    parts.extend(["", "### Активные находки", ""])
    for item in findings_rows:
        parts.append(f"- [{item['id']}] [{item['status']}] {item['title']}: {item['statement']}")
    if not findings_rows:
        parts.append("Нет.")

    parts.extend(["", "### Глоссарий: формы и ловушки", ""])
    for item in glossary:
        note = glossary_note(item)
        if russian_only:
            note = CJK_RE.sub("", note).strip()
            parts.append(f"- {item.get('preferred_ru')} [{item.get('status')}]"
                         + (f": {note}" if note else ""))
        else:
            parts.append(f"- {item.get('source')} -> {item.get('preferred_ru')} "
                         f"[{item.get('status')}]" + (f": {note}" if note else ""))
    if not glossary:
        parts.append("Нет.")

    parts.extend(["", "### Голоса и обращения", ""])
    voice_items = []
    for speaker in sorted({str(row.get("speaker")) for row in rows if row.get("speaker")}):
        found = character_doc_path(root, config, speaker)
        if found:
            voice_items.append(
                f"#### {labels.get(speaker, speaker if not russian_only else 'SPK-UNKNOWN')}\n"
                f"{voice_contract(found[1], russian_only=russian_only)}"
            )
    parts.extend(voice_items or ["Нет карточек для участников."])

    parts.extend(["", "### Открытые вопросы и рабочие варианты", ""])
    for item in questions_rows:
        if russian_only:
            safe = {
                "id": item.get("id"), "kind": item.get("kind"),
                "segment_ids": item.get("segment_ids", []),
                "provisional": CJK_RE.sub("", str(item.get("provisional", ""))).strip(),
            }
        else:
            safe = {key: item.get(key) for key in (
                "id", "kind", "scene_id", "segment_ids", "question", "provisional")}
            if item.get("source_terms"):
                safe["source_terms"] = item.get("source_terms")
        parts.append("- " + json.dumps(safe, ensure_ascii=False))
    if not questions_rows:
        parts.append("Нет.")

    parts.extend(["", "### Действующие флаги", ""])
    flagged = [{"id": row.get("id"), "flags": list(row.get("flags", []) or [])}
               for row in rows if row.get("flags")]
    parts.extend(["- " + json.dumps(item, ensure_ascii=False) for item in flagged] or ["Нет."])

    parts.extend(["", "### Ранее принятые замечания ревьюеров", ""])
    for item in reviews:
        safe_item = dict(item)
        if russian_only:
            for field in ("problem", "reason", "supersession_reason"):
                safe_item[field] = CJK_RE.sub("", str(safe_item.get(field, ""))).strip()
        parts.append("- " + json.dumps(safe_item, ensure_ascii=False))
    if not reviews:
        parts.append("Нет.")

    parts.extend(["", "### Безопасные сюжетные ограничения", ""])
    constraints = safe_constraints(root, config, segment_ids)
    for item in constraints:
        rules = [str(rule) for rule in item.get("safe_rules", [])]
        if russian_only:
            rules = [CJK_RE.sub("", rule).strip() for rule in rules]
        parts.append(f"- {item.get('id')}: " + "; ".join(rule for rule in rules if rule))
    if not constraints:
        parts.append("Нет.")

    parts.extend([
        "", "### Неприкосновенные смысловые опоры", "",
        "Конкретные существа, виды, предметы, части тела, места, числа, элементы "
        "перечня, оба участника и направление сравнения, отрицание, модальность, "
        "причина и следствие не обобщаются и не удаляются.",
        "", "### Защищённая разметка", "",
    ])
    markup_rows = []
    for row in rows:
        source = str(row.get("translation", "")) if russian_only else str(
            (row.get("sources") or {}).get("ja", row.get("source", "")))
        contract = markup_contract(source)
        if contract["preserve_exact"] or contract["remove_ruby_keep_base"]:
            markup_rows.append({"id": row.get("id"), **contract})
    parts.extend(["- " + json.dumps(item, ensure_ascii=False) for item in markup_rows] or ["Нет."])

    routes = {str(scene.get("scene_id")): str(scene.get("route", ""))
              for scene in load_scenes(root, config)}
    parts.extend(["", "### Состояние блока и ревью", ""])
    for scene_id in sorted(scene_ids):
        latest = latest_review_for_scene(root, config, scene_id)
        review_state = "нет review-run"
        if latest:
            open_ids = review_open_issue_ids(latest)
            review_state = "accepted" if latest.get("accepted") else (
                f"open:{len(open_ids)}" if open_ids else
                "resolved" if latest.get("resolution") else "open")
        parts.append(f"- {scene_id}: route={routes.get(scene_id, '')}, review={review_state}")

    parts.extend(["", "### Релевантные прежние переводы", ""])
    if role == "translator":
        parts.append("Автоподстановки нет: одинаковый японский текст может требовать разных "
                     "форм. Кандидаты из индекса — только подсказка с проверкой контекста.")
    else:
        parts.append("Текущий русский текст и соседний контекст переданы ниже; предыдущие "
                     "решения ревью перечислены отдельным разделом выше.")
    output = "\n".join(parts)
    if "private_reason" in output:
        raise RuntimeError("Spoiler safety failure: private_reason leaked into knowledge block")
    if russian_only and CJK_RE.search(output):
        raise RuntimeError("Russian-only knowledge block contains CJK")
    return output


def work_next(root: Path, config: dict[str, Any], scene_id: str,
              size: int, start: int | None) -> str:
    """Компактный рабочий пакет на одну порцию строк.

    Полная спецификация сюда не входит намеренно: агент обязан прочитать её из
    своего определения, а повторять её в каждом вызове дорого и не помогает -
    модель хуже соблюдает инструкции именно на длинной дистанции.
    """
    db = db_path(root, config)
    if not db.exists():
        raise FileNotFoundError(f"Index not found: {db}. Run: python tools/vnctl.py index")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM segments WHERE scene_id=? ORDER BY ord", (scene_id,)).fetchall()
    if not rows:
        con.close()
        raise ValueError(f"Unknown or empty scene: {scene_id}")

    if start is None:
        pending = [i for i, r in enumerate(rows) if not str(r["translation"] or "").strip()]
        if not pending:
            con.close()
            return f"# {scene_id}\n\nВся сцена переведена: {len(rows)} сегментов.\n"
        first = pending[0]
    else:
        first = max(0, start - 1)
    # size = 0 означает сцену целиком: процесс требует прочитать её
    # до перевода первой строки, а порция это правило нарушает.
    batch = rows[first:] if size <= 0 else rows[first:first + size]
    lead = rows[max(0, first - 5):first]

    speakers = sorted({str(r["speaker"]) for r in batch if r["speaker"]})
    source_text = "\n".join(
        ["\n".join(json.loads(r["sources_json"]).values()) for r in batch] + speakers)
    glossary = glossary_for_scene(root, config, source_text)
    batch_items = []
    for row in batch:
        item = dict(row)
        item["sources"] = json.loads(row["sources_json"])
        item["flags"] = json.loads(row["flags_json"] or "[]")
        batch_items.append(item)
    con.close()

    parts: list[str] = []
    parts.append(f"# Порция: {scene_id}, строки {first + 1}-{first + len(batch)} "
                 f"из {len(rows)}")
    parts.append("\nСпецификация здесь не повторяется: читай её из своего определения.\n"
                 "Ниже только то, что меняется от порции к порции.")

    parts.append("\n" + render_required_knowledge(
        root, config, batch_items, glossary, role="translator"))

    # Даже при нескольких work-файлах в одном вызове пакет остаётся
    # самостоятельным. Поиск по канону нужен для решений из прошлых вызовов, а
    # решения уже закрытых файлов текущего вызова агент удерживает в контексте.
    parts.append("\n## Прежде чем вводить новое слово\n")
    parts.append("Термин, реалию, прозвище и название постройки проверяй по уже "
                 "переведённому канону:\n\n"
                 "```bash\npython tools/vnctl.py lines --contains СЛОВО --limit 20\n```\n\n"
                 "Нашёл русскую форму — бери её. Не нашёл и слово повторится "
                 "дальше — заводи вопрос в очередь, а не молча решай. Если форму "
                 "уже выбрал в предыдущем work-файле этого же вызова, сохраняй её.")

    if lead:
        parts.append("\n## Предыдущие строки, для связности\n```jsonl")
        for r in lead:
            parts.append(json.dumps({
                "speaker": r["speaker"],
                "ja": json.loads(r["sources_json"]).get("ja", ""),
                "ru": r["translation"] or "",
            }, ensure_ascii=False))
        parts.append("```")

    parts.append("\n## Переводить\n```jsonl")
    for r in batch_items:
        parts.append(json.dumps({
            "id": r["id"],
            "speaker": r["speaker"],
            "sources": r["sources"],
            "flags": r["flags"],
            "markup": markup_contract(str(r["sources"].get("ja", ""))),
        }, ensure_ascii=False))
    parts.append("```")

    parts.append(
        "\n## Как сдать\n\n"
        "1. Напиши патч `build/patch-" + scene_id + ".jsonl`, по строке на сегмент:\n"
        '   `{"id": "...", "translation": "...", "status": "draft", "flags": []}`\n'
        "2. Проверь себя: `python tools/vnctl.py work check " + scene_id
        + " build/patch-" + scene_id + ".jsonl --start " + str(first + 1)
        + " --count " + str(len(batch)) + "`\n"
        "3. Применяй: `python tools/vnctl.py apply-translation " + scene_id
        + " build/patch-" + scene_id + ".jsonl --start " + str(first + 1)
        + " --count " + str(len(batch)) + "`\n")
    return "\n".join(parts)


def write_package_files(root: Path, output_dir: Path,
                        packages: list[tuple[str, str]]) -> list[Path]:
    directory = output_dir if output_dir.is_absolute() else root / output_dir
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for filename, content in packages:
        path = directory / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def dispatch_limit(config: dict[str, Any], key: str, default: int) -> int:
    value = int(config.get("workflow", {}).get(key, default))
    if value < 1:
        raise ValueError(f"workflow.{key} must be at least 1")
    return value


def enforce_dispatch_budget(label: str, item_count: int, workload: int,
                            limit: int, unit: str, allow_oversize: bool) -> None:
    if item_count > 1 and workload > limit and not allow_oversize:
        raise ValueError(
            f"{label} dispatch has {workload} {unit}, configured limit is {limit}; "
            "split the call or pass --allow-oversize")


def work_dispatch_segments(root: Path, config: dict[str, Any],
                           scene_ids: list[str]) -> int:
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    total = 0
    for scene_id in scene_ids:
        rows = read_jsonl(seg_dir / f"{scene_id}.jsonl")
        first = next((index for index, row in enumerate(rows)
                      if not str(row.get("translation", "")).strip()), len(rows))
        total += len(rows) - first
    return total


def review_dispatch_workload(runs: dict[str, dict[str, Any]],
                             review_ids: list[str], command: str) -> int:
    total = 0
    for review_id in review_ids:
        run = runs.get(review_id)
        if not run:
            raise ValueError(f"unknown review ID: {review_id}")
        if command == "fix":
            total += len(review_open_issue_ids(run))
        elif command == "recheck":
            total += len(effective_review_resolutions(run))
        else:
            raise ValueError(f"unsupported review dispatch command: {command}")
    return total


def lines_query(root: Path, config: dict[str, Any], speaker: str | None,
                contains: str | None, scene: str | None, limit: int, stats: bool) -> int:
    """Выборка реплик из индекса.

    Нужна затем, чтобы агент знаний и аудитор не обходили 96 806 сегментов
    файлами. Без неё единственный доступный путь - регулярное выражение по
    пакетам контекста, где хвост предыдущей сцены повторяется в следующей,
    поэтому счётчики выходят завышенными.
    """
    db = db_path(root, config)
    if not db.exists():
        eprint(f"ERROR: index not found: {db}. Run: python tools/vnctl.py index")
        return 1
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    where: list[str] = []
    params: list[Any] = []
    if speaker:
        where.append("speaker = ?")
        params.append(speaker)
    if contains:
        where.append("(sources_json LIKE ? OR translation LIKE ?)")
        params.extend([f"%{contains}%"] * 2)
    if scene:
        where.append("scene_id = ?")
        params.append(scene)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    total = con.execute(f"SELECT COUNT(*) FROM segments{clause}", params).fetchone()[0]
    scenes = con.execute(
        f"SELECT COUNT(DISTINCT scene_id) FROM segments{clause}", params).fetchone()[0]
    print(f"Найдено: {total} записей в {scenes} сценах")

    if stats:
        done = con.execute(
            f"SELECT COUNT(*) FROM segments{clause}"
            + (" AND " if clause else " WHERE ") + "TRIM(translation) <> ''",
            params).fetchone()[0]
        print(f"Переведено: {done}")
        rows = con.execute(
            f"SELECT scene_id, COUNT(*) n FROM segments{clause} "
            "GROUP BY scene_id ORDER BY n DESC LIMIT 10", params).fetchall()
        print("Больше всего в сценах:")
        for row in rows:
            print(f"  {row['scene_id']}: {row['n']}")
        con.close()
        return 0

    rows = con.execute(
        f"SELECT id, scene_id, route, ord, speaker, sources_json, translation, "
        f"status, flags_json "
        f"FROM segments{clause} ORDER BY scene_id, ord LIMIT ?",
        params + [limit]).fetchall()
    for row in rows:
        sources = json.loads(row["sources_json"])
        print(json.dumps({
            "id": row["id"], "scene": row["scene_id"], "ord": row["ord"],
            "speaker": row["speaker"], "ja": sources.get("ja", ""),
            "en": sources.get("en", ""), "zh-Hans": sources.get("zh-Hans", ""),
            "ru": row["translation"] or "", "status": row["status"],
            "flags": json.loads(row["flags_json"] or "[]"), "route": row["route"],
        }, ensure_ascii=False))
    con.close()
    return 0


def translation_batch_ids(root: Path, config: dict[str, Any], scene_id: str,
                          start: int = 1, count: int | None = None) -> list[str]:
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    seg_file = seg_dir / f"{scene_id}.jsonl"
    if not seg_file.exists():
        raise ValueError(f"unknown scene: {scene_id}")
    if start < 1:
        raise ValueError("translation batch start must be at least 1")
    if count is not None and count < 1:
        raise ValueError("translation batch count must be at least 1")

    segments = read_jsonl(seg_file)
    first = start - 1
    if first >= len(segments):
        raise ValueError(
            f"translation batch starts after scene end: {start} > {len(segments)}")
    batch = segments[first:] if count is None else segments[first:first + count]
    if count is not None and len(batch) != count:
        raise ValueError(
            f"translation batch exceeds scene: requested {count}, found {len(batch)}")
    return [str(row["id"]) for row in batch]


def translation_patch_errors(patch: list[dict[str, Any]], expected_ids: list[str]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    actual: list[str] = []
    expected = set(expected_ids)
    for index, raw in enumerate(patch, start=1):
        entry = {k: v for k, v in raw.items() if not k.startswith("__")}
        sid = str(entry.get("id", ""))
        if not sid:
            errors.append(f"patch line {index}: missing id")
            continue
        if sid in seen:
            errors.append(f"patch line {index}: duplicate id {sid!r}")
            continue
        seen.add(sid)
        actual.append(sid)
        if not str(entry.get("translation", "")).strip():
            errors.append(f"patch line {index}: id {sid!r} has empty translation")

    missing = [sid for sid in expected_ids if sid not in seen]
    unexpected = [sid for sid in actual if sid not in expected]
    if missing:
        errors.append(
            f"patch is incomplete: missing {len(missing)} expected ids: "
            + ", ".join(missing[:20]))
    if unexpected:
        errors.append(
            f"patch contains {len(unexpected)} ids outside the expected batch: "
            + ", ".join(unexpected[:20]))
    return errors


def work_check(root: Path, config: dict[str, Any], scene_id: str,
               patch_path: Path, start: int = 1, count: int | None = None) -> int:
    """Прогнать правила по патчу, ничего не записывая.

    Существует затем, чтобы агент узнавал о нарушении от инструмента до сдачи,
    а не от оркестратора после.
    """
    patch_file = patch_path if patch_path.is_absolute() else root / patch_path
    if not patch_file.exists():
        eprint(f"ERROR: patch not found: {patch_file}")
        return 1

    patch = read_jsonl(patch_file)
    try:
        expected_ids = translation_batch_ids(root, config, scene_id, start, count)
    except ValueError as exc:
        eprint(f"ERROR: {exc}")
        return 1
    batch_errors = translation_patch_errors(patch, expected_ids)
    if batch_errors:
        for message in batch_errors[:20]:
            eprint(f"ERROR: {message}")
        eprint(f"ERROR: patch rejected, {len(batch_errors)} batch problems")
        return 1

    db = db_path(root, config)
    con = sqlite3.connect(db) if db.exists() else None
    if con:
        con.row_factory = sqlite3.Row

    qa = read_yaml(root / "config/qa-rules.yaml", {}) or {}
    protected = [re.compile(p) for p in qa.get("protected_patterns", [])]

    problems = 0
    checked = 0
    for raw in patch:
        entry = {k: v for k, v in raw.items() if not k.startswith("__")}
        sid = str(entry.get("id", ""))
        text = str(entry.get("translation", ""))
        checked += 1
        speaker = None
        english = japanese = ""
        if con:
            row = con.execute(
                "SELECT speaker, sources_json FROM segments WHERE id=?", (sid,)).fetchone()
            if row:
                speaker = row["speaker"]
                sources = json.loads(row["sources_json"])
                english = sources.get("en", "")
                japanese = sources.get("ja", "")
        findings = allowed_line_findings(
            root, sid, check_line(text, is_dialogue=bool(speaker)))
        findings += check_length(text, english)
        # Без этого самопроверка молчит о сломанной разметке, и агент сдаёт
        # патч, не узнав о ней. Пропуск найден независимо двумя рецензентами.
        findings += check_markup(japanese, text)
        for f in findings:
            problems += 1
            print(f"{sid}  {f.severity:8} {f.decision}  {f.message}")
        # Имя говорящего живёт в отдельном поле, а не в тексте. Без этой
        # проверки патч с придуманным @Имя@ проходил work check и всплывал
        # только в validate — уже после применения.
        for pattern in protected:
            src_tokens = pattern.findall(strip_ruby(japanese))
            dst_tokens = pattern.findall(strip_ruby(text))
            if src_tokens != dst_tokens:
                problems += 1
                print(f"{sid}  error    protected-token  {pattern.pattern}: "
                      f"источник={src_tokens!r} перевод={dst_tokens!r}")
    if con:
        con.close()

    print(f"\nПроверено строк: {checked}, замечаний: {problems}")
    return 0 if problems == 0 else 1


def render_global_reference(root: Path, config: dict[str, Any]) -> str:
    progress = read_yaml(root / "docs/progress.yaml", {}) or {}
    rules = rules_checklist(root, config)
    parts = [
        "## Текущий прогресс", "```yaml",
        yaml.safe_dump(progress, allow_unicode=True, sort_keys=False)
        if yaml else json.dumps(progress, ensure_ascii=False, indent=2),
        "```", "",
    ]
    spec = (root / "docs/translation-spec.md").read_text(encoding="utf-8-sig")
    parts.extend(["## Глобальная спецификация", spec, ""])
    parts.append("## Действующие утверждённые решения")
    parts.extend(["- " + rule for rule in rules] or ["Нет."])
    return "\n".join(parts)


def build_context(root: Path, config: dict[str, Any], scene_id: str,
                  purpose: str = "context",
                  focus_segment_ids: set[str] | None = None) -> str:
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

    if previous_scene_id and focus_segment_ids is None:
        previous = con.execute(
            "SELECT * FROM segments WHERE scene_id=? ORDER BY ord DESC LIMIT ?",
            (previous_scene_id, prev_n),
        ).fetchall()[::-1]
    else:
        previous = []
    if next_scene_id and focus_segment_ids is None:
        following = con.execute(
            "SELECT * FROM segments WHERE scene_id=? ORDER BY ord LIMIT ?",
            (next_scene_id, next_n),
        ).fetchall()
    else:
        following = []
    previous_summary = (
        con.execute("SELECT safe_summary FROM summaries WHERE scene_id=?", (previous_scene_id,)).fetchone()
        if previous_scene_id and focus_segment_ids is None else None
    )
    context_rows = list(rows)
    if focus_segment_ids is not None:
        radius = int(config.get("workflow", {}).get("review_issue_context_segments", 5))
        positions = {str(row["id"]): index for index, row in enumerate(rows)}
        unknown = focus_segment_ids - set(positions)
        if unknown:
            con.close()
            raise ValueError(
                f"review focus references unknown segments: {', '.join(sorted(unknown))}")
        selected: set[int] = set()
        for segment_id in focus_segment_ids:
            index = positions[segment_id]
            selected.update(range(
                max(0, index - radius), min(len(rows), index + radius + 1)))
        context_rows = [rows[index] for index in sorted(selected)]
    con.close()

    speakers = sorted({str(r["speaker"]) for r in context_rows if r["speaker"]})
    # Имя говорящего лежит отдельным полем, но выводится на экран и переводится.
    # Без него отбор глоссария пропускал ярлыки говорящих целиком (FND-0042).
    source_text = "\n".join(
        ["\n".join(json.loads(r["sources_json"]).values()) or str(r["source"])
         for r in context_rows] + speakers
    )
    seg_ids = {str(r["id"]) for r in context_rows}
    glossary = glossary_for_scene(root, config, source_text)
    constraints = safe_constraints(root, config, seg_ids)
    decisions = linked_decisions(db, seg_ids)
    workflow = config.get("workflow", {})
    example_limit = int(workflow.get(
        "internal_examples_limit",
        workflow.get("similar_examples_limit", 20),
    ))
    examples = approved_examples(db, speakers, scene_id, example_limit)
    current_items: list[dict[str, Any]] = []
    for row in context_rows:
        item = dict(row)
        item["sources"] = json.loads(row["sources_json"])
        item["flags"] = json.loads(row["flags_json"] or "[]")
        current_items.append(item)

    include_full_reference = focus_segment_ids is None

    parts: list[str] = []
    parts.append(f"# Контекст сцены {scene_id}\n")
    task_text = {
        "review": "Провести независимое двуязычное ревью текущего draft.",
        "review-fix": "Применить и формально разрешить текущую дельту замечаний ревью.",
        "review-recheck": "Перепроверить только текущую дельту применённых замечаний ревью.",
        "knowledge": "Извлечь минимальную дельту знаний из проверенной сцены.",
    }.get(purpose, "Перевести или проверить текущую сцену по правилам проекта.")
    parts.append(f"## Задача\n{task_text} Не выводить будущие сюжетные сведения.\n")
    parts.append(render_required_knowledge(
        root, config, current_items, glossary, role=purpose))
    parts.append("")
    parts.append("## Участники\n" + (", ".join(speakers) if speakers else "Повествование / неизвестно") + "\n")
    if include_full_reference:
        parts.append(render_global_reference(root, config) + "\n")
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
        parts.append("## Связанные с сегментами утверждённые решения\n")
        if decisions:
            parts.append("```json\n" + json.dumps(decisions, ensure_ascii=False, indent=2) + "\n```\n")
        else:
            parts.append("Нет.\n")
        parts.append("## Утверждённые внутренние примеры письменной речи\n")
        if examples:
            parts.append("```jsonl")
            for item in examples:
                parts.append(json.dumps(item, ensure_ascii=False))
            parts.append("```\n")
        else:
            parts.append("Пока нет.\n")

    parts.append("## Безопасное резюме предыдущей сцены\n")
    if previous_summary and previous_summary["safe_summary"]:
        parts.append(str(previous_summary["safe_summary"]) + "\n")
    else:
        parts.append("Нет утверждённого безопасного резюме; используйте только непосредственные соседние сегменты.\n")

    def render_segments(title: str, segment_rows: Iterable[sqlite3.Row]) -> None:
        parts.append(f"## {title}\n```jsonl")
        for r in segment_rows:
            item = {
                "id": r["id"], "source_id": r["source_id"], "speaker": r["speaker"],
                "sources": json.loads(r["sources_json"]), "source": r["source"],
                "translation": r["translation"], "status": r["status"],
                "flags": json.loads(r["flags_json"] or "[]"),
                "route": r["route"],
                "markup": markup_contract(json.loads(r["sources_json"]).get("ja", "")),
            }
            parts.append(json.dumps(item, ensure_ascii=False))
        parts.append("```\n")

    if focus_segment_ids is None:
        render_segments("Предыдущие сегменты", previous)
    render_segments(
        "Текущая сцена" if focus_segment_ids is None else "Контекст затронутых строк",
        context_rows)
    if focus_segment_ids is None:
        render_segments("Следующие сегменты", following)

    output = "\n".join(parts)
    if "private_reason" in output:
        raise RuntimeError("Spoiler safety failure: private_reason leaked into context")
    return output


QUESTION_KINDS = {"terminology", "voice", "ambiguity", "humour", "realia", "policy", "technical"}
QUESTION_STATUSES = {"open", "resolved", "superseded"}
QUESTION_REQUIRED = ("id", "date", "kind", "question", "status")


def questions(root: Path, config: dict[str, Any]) -> int:
    """Validate the open-questions queue.

    The queue exists so that a disputed point never stops the pipeline: the
    agent records the doubt, commits to a provisional answer, and moves on.
    """
    rel = config.get("paths", {}).get("questions", "translation/open-questions.jsonl")
    path = root / rel
    if not path.exists():
        print(f"Validated 0 questions: 0 errors, 0 warnings ({rel} not created yet)")
        return 0

    rows = read_jsonl(path)
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()

    # Тексты переводов нужны, чтобы проверять не наличие поля provisional, а то,
    # что предложенный вариант действительно стоит в сегменте.
    segment_translations: dict[str, str] = {}
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    if seg_dir.exists():
        for seg_file in sorted(seg_dir.glob("*.jsonl")):
            for seg in read_jsonl(seg_file):
                segment_translations[str(seg.get("id"))] = str(seg.get("translation", ""))

    for line_no, row in enumerate(rows, start=1):
        tag = row.get("id") or f"line {line_no}"
        for field in QUESTION_REQUIRED:
            if not row.get(field):
                errors.append(f"{tag}: missing field '{field}'")
        if row.get("id") in seen:
            errors.append(f"{tag}: duplicate id")
        seen.add(row.get("id", ""))
        if row.get("kind") not in QUESTION_KINDS:
            errors.append(f"{tag}: unknown kind '{row.get('kind')}'")
        if row.get("status") not in QUESTION_STATUSES:
            errors.append(f"{tag}: unknown status '{row.get('status')}'")
        # The whole point of the queue: an open question still has a working answer.
        if row.get("status") == "open" and not row.get("provisional"):
            errors.append(f"{tag}: open question without a provisional answer")
        source_terms = row.get("source_terms")
        if source_terms is not None:
            if (not isinstance(source_terms, list)
                    or not source_terms
                    or any(not isinstance(term, str) or not term.strip()
                           for term in source_terms)
                    or len(source_terms) != len(set(source_terms))):
                errors.append(
                    f"{tag}: source_terms must be a non-empty list of unique strings")
        # ...and the answer has to actually stand in the text. Checking only that
        # the field exists lets a question promise a solution that was never
        # written, which is exactly what the queue was meant to prevent.
        if row.get("status") == "open" and row.get("segment_ids"):
            empty = [sid for sid in row["segment_ids"]
                     if not str(segment_translations.get(sid, "")).strip()]
            if len(empty) == len(row["segment_ids"]):
                errors.append(
                    f"{tag}: provisional answer is not in the text - "
                    f"all {len(empty)} referenced segments are untranslated")
            elif empty:
                warnings.append(
                    f"{tag}: {len(empty)} of {len(row['segment_ids'])} "
                    f"referenced segments are untranslated")
        if row.get("status") == "resolved" and not row.get("resolution"):
            errors.append(f"{tag}: resolved question without a resolution")

    for message in warnings:
        eprint(f"WARN: {message}")
    for message in errors:
        eprint(f"ERROR: {message}")

    open_rows = [r for r in rows if r.get("status") == "open"]
    by_kind: dict[str, int] = {}
    for row in open_rows:
        by_kind[row.get("kind", "?")] = by_kind.get(row.get("kind", "?"), 0) + 1
    print(f"Validated {len(rows)} questions: {len(errors)} errors, {len(warnings)} warnings")
    print(f"Open: {len(open_rows)}" + (f" ({by_kind})" if by_kind else ""))
    for row in open_rows[:15]:
        scene = row.get("scene_id") or "-"
        print(f"  {row.get('id')}  [{row.get('kind')}]  {scene}  {str(row.get('question'))[:70]}")
    return 1 if errors else 0


APPLY_ALLOWED_FIELDS = {"translation", "status", "flags", "translator_note_safe", "confidence"}
APPLY_CONFIDENCE = {"high", "medium", "low"}


def apply_translation(root: Path, config: dict[str, Any], scene_id: str,
                      patch_path: Path, start: int = 1,
                      count: int | None = None) -> int:
    """Apply a translation patch to one scene's segments.

    Worker agents must not rewrite canonical segment files directly: the
    invariant that the record count never changes has to be enforced by code,
    not by asking an agent to be careful. The agent writes a small patch of
    id plus changed fields; this command validates it and does the write.
    """
    seg_dir = root / config.get("paths", {}).get("segments", "translation/segments")
    seg_file = seg_dir / f"{scene_id}.jsonl"
    if not seg_file.exists():
        eprint(f"ERROR: unknown scene: {seg_file}")
        return 1

    patch_file = patch_path if patch_path.is_absolute() else root / patch_path
    if not patch_file.exists():
        eprint(f"ERROR: patch not found: {patch_file}")
        return 1

    segments = read_jsonl(seg_file)
    patch = read_jsonl(patch_file)
    by_id = {str(row["id"]): row for row in segments}

    try:
        expected_ids = translation_batch_ids(root, config, scene_id, start, count)
    except ValueError as exc:
        eprint(f"ERROR: {exc}")
        return 1
    batch_errors = translation_patch_errors(patch, expected_ids)
    if batch_errors:
        for message in batch_errors[:20]:
            eprint(f"ERROR: {message}")
        eprint(f"ERROR: patch rejected, {len(batch_errors)} batch problems; file not written")
        return 1

    qa = read_yaml(root / "config/qa-rules.yaml", {}) or {}
    allowed_statuses = set(qa.get("allowed_statuses", sorted(ALLOWED_STATUSES)))
    allowed_flags = set(qa.get("allowed_flags", []))

    errors: list[str] = []
    touched = 0
    for index, raw in enumerate(patch, start=1):
        # read_jsonl добавляет служебные ключи для сообщений об ошибках.
        entry = {k: v for k, v in raw.items() if not k.startswith("__")}
        sid = str(entry.get("id", ""))
        if sid not in by_id:
            errors.append(f"patch line {index}: id {sid!r} is not in {scene_id}")
            continue
        unknown = set(entry) - APPLY_ALLOWED_FIELDS - {"id"}
        if unknown:
            errors.append(f"patch line {index}: fields not allowed here: {sorted(unknown)}")
            continue
        if "status" in entry and entry["status"] not in allowed_statuses:
            errors.append(f"patch line {index}: invalid status {entry['status']!r}")
            continue
        if "status" in entry and entry["status"] not in {"todo", "draft"}:
            errors.append(
                f"patch line {index}: apply-translation may not grant "
                f"{entry['status']!r}; use review close, build read-back or LQA")
            continue
        if "confidence" in entry and entry["confidence"] not in APPLY_CONFIDENCE:
            errors.append(f"patch line {index}: invalid confidence {entry['confidence']!r}")
            continue
        bad_flags = [f for f in entry.get("flags", []) if f not in allowed_flags]
        if bad_flags:
            errors.append(f"patch line {index}: unknown flags {bad_flags}")
            continue
        target = by_id[sid]
        for field in APPLY_ALLOWED_FIELDS:
            if field in entry:
                target[field] = entry[field]
        touched += 1

    if errors:
        for message in errors[:20]:
            eprint(f"ERROR: {message}")
        eprint(f"ERROR: patch rejected, {len(errors)} problems; file not written")
        return 1

    before = len(segments)
    write_jsonl_atomic(seg_file, segments)
    after = read_jsonl(seg_file)
    if len(after) != before:
        eprint(f"ERROR: record count changed {before} -> {len(after)}")
        return 1

    filled = sum(1 for row in after if str(row.get("translation", "")).strip())
    print(f"Scene {scene_id}: {touched} segments updated, {before} records preserved")
    print(f"Translated now: {filled}/{before}")
    return 0


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            clean = {k: v for k, v in row.items() if not k.startswith("__")}
            fh.write(json.dumps(clean, ensure_ascii=False) + "\n")
    tmp.replace(path)


@contextmanager
def exclusive_file_lock(path: Path, timeout: float = 30.0):
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"timed out waiting for ledger lock: {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)


from textrules import RUBY, check_length, check_line, check_markup, check_names, strip_ruby  # noqa: E402


FINDING_AREAS = {"scene-pack", "engine", "font", "encoding", "tooling", "content"}
FINDING_KINDS = {"fact", "decision", "limitation"}
FINDING_STATUSES = {"verified", "assumed", "refuted", "deprecated"}
FINDING_REQUIRED = ("id", "date", "area", "kind", "title", "statement", "status")


def findings(root: Path, config: dict[str, Any]) -> int:
    """Validate the technical findings journal (docs/project/findings.jsonl)."""
    rel = config.get("paths", {}).get("findings", "docs/project/findings.jsonl")
    path = root / rel
    if not path.exists():
        eprint(f"ERROR: {rel} not found")
        return 2

    # Архив проверяется наравне с действующим журналом: он не мусор, а материал,
    # на который ссылаются supersedes. Разведены они ради чтения, а не ради того,
    # чтобы про архив забыть.
    archive = path.with_name(path.stem + "-archive" + path.suffix)
    active = read_jsonl(path)
    archived = read_jsonl(archive) if archive.exists() else []
    rows = active + archived

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
    print(f"Active journal: {len(active)} | archive: {len(archived)}")
    misplaced = [r["id"] for r in active if findings_relevance(r) == "archive"]
    if misplaced:
        print(f"Should move to archive: {', '.join(misplaced)}")
    return 1 if errors else 0


def configure_stdio_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not reconfigure:
            continue
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except (AttributeError, TypeError, ValueError):
            pass


def main() -> int:
    configure_stdio_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("index")
    sub.add_parser("stats")
    sub.add_parser("findings")
    sub.add_parser("questions")
    sub.add_parser("status")
    sub.add_parser("resume")
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
    p_context.add_argument("--purpose", choices=("context", "knowledge"), default="context")
    p_context.add_argument("-o", "--output", type=Path)
    sub.add_parser("brief")
    p_lines = sub.add_parser("lines")
    p_lines.add_argument("--speaker")
    p_lines.add_argument("--contains")
    p_lines.add_argument("--scene")
    p_lines.add_argument("--limit", type=int, default=50)
    p_lines.add_argument("--stats", action="store_true")
    p_work = sub.add_parser("work")
    work_sub = p_work.add_subparsers(dest="work_command", required=True)
    p_wnext = work_sub.add_parser("next")
    p_wnext.add_argument("scene_ids", nargs="*")
    p_wnext.add_argument("--scenes", type=int)
    p_wnext.add_argument("--max-segments", type=int, default=0)
    p_wnext.add_argument("--size", type=int, default=0)
    p_wnext.add_argument("--start", type=int, default=None)
    p_wnext.add_argument("-o", "--output", type=Path)
    p_wnext.add_argument("--output-dir", type=Path)
    p_wnext.add_argument("--allow-oversize", action="store_true")
    work_sub.add_parser("queue")
    p_wcheck = work_sub.add_parser("check")
    p_wcheck.add_argument("scene_id")
    p_wcheck.add_argument("patch", type=Path)
    p_wcheck.add_argument("--start", type=int, default=1)
    p_wcheck.add_argument("--count", type=int)
    p_review = sub.add_parser("review")
    review_sub = p_review.add_subparsers(dest="review_command", required=True)
    review_sub.add_parser("status")
    p_rpackage = review_sub.add_parser("package")
    p_rpackage.add_argument("scene_ids", nargs="+")
    p_rpackage.add_argument("-o", "--output", type=Path)
    p_rpackage.add_argument("--output-dir", type=Path)
    p_rpackage.add_argument("--allow-oversize", action="store_true")
    p_rimport = review_sub.add_parser("import")
    p_rimport.add_argument("scene_id")
    p_rimport.add_argument("report", type=Path)
    p_rimport.add_argument("--reviewer", required=True)
    p_rfix = review_sub.add_parser("fix")
    p_rfix.add_argument("review_ids", nargs="+")
    p_rfix.add_argument("-o", "--output", type=Path)
    p_rfix.add_argument("--output-dir", type=Path)
    p_rfix.add_argument("--allow-oversize", action="store_true")
    p_rresolve = review_sub.add_parser("resolve")
    p_rresolve.add_argument("review_id")
    p_rresolve.add_argument("resolutions", type=Path)
    p_rresolve.add_argument("--actor", required=True)
    p_rrecheck = review_sub.add_parser("recheck")
    p_rrecheck.add_argument("review_ids", nargs="+")
    p_rrecheck.add_argument("-o", "--output", type=Path)
    p_rrecheck.add_argument("--output-dir", type=Path)
    p_rrecheck.add_argument("--allow-oversize", action="store_true")
    p_rclose = review_sub.add_parser("close")
    p_rclose.add_argument("review_id")
    p_rclose.add_argument("verdict", type=Path)
    p_rclose.add_argument("--reviewer", required=True)
    p_rfinalize = review_sub.add_parser("finalize")
    p_rfinalize.add_argument("review_id")
    p_rfinalize.add_argument("--actor", required=True)
    p_rblock = review_sub.add_parser("block")
    p_rblock.add_argument("review_id")
    p_rblock.add_argument("issue_ids", nargs="+")
    p_rblock.add_argument("--actor", required=True)
    p_rblock.add_argument("--reason", required=True)
    p_rsupersede = review_sub.add_parser("supersede")
    p_rsupersede.add_argument("issue_id")
    p_rsupersede.add_argument("--by-question", dest="question_id", required=True)
    p_rsupersede.add_argument("--actor", required=True)
    p_rsupersede.add_argument("--reason", required=True)
    p_rinvalidate = review_sub.add_parser("invalidate")
    p_rinvalidate.add_argument("review_id")
    p_rinvalidate.add_argument("--actor", required=True)
    p_rinvalidate.add_argument("--reason", required=True)
    p_style = sub.add_parser("style")
    style_sub = p_style.add_subparsers(dest="style_command", required=True)
    style_sub.add_parser("status")
    p_sstart = style_sub.add_parser("start")
    p_sstart.add_argument("route")
    p_snext = style_sub.add_parser("next")
    p_snext.add_argument("run_id")
    p_snext.add_argument("--window", dest="window_id")
    p_snext.add_argument("-o", "--output", type=Path)
    p_scheck = style_sub.add_parser("check")
    p_scheck.add_argument("run_id")
    p_scheck.add_argument("window_id")
    p_scheck.add_argument("patch", type=Path)
    p_sapply = style_sub.add_parser("apply")
    p_sapply.add_argument("run_id")
    p_sapply.add_argument("window_id")
    p_sapply.add_argument("patch", type=Path)
    p_srevise = style_sub.add_parser("revise")
    p_srevise.add_argument("run_id")
    p_srevise.add_argument("window_id")
    p_srevise.add_argument("patch", type=Path)
    p_srevise.add_argument("--report", type=Path, required=True)
    p_srevise.add_argument("--actor", required=True)
    p_sreview = style_sub.add_parser("review")
    p_sreview.add_argument("run_id")
    p_sreview.add_argument("window_id")
    p_sreview.add_argument("-o", "--output", type=Path)
    p_sfix = style_sub.add_parser("fix")
    p_sfix.add_argument("run_id")
    p_sfix.add_argument("window_id")
    p_sfix.add_argument("report", type=Path)
    p_sfix.add_argument("-o", "--output", type=Path)
    p_saccept = style_sub.add_parser("accept")
    p_saccept.add_argument("run_id")
    p_saccept.add_argument("window_id")
    p_saccept.add_argument("report", type=Path)
    p_saccept.add_argument("--reviewer", required=True)
    p_saudit = style_sub.add_parser("audit")
    p_saudit.add_argument("run_id")
    p_saudit.add_argument("-o", "--output", type=Path)
    p_saa = style_sub.add_parser("accept-audit")
    p_saa.add_argument("run_id")
    p_saa.add_argument("report", type=Path)
    p_saa.add_argument("--auditor", required=True)
    p_apply = sub.add_parser("apply-translation")
    p_apply.add_argument("scene_id")
    p_apply.add_argument("patch", type=Path)
    p_apply.add_argument("--start", type=int, default=1)
    p_apply.add_argument("--count", type=int)

    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "status":
            return project_status_report(root)
        if args.command == "resume":
            return project_resume_report(root)
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
        if args.command == "questions":
            return questions(root, config)
        if args.command == "brief":
            return brief(root, config)
        if args.command == "lines":
            return lines_query(root, config, args.speaker, args.contains,
                               args.scene, args.limit, args.stats)
        if args.command == "work":
            if args.work_command == "queue":
                return work_queue(root, config)
            if args.work_command == "next":
                if args.output and args.output_dir:
                    raise ValueError("use either -o or --output-dir, not both")
                if args.scene_ids and args.scenes is not None:
                    raise ValueError("--scenes is only valid for automatic selection")
                if args.scene_ids and args.max_segments:
                    raise ValueError("--max-segments is only valid for automatic selection")
                scene_ids = list(dict.fromkeys(args.scene_ids))
                if len(scene_ids) != len(args.scene_ids):
                    raise ValueError("duplicate scene IDs")
                if not scene_ids:
                    if args.scenes is None:
                        scene_id = next_unfinished_scene(root, config)
                        scene_ids = [scene_id] if scene_id else []
                    else:
                        max_segments = args.max_segments or dispatch_limit(
                            config, "translation_dispatch_max_segments", 900)
                        scene_ids = next_unfinished_scenes(
                            root, config, args.scenes, max_segments)
                if not scene_ids:
                    print("Непереведённых сцен не осталось.")
                    return 0
                if len(scene_ids) > 1 and (args.size > 0 or args.start is not None):
                    raise ValueError("--size and --start require one scene")
                enforce_dispatch_budget(
                    "translation", len(scene_ids), len(scene_ids),
                    dispatch_limit(config, "translation_dispatch_max_files", 4),
                    "files", args.allow_oversize)
                enforce_dispatch_budget(
                    "translation", len(scene_ids),
                    work_dispatch_segments(root, config, scene_ids),
                    dispatch_limit(config, "translation_dispatch_max_segments", 900),
                    "segments", args.allow_oversize)
                packages = [
                    (f"work-{scene_id}.md",
                     work_next(root, config, scene_id, args.size, args.start))
                    for scene_id in scene_ids
                ]
                if args.output_dir:
                    for path in write_package_files(root, args.output_dir, packages):
                        print(path)
                    return 0
                if len(packages) > 1:
                    raise ValueError("multiple work files require --output-dir")
                content = packages[0][1]
                if args.output:
                    out = args.output if args.output.is_absolute() else root / args.output
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(content, encoding="utf-8")
                    print(out)
                else:
                    print(content)
                return 0
            return work_check(
                root, config, args.scene_id, args.patch, args.start, args.count)
        if args.command == "review":
            if args.review_command == "status":
                return review_status(root, config)
            if args.review_command == "import":
                return review_import(root, config, args.scene_id, args.report, args.reviewer)
            if args.review_command == "resolve":
                return review_resolve(
                    root, config, args.review_id, args.resolutions, args.actor)
            if args.review_command == "close":
                return review_close(
                    root, config, args.review_id, args.verdict, args.reviewer)
            if args.review_command == "finalize":
                return review_finalize(root, config, args.review_id, args.actor)
            if args.review_command == "block":
                return review_block(
                    root, config, args.review_id, args.issue_ids,
                    args.actor, args.reason)
            if args.review_command == "supersede":
                return review_issue_supersede(
                    root, config, args.issue_id, args.question_id, args.actor, args.reason)
            if args.review_command == "invalidate":
                return review_invalidate(
                    root, config, args.review_id, args.actor, args.reason)
            if args.output and args.output_dir:
                raise ValueError("use either -o or --output-dir, not both")
            if args.review_command == "package":
                workload = sum(len(read_jsonl(
                    root / config.get("paths", {}).get(
                        "segments", "translation/segments") / f"{scene_id}.jsonl"))
                    for scene_id in args.scene_ids)
                enforce_dispatch_budget(
                    "initial review", len(args.scene_ids), len(args.scene_ids),
                    dispatch_limit(config, "review_initial_dispatch_max_files", 4),
                    "files", args.allow_oversize)
                enforce_dispatch_budget(
                    "initial review", len(args.scene_ids), workload,
                    dispatch_limit(config, "review_initial_dispatch_max_segments", 600),
                    "segments", args.allow_oversize)
                packages = [
                    (f"review-package-{scene_id}.md",
                     review_package(root, config, scene_id))
                    for scene_id in args.scene_ids
                ]
            elif args.review_command == "fix":
                workload = review_dispatch_workload(
                    review_runs(load_review_events(root, config)), args.review_ids, "fix")
                enforce_dispatch_budget(
                    "review fix", len(args.review_ids), len(args.review_ids),
                    dispatch_limit(config, "review_fix_dispatch_max_files", 10),
                    "files", args.allow_oversize)
                enforce_dispatch_budget(
                    "review fix", len(args.review_ids), workload,
                    dispatch_limit(config, "review_fix_dispatch_max_issues", 80),
                    "issues", args.allow_oversize)
                packages = [
                    (f"review-fix-{review_id}.md",
                     review_resolution_package(root, config, review_id))
                    for review_id in args.review_ids
                ]
            else:
                workload = review_dispatch_workload(
                    review_runs(load_review_events(root, config)),
                    args.review_ids, "recheck")
                enforce_dispatch_budget(
                    "review recheck", len(args.review_ids), len(args.review_ids),
                    dispatch_limit(config, "review_recheck_dispatch_max_files", 6),
                    "files", args.allow_oversize)
                enforce_dispatch_budget(
                    "review recheck", len(args.review_ids), workload,
                    dispatch_limit(config, "review_recheck_dispatch_max_issues", 63),
                    "resolutions", args.allow_oversize)
                packages = [
                    (f"review-recheck-{review_id}.md",
                     review_recheck_package(root, config, review_id))
                    for review_id in args.review_ids
                ]
            if args.output_dir:
                for path in write_package_files(root, args.output_dir, packages):
                    print(path)
                return 0
            if len(packages) > 1:
                raise ValueError("multiple review files require --output-dir")
            content = packages[0][1]
            if args.output:
                out = args.output if args.output.is_absolute() else root / args.output
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(content, encoding="utf-8")
                print(out)
            else:
                print(content)
            return 0
        if args.command == "style":
            if args.style_command == "status":
                return style_status(root, config)
            if args.style_command == "start":
                return style_start(root, config, args.route)
            if args.style_command == "next":
                content = style_package(root, config, args.run_id, args.window_id)
                if args.output:
                    out = args.output if args.output.is_absolute() else root / args.output
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(content, encoding="utf-8")
                    print(out)
                else:
                    print(content)
                return 0
            if args.style_command == "check":
                return style_check(root, config, args.run_id, args.window_id, args.patch)
            if args.style_command == "apply":
                return style_apply(root, config, args.run_id, args.window_id, args.patch)
            if args.style_command == "revise":
                return style_revise(
                    root, config, args.run_id, args.window_id, args.patch,
                    args.report, args.actor)
            if args.style_command == "review":
                content = style_review_package(root, config, args.run_id, args.window_id)
                if args.output:
                    out = args.output if args.output.is_absolute() else root / args.output
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(content, encoding="utf-8")
                    print(out)
                else:
                    print(content)
                return 0
            if args.style_command == "fix":
                content = style_revision_package(
                    root, config, args.run_id, args.window_id, args.report)
                if args.output:
                    out = args.output if args.output.is_absolute() else root / args.output
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(content, encoding="utf-8")
                    print(out)
                else:
                    print(content)
                return 0
            if args.style_command == "accept":
                return style_accept(root, config, args.run_id, args.window_id,
                                    args.report, args.reviewer)
            if args.style_command == "audit":
                content = style_audit_package(root, config, args.run_id)
                if args.output:
                    out = args.output if args.output.is_absolute() else root / args.output
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(content, encoding="utf-8")
                    print(out)
                else:
                    print(content)
                return 0
            return style_accept_audit(root, config, args.run_id, args.report, args.auditor)
        if args.command == "apply-translation":
            return apply_translation(
                root, config, args.scene_id, args.patch, args.start, args.count)
        if args.command == "context":
            content = build_context(root, config, args.scene_id, purpose=args.purpose)
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
