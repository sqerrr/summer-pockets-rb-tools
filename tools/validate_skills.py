#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".agents" / "skills"
errors = []
for directory in sorted(SKILLS.iterdir()):
    if not directory.is_dir():
        continue
    path = directory / "SKILL.md"
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        errors.append(f"{path}: missing YAML frontmatter")
        continue
    frontmatter = match.group(1)
    name = re.search(r"^name:\s*(.+)$", frontmatter, re.M)
    description = re.search(r"^description:\s*(.+)$", frontmatter, re.M)
    if not name or name.group(1).strip() != directory.name:
        errors.append(f"{path}: name must match directory {directory.name}")
    if not description or not description.group(1).strip():
        errors.append(f"{path}: missing description")
    if len(text.splitlines()) > 500:
        errors.append(f"{path}: SKILL.md exceeds 500 lines")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("Agent Skills validation: OK")
