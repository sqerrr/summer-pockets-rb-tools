from __future__ import annotations

import json
import re

from conftest import bootstrap, run, write_jsonl


def package_hash(path):
    match = re.search(r"Base hash: (sha256:[0-9a-f]{64})", path.read_text(encoding="utf-8"))
    assert match
    return match.group(1)


def test_mock_roundtrip_translation_and_review_cycle(project):
    bootstrap(project)
    run(project, "adapters/mock.py", "roundtrip", "source/records.jsonl", "build/mock")
    run(project, "tools/vnctl.py", "validate")
    run(
        project,
        "tools/vnctl.py",
        "work",
        "next",
        "SCN0001",
        "-o",
        "build/work-SCN0001.md",
    )
    work_hash = package_hash(project / "build" / "work-SCN0001.md")

    scene_path = project / "translation" / "segments" / "SCN0001.jsonl"
    scene = [json.loads(line) for line in scene_path.read_text(encoding="utf-8").splitlines()]
    patch = [
        {
            "type": "translation_patch",
            "scene_id": "SCN0001",
            "base_sha256": work_hash,
        },
        {
            "id": scene[0]["id"],
            "translation": "Target greeting, {name}.",
            "status": "draft",
            "flags": [],
            "confidence": "high",
        },
        {
            "id": scene[1]["id"],
            "translation": "Target question?",
            "status": "draft",
            "flags": [],
            "confidence": "medium",
        },
    ]
    write_jsonl(project / "build" / "patch-SCN0001.jsonl", patch)
    run(project, "tools/vnctl.py", "work", "check", "build/patch-SCN0001.jsonl")
    run(
        project,
        "tools/vnctl.py",
        "apply-translation",
        "SCN0001",
        "build/patch-SCN0001.jsonl",
        "--actor",
        "test-translator",
    )

    run(
        project,
        "tools/vnctl.py",
        "review",
        "package",
        "SCN0001",
        "-o",
        "build/review-SCN0001.md",
    )
    base_hash = package_hash(project / "build" / "review-SCN0001.md")
    review_id = "REV-SCN0001-01"
    write_jsonl(
        project / "build" / "issues-SCN0001.jsonl",
        [
            {
                "type": "review",
                "review_id": review_id,
                "scene_id": "SCN0001",
                "base_sha256": base_hash,
                "verdict": "revise",
            },
            {
                "issue_id": f"{review_id}-I001",
                "segment_id": scene[1]["id"],
                "severity": "minor",
                "message": "The target can be more specific.",
                "suggested_translation": "Target question for today?",
            },
        ],
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "import",
        "SCN0001",
        "build/issues-SCN0001.jsonl",
        "--reviewer",
        "test-reviewer",
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "fix",
        review_id,
        "-o",
        "build/fix-SCN0001.md",
    )
    write_jsonl(
        project / "build" / "resolutions-SCN0001.jsonl",
        [
            {"type": "resolutions", "review_id": review_id, "base_sha256": base_hash},
            {
                "issue_id": f"{review_id}-I001",
                "disposition": "applied",
                "reason": "Uses the source nuance.",
                "changes": [
                    {
                        "id": scene[1]["id"],
                        "translation": "Target question for today?",
                        "flags": [],
                    }
                ],
            },
        ],
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "resolve",
        review_id,
        "build/resolutions-SCN0001.jsonl",
        "--actor",
        "test-editor",
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "recheck",
        review_id,
        "-o",
        "build/recheck-SCN0001.md",
    )
    current_hash = package_hash(project / "build" / "recheck-SCN0001.md")
    write_jsonl(
        project / "build" / "verdict-self-review.jsonl",
        [
            {
                "review_id": review_id,
                "base_sha256": current_hash,
                "verdict": "accept",
                "open_issue_ids": [],
                "notes": "Self-review must be rejected.",
            }
        ],
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "close",
        review_id,
        "build/verdict-self-review.jsonl",
        "--reviewer",
        "test-translator",
        expected=1,
    )
    write_jsonl(
        project / "build" / "verdict-revise-SCN0001.jsonl",
        [
            {
                "review_id": review_id,
                "base_sha256": current_hash,
                "verdict": "revise",
                "open_issue_ids": [f"{review_id}-I001"],
                "notes": "Check the issue again.",
            }
        ],
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "close",
        review_id,
        "build/verdict-revise-SCN0001.jsonl",
        "--reviewer",
        "test-reviewer",
    )
    write_jsonl(
        project / "build" / "verdict-SCN0001.jsonl",
        [
            {
                "review_id": review_id,
                "base_sha256": current_hash,
                "verdict": "accept",
                "open_issue_ids": [],
                "notes": "All issues are closed.",
            }
        ],
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "close",
        review_id,
        "build/verdict-SCN0001.jsonl",
        "--reviewer",
        "test-reviewer",
        expected=1,
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "fix",
        review_id,
        "-o",
        "build/fix-repeat-SCN0001.md",
    )
    write_jsonl(
        project / "build" / "resolutions-repeat-SCN0001.jsonl",
        [
            {"type": "resolutions", "review_id": review_id, "base_sha256": current_hash},
            {
                "issue_id": f"{review_id}-I001",
                "disposition": "applied",
                "reason": "The existing corrected target is retained.",
                "changes": [],
            },
        ],
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "resolve",
        review_id,
        "build/resolutions-repeat-SCN0001.jsonl",
        "--actor",
        "test-editor",
    )
    run(
        project,
        "tools/vnctl.py",
        "review",
        "recheck",
        review_id,
        "-o",
        "build/recheck-repeat-SCN0001.md",
    )
    repeat_hash = package_hash(project / "build" / "recheck-repeat-SCN0001.md")
    verdict = json.loads(
        (project / "build" / "verdict-SCN0001.jsonl").read_text(encoding="utf-8")
    )
    verdict["base_sha256"] = repeat_hash
    write_jsonl(project / "build" / "verdict-SCN0001.jsonl", [verdict])
    run(
        project,
        "tools/vnctl.py",
        "review",
        "close",
        review_id,
        "build/verdict-SCN0001.jsonl",
        "--reviewer",
        "test-reviewer",
    )
    run(project, "tools/vnctl.py", "validate")
    final_scene = [
        json.loads(line) for line in scene_path.read_text(encoding="utf-8").splitlines()
    ]
    assert {row["status"] for row in final_scene} == {"reviewed"}
    brief = run(project, "tools/vnctl.py", "brief")
    assert "Round trip verified: yes" in brief.stdout
    assert "Hello, {name}." not in brief.stdout


def test_invalid_patch_is_atomic(project):
    bootstrap(project)
    run(
        project,
        "tools/vnctl.py",
        "work",
        "next",
        "SCN0001",
        "-o",
        "build/work-SCN0001.md",
    )
    work_hash = package_hash(project / "build" / "work-SCN0001.md")
    scene_path = project / "translation" / "segments" / "SCN0001.jsonl"
    before = scene_path.read_bytes()
    scene = [json.loads(line) for line in before.decode("utf-8").splitlines()]
    patch = [
        {
            "type": "translation_patch",
            "scene_id": "SCN0001",
            "base_sha256": work_hash,
        },
        {
            "id": scene[0]["id"],
            "translation": "Target greeting without the required token.",
            "status": "draft",
            "flags": [],
            "confidence": "high",
        },
        {
            "id": scene[1]["id"],
            "translation": "Target question?",
            "status": "draft",
            "flags": [],
            "confidence": "high",
        },
    ]
    write_jsonl(project / "build" / "bad-patch.jsonl", patch)
    run(
        project,
        "tools/vnctl.py",
        "apply-translation",
        "SCN0001",
        "build/bad-patch.jsonl",
        "--actor",
        "test-translator",
        expected=1,
    )
    assert scene_path.read_bytes() == before
