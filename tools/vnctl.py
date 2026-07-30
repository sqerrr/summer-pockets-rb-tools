#!/usr/bin/env python3
"""Minimal project CLI for a VN translation repository.

The canonical data stays in JSONL/YAML/Markdown. SQLite is rebuilt as an index.
"""
from __future__ import annotations

import argparse
import hashlib
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
    print(
        f"Validated {len(segments)} segments and {source_totals['candidate']} source records: "
        f"{len(errors)} errors, {len(warnings)} warnings"
    )
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
            source_set_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            file_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
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
            "INSERT INTO segments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["id"], r.get("source_set_id", ""), r.get("source_id", ""),
                r.get("source_hash", ""), r["file_id"], r["scene_id"], r["order"],
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

    source_text = "\n".join(
        "\n".join(json.loads(r["sources_json"]).values()) or str(r["source"])
        for r in rows
    )
    speakers = sorted({str(r["speaker"]) for r in rows if r["speaker"]})
    seg_ids = {str(r["id"]) for r in rows}
    glossary = glossary_for_scene(root, config, source_text)
    constraints = safe_constraints(root, config, seg_ids)
    decisions = linked_decisions(db, seg_ids)
    workflow = config.get("workflow", {})
    example_limit = int(workflow.get(
        "internal_examples_limit",
        workflow.get("similar_examples_limit", 20),
    ))
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

    parts.append("## Утверждённые внутренние примеры письменной речи\n")
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
                "id": r["id"], "source_id": r["source_id"], "speaker": r["speaker"],
                "sources": json.loads(r["sources_json"]), "source": r["source"],
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
    p_context.add_argument("-o", "--output", type=Path)

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
