from __future__ import annotations

import json

import yaml

from conftest import bootstrap, run, write_jsonl
from test_pipeline import package_hash


def translated_patch(project, scene_id="SCN0001", suffix="one"):
    run(
        project,
        "tools/vnctl.py",
        "work",
        "next",
        scene_id,
        "-o",
        f"build/work-{suffix}.md",
    )
    base_hash = package_hash(project / "build" / f"work-{suffix}.md")
    scene_path = project / "translation" / "segments" / f"{scene_id}.jsonl"
    scene = [json.loads(line) for line in scene_path.read_text(encoding="utf-8").splitlines()]
    rows = [
        {"type": "translation_patch", "scene_id": scene_id, "base_sha256": base_hash}
    ]
    for index, segment in enumerate(scene):
        token = " {name}" if index == 0 else ""
        rows.append(
            {
                "id": segment["id"],
                "translation": f"Target {suffix} {index}.{token}".strip(),
                "status": "draft",
                "flags": [],
                "confidence": "high",
            }
        )
    return scene_path, rows


def test_ingest_preserves_translations_when_scene_catalog_is_lost(project):
    bootstrap(project)
    scene_path, patch = translated_patch(project)
    write_jsonl(project / "build" / "patch.jsonl", patch)
    run(
        project,
        "tools/vnctl.py",
        "apply-translation",
        "SCN0001",
        "build/patch.jsonl",
        "--actor",
        "translator",
    )
    before = [json.loads(line)["translation"] for line in scene_path.read_text(encoding="utf-8").splitlines()]
    (project / "translation" / "scenes.jsonl").write_text("", encoding="utf-8")
    run(project, "tools/vnctl.py", "validate", expected=1)
    run(project, "tools/vnctl.py", "ingest")
    after = [json.loads(line)["translation"] for line in scene_path.read_text(encoding="utf-8").splitlines()]
    assert after == before


def test_stale_translation_patch_is_rejected_atomically(project):
    bootstrap(project)
    scene_path, first = translated_patch(project, suffix="first")
    second = [dict(row) for row in first]
    for row in second[1:]:
        row["translation"] = row["translation"].replace("first", "stale")
    write_jsonl(project / "build" / "first.jsonl", first)
    write_jsonl(project / "build" / "stale.jsonl", second)
    run(
        project,
        "tools/vnctl.py",
        "apply-translation",
        "SCN0001",
        "build/first.jsonl",
        "--actor",
        "translator",
    )
    current = scene_path.read_bytes()
    run(
        project,
        "tools/vnctl.py",
        "apply-translation",
        "SCN0001",
        "build/stale.jsonl",
        "--actor",
        "translator",
        expected=1,
    )
    assert scene_path.read_bytes() == current


def test_roundtrip_receipt_is_invalidated_by_source_change(project):
    bootstrap(project)
    run(project, "adapters/mock.py", "roundtrip", "source/records.jsonl", "build/mock")
    assert "Round trip verified: yes" in run(project, "tools/vnctl.py", "brief").stdout
    source_path = project / "source" / "records.jsonl"
    rows = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["texts"]["source"] = "Changed source, {name}."
    write_jsonl(source_path, rows)
    assert "Round trip verified: no" in run(project, "tools/vnctl.py", "brief").stdout
    run(project, "tools/vnctl.py", "validate", expected=1)


def test_roundtrip_receipt_must_match_configured_pristine_hash(project):
    bootstrap(project)
    receipt_path = project / "build" / "roundtrip-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_sha256"] = "sha256:" + "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert "Round trip verified: no" in run(project, "tools/vnctl.py", "brief").stdout
    run(project, "tools/vnctl.py", "validate", expected=1)


def test_private_review_fields_are_rejected(project):
    bootstrap(project)
    _, patch = translated_patch(project)
    write_jsonl(project / "build" / "patch.jsonl", patch)
    run(
        project,
        "tools/vnctl.py",
        "apply-translation",
        "SCN0001",
        "build/patch.jsonl",
        "--actor",
        "translator",
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "package",
        "SCN0001",
        "-o",
        "build/review.md",
    )
    base_hash = package_hash(project / "build" / "review.md")
    scene = [
        json.loads(line)
        for line in (project / "translation" / "segments" / "SCN0001.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    issue_rows = [
        {
            "type": "review",
            "review_id": "REV-SCN0001-PRIVATE",
            "scene_id": "SCN0001",
            "base_sha256": base_hash,
            "verdict": "revise",
        },
        {
            "issue_id": "REV-SCN0001-PRIVATE-I001",
            "segment_id": scene[0]["id"],
            "severity": "minor",
            "message": "A normal issue.",
            "private_reason": "Must never enter the ledger.",
        },
    ]
    write_jsonl(project / "build" / "issues.jsonl", issue_rows)
    run(
        project,
        "tools/vnctl.py",
        "review",
        "import",
        "SCN0001",
        "build/issues.jsonl",
        "--reviewer",
        "reviewer",
        expected=1,
    )
    issue_rows[1].pop("private_reason")
    issue_rows[1]["message"] = "How are you?"
    write_jsonl(project / "build" / "issues.jsonl", issue_rows)
    run(
        project,
        "tools/vnctl.py",
        "review",
        "import",
        "SCN0001",
        "build/issues.jsonl",
        "--reviewer",
        "reviewer",
        expected=1,
    )
    issue_rows[1]["message"] = "X"
    write_jsonl(project / "build" / "issues.jsonl", issue_rows)
    run(
        project,
        "tools/vnctl.py",
        "review",
        "import",
        "SCN0001",
        "build/issues.jsonl",
        "--reviewer",
        "reviewer",
        expected=1,
    )
    assert (project / "translation" / "review-ledger.jsonl").read_text(encoding="utf-8") == ""
    private_text = "Hidden future identity must not enter tracked review metadata."
    write_jsonl(
        project / "private" / "constraints.jsonl",
        [
            {
                "id": "PC-0001",
                "private_reason": private_text,
                "safe_rules": ["Keep the identity ambiguous."],
            }
        ],
    )
    issue_rows = [
        {
            "type": "review",
            "review_id": "REV-SCN0001-PRIVATE",
            "scene_id": "SCN0001",
            "base_sha256": base_hash,
            "verdict": "revise",
        },
        {
            "issue_id": "REV-SCN0001-PRIVATE-I001",
            "segment_id": scene[0]["id"],
            "severity": "minor",
            "message": private_text,
        },
    ]
    write_jsonl(project / "build" / "issues.jsonl", issue_rows)
    run(
        project,
        "tools/vnctl.py",
        "review",
        "import",
        "SCN0001",
        "build/issues.jsonl",
        "--reviewer",
        "reviewer",
        expected=1,
    )


def test_question_import_requires_nonempty_provisional(project):
    bootstrap(project)
    segment = json.loads(
        (project / "translation" / "segments" / "SCN0001.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    proposal = {
        "id": "OQ-0001",
        "kind": "terminology",
        "scene_id": "SCN0001",
        "segment_ids": [segment["id"]],
        "question": "Choose a stable target form.",
        "provisional": "",
        "status": "open",
    }
    write_jsonl(project / "build" / "questions.jsonl", [proposal])
    run(
        project,
        "tools/vnctl.py",
        "questions",
        "--import-file",
        "build/questions.jsonl",
        "--actor",
        "translator",
        expected=1,
    )
    proposal["provisional"] = "Working form"
    write_jsonl(project / "build" / "questions.jsonl", [proposal])
    result = run(
        project,
        "tools/vnctl.py",
        "questions",
        "--import-file",
        "build/questions.jsonl",
        "--actor",
        "translator",
    )
    assert "1 total" in result.stdout


def test_configured_paths_cannot_escape_project(project):
    run(project, "tools/vnctl.py", "init")
    config_path = project / "config" / "project.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["paths"]["database"] = "../outside.db"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    run(project, "tools/vnctl.py", "index", expected=1)
    assert not (project.parent / "outside.db").exists()


def test_reviewed_and_approved_cannot_be_assigned_manually(project):
    bootstrap(project)
    scene_path, patch = translated_patch(project)
    write_jsonl(project / "build" / "patch.jsonl", patch)
    run(
        project,
        "tools/vnctl.py",
        "apply-translation",
        "SCN0001",
        "build/patch.jsonl",
        "--actor",
        "translator",
    )
    rows = [json.loads(line) for line in scene_path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["status"] = "reviewed"
    write_jsonl(scene_path, rows)
    reviewed = run(project, "tools/vnctl.py", "validate", expected=1)
    assert "no closed review" in reviewed.stdout
    rows[0]["status"] = "approved"
    write_jsonl(scene_path, rows)
    approved = run(project, "tools/vnctl.py", "validate", expected=1)
    assert "approved requires" in approved.stdout


def test_scene_ids_are_safe_on_case_insensitive_filesystems(project):
    run(project, "tools/vnctl.py", "init")
    records = [
        {
            "source_id": "SRC_A",
            "scene_id": "Scene",
            "order": 1,
            "speaker": "",
            "texts": {"source": "A", "reference": "A"},
            "protected_tokens": [],
        },
        {
            "source_id": "SRC_B",
            "scene_id": "scene",
            "order": 2,
            "speaker": "",
            "texts": {"source": "B", "reference": "B"},
            "protected_tokens": [],
        },
    ]
    write_jsonl(project / "source" / "records.jsonl", records)
    run(project, "tools/vnctl.py", "ingest", expected=1)
    records[1]["scene_id"] = "CON"
    write_jsonl(project / "source" / "records.jsonl", records)
    run(project, "tools/vnctl.py", "ingest", expected=1)


def test_translation_is_locked_without_verified_roundtrip(project):
    run(project, "tools/vnctl.py", "init")
    run(project, "adapters/mock.py", "seed", "source/records.jsonl")
    run(project, "tools/vnctl.py", "ingest")
    run(project, "tools/vnctl.py", "validate", expected=1)
    run(
        project,
        "tools/vnctl.py",
        "work",
        "next",
        "SCN0001",
        "-o",
        "build/work.md",
        expected=1,
    )


def test_mock_receipt_path_cannot_escape_project(project):
    run(project, "tools/vnctl.py", "init")
    run(project, "adapters/mock.py", "seed", "source/records.jsonl")
    config_path = project / "config" / "project.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["paths"]["roundtrip_receipt"] = "../outside-receipt.json"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    run(
        project,
        "adapters/mock.py",
        "roundtrip",
        "source/records.jsonl",
        "build/mock",
        expected=1,
    )
    assert not (project.parent / "outside-receipt.json").exists()
