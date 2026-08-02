from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


STARTER_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    target = tmp_path / "VN Starter With Spaces"
    shutil.copytree(
        STARTER_ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".pytest_cache", "__pycache__", "*.pyc", "project.yaml", "*.db"
        ),
    )
    return target


def run(project: Path, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, *args],
        cwd=project,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == expected, (
        f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def bootstrap(project: Path) -> None:
    run(
        project,
        "tools/vnctl.py",
        "init",
        "--title",
        "Synthetic Project",
        "--source-language",
        "source",
        "--source-language",
        "reference",
        "--target-language",
        "target",
    )
    run(project, "adapters/mock.py", "seed", "source/records.jsonl")
    run(project, "adapters/mock.py", "roundtrip", "source/records.jsonl", "build/mock")
    run(project, "tools/vnctl.py", "ingest")
