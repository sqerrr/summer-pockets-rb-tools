import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_module(path: Path, name: str):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_report_verdict_requires_one_unambiguous_marker(tmp_path):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_style_verdict_test")
    report = tmp_path / "report.md"

    report.write_text("# Review\nVERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.report_verdict(report) == "ACCEPT"
    assert vnctl.report_accepts(report)

    report.write_text("VERDICT: ACCEPT\nVERDICT: REVISE\n", encoding="utf-8")
    assert vnctl.report_verdict(report) is None
    assert not vnctl.report_accepts(report)

    report.write_text("> VERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.report_verdict(report) is None


def make_project(tmp_path: Path):
    (tmp_path / "translation/segments").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "private").mkdir()
    (tmp_path / "source/parsed").mkdir(parents=True)
    scenes = [{"scene_id": "SCN0001", "file_id": "S1", "route": "BLK0002"}]
    write_jsonl(tmp_path / "translation/scenes.jsonl", scenes)
    rows = []
    records = []
    for index in range(5):
        source_id = f"SRC{index}"
        rows.append({
            "id": f"SEG{index}",
            "source_set_id": "SET",
            "source_id": source_id,
            "source_hash": "sha256:" + "0" * 64,
            "file_id": "S1",
            "scene_id": "SCN0001",
            "order": index,
            "speaker": "話者",
            "translation": ("Имя пишется как 空." if index == 4 else f"Фраза {index}."),
            "status": "reviewed",
            "flags": [],
        })
        records.append({
            "source_id": source_id,
            "slots": [
                {"language": "ja", "text": f"原文{index}"},
                {"language": "en", "text": f"source {index}"},
                {"language": "zh-Hans", "text": f"中文{index}"},
            ],
        })
    write_jsonl(tmp_path / "translation/segments/SCN0001.jsonl", rows)
    write_jsonl(tmp_path / "translation/speakers.jsonl", [{
        "id": "SPK-0001", "source": "話者", "preferred_ru": "Говорящий"
    }])
    write_jsonl(tmp_path / "translation/style-ledger.jsonl", [{
        "schema_version": 1, "event": "ledger_initialized"
    }])
    write_jsonl(tmp_path / "private/constraints.jsonl", [{
        "id": "HIDDEN-1", "segment_ids": ["SEG0"], "status": "active",
        "safe_rules": ["Сохранить двусмысленность 原文."]
    }])
    write_jsonl(tmp_path / "docs/decisions.jsonl", [{
        "id": "DEC-1", "type": "terminology", "scope": "global",
        "status": "approved", "decision": "Сохранять бэнто и お兄ちゃん.",
    }])
    write_jsonl(tmp_path / "source/manifest.jsonl", [{
        "source_set_id": "SET", "catalog_path": "source/parsed/records.jsonl"
    }])
    write_jsonl(tmp_path / "source/parsed/records.jsonl", records)
    (tmp_path / "config/qa-rules.yaml").write_text(
        "allowed_flags:\n- needs_source_check\n- needs_term_decision\n", encoding="utf-8")
    config = {
        "paths": {
            "segments": "translation/segments",
            "scenes": "translation/scenes.jsonl",
            "style_ledger": "translation/style-ledger.jsonl",
            "source_manifest": "source/manifest.jsonl",
            "speakers": "translation/speakers.jsonl",
        },
        "workflow": {
            "style_window_min": 2,
            "style_window_max": 4,
            "style_context_segments": 1,
            "style_service_routes": [],
        },
    }
    return config


def make_sibling_preflight_project(
        tmp_path: Path, *, anchor_translation: str = "Новая формулировка.",
        sibling_translation: str = "Старая формулировка.",
        sibling_speaker: str = "話者", sibling_context_change: bool = False):
    (tmp_path / "translation/segments").mkdir(parents=True)
    (tmp_path / "source/parsed").mkdir(parents=True)
    scenes = [
        {"scene_id": "SCN0001", "file_id": "S1", "route": "BLK0002"},
        {"scene_id": "SCN0002", "file_id": "S2", "route": "BLK0002"},
    ]
    write_jsonl(tmp_path / "translation/scenes.jsonl", scenes)
    source_bodies = ["前二", "前一", "同じ原文", "後一", "後二"]
    records = []
    for scene_index, scene in enumerate(scenes, start=1):
        rows = []
        for index, body in enumerate(source_bodies):
            if scene_index == 2 and sibling_context_change and index == 1:
                body = "異なる前一"
            source_id = f"SRC{scene_index}_{index}"
            sid = f"SEG{scene_index}_{index}"
            translation = f"Контекст {scene_index}-{index}."
            speaker = "話者"
            if index == 2:
                translation = anchor_translation if scene_index == 1 else sibling_translation
                speaker = "話者" if scene_index == 1 else sibling_speaker
            rows.append({
                "id": sid,
                "source_set_id": "SET",
                "source_id": source_id,
                "source_hash": "sha256:" + str(scene_index) * 64,
                "file_id": scene["file_id"],
                "scene_id": scene["scene_id"],
                "order": index,
                "speaker": speaker,
                "translation": translation,
                "status": "reviewed",
                "flags": [],
            })
            records.append({
                "source_id": source_id,
                "slots": [{"language": "ja", "body_text": body, "text": body}],
            })
        write_jsonl(tmp_path / f"translation/segments/{scene['scene_id']}.jsonl", rows)
    write_jsonl(tmp_path / "translation/speakers.jsonl", [{
        "id": "SPK-1", "source": "話者", "preferred_ru": "Говорящий",
    }])
    write_jsonl(tmp_path / "source/manifest.jsonl", [{
        "source_set_id": "SET", "catalog_path": "source/parsed/records.jsonl",
    }])
    write_jsonl(tmp_path / "source/parsed/records.jsonl", records)
    write_jsonl(tmp_path / "translation/review-ledger.jsonl", [{
        "schema_version": 1, "event": "ledger_initialized",
    }])
    write_style_transitions(tmp_path, [])
    return {
        "paths": {
            "segments": "translation/segments",
            "scenes": "translation/scenes.jsonl",
            "review_ledger": "translation/review-ledger.jsonl",
            "style_ledger": "translation/style-ledger.jsonl",
            "source_manifest": "source/manifest.jsonl",
            "speakers": "translation/speakers.jsonl",
        },
    }


def write_review_transitions(tmp_path: Path, transitions: list[tuple[str, str]],
                             *, accepted: bool = True, superseded: bool = False):
    review_id = "REV-SCN0001-01"
    issue_id = f"{review_id}-I001"
    events = [
        {"schema_version": 1, "event": "ledger_initialized"},
        {"schema_version": 1, "event": "review_imported",
         "review_id": review_id, "scene_id": "SCN0001",
         "issues": [{"issue_id": issue_id, "severity": "minor",
                     "category": "style", "segment_ids": ["SEG1_2"],
                     "problem": "Уточнить формулировку.", "suggested_changes": []}]},
    ]
    for before, after in transitions:
        events.append({
            "schema_version": 1, "event": "review_resolved",
            "review_id": review_id, "scene_id": "SCN0001",
            "resolutions": [{
                "issue_id": issue_id, "disposition": "applied", "reason": "Исправлено.",
                "changes": [{"id": "SEG1_2", "before": before,
                             "translation": after, "flags": []}],
            }],
        })
    if accepted:
        events.append({
            "schema_version": 1, "event": "review_accepted",
            "review_id": review_id, "scene_id": "SCN0001",
        })
    if superseded:
        events.append({
            "schema_version": 1, "event": "review_issue_superseded",
            "review_id": review_id, "issue_id": issue_id, "question_id": "OQ-1",
            "actor": "vn-auditor", "reason": "Заменено более новым решением.",
        })
    write_jsonl(tmp_path / "translation/review-ledger.jsonl", events)


def write_style_transitions(tmp_path: Path, transitions: list[tuple[str, str]]):
    changes = []
    if transitions:
        before, after = transitions[0]
        changes = [{"id": "SEG1_2", "scene_id": "SCN0001",
                    "before": before, "after": after}]
    events = [
        {"schema_version": 1, "event": "ledger_initialized"},
        {"schema_version": 1, "event": "run_started",
         "run_id": "STYLE-BLK0002-01", "route": "BLK0002",
         "windows": [{"window_id": "W001"}]},
        {"schema_version": 1, "event": "window_applied",
         "run_id": "STYLE-BLK0002-01", "window_id": "W001",
         "changes": changes},
    ]
    for before, after in transitions[1:]:
        events.append({
            "schema_version": 1, "event": "window_revised",
            "run_id": "STYLE-BLK0002-01", "window_id": "W001",
            "changes": [{"id": "SEG1_2", "scene_id": "SCN0001",
                         "before": before, "after": after}],
        })
    events.append({
        "schema_version": 1, "event": "window_accepted",
        "run_id": "STYLE-BLK0002-01", "window_id": "W001",
    })
    write_jsonl(tmp_path / "translation/style-ledger.jsonl", events)


def sibling_blockers(vnctl, tmp_path: Path, config: dict):
    run = vnctl.style_runs(vnctl.load_style_events(
        tmp_path, config))["STYLE-BLK0002-01"]
    rows = vnctl.style_route_rows(tmp_path, config, "BLK0002")
    source_texts = vnctl.source_text_by_segment(tmp_path, config, rows)
    return vnctl.style_exact_source_sibling_blockers(
        tmp_path, config, run, rows, source_texts)


@pytest.mark.parametrize("anchor_kind, provenance", [
    ("review", "REV-SCN0001-01-I001"),
    ("style", "STYLE-BLK0002-01/W001"),
])
def test_exact_source_sibling_preflight_blocks_stale_before(
        tmp_path, anchor_kind, provenance):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", f"vnctl_sibling_{anchor_kind}_test")
    config = make_sibling_preflight_project(tmp_path)
    transition = [("Старая формулировка.", "Новая формулировка.")]
    if anchor_kind == "review":
        write_review_transitions(tmp_path, transition)
    else:
        write_style_transitions(tmp_path, transition)

    expected = [{
        "anchor": "SEG1_2",
        "sibling": "SEG2_2",
        "provenance": provenance,
        "before": "Старая формулировка.",
        "after": "Новая формулировка.",
    }]
    assert sibling_blockers(vnctl, tmp_path, config) == expected
    with pytest.raises(ValueError, match="1 blocker") as exc:
        vnctl.style_audit_package(tmp_path, config, "STYLE-BLK0002-01")
    assert str(exc.value).splitlines()[1] == json.dumps(expected[0], ensure_ascii=False)


def test_exact_source_sibling_preflight_passes_same_after(tmp_path):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_sibling_same_after_test")
    config = make_sibling_preflight_project(
        tmp_path, sibling_translation="Новая формулировка.")
    write_review_transitions(
        tmp_path, [("Старая формулировка.", "Новая формулировка.")])

    assert sibling_blockers(vnctl, tmp_path, config) == []


@pytest.mark.parametrize("difference", ["speaker", "context"])
def test_exact_source_sibling_preflight_passes_different_speaker_or_context(
        tmp_path, difference):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", f"vnctl_sibling_{difference}_test")
    config = make_sibling_preflight_project(
        tmp_path,
        sibling_speaker="別人" if difference == "speaker" else "話者",
        sibling_context_change=difference == "context",
    )
    write_review_transitions(
        tmp_path, [("Старая формулировка.", "Новая формулировка.")])

    assert sibling_blockers(vnctl, tmp_path, config) == []


def test_exact_source_sibling_preflight_does_not_block_third_form(tmp_path):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_sibling_third_form_test")
    config = make_sibling_preflight_project(
        tmp_path, sibling_translation="Третья формулировка.")
    write_review_transitions(
        tmp_path, [("Старая формулировка.", "Новая формулировка.")])

    assert sibling_blockers(vnctl, tmp_path, config) == []


@pytest.mark.parametrize("anchor_kind", ["review", "style"])
def test_exact_source_sibling_preflight_uses_latest_transition(tmp_path, anchor_kind):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", f"vnctl_sibling_latest_{anchor_kind}_test")
    config = make_sibling_preflight_project(
        tmp_path, anchor_translation="Третья формулировка.",
        sibling_translation="Вторая формулировка.")
    transitions = [
        ("Первая формулировка.", "Вторая формулировка."),
        ("Вторая формулировка.", "Третья формулировка."),
    ]
    if anchor_kind == "review":
        write_review_transitions(tmp_path, transitions)
    else:
        write_style_transitions(tmp_path, transitions)

    blockers = sibling_blockers(vnctl, tmp_path, config)
    assert len(blockers) == 1
    assert blockers[0]["before"] == "Вторая формулировка."
    assert blockers[0]["after"] == "Третья формулировка."


@pytest.mark.parametrize("accepted, superseded", [(False, False), (True, True)])
def test_exact_source_sibling_preflight_ignores_ineffective_review_transition(
        tmp_path, accepted, superseded):
    root = Path(__file__).parents[2]
    vnctl = load_module(
        root / "tools/vnctl.py", f"vnctl_sibling_ineffective_{accepted}_{superseded}")
    config = make_sibling_preflight_project(tmp_path)
    write_review_transitions(
        tmp_path, [("Старая формулировка.", "Новая формулировка.")],
        accepted=accepted, superseded=superseded)

    assert sibling_blockers(vnctl, tmp_path, config) == []


def test_exact_source_sibling_preflight_is_read_only(tmp_path):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_sibling_read_only_test")
    config = make_sibling_preflight_project(tmp_path)
    write_review_transitions(
        tmp_path, [("Старая формулировка.", "Новая формулировка.")])
    tracked = sorted((tmp_path / "translation").rglob("*.jsonl"))
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tracked}

    assert len(sibling_blockers(vnctl, tmp_path, config)) == 1
    with pytest.raises(ValueError, match="Exact-source sibling preflight"):
        vnctl.style_audit_package(tmp_path, config, "STYLE-BLK0002-01")

    after_paths = sorted((tmp_path / "translation").rglob("*.jsonl"))
    assert [path.relative_to(tmp_path) for path in after_paths] == list(before)
    assert {path.relative_to(tmp_path): path.read_bytes() for path in after_paths} == before


def test_style_slice_hash_ignores_context_status_changes():
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_style_context_status")
    rows = [
        {"id": "EDIT", "translation": "Правка.", "status": "reviewed", "flags": []},
        {"id": "CONTEXT", "translation": "Контекст.", "status": "draft", "flags": []},
    ]
    base = vnctl.style_slice_hash(rows, status_ids={"EDIT"})

    rows[1]["status"] = "reviewed"
    assert vnctl.style_slice_hash(rows, status_ids={"EDIT"}) == base

    rows[0]["status"] = "playable"
    assert vnctl.style_slice_hash(rows, status_ids={"EDIT"}) != base


def test_style_pipeline_is_windowed_russian_only_and_never_creates_lqa(tmp_path):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_style_test")
    config = make_project(tmp_path)

    assert vnctl.style_start(tmp_path, config, "BLK0002") == 0
    run_id = "STYLE-BLK0002-01"
    package = vnctl.style_package(tmp_path, config, run_id)
    assert "原文" not in package
    assert "話者" not in package
    assert "お兄ちゃん" not in package
    assert "бэнто" in package
    assert "Смысловой инвентарь `before` заблокирован" in package
    assert "оба участника сравнения" in package
    assert "ОБЯЗАТЕЛЬНЫЕ ЗНАНИЯ" in package
    assert "Активные находки" in package
    assert "Открытые вопросы и рабочие варианты" in package
    assert "Ранее принятые замечания ревьюеров" in package
    assert package.count('"scope": "editable"') == 3
    assert package.count('"scope": "context"') == 1

    parallel_package = vnctl.style_package(tmp_path, config, run_id, "W002")
    assert "STYLE-BLK0002-01 / W002" in parallel_package
    assert "Имя пишется как [иероглиф]." in parallel_package
    assert parallel_package.count('"scope": "editable"') == 1
    assert parallel_package.count('"scope": "context"') == 2

    run = vnctl.style_runs(vnctl.load_style_events(tmp_path, config))[run_id]
    route_rows = vnctl.style_route_rows(tmp_path, config, "BLK0002")
    package_rows, editable = vnctl.style_window_rows(route_rows, run["windows"][0])
    patch1 = tmp_path / "build/style-1.jsonl"
    write_jsonl(patch1, [
        {"__style_window__": {
            "run_id": run_id,
            "window_id": "W001",
            "base_sha256": vnctl.style_package_hash(package_rows, editable),
        }},
        {"id": "SEG0", "before": "Фраза 0.",
         "translation": "Новая фраза.", "reason": "Естественнее."},
        {"id": "SEG1", "before": "Фраза 1.",
         "translation": "Новая вторая фраза.", "reason": "Естественнее."},
    ])
    assert vnctl.style_check(tmp_path, config, run_id, "W001", patch1) == 0
    assert vnctl.style_apply(tmp_path, config, run_id, "W001", patch1) == 0
    changed = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")[0]
    assert changed["status"] == "draft"
    assert changed["status"] != "lqa"

    revise_report = tmp_path / "build/style-review-revise.md"
    revise_report.write_text(
        "# Review\n\nVERDICT: REVISE\n\n- SEG0: уточнить формулировку.\n",
        encoding="utf-8")
    fix_package = vnctl.style_revision_package(
        tmp_path, config, run_id, "W001", revise_report)
    assert "__style_revision__" in fix_package
    assert "SEG0: уточнить формулировку" in fix_package

    revision = tmp_path / "build/style-revision-1.jsonl"
    current = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")[0]
    write_jsonl(revision, [
        {"__style_revision__": {
            "run_id": run_id,
            "window_id": "W001",
            "base_sha256": vnctl.style_slice_hash([current]),
            "report_sha256": vnctl.sha256_file(revise_report),
            "allowed_ids": ["SEG0"],
        }},
        {"id": "SEG0", "before": "Новая фраза.",
          "translation": "Исправленная фраза.",
          "reason": "Уточнено после source-aware проверки.",
          "flags": ["needs_term_decision"]},
    ])
    assert vnctl.style_revise(
        tmp_path, config, run_id, "W001", revision, revise_report,
        "vn-stylist") == 0
    revised = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")[0]
    assert revised["translation"] == "Исправленная фраза."
    assert revised["flags"] == ["needs_term_decision"]

    review_package = vnctl.style_review_package(tmp_path, config, run_id, "W001")
    assert "原文0" in review_package
    assert "Исправленная фраза." in review_package
    report1 = tmp_path / "build/review-1.md"
    report1.write_text("# Review\nVERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.style_accept(
        tmp_path, config, run_id, "W001", report1, "vn-reviewer") == 0

    late_report = tmp_path / "build/style-audit-revise.md"
    late_report.write_text(
        "# Audit\n\nVERDICT: REVISE\n\n- SEG0: исправить найденный сквозным аудитом повтор.\n",
        encoding="utf-8")
    late_fix_package = vnctl.style_revision_package(
        tmp_path, config, run_id, "W001", late_report)
    assert "__style_revision__" in late_fix_package
    current = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")[0]
    late_revision = tmp_path / "build/style-revision-late.jsonl"
    write_jsonl(late_revision, [
        {"__style_revision__": {
            "run_id": run_id,
            "window_id": "W001",
            "base_sha256": vnctl.style_slice_hash([current]),
            "report_sha256": vnctl.sha256_file(late_report),
            "allowed_ids": ["SEG0"],
        }},
        {"id": "SEG0", "before": "Исправленная фраза.",
         "translation": "Итоговая фраза.",
         "reason": "Исправлен сквозной повтор после route audit."},
    ])
    assert vnctl.style_revise(
        tmp_path, config, run_id, "W001", late_revision, late_report,
        "vn-stylist") == 0
    run = vnctl.style_runs(vnctl.load_style_events(tmp_path, config))[run_id]
    assert "W001" not in run["accepted"]
    assert vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")[0]["status"] == "draft"
    assert vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")[1]["status"] == "reviewed"
    late_accept = tmp_path / "build/review-late.md"
    late_accept.write_text("# Review\nVERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.style_accept(
        tmp_path, config, run_id, "W001", late_accept, "vn-reviewer") == 0
    assert all(row["status"] == "reviewed" for row in vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")[:2])

    package2 = vnctl.style_package(tmp_path, config, run_id)
    run = vnctl.style_runs(vnctl.load_style_events(tmp_path, config))[run_id]
    route_rows = vnctl.style_route_rows(tmp_path, config, "BLK0002")
    package_rows, editable = vnctl.style_window_rows(route_rows, run["windows"][1])
    patch2 = tmp_path / "build/style-2.jsonl"
    write_jsonl(patch2, [{"__style_window__": {
        "run_id": run_id,
        "window_id": "W002",
        "base_sha256": vnctl.style_package_hash(package_rows, editable),
    }}])
    assert "W002" in package2
    assert vnctl.style_apply(tmp_path, config, run_id, "W002", patch2) == 0
    report2 = tmp_path / "build/review-2.md"
    report2.write_text("# Review\nVERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.style_accept(
        tmp_path, config, run_id, "W002", report2, "vn-reviewer") == 0

    audit_package = vnctl.style_audit_package(tmp_path, config, run_id)
    assert "Итоговая фраза." in audit_package
    audit = tmp_path / "build/audit.md"
    audit.write_text("# Audit\nVERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.style_accept_audit(
        tmp_path, config, run_id, audit, "vn-auditor") == 0
    assert vnctl.style_run_complete(tmp_path, config, "BLK0002")
    statuses = {row["status"] for row in vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")}
    assert statuses == {"reviewed"}


def test_release_preflight_rejects_block_without_current_audit(tmp_path):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_style_build_test")
    builder = load_module(root / "game-tools/build_luca_release.py", "luca_release_test")
    config = make_project(tmp_path)
    old_root = builder.ROOT
    builder.ROOT = tmp_path
    try:
        with pytest.raises(SystemExit, match="художественная вычитка не завершена"):
            builder.style_build_preflight(
                config, tmp_path / "translation/segments", {"SCN0001"})
        vnctl.style_start(tmp_path, config, "BLK0002")
        run_id = "STYLE-BLK0002-01"
        run = vnctl.style_runs(vnctl.load_style_events(tmp_path, config))[run_id]
        for window in run["windows"]:
            window_id = window["window_id"]
            route_rows = vnctl.style_route_rows(tmp_path, config, "BLK0002")
            package_rows, editable = vnctl.style_window_rows(route_rows, window)
            patch = tmp_path / f"build/{window_id}.jsonl"
            write_jsonl(patch, [{"__style_window__": {
                "run_id": run_id,
                "window_id": window_id,
                "base_sha256": vnctl.style_package_hash(package_rows, editable),
            }}])
            vnctl.style_apply(tmp_path, config, run_id, window_id, patch)
            report = tmp_path / f"build/{window_id}.md"
            report.write_text("VERDICT: ACCEPT\n", encoding="utf-8")
            vnctl.style_accept(tmp_path, config, run_id, window_id, report, "reviewer")
        audit = tmp_path / "build/audit.md"
        audit.write_text("VERDICT: ACCEPT\n", encoding="utf-8")
        vnctl.style_accept_audit(tmp_path, config, run_id, audit, "auditor")
        assert builder.style_build_preflight(
            config, tmp_path / "translation/segments", {"SCN0001"}) == {
                "BLK0002": run_id
            }
    finally:
        builder.ROOT = old_root


def test_release_reviewed_route_keeps_higher_statuses_global(tmp_path, monkeypatch,
                                                             capsys):
    root = Path(__file__).parents[2]
    builder = load_module(root / "game-tools/build_luca_release.py",
                          "luca_release_route_test")
    (tmp_path / "translation/segments").mkdir(parents=True)
    write_jsonl(tmp_path / "translation/scenes.jsonl", [
        {"scene_id": "SCN0001", "route": "BLK0001"},
        {"scene_id": "SCN0002", "route": "BLK0002"},
        {"scene_id": "SCN0003", "route": "BLK0003"},
    ])
    write_jsonl(tmp_path / "translation/segments/SCN0001.jsonl", [
        {
            "id": "SEG-P", "source_id": "SRC-P", "scene_id": "SCN0001",
            "translation": "Старый playable-текст.", "status": "playable",
        },
        {
            "id": "SEG-L", "source_id": "SRC-L", "scene_id": "SCN0001",
            "translation": "Старый LQA-текст.", "status": "lqa",
        },
        {
            "id": "SEG-A", "source_id": "SRC-A", "scene_id": "SCN0001",
            "translation": "Старый approved-текст.", "status": "approved",
        },
    ])
    write_jsonl(tmp_path / "translation/segments/SCN0002.jsonl", [{
        "id": "SEG-R2", "source_id": "SRC-R2", "scene_id": "SCN0002",
        "translation": "Новый проверенный route.", "status": "reviewed",
    }])
    write_jsonl(tmp_path / "translation/segments/SCN0003.jsonl", [{
        "id": "SEG-R3", "source_id": "SRC-R3", "scene_id": "SCN0003",
        "translation": "Downstream reviewed-текст.", "status": "reviewed",
    }])
    write_jsonl(tmp_path / "translation/speakers.jsonl", [])
    write_jsonl(tmp_path / "translation/style-ledger.jsonl", [{
        "schema_version": 1, "event": "ledger_initialized",
    }])
    config = {
        "source_sets": {"steam_luca": {
            "archive": "pristine.pak",
            "archive_sha256": "sha256:source",
            "build_slot": 1,
            "slots": [
                {"language": "ja"}, {"language": "en"}, {"language": "zh-Hans"},
            ],
        }},
        "paths": {
            "segments": "translation/segments",
            "scenes": "translation/scenes.jsonl",
            "style_ledger": "translation/style-ledger.jsonl",
        },
        "workflow": {"style_service_routes": ["BLK0001"]},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "build/SCRIPT.russian.PAK"
    receipt_path = tmp_path / "build/release-receipt.json"

    built_text_by_offset = {}

    class FakeRecord:
        def __init__(self, offset, built_text=None):
            self.offset = offset
            self.params = b"old"
            self.built_text = built_text

    script_entry = SimpleNamespace(index=0, entry_id=1, name="script")
    metadata_entry = SimpleNamespace(index=1, entry_id=2, name="_build_time")

    class FakePak:
        def __init__(self, path):
            self.entries = [script_entry, metadata_entry]
            self.entry_count = 2
            if path == output:
                self.records = [
                    FakeRecord(offset, built_text_by_offset[offset])
                    for offset in sorted(built_text_by_offset)
                ]
            else:
                self.records = [
                    FakeRecord(10), FakeRecord(20), FakeRecord(30), FakeRecord(40),
                ]

        def read_entry(self, entry):
            return self.records if entry.index == 0 else []

        def build(self, path, replacements):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-pak")

    def classify(record):
        text = record.built_text if record.built_text is not None else "old"
        value = SimpleNamespace(text=text, encoding="utf-8", offset=0, end_offset=3)
        return SimpleNamespace(classification="translatable", strings=[value, value, value])

    def relocate(_pak, edits):
        for (_entry_index, offset), payload in edits.items():
            built_text_by_offset[offset] = payload.decode("utf-8")
        return SimpleNamespace(
            replacements=edits,
            offset_maps={0: {offset: offset for offset in built_text_by_offset}},
        )

    def preflight(_config, _seg_dir, scene_ids):
        assert scene_ids == {"SCN0001", "SCN0002"}
        return {"BLK0002": "STYLE-BLK0002-01"}

    old_root = builder.ROOT
    builder.ROOT = tmp_path
    monkeypatch.setattr(builder, "Pak", FakePak)
    monkeypatch.setattr(builder, "digest_file", lambda path: (
        "sha256:output" if path == output else "sha256:source"))
    monkeypatch.setattr(builder, "iter_script_records", lambda rows: iter(rows))
    source_ids = ["SRC-P", "SRC-L", "SRC-A", "SRC-R2"]
    monkeypatch.setattr(builder, "make_source_id",
                        lambda _entry_id, ordinal: source_ids[ordinal])
    monkeypatch.setattr(builder, "classify_source_record", classify)
    monkeypatch.setattr(builder, "encode_luca_string",
                        lambda text, _encoding: text.encode("utf-8"))
    monkeypatch.setattr(builder, "relocate_script_records", relocate)
    monkeypatch.setattr(builder, "validate_script_references", lambda _pak: {
        "records": 4, "references": 0, "labels": 0,
    })
    monkeypatch.setattr(builder, "style_build_preflight", preflight)
    try:
        assert builder.main([
            "--config", str(config_path),
            "--output", str(output),
            "--receipt", str(receipt_path),
            "--reviewed-route", "BLK0002",
        ]) == 0
    finally:
        builder.ROOT = old_root

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["reviewed_routes"] == ["BLK0002"]
    assert receipt["skipped_reviewed_by_route"] == 1
    assert receipt["segments_written"] == 4
    assert receipt["promoted_to_playable"] == 1
    output_text = capsys.readouterr().out
    assert "reviewed_routes: BLK0002" in output_text
    assert "reviewed пропущено по route: 1" in output_text
    assert builder.read_jsonl(tmp_path / "translation/segments/SCN0002.jsonl")[0][
        "status"] == "playable"
    assert builder.read_jsonl(tmp_path / "translation/segments/SCN0003.jsonl")[0][
        "status"] == "reviewed"


def test_release_default_still_preflights_all_reviewed_routes(tmp_path):
    root = Path(__file__).parents[2]
    builder = load_module(root / "game-tools/build_luca_release.py",
                          "luca_release_default_routes_test")
    config = make_project(tmp_path)
    write_jsonl(tmp_path / "translation/scenes.jsonl", [
        {"scene_id": "SCN0001", "route": "BLK0002"},
        {"scene_id": "SCN0002", "route": "BLK0003"},
        {"scene_id": "SCN0003", "route": "BLK0004"},
    ])
    for index, (scene_id, route) in enumerate([
            ("SCN0002", "BLK0003"), ("SCN0003", "BLK0004")], start=2):
        write_jsonl(tmp_path / f"translation/segments/{scene_id}.jsonl", [{
            "id": f"SEG{index}", "source_id": f"SRC{index}",
            "scene_id": scene_id, "translation": route, "status": "reviewed",
        }])

    old_root = builder.ROOT
    builder.ROOT = tmp_path
    try:
        translations, skipped_status, skipped_route = builder.load_translations(
            tmp_path / "translation/segments", set(builder.DEFAULT_STATUSES))
        assert skipped_status == 0
        assert skipped_route == 0
        included = {str(item["scene_id"]) for item in translations.values()}
        with pytest.raises(SystemExit) as error:
            builder.style_build_preflight(
                config, tmp_path / "translation/segments", included)
        assert "BLK0003: художественная вычитка не завершена" in str(error.value)
        assert "BLK0004: художественная вычитка не завершена" in str(error.value)
    finally:
        builder.ROOT = old_root


def test_release_reviewed_route_rejects_unknown_or_empty_route(tmp_path):
    root = Path(__file__).parents[2]
    builder = load_module(root / "game-tools/build_luca_release.py",
                          "luca_release_route_errors_test")
    config = make_project(tmp_path)
    old_root = builder.ROOT
    builder.ROOT = tmp_path
    try:
        route_by_scene = builder.load_scene_routes(config)
        with pytest.raises(SystemExit, match="неизвестный route"):
            builder.load_translations(
                tmp_path / "translation/segments", set(builder.DEFAULT_STATUSES),
                route_by_scene, {"BLK9999"})
        with pytest.raises(SystemExit, match="не включает reviewed-строк"):
            builder.load_translations(
                tmp_path / "translation/segments", {"playable"},
                route_by_scene, {"BLK0002"})
    finally:
        builder.ROOT = old_root


def test_style_audit_marks_review_issue_superseded_by_open_question(tmp_path):
    root = Path(__file__).parents[2]
    vnctl = load_module(root / "tools/vnctl.py", "vnctl_style_supersession_test")
    config = make_project(tmp_path)
    config["paths"]["review_ledger"] = "translation/review-ledger.jsonl"
    config["paths"]["questions"] = "translation/open-questions.jsonl"
    issue_id = "REV-SCN0001-01-I001"
    write_jsonl(tmp_path / "translation/open-questions.jsonl", [{
        "id": "OQ-1", "date": "2026-08-02", "kind": "terminology",
        "scene_id": "SCN0001", "segment_ids": ["SEG0"],
        "question": "Какая форма действует?", "provisional": "Новая форма",
        "status": "open",
    }])
    write_jsonl(tmp_path / "translation/review-ledger.jsonl", [
        {"schema_version": 1, "event": "ledger_initialized"},
        {"schema_version": 1, "event": "review_imported",
         "review_id": "REV-SCN0001-01", "scene_id": "SCN0001",
         "issues": [{"issue_id": issue_id, "severity": "minor",
                     "category": "terminology", "segment_ids": ["SEG0"],
                     "problem": "Старая форма.", "suggested_changes": []}]},
        {"schema_version": 1, "event": "review_resolved",
         "review_id": "REV-SCN0001-01", "scene_id": "SCN0001",
         "resolutions": [{"issue_id": issue_id, "disposition": "applied",
                          "reason": "Старое решение.", "changes": []}]},
        {"schema_version": 1, "event": "review_accepted",
         "review_id": "REV-SCN0001-01", "scene_id": "SCN0001"},
        {"schema_version": 1, "event": "review_issue_superseded",
         "review_id": "REV-SCN0001-01", "issue_id": issue_id,
         "question_id": "OQ-1", "actor": "vn-auditor",
         "reason": "Активный вопрос задаёт новый рабочий вариант."},
    ])
    assert vnctl.style_start(tmp_path, config, "BLK0002") == 0
    run_id = "STYLE-BLK0002-01"
    run = vnctl.style_runs(vnctl.load_style_events(tmp_path, config))[run_id]
    for window in run["windows"]:
        route_rows = vnctl.style_route_rows(tmp_path, config, "BLK0002")
        package_rows, editable = vnctl.style_window_rows(route_rows, window)
        patch = tmp_path / f"build/{window['window_id']}.jsonl"
        write_jsonl(patch, [{"__style_window__": {
            "run_id": run_id, "window_id": window["window_id"],
            "base_sha256": vnctl.style_package_hash(package_rows, editable),
        }}])
        assert vnctl.style_apply(
            tmp_path, config, run_id, window["window_id"], patch) == 0
        report = tmp_path / f"build/{window['window_id']}.md"
        report.write_text("VERDICT: ACCEPT\n", encoding="utf-8")
        assert vnctl.style_accept(
            tmp_path, config, run_id, window["window_id"], report, "reviewer") == 0

    package = vnctl.style_audit_package(tmp_path, config, run_id)
    assert issue_id in package
    assert '"state": "superseded"' in package
    assert '"superseded_by_question": "OQ-1"' in package
    assert "Активный вопрос задаёт новый рабочий вариант." in package


def test_agent_contracts_forbid_generalizing_concrete_images():
    root = Path(__file__).parents[2]
    stylist = (root / ".opencode/agent/vn-stylist.md").read_text(encoding="utf-8")
    translator = (root / ".opencode/agent/vn-translator.md").read_text(encoding="utf-8")
    reviewer = (root / ".opencode/agent/vn-reviewer.md").read_text(encoding="utf-8")
    for text in (stylist, translator, reviewer):
        assert "как тануки" in text
        assert "не по-лисьи" in text
    assert "заблокированными" in stylist
    assert "минимум `major`" in reviewer
    assert "Применение замечаний ревью" in stylist
    assert "review resolve" in stylist
    assert "бэнто" in stylist
    assert "братик" in stylist


def test_project_agents_use_gpt_and_have_required_execution_permissions():
    root = Path(__file__).parents[2]
    agent_dir = root / ".opencode/agent"
    names = (
        "vn-translator.md", "vn-translator-alt.md", "vn-reviewer.md",
        "vn-reviewer-alt.md", "vn-stylist.md", "vn-knowledge.md",
        "vn-auditor.md", "second-opinion.md",
    )
    agents = {name: (agent_dir / name).read_text(encoding="utf-8") for name in names}
    for text in agents.values():
        assert "model: fasday/gpt5_6_sol" in text
    for text in agents.values():
        assert "  bash:\n    '*': allow" in text
    stylist = agents["vn-stylist.md"]
    assert "  read:\n    '*': deny\n    build/**: allow" in stylist
    assert "  edit:\n    '*': deny\n    build/**: allow" in stylist


def test_translation_agents_keep_mandatory_read_sets():
    root = Path(__file__).parents[2]
    agent_dir = root / ".opencode/agent"
    translators = [
        (agent_dir / name).read_text(encoding="utf-8")
        for name in ("vn-translator.md", "vn-translator-alt.md")
    ]
    for text in translators:
        for required in (
                "`AGENTS.md`", "python tools/vnctl.py brief",
                "`docs/translation-spec.md`", "`docs/style-profile.yaml`",
                "`docs/glossary.yaml`", "`docs/characters/`", "рабочие пакеты"):
            assert required in text
        assert "не заменяет документы выше" in text

    reviewers = [
        (agent_dir / name).read_text(encoding="utf-8")
        for name in ("vn-reviewer.md", "vn-reviewer-alt.md")
    ]
    for text in reviewers:
        assert "steps: 120" in text
        assert "Не\nзагружай все выданные packages заранее" in text
        assert "один package-файл" in text
        assert "## Прочитать перед работой" in text
        for required in (
                "`docs/translation-spec.md`", "`docs/style-profile.yaml`",
                "`config/qa-rules.yaml`", "пакет контекста"):
            assert required in text
        assert "перечитывай отдельные `translation/segments/*.jsonl`" in text
        assert "Пакет не заменяет три документа выше" in text
        assert "Не перечитывай полную" not in text
