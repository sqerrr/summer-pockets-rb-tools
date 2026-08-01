import importlib.util
import json
import sys
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
    with pytest.raises(ValueError, match="every issue needs a disposition"):
        vnctl.review_resolve(tmp_path, config, review_id, incomplete, "vn-stylist")

    fix_package = vnctl.review_resolution_package(tmp_path, config, review_id)
    assert "Применение замечаний ревью" in fix_package
    assert "vn-stylist" in fix_package
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

    recheck = vnctl.review_recheck_package(tmp_path, config, review_id)
    assert "Перепроверка применённых замечаний" in recheck
    current_hash = vnctl.scene_review_hash(vnctl.read_jsonl(
        tmp_path / "translation/segments/SCN0001.jsonl"))
    verdict = tmp_path / "build/verdict.jsonl"
    write_jsonl(verdict, [{"review_id": review_id, "scene_sha256": current_hash,
                           "verdict": "accept", "open_issue_ids": []}])
    with pytest.raises(ValueError, match="unresolved user escalations"):
        vnctl.review_close(tmp_path, config, review_id, verdict, "vn-reviewer")

    settled = tmp_path / "build/settled.jsonl"
    write_jsonl(settled, [
        {"issue_id": f"{review_id}-I001", "disposition": "applied",
         "reason": "Уже применено в текущем тексте.", "changes": []},
        {"issue_id": f"{review_id}-I002", "disposition": "rejected",
         "reason": "Пользователь оставил текущий регистр.", "changes": []},
    ])
    assert vnctl.review_resolve(
        tmp_path, config, review_id, settled, "vn-stylist") == 0
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
