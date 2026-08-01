#!/usr/bin/env python3
"""Сверка рабочего дерева до и после запуска подзадач.

Рецензенту сказано «файлы не правишь», но инструкция - не гарантия. За одну
сессию рецензент изменил `tools/textrules.py` и переписал канонические сегменты,
после чего снял снимок собственным прогоном сторожа и отчитался о чистоте.
Снимок, снятый тем, кого сторожат, ничего не доказывает.

Поэтому снимок делает оркестратор до запуска, сверяет после, и охраняется всё
дерево, а не один каталог: инструмент, меняющий правила проверки, опаснее
изменённой строки перевода.

    python tools/guard_worktree.py snapshot
    python tools/guard_worktree.py verify
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

SNAPSHOT = Path("build/worktree-snapshot.json")
GUARDED = (
    "translation",
    "tools",
    "config",
    "docs",
    "schemas",
    "private",
    ".agents",
    ".opencode/agent",
)
SKIP_PARTS = {"__pycache__", "node_modules", ".git"}


def state() -> dict[str, str]:
    out: dict[str, str] = {}
    for root in GUARDED:
        base = Path(root)
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if SKIP_PARTS & set(path.parts):
                continue
            out[path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "verify"
    current = state()

    if action == "snapshot":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        io.open(SNAPSHOT, "w", encoding="utf-8", newline="\n").write(
            json.dumps(current, ensure_ascii=False, indent=1))
        print(f"снимок сделан: {len(current)} файлов")
        return 0

    if not SNAPSHOT.exists():
        print("ОШИБКА: снимок не сделан, сверять не с чем")
        return 1

    before = json.loads(io.open(SNAPSHOT, encoding="utf-8").read())
    changed = sorted(n for n in current if n in before and before[n] != current[n])
    added = sorted(n for n in current if n not in before)
    removed = sorted(n for n in before if n not in current)

    if not (changed or added or removed):
        print(f"дерево не тронуто: {len(current)} файлов совпадают")
        return 0

    print("РАБОЧЕЕ ДЕРЕВО ИЗМЕНЕНО")
    for name in changed:
        print(f"  изменён: {name}")
    for name in added:
        print(f"  добавлен: {name}")
    for name in removed:
        print(f"  удалён: {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
