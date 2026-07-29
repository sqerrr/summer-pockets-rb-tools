from pathlib import Path
import importlib.util


def load_vnctl():
    path = Path(__file__).parents[1] / "vnctl.py"
    spec = importlib.util.spec_from_file_location("vnctl", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_safe_constraint_projection(tmp_path):
    vnctl = load_vnctl()
    (tmp_path / "private").mkdir()
    (tmp_path / "private/constraints.jsonl").write_text(
        '{"id":"H1","segment_ids":["S1"],"private_reason":"SECRET",'
        '"safe_rules":["Keep ambiguity"],"status":"active"}\n',
        encoding="utf-8",
    )
    cfg = {"paths": {"private_constraints": "private/constraints.jsonl"}}
    result = vnctl.safe_constraints(tmp_path, cfg, {"S1"})
    assert result == [{"id": "H1", "segment_ids": ["S1"], "safe_rules": ["Keep ambiguity"]}]
    assert "SECRET" not in repr(result)
