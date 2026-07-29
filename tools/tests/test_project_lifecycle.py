import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def load_vnctl():
    path = Path(__file__).parents[1] / "vnctl.py"
    spec = importlib.util.spec_from_file_location("vnctl_lifecycle", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def make_status(vnctl, phase="bootstrap"):
    required_for = {
        "repository_audited": ["cataloguing", "reference_preparation", "pilot", "production"],
        "parser_extraction_verified": ["cataloguing", "pilot", "production"],
        "parser_roundtrip_verified": ["pilot", "production"],
        "cyrillic_verified": ["pilot", "production"],
        "technical_tags_verified": ["pilot", "production"],
        "choices_and_jumps_verified": ["pilot", "production"],
        "layout_limits_measured": ["production"],
        "scenario_catalogued": ["pilot", "production"],
        "stable_ids_created": ["pilot", "production"],
        "scenes_segmented": ["pilot", "production"],
        "reference_corpus_audited": ["production"],
        "knowledge_index_built": ["pilot", "production"],
        "spoiler_protection_verified": ["pilot", "production"],
        "pilot_completed": ["production"],
        "production_completed": ["final_lqa"],
    }
    status = {
        "schema_version": 1,
        "phase": phase,
        "overall_status": "blocked",
        "criticality": "critical",
        "bypass_allowed": False,
        "critical_gates": {
            name: {"status": "pending", "evidence": None, "required_for": targets}
            for name, targets in required_for.items()
        },
        "permissions": {},
        "current_task": {
            "id": "TEST-001",
            "description": "test",
            "assigned_skill": "vn-bootstrap",
        },
        "last_updated": None,
    }
    status["permissions"] = vnctl.permission_snapshot(status)
    return status


def write_status(tmp_path, status):
    path = tmp_path / "translation/project-status.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(status, sort_keys=False), encoding="utf-8")
    return path


def pass_gates(tmp_path, status, names):
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("verified", encoding="utf-8")
    for name in names:
        status["critical_gates"][name]["status"] = "passed"
        status["critical_gates"][name]["evidence"] = "evidence.txt"


def test_production_translation_blocked_in_bootstrap():
    vnctl = load_vnctl()
    status = make_status(vnctl)
    result = vnctl.evaluate_operation(status, "translate-production")
    assert result["allowed"] is False
    assert result["phase_allowed"] is False
    assert "pilot_completed" in result["blocking_gates"]


def test_verify_engine_available_in_bootstrap_after_extraction():
    """Roundtrip, Cyrillic, tag and layout evidence can only come from a build,
    so the verification build must not be locked behind the gates it feeds."""
    vnctl = load_vnctl()
    status = make_status(vnctl)

    blocked = vnctl.evaluate_operation(status, "verify-engine")
    assert blocked["allowed"] is False
    assert "parser_extraction_verified" in blocked["blocking_gates"]

    status["critical_gates"]["parser_extraction_verified"]["status"] = "passed"
    status["permissions"] = vnctl.permission_snapshot(status)
    allowed = vnctl.evaluate_operation(status, "verify-engine", check_permissions=False)
    assert allowed["allowed"] is True
    assert allowed["phase_allowed"] is True


def test_verify_engine_does_not_unlock_release_build():
    """Relaxing the verification path must leave translated output gated."""
    vnctl = load_vnctl()
    status = make_status(vnctl)
    for gate in status["critical_gates"].values():
        gate["status"] = "passed"
        gate["evidence"] = "evidence.txt"
    status["permissions"] = vnctl.permission_snapshot(status)
    result = vnctl.evaluate_operation(status, "build-game-text")
    assert result["allowed"] is False
    assert result["phase_allowed"] is False


def test_pilot_blocked_before_catalogue_and_index():
    vnctl = load_vnctl()
    status = make_status(vnctl, phase="pilot")
    result = vnctl.evaluate_operation(status, "translate-pilot")
    assert result["allowed"] is False
    assert "scenario_catalogued" in result["blocking_gates"]
    assert "stable_ids_created" in result["blocking_gates"]
    assert "knowledge_index_built" in result["blocking_gates"]


def test_passed_requires_existing_evidence(tmp_path):
    vnctl = load_vnctl()
    write_status(tmp_path, make_status(vnctl))
    with pytest.raises(ValueError, match="requires --evidence"):
        vnctl.set_gate(tmp_path, "technical_tags_verified", "passed")
    with pytest.raises(ValueError, match="requires --evidence"):
        vnctl.set_gate(tmp_path, "technical_tags_verified", "passed", "missing.txt")


def test_unknown_gate_rejected(tmp_path):
    vnctl = load_vnctl()
    write_status(tmp_path, make_status(vnctl))
    with pytest.raises(ValueError, match="Unknown gate"):
        vnctl.set_gate(tmp_path, "not_a_gate", "pending")


def test_unknown_gate_status_rejected(tmp_path):
    vnctl = load_vnctl()
    write_status(tmp_path, make_status(vnctl))
    with pytest.raises(ValueError, match="Unknown gate status"):
        vnctl.set_gate(tmp_path, "technical_tags_verified", "done")


def test_gate_change_appends_history(tmp_path):
    vnctl = load_vnctl()
    write_status(tmp_path, make_status(vnctl))
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("verified", encoding="utf-8")

    assert vnctl.set_gate(tmp_path, "technical_tags_verified", "passed", "evidence.txt") == 0

    history = tmp_path / "translation/project-history.jsonl"
    rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    gate_events = [row for row in rows if row["event"] == "gate_status_changed"]
    assert gate_events[-1]["gate"] == "technical_tags_verified"
    assert gate_events[-1]["new_status"] == "passed"
    assert gate_events[-1]["evidence"] == "evidence.txt"


def test_operation_allowed_after_required_gates_pass(tmp_path):
    vnctl = load_vnctl()
    status = make_status(vnctl, phase="pilot")
    required = vnctl.gates_required_for(status, "pilot")
    pass_gates(tmp_path, status, required)
    status["permissions"] = vnctl.permission_snapshot(status)
    write_status(tmp_path, status)

    loaded = vnctl.load_project_status(tmp_path)
    result = vnctl.evaluate_operation(loaded, "translate-pilot")
    assert result["allowed"] is True
    vnctl.require_operation_allowed("translate-pilot", tmp_path)


def test_explicit_permission_blocks_operation(tmp_path):
    vnctl = load_vnctl()
    status = make_status(vnctl, phase="pilot")
    required = vnctl.gates_required_for(status, "pilot")
    pass_gates(tmp_path, status, required)
    status["permissions"] = vnctl.permission_snapshot(status)
    status["permissions"]["translate_pilot_scene"] = False

    result = vnctl.evaluate_operation(status, "translate-pilot")

    assert result["allowed"] is False
    assert result["blocking_permissions"] == ["translate_pilot_scene"]


def test_existing_cli_commands_still_work(tmp_path):
    root = tmp_path
    (root / "config").mkdir()
    (root / "translation/segments").mkdir(parents=True)
    (root / "docs/project").mkdir(parents=True)
    (root / "config/project.yaml").write_text(
        "paths:\n"
        "  segments: translation/segments\n"
        "  database: database/knowledge.db\n"
        "  findings: docs/project/findings.jsonl\n",
        encoding="utf-8",
    )
    (root / "translation/segments/test.jsonl").write_text(
        json.dumps({
            "id": "S1",
            "file_id": "F1",
            "scene_id": "SC1",
            "order": 1,
            "source": "Hello",
            "translation": "",
            "status": "todo",
        }) + "\n",
        encoding="utf-8",
    )
    (root / "docs/project/findings.jsonl").write_text(
        json.dumps({
            "id": "FND-TEST",
            "date": "2026-07-29",
            "area": "tooling",
            "kind": "fact",
            "title": "Test",
            "statement": "Test finding",
            "status": "verified",
            "method": "Unit test",
        }) + "\n",
        encoding="utf-8",
    )

    script = Path(__file__).parents[1] / "vnctl.py"
    for command in ("validate", "index", "stats", "findings"):
        result = subprocess.run(
            [sys.executable, str(script), "--root", str(root), command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stderr
