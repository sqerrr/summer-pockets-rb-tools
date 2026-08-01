import importlib.util
import json
import sys
from pathlib import Path

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


def make_project(tmp_path: Path):
    (tmp_path / "translation/segments").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "docs").mkdir()
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
            "translation": f"Фраза {index}.",
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
    write_jsonl(tmp_path / "docs/decisions.jsonl", [{
        "id": "DEC-1", "type": "terminology", "scope": "global",
        "status": "approved", "decision": "Сохранять бэнто и お兄ちゃん.",
    }])
    write_jsonl(tmp_path / "source/manifest.jsonl", [{
        "source_set_id": "SET", "catalog_path": "source/parsed/records.jsonl"
    }])
    write_jsonl(tmp_path / "source/parsed/records.jsonl", records)
    (tmp_path / "config/qa-rules.yaml").write_text(
        "allowed_flags:\n- needs_source_check\n", encoding="utf-8")
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

    run = vnctl.style_runs(vnctl.load_style_events(tmp_path, config))[run_id]
    route_rows = vnctl.style_route_rows(tmp_path, config, "BLK0002")
    package_rows, _ = vnctl.style_window_rows(route_rows, run["windows"][0])
    patch1 = tmp_path / "build/style-1.jsonl"
    write_jsonl(patch1, [
        {"__style_window__": {
            "run_id": run_id,
            "window_id": "W001",
            "base_sha256": vnctl.style_slice_hash(package_rows),
        }},
        {"id": "SEG0", "before": "Фраза 0.",
         "translation": "Новая фраза.", "reason": "Естественнее."},
    ])
    assert vnctl.style_check(tmp_path, config, run_id, "W001", patch1) == 0
    assert vnctl.style_apply(tmp_path, config, run_id, "W001", patch1) == 0
    changed = vnctl.read_jsonl(tmp_path / "translation/segments/SCN0001.jsonl")[0]
    assert changed["status"] == "draft"
    assert changed["status"] != "lqa"

    review_package = vnctl.style_review_package(tmp_path, config, run_id, "W001")
    assert "原文0" in review_package
    report1 = tmp_path / "build/review-1.md"
    report1.write_text("# Review\nVERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.style_accept(
        tmp_path, config, run_id, "W001", report1, "vn-reviewer") == 0

    package2 = vnctl.style_package(tmp_path, config, run_id)
    run = vnctl.style_runs(vnctl.load_style_events(tmp_path, config))[run_id]
    route_rows = vnctl.style_route_rows(tmp_path, config, "BLK0002")
    package_rows, _ = vnctl.style_window_rows(route_rows, run["windows"][1])
    patch2 = tmp_path / "build/style-2.jsonl"
    write_jsonl(patch2, [{"__style_window__": {
        "run_id": run_id,
        "window_id": "W002",
        "base_sha256": vnctl.style_slice_hash(package_rows),
    }}])
    assert "W002" in package2
    assert vnctl.style_apply(tmp_path, config, run_id, "W002", patch2) == 0
    report2 = tmp_path / "build/review-2.md"
    report2.write_text("# Review\nVERDICT: ACCEPT\n", encoding="utf-8")
    assert vnctl.style_accept(
        tmp_path, config, run_id, "W002", report2, "vn-reviewer") == 0

    audit_package = vnctl.style_audit_package(tmp_path, config, run_id)
    assert "Новая фраза." in audit_package
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
            package_rows, _ = vnctl.style_window_rows(route_rows, window)
            patch = tmp_path / f"build/{window_id}.jsonl"
            write_jsonl(patch, [{"__style_window__": {
                "run_id": run_id,
                "window_id": window_id,
                "base_sha256": vnctl.style_slice_hash(package_rows),
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
    for name, text in agents.items():
        if name != "vn-stylist.md":
            assert "  bash:\n    '*': allow" in text
    stylist = agents["vn-stylist.md"]
    assert "  bash:\n    '*': deny\n    '*vnctl.py*': allow" in stylist
    assert "  read:\n    '*': deny\n    build/**: allow" in stylist
    assert "  edit:\n    '*': deny\n    build/**: allow" in stylist
