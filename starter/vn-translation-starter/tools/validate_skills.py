#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".opencode" / "skills"


def main() -> int:
    errors: list[str] = []
    files = sorted(SKILL_ROOT.glob("*/SKILL.md"))
    if not files:
        errors.append("no skills found")
    for path in files:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
            continue
        try:
            _, raw, _ = text.split("---", 2)
            data = yaml.safe_load(raw)
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid frontmatter: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path.relative_to(ROOT)}: frontmatter must be a mapping")
            continue
        name = data.get("name")
        description = data.get("description")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", name):
            errors.append(f"{path.relative_to(ROOT)}: invalid skill name")
        if name != path.parent.name:
            errors.append(f"{path.relative_to(ROOT)}: name must match directory")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{path.relative_to(ROOT)}: description is required")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Validated {len(files)} skills: {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
