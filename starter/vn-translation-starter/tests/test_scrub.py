from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_archive_contains_no_current_project_data_or_binaries():
    denylist = [
        "Summer" + " Pockets",
        "REFLECTION" + " BLUE",
        "steam" + "_luca",
        "steam" + "-luca",
        "legacy" + "_siglus",
        "fas" + "day/",
        "A:" + "\\Projects",
        "HA" + "IRI",
        "SHI" + "ROHA",
        "KA" + "MOME",
        "OQ-" + "SCN",
        "DEC-" + "00",
        "FND-" + "00",
    ]
    forbidden_suffixes = {
        ".pak",
        ".pck",
        ".arc",
        ".xp3",
        ".exe",
        ".dll",
        ".ttf",
        ".otf",
        ".db",
        ".png",
        ".jpg",
        ".jpeg",
        ".ogg",
        ".wav",
        ".mp4",
        ".pyc",
    }
    credential_patterns = [
        re.compile("sk" + r"-[A-Za-z0-9]{16,}"),
        re.compile("api" + r"Key\s*[:=]\s*['\"][^'\"]+"),
        re.compile("pass" + r"word\s*[:=]\s*['\"][^'\"]+", re.IGNORECASE),
    ]
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        assert path.suffix.lower() not in forbidden_suffixes, path
        if path.suffix.lower() in {
            ".md",
            ".py",
            ".yaml",
            ".yml",
            ".json",
            ".jsonl",
            ".txt",
        }:
            text = path.read_text(encoding="utf-8")
            for token in denylist:
                assert token not in text, f"{token!r} found in {path}"
            for pattern in credential_patterns:
                assert not pattern.search(text), f"credential pattern found in {path}"


def test_agents_inherit_user_model_and_restrict_network():
    for path in (ROOT / ".opencode" / "agent").glob("*.md"):
        text = path.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        assert "model:" not in frontmatter
        assert "webfetch: deny" in frontmatter
        assert "websearch: deny" in frontmatter
        assert "read:\n    '*': deny" in frontmatter
        assert "edit:\n    '*': deny" in frontmatter
