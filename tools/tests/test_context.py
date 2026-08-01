import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def load_vnctl():
    path = Path(__file__).parents[1] / "vnctl.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("vnctl_context", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_linked_decisions_only_returns_current_approved_items(tmp_path):
    vnctl = load_vnctl()
    db = tmp_path / "knowledge.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE decisions (payload_json TEXT NOT NULL)")
    rows = [
        {"id": "DEC-1", "segment_ids": ["SEG-1"], "status": "approved",
         "decision": "keep", "private_reason": "secret"},
        {"id": "DEC-2", "segment_ids": ["SEG-1"], "status": "proposed",
         "decision": "skip"},
        {"id": "DEC-3", "segment_ids": ["SEG-1"], "status": "approved",
         "decision": "old"},
        {"id": "DEC-4", "segment_ids": ["SEG-2"], "status": "approved",
         "decision": "new", "supersedes": "DEC-3"},
    ]
    con.executemany("INSERT INTO decisions VALUES (?)",
                    [(json.dumps(row),) for row in rows])
    con.commit()
    con.close()

    result = vnctl.linked_decisions(db, {"SEG-1"})

    assert [row["id"] for row in result] == ["DEC-1"]
    assert "private_reason" not in result[0]
