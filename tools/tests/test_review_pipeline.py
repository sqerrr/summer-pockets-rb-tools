import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def load_vnctl():
    path = Path(__file__).parents[1] / "vnctl.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("vnctl_review_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_project(tmp_path: Path):
    (tmp_path / "translation/segments").mkdir(parents=True)
    (tmp_path / "source/parsed").mkdir(parents=True)
    (tmp_path / "docs/characters").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "database").mkdir()
    (tmp_path / "docs/translation-spec.md").write_text("# Spec\n", encoding="utf-8")
    (tmp_path / "docs/progress.yaml").write_text("mode: strict\n", encoding="utf-8")
    (tmp_path / "docs/scene-summaries.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "config/qa-rules.yaml").write_text(
        "allowed_statuses:\n- todo\n- draft\n- reviewed\n"
        "allowed_flags:\n- needs_source_check\n- needs_term_decision\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/glossary.yaml").write_text(
        "- id: GLO-1\n"
        "  source: 弁当\n"
        "  preferred_ru: бэнто\n"
        "  status: approved\n"
        "  note: Не заменять обедом с собой.\n",
        encoding="utf-8",
    )
    write_jsonl(tmp_path / "docs/decisions.jsonl", [{
        "id": "DEC-1", "type": "terminology", "scope": "global",
        "status": "approved", "decision": "Сохранять бэнто.",
    }])
    write_jsonl(tmp_path / "docs/project/findings.jsonl", [
        {"id": "FND-1", "status": "verified", "area": "content", "kind": "limitation",
         "title": "Конкретику нельзя обобщать", "statement": "Сохранять предмет.",
         "date": "2026-08-01", "method": "test"},
        {"id": "FND-2", "status": "assumed", "area": "content", "kind": "limitation",
         "title": "Причина не доказана", "statement": "Не считать фактом.",
         "date": "2026-08-01", "evidence": "test"},
    ])
    write_jsonl(tmp_path / "translation/open-questions.jsonl", [{
        "id": "OQ-1", "date": "2026-08-01", "kind": "realia",
        "scene_id": "SCN0001", "segment_ids": ["SEG1"],
        "question": "Как передать 弁当?", "provisional": "бэнто", "status": "open",
    }])
    write_jsonl(tmp_path / "translation/scenes.jsonl", [{
        "scene_id": "SCN0001", "file_id": "S1", "route": "BLK0002",
    }])
    write_jsonl(tmp_path / "translation/speakers.jsonl", [{
        "id": "SPK-1", "source": "話者", "preferred_ru": "Говорящий",
    }])
    write_jsonl(tmp_path / "translation/review-ledger.jsonl", [{
        "schema_version": 1, "event": "ledger_initialized",
    }])
    write_jsonl(tmp_path / "source/manifest.jsonl", [{
        "source_set_id": "SET", "catalog_path": "source/parsed/records.jsonl",
    }])
    records = [
        {"source_id": "SRC1", "slots": [
            {"language": "ja", "text": "弁当"},
            {"language": "en", "text": "lunch"},
            {"language": "zh-Hans", "text": "便当"},
        ]},
        {"source_id": "SRC2", "slots": [
            {"language": "ja", "text": "$S(044,1)原文$S"},
            {"language": "en", "text": "source"},
            {"language": "zh-Hans", "text": "原文"},
        ]},
    ]
    write_jsonl(tmp_path / "source/parsed/records.jsonl", records)
    rows = [
        {"id": "SEG1", "source_set_id": "SET", "source_id": "SRC1",
         "source_hash": "sha256:" + "0" * 64, "file_id": "S1",
         "scene_id": "SCN0001", "order": 1, "speaker": "話者",
         "translation": "Обед с собой.", "status": "draft",
         "flags": ["needs_term_decision"]},
        {"id": "SEG2", "source_set_id": "SET", "source_id": "SRC2",
         "source_hash": "sha256:" + "1" * 64, "file_id": "S1",
         "scene_id": "SCN0001", "order": 2, "speaker": None,
         "translation": "$S(044,1)Фраза.$S", "status": "draft", "flags": []},
    ]
    write_jsonl(tmp_path / "translation/segments/SCN0001.jsonl", rows)
    config = {
        "paths": {
            "segments": "translation/segments",
            "scenes": "translation/scenes.jsonl",
            "glossary": "docs/glossary.yaml",
            "decisions": "docs/decisions.jsonl",
            "findings": "docs/project/findings.jsonl",
            "questions": "translation/open-questions.jsonl",
            "review_ledger": "translation/review-ledger.jsonl",
            "summaries": "docs/scene-summaries.jsonl",
            "characters": "docs/characters",
            "source_manifest": "source/manifest.jsonl",
            "database": "database/knowledge.db",
        },
        "source_sets": {"test": {"id": "SET", "working_source_language": "ja"}},
        "workflow": {"context_previous_segments": 0, "context_next_segments": 0,
                     "internal_examples_limit": 0},
    }
    return config


def test_review_pipeline_tracks_every_issue_and_only_close_grants_reviewed(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    assert vnctl.index_project(tmp_path, config) == 0

    package = vnctl.review_package(tmp_path, config, "SCN0001")
    for heading in (
        "ОБЯЗАТЕЛЬНЫЕ ЗНАНИЯ", "Активные находки", "Глоссарий: формы и ловушки",
        "Открытые вопросы и рабочие варианты", "Действующие флаги",
        "Ранее принятые замечания ревьюеров", "Защищённая разметка",
    ):
        assert heading in package
    assert "Не заменять обедом с собой" in package
    assert "[verified]" in package
    assert "[assumed]" in package
    assert "needs_term_decision" in package
    assert "$S(044,1)" in package
    assert "## Глобальная спецификация" in package
    assert "## Текущий прогресс" in package

    review_id = "REV-SCN0001-01"
    base_hash = vnctl.scene_review_hash(vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl"))
    report = tmp_path / "build/review.jsonl"
    write_jsonl(report, [
        {"__review__": {"review_id": review_id, "scene_id": "SCN0001",
                         "base_sha256": base_hash}},
        {"issue_id": f"{review_id}-I001", "severity": "major",
         "category": "terminology", "segment_ids": ["SEG1"],
         "problem": "Закреплённая реалия локализована.",
         "suggested_changes": [{"id": "SEG1", "translation": "Бэнто."}]},
        {"issue_id": f"{review_id}-I002", "severity": "preference",
         "category": "style", "segment_ids": ["SEG2"],
         "problem": "Можно переставить слово.", "suggested_changes": []},
    ])
    assert vnctl.review_import(
        tmp_path, config, "SCN0001", report, "vn-reviewer") == 0

    incomplete = tmp_path / "build/incomplete.jsonl"
    write_jsonl(incomplete, [{
        "issue_id": f"{review_id}-I001", "disposition": "applied",
        "reason": "Глоссарий.",
        "changes": [{"id": "SEG1", "before": "Обед с собой.",
                     "translation": "Бэнто.", "flags": []}],
    }])
    with pytest.raises(ValueError, match="every open issue needs a disposition"):
        vnctl.review_resolve(tmp_path, config, review_id, incomplete, "vn-stylist")

    fix_package = vnctl.review_resolution_package(tmp_path, config, review_id)
    assert "Применение замечаний ревью" in fix_package
    assert "vn-stylist" in fix_package
    assert "## Глобальная спецификация" in fix_package
    assert "$S(044,1)原文$S" in fix_package
    resolutions = tmp_path / "build/resolutions.jsonl"
    write_jsonl(resolutions, [
        {"issue_id": f"{review_id}-I001", "disposition": "applied",
         "reason": "Применена утверждённая форма.",
         "changes": [{"id": "SEG1", "before": "Обед с собой.",
                      "translation": "Бэнто.", "flags": []}]},
        {"issue_id": f"{review_id}-I002", "disposition": "rejected",
         "reason": "Нужно решение по общему регистру.", "changes": [],
         "escalation": {"question": "Менять общий регистр?",
                        "provisional": "Оставить текущий."}},
    ])
    assert vnctl.review_resolve(
        tmp_path, config, review_id, resolutions, "vn-stylist") == 0
    assert {row["status"] for row in vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")} == {"draft"}

    with pytest.raises(ValueError, match="awaiting resolution"):
        vnctl.review_recheck_package(tmp_path, config, review_id)
    current_hash = vnctl.scene_review_hash(vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl"))
    verdict = tmp_path / "build/verdict.jsonl"
    write_jsonl(verdict, [{"review_id": review_id, "scene_sha256": current_hash,
                           "verdict": "accept", "open_issue_ids": []}])
    with pytest.raises(ValueError, match="unresolved user escalations"):
        vnctl.review_close(tmp_path, config, review_id, verdict, "vn-reviewer")

    settled = tmp_path / "build/settled.jsonl"
    write_jsonl(settled, [{
        "issue_id": f"{review_id}-I002", "disposition": "rejected",
        "reason": "Пользователь оставил текущий регистр.", "changes": [],
    }])
    assert vnctl.review_resolve(
        tmp_path, config, review_id, settled, "vn-stylist") == 0
    recheck = vnctl.review_recheck_package(tmp_path, config, review_id)
    assert "Перепроверка применённых замечаний" in recheck
    assert "## Глобальная спецификация" in recheck
    assert "$S(044,1)原文$S" in recheck
    assert "Бэнто." in recheck
    assert vnctl.indexed_scene_review_hash(
        tmp_path, config, "SCN0001") == current_hash
    assert vnctl.review_close(
        tmp_path, config, review_id, verdict, "vn-reviewer") == 0
    assert {row["status"] for row in vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")} == {"reviewed"}

    forbidden = tmp_path / "build/forbidden.jsonl"
    write_jsonl(forbidden, [{"id": "SEG1", "status": "reviewed"}])
    assert vnctl.apply_translation(tmp_path, config, "SCN0001", forbidden) == 1


def test_review_ledger_validation_accepts_complete_state(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    errors, warnings = vnctl.validate_review_ledger(tmp_path, config)
    assert errors == []
    assert warnings == []


def test_untouched_imported_review_can_be_invalidated(tmp_path, capsys):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    assert vnctl.index_project(tmp_path, config) == 0
    review_id = "REV-SCN0001-01"
    base_hash = vnctl.scene_review_hash(vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl"))
    report = tmp_path / "build/review.jsonl"
    write_jsonl(report, [
        {"__review__": {"review_id": review_id, "scene_id": "SCN0001",
                         "base_sha256": base_hash}},
        {"issue_id": f"{review_id}-I001", "severity": "major",
         "category": "accuracy", "segment_ids": ["SEG1"],
         "problem": "Неверный смысл.", "suggested_changes": []},
    ])
    assert vnctl.review_import(
        tmp_path, config, "SCN0001", report, "vn-reviewer") == 0
    assert vnctl.review_invalidate(
        tmp_path, config, review_id, "orchestrator",
        "Reviewer contract was incomplete.") == 0

    events = vnctl.load_review_events(tmp_path, config)
    run = vnctl.review_runs(events)[review_id]
    assert events[-1]["event"] == "review_invalidated"
    assert run["invalidated"]["reason"] == "Reviewer contract was incomplete."
    assert vnctl.latest_review_for_scene(tmp_path, config, "SCN0001") is None
    assert vnctl.next_review_id(tmp_path, config, "SCN0001") == "REV-SCN0001-02"
    with pytest.raises(ValueError, match="invalidated"):
        vnctl.review_resolution_package(tmp_path, config, review_id)
    with pytest.raises(ValueError, match="already invalidated"):
        vnctl.review_invalidate(
            tmp_path, config, review_id, "orchestrator", "Again.")
    errors, warnings = vnctl.validate_review_ledger(tmp_path, config)
    assert errors == []
    assert warnings == []
    assert vnctl.work_queue(tmp_path, config) == 0
    assert "review initial SCN0001 (2)" in capsys.readouterr().out


def test_revise_verdict_has_one_recheck_then_finalize_or_wait(tmp_path, capsys):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    config["workflow"]["review_issue_context_segments"] = 0
    assert vnctl.index_project(tmp_path, config) == 0
    review_id = "REV-SCN0001-01"
    base_hash = vnctl.scene_review_hash(vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl"))
    report = tmp_path / "build/review.jsonl"
    write_jsonl(report, [
        {"__review__": {"review_id": review_id, "scene_id": "SCN0001",
                         "base_sha256": base_hash}},
        {"issue_id": f"{review_id}-I001", "severity": "minor",
         "category": "language", "segment_ids": ["SEG1"],
         "problem": "Первая проблема.", "suggested_changes": []},
        {"issue_id": f"{review_id}-I002", "severity": "minor",
         "category": "language", "segment_ids": ["SEG2"],
         "problem": "Вторая проблема.", "suggested_changes": []},
    ])
    assert vnctl.review_import(
        tmp_path, config, "SCN0001", report, "vn-reviewer") == 0
    initial = tmp_path / "build/resolutions.jsonl"
    write_jsonl(initial, [
        {"issue_id": f"{review_id}-I001", "disposition": "applied",
         "reason": "Принято.", "changes": []},
        {"issue_id": f"{review_id}-I002", "disposition": "applied",
         "reason": "Принято.", "changes": []},
    ])
    assert vnctl.review_resolve(
        tmp_path, config, review_id, initial, "vn-stylist") == 0
    verdict = tmp_path / "build/verdict-revise.jsonl"
    write_jsonl(verdict, [{
        "review_id": review_id, "scene_sha256": base_hash,
        "verdict": "revise", "open_issue_ids": [f"{review_id}-I001"],
    }])
    assert vnctl.review_close(
        tmp_path, config, review_id, verdict, "vn-reviewer") == 0
    run = vnctl.review_runs(vnctl.load_review_events(tmp_path, config))[review_id]
    assert vnctl.review_open_issue_ids(run) == {f"{review_id}-I001"}

    delta_package = vnctl.review_resolution_package(tmp_path, config, review_id)
    assert f"{review_id}-I001" in delta_package
    assert f"{review_id}-I002" not in delta_package
    assert "弁当" in delta_package
    assert "$S(044,1)原文$S" not in delta_package
    assert "## Глобальная спецификация" not in delta_package

    repeated_full = tmp_path / "build/repeated-full.jsonl"
    write_jsonl(repeated_full, [
        {"issue_id": f"{review_id}-I001", "disposition": "applied",
         "reason": "Исправлено.", "changes": []},
        {"issue_id": f"{review_id}-I002", "disposition": "applied",
         "reason": "Лишний повтор.", "changes": []},
    ])
    with pytest.raises(ValueError, match="extra"):
        vnctl.review_resolve(
            tmp_path, config, review_id, repeated_full, "vn-stylist")

    delta = tmp_path / "build/delta.jsonl"
    write_jsonl(delta, [{
        "issue_id": f"{review_id}-I001", "disposition": "applied",
        "reason": "Исправлено.", "changes": [],
    }])
    assert vnctl.review_resolve(
        tmp_path, config, review_id, delta, "vn-stylist") == 0
    with pytest.raises(ValueError, match="single recheck"):
        vnctl.review_recheck_package(tmp_path, config, review_id)

    assert vnctl.review_block(
        tmp_path, config, review_id, [f"{review_id}-I001"],
        "orchestrator", "Final text conflicts with a validator.") == 0
    blocked = vnctl.review_runs(vnctl.load_review_events(tmp_path, config))[review_id]
    assert vnctl.review_open_issue_ids(blocked) == {f"{review_id}-I001"}
    with pytest.raises(ValueError, match="blocked"):
        vnctl.review_finalize(tmp_path, config, review_id, "orchestrator-finalize")
    assert vnctl.work_queue(tmp_path, config) == 0
    assert "review wait  SCN0001" in capsys.readouterr().out

    settled_after_block = tmp_path / "build/settled-after-block.jsonl"
    write_jsonl(settled_after_block, [{
        "issue_id": f"{review_id}-I001", "disposition": "rejected",
        "reason": "Конфликт разрешён инструментально.", "changes": [],
    }])
    assert vnctl.review_resolve(
        tmp_path, config, review_id, settled_after_block, "orchestrator") == 0
    assert vnctl.review_finalize(
        tmp_path, config, review_id, "orchestrator-finalize") == 0
    assert {row["status"] for row in vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")} == {"reviewed"}
    errors, warnings = vnctl.validate_review_ledger(tmp_path, config)
    assert errors == []
    assert warnings == []


def test_scene_work_packages_remain_independent_for_shared_agent_call(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    scene_one = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")
    for row in scene_one:
        row["translation"] = ""
        row["status"] = "todo"
    write_jsonl(tmp_path / "translation/segments/SCN0001.jsonl", scene_one)
    write_jsonl(tmp_path / "translation/segments/SCN0002.jsonl", [{
        **scene_one[0], "id": "SEG3", "scene_id": "SCN0002", "order": 1,
    }])
    write_jsonl(tmp_path / "translation/scenes.jsonl", [
        {"scene_id": "SCN0001", "file_id": "S1", "route": "BLK0002"},
        {"scene_id": "SCN0002", "file_id": "S1", "route": "BLK0002"},
    ])
    assert vnctl.index_project(tmp_path, config) == 0

    first = vnctl.work_next(tmp_path, config, "SCN0001", 0, None)
    second = vnctl.work_next(tmp_path, config, "SCN0002", 0, None)
    assert "# Порция: SCN0001" in first
    assert "build/patch-SCN0001.jsonl" in first
    assert "build/patch-SCN0002.jsonl" not in first
    assert "# Порция: SCN0002" in second
    assert "build/patch-SCN0002.jsonl" in second
    assert "build/patch-SCN0001.jsonl" not in second


def test_review_packages_remain_independent_for_shared_agent_call(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    scene_one = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")
    write_jsonl(tmp_path / "translation/segments/SCN0002.jsonl", [{
        **scene_one[0], "id": "SEG3", "scene_id": "SCN0002", "order": 1,
    }])
    write_jsonl(tmp_path / "translation/scenes.jsonl", [
        {"scene_id": "SCN0001", "file_id": "S1", "route": "BLK0002"},
        {"scene_id": "SCN0002", "file_id": "S1", "route": "BLK0002"},
    ])
    assert vnctl.index_project(tmp_path, config) == 0

    first = vnctl.review_package(tmp_path, config, "SCN0001")
    second = vnctl.review_package(tmp_path, config, "SCN0002")
    assert "# Контекст сцены SCN0001" in first
    assert "# Контекст сцены SCN0002" not in first
    assert "# Контекст сцены SCN0002" in second
    assert "# Контекст сцены SCN0001" not in second
    assert "build/review-REV-SCN0001-01.jsonl" in first
    assert "build/review-REV-SCN0002-01.jsonl" in second


def test_cli_multi_output_writes_separate_files_without_wrapper(tmp_path, monkeypatch):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    config["workflow"].update({
        "translation_dispatch_max_segments": 2,
        "review_initial_dispatch_max_segments": 2,
    })
    (tmp_path / "config/project.yaml").write_text(
        vnctl.yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    scene_one = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")
    write_jsonl(tmp_path / "translation/segments/SCN0002.jsonl", [{
        **scene_one[0], "id": "SEG3", "scene_id": "SCN0002", "order": 1,
    }])
    write_jsonl(tmp_path / "translation/scenes.jsonl", [
        {"scene_id": "SCN0001", "file_id": "S1", "route": "BLK0002"},
        {"scene_id": "SCN0002", "file_id": "S1", "route": "BLK0002"},
    ])
    assert vnctl.index_project(tmp_path, config) == 0

    monkeypatch.setattr(sys, "argv", [
        "vnctl.py", "--root", str(tmp_path), "review", "package",
        "SCN0001", "SCN0002", "--output-dir", "build/reviews",
    ])
    assert vnctl.main() == 2
    monkeypatch.setattr(sys, "argv", [
        "vnctl.py", "--root", str(tmp_path), "review", "package",
        "SCN0001", "SCN0002", "--output-dir", "build/reviews",
        "--allow-oversize",
    ])
    assert vnctl.main() == 0
    review_files = sorted(
        path.name for path in (tmp_path / "build/reviews").iterdir())
    assert review_files == [
        "review-package-SCN0001.md", "review-package-SCN0002.md"]

    for scene_id in ("SCN0001", "SCN0002"):
        rows = vnctl.read_jsonl(
            tmp_path / f"translation/segments/{scene_id}.jsonl")
        for row in rows:
            row["translation"] = ""
            row["status"] = "todo"
        write_jsonl(tmp_path / f"translation/segments/{scene_id}.jsonl", rows)
    assert vnctl.index_project(tmp_path, config) == 0

    monkeypatch.setattr(sys, "argv", [
        "vnctl.py", "--root", str(tmp_path), "work", "next",
        "SCN0001", "SCN0002", "--output-dir", "build/work",
    ])
    assert vnctl.main() == 2
    monkeypatch.setattr(sys, "argv", [
        "vnctl.py", "--root", str(tmp_path), "work", "next",
        "SCN0001", "SCN0002", "--output-dir", "build/work",
        "--allow-oversize",
    ])
    assert vnctl.main() == 0
    work_files = sorted(path.name for path in (tmp_path / "build/work").iterdir())
    assert work_files == ["work-SCN0001.md", "work-SCN0002.md"]


def test_dispatch_review_budget_counts_issues_and_resolutions():
    vnctl = load_vnctl()
    runs = {
        "REV-1": {
            "issues": [{"issue_id": "I1"}, {"issue_id": "I2"}],
            "resolution": None,
        },
        "REV-2": {
            "issues": [{"issue_id": "I3"}],
            "resolution": None,
        },
    }
    assert vnctl.review_dispatch_workload(runs, ["REV-1", "REV-2"], "fix") == 3
    with pytest.raises(ValueError, match="configured limit is 2"):
        vnctl.enforce_dispatch_budget("review fix", 2, 3, 2, "issues", False)

    for review_id, run in runs.items():
        resolutions = [{"issue_id": issue["issue_id"], "disposition": "applied"}
                       for issue in run["issues"]]
        run.update({
            "resolution": {"resolutions": resolutions},
            "effective_resolutions": {
                row["issue_id"]: row for row in resolutions
            },
        })
    assert vnctl.review_dispatch_workload(
        runs, ["REV-1", "REV-2"], "recheck") == 3


def test_question_source_terms_select_reusable_provisional(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    write_jsonl(tmp_path / "translation/open-questions.jsonl", [{
        "id": "OQ-OLD", "date": "2026-08-01", "kind": "terminology",
        "scene_id": "SCN9999", "segment_ids": [],
        "source_terms": ["弁当"], "question": "Как передавать 弁当?",
        "provisional": "бэнто", "status": "open",
    }])

    selected = vnctl.related_questions(
        tmp_path, config, {"SCN0001"}, {"SEG1"}, [], "今日は弁当を食べる")
    assert [row["id"] for row in selected] == ["OQ-OLD"]
    assert vnctl.related_questions(
        tmp_path, config, {"SCN0001"}, {"SEG1"}, [], "別の食べ物") == []
    assert vnctl.questions(tmp_path, config) == 0


def test_accepted_review_issue_can_be_superseded_by_open_question(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    review_id = "REV-SCN0001-01"
    issue_id = f"{review_id}-I001"
    scene_path = tmp_path / "translation/segments/SCN0001.jsonl"
    questions_path = tmp_path / "translation/open-questions.jsonl"
    scene_before = scene_path.read_bytes()
    questions_before = questions_path.read_bytes()
    base_hash = vnctl.scene_review_hash(vnctl.read_jsonl(scene_path))
    vnctl.append_review_event(tmp_path, config, {
        "schema_version": 1, "event": "review_imported",
        "review_id": review_id, "scene_id": "SCN0001",
        "issues": [{
            "issue_id": issue_id, "severity": "minor", "category": "terminology",
            "segment_ids": ["SEG1"], "problem": "Историческая форма.",
            "suggested_changes": [],
        }],
    })
    vnctl.append_review_event(tmp_path, config, {
        "schema_version": 1, "event": "review_resolved",
        "review_id": review_id, "scene_id": "SCN0001",
        "result_sha256": base_hash,
        "resolutions": [{
            "issue_id": issue_id, "disposition": "applied",
            "reason": "Старое решение.", "changes": [],
        }],
    })
    vnctl.append_review_event(tmp_path, config, {
        "schema_version": 1, "event": "review_accepted",
        "review_id": review_id, "scene_id": "SCN0001", "scene_sha256": base_hash,
    })

    assert vnctl.review_issue_supersede(
        tmp_path, config, issue_id, "OQ-1", "vn-auditor",
        "Активный вопрос задаёт более новый рабочий вариант.") == 0
    assert scene_path.read_bytes() == scene_before
    assert questions_path.read_bytes() == questions_before
    run = vnctl.review_runs(vnctl.load_review_events(tmp_path, config))[review_id]
    assert run["accepted"]
    assert run["superseded_issues"][issue_id]["question_id"] == "OQ-1"
    projected = vnctl.prior_review_issues(tmp_path, config, {"SEG1"})
    assert projected[0]["state"] == "superseded"
    assert projected[0]["superseded_by_question"] == "OQ-1"
    errors, warnings = vnctl.validate_review_ledger(tmp_path, config)
    assert errors == []
    assert warnings == []
    with pytest.raises(ValueError, match="already superseded"):
        vnctl.review_issue_supersede(
            tmp_path, config, issue_id, "OQ-1", "vn-auditor", "Повтор.")


def test_translation_patch_must_cover_expected_batch_before_write(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    assert vnctl.index_project(tmp_path, config) == 0

    scene_path = tmp_path / "translation/segments/SCN0001.jsonl"
    before = scene_path.read_bytes()
    incomplete = tmp_path / "build/incomplete-translation.jsonl"
    write_jsonl(incomplete, [{
        "id": "SEG1", "translation": "Бэнто.", "status": "draft", "flags": [],
    }])

    assert vnctl.work_check(
        tmp_path, config, "SCN0001", incomplete, start=1, count=2) == 1
    assert vnctl.apply_translation(
        tmp_path, config, "SCN0001", incomplete, start=1, count=2) == 1
    assert scene_path.read_bytes() == before

    complete = tmp_path / "build/complete-translation.jsonl"
    write_jsonl(complete, [
        {"id": "SEG1", "translation": "Бэнто.", "status": "draft", "flags": []},
        {"id": "SEG2", "translation": "$S(044,1)Фраза.$S",
         "status": "draft", "flags": []},
    ])
    assert vnctl.work_check(
        tmp_path, config, "SCN0001", complete, start=1, count=2) == 0
    assert vnctl.apply_translation(
        tmp_path, config, "SCN0001", complete, start=1, count=2) == 0
    assert [row["translation"] for row in vnctl.read_jsonl(scene_path)] == [
        "Бэнто.", "$S(044,1)Фраза.$S",
    ]


def test_glossary_link_carries_cross_scene_question(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    (tmp_path / "docs/glossary.yaml").write_text(
        "- id: GLO-REMOTE\n"
        "  type: realia\n"
        "  source: 別名\n"
        "  preferred_ru: Рабочая форма\n"
        "  status: provisional\n"
        "  open_questions:\n"
        "  - OQ-REMOTE\n",
        encoding="utf-8",
    )
    write_jsonl(tmp_path / "translation/open-questions.jsonl", [{
        "id": "OQ-REMOTE", "date": "2026-08-02", "kind": "terminology",
        "scene_id": "SCN9999", "segment_ids": ["OTHER"],
        "question": "Как передать термин?", "provisional": "Рабочая форма",
        "status": "open",
    }])

    glossary = vnctl.glossary_for_scene(tmp_path, config, "Здесь встречается 別名")
    related = vnctl.related_questions(
        tmp_path, config, {"SCN0001"}, {"SEG1"}, glossary)

    assert [row["id"] for row in related] == ["OQ-REMOTE"]


def test_project_oneesan_question_has_structural_glossary_link():
    vnctl = load_vnctl()
    root = Path(__file__).parents[2]
    config = vnctl.load_config(root)

    glossary = vnctl.glossary_for_scene(root, config, "おねーさん")
    related = vnctl.related_questions(
        root, config, {"SCN0045"}, set(), glossary)

    assert "OQ-SCN0027-02" in {row["id"] for row in related}


def test_project_kakigori_question_has_structural_glossary_link():
    vnctl = load_vnctl()
    root = Path(__file__).parents[2]
    config = vnctl.load_config(root)

    glossary = vnctl.glossary_for_scene(root, config, "かき氷")
    related = vnctl.related_questions(
        root, config, {"SCN0252"}, set(), glossary)

    assert "OQ-SCN0015-01" in {row["id"] for row in related}


def test_review_ledger_serializes_concurrent_events(tmp_path):
    vnctl = load_vnctl()
    config = make_project(tmp_path)

    def append(index):
        vnctl.append_review_event(tmp_path, config, {
            "schema_version": 1,
            "event": "review_imported",
            "review_id": f"REV-SCN0001-{index:02d}",
            "scene_id": "SCN0001",
        })

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(1, 17)))

    events = vnctl.load_review_events(tmp_path, config)
    assert len(events) == 17
    assert len({event.get("review_id") for event in events[1:]}) == 16


def test_review_close_rolls_back_and_recovers_interrupted_ledger_write(tmp_path, monkeypatch):
    vnctl = load_vnctl()
    config = make_project(tmp_path)
    assert vnctl.index_project(tmp_path, config) == 0
    review_id = "REV-SCN0001-01"
    base_hash = vnctl.scene_review_hash(vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl"))
    report = tmp_path / "build/review.jsonl"
    write_jsonl(report, [
        {"__review__": {"review_id": review_id, "scene_id": "SCN0001",
                         "base_sha256": base_hash}},
        {"issue_id": f"{review_id}-I001", "severity": "minor",
         "category": "language", "segment_ids": ["SEG1"],
         "problem": "Проверка.", "suggested_changes": []},
    ])
    assert vnctl.review_import(
        tmp_path, config, "SCN0001", report, "vn-reviewer") == 0
    resolutions = tmp_path / "build/resolutions.jsonl"
    write_jsonl(resolutions, [{
        "issue_id": f"{review_id}-I001", "disposition": "applied",
        "reason": "Текст уже корректен.", "changes": [],
    }])
    assert vnctl.review_resolve(
        tmp_path, config, review_id, resolutions, "vn-stylist") == 0
    verdict = tmp_path / "build/verdict.jsonl"
    write_jsonl(verdict, [{
        "review_id": review_id, "scene_sha256": base_hash,
        "verdict": "accept", "open_issue_ids": [],
    }])

    real_append = vnctl.append_review_event
    monkeypatch.setattr(vnctl, "append_review_event", lambda *args: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(OSError, match="busy"):
        vnctl.review_close(tmp_path, config, review_id, verdict, "vn-reviewer")
    assert {row["status"] for row in vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl")} == {"draft"}

    rows = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")
    for row in rows:
        row["status"] = "reviewed"
    write_jsonl(tmp_path / "translation/segments/SCN0001.jsonl", rows)
    monkeypatch.setattr(vnctl, "append_review_event", real_append)
    assert vnctl.review_close(
        tmp_path, config, review_id, verdict, "vn-reviewer") == 0
    assert vnctl.review_runs(vnctl.load_review_events(
        tmp_path, config))[review_id]["accepted"]


def test_markup_contract_preserves_wait_token_in_order():
    vnctl = load_vnctl()
    assert vnctl.markup_contract("選択肢A$d$w選択肢B")["preserve_exact"] == ["$d", "$w"]


def test_markup_contract_preserves_emphasis_wrappers():
    vnctl = load_vnctl()
    contract = vnctl.markup_contract("知りませんか？　$[$bって$]")
    assert contract["preserve_exact"] == ["$[$b", "$]"]
    assert contract["remove_ruby_keep_base"] == []
