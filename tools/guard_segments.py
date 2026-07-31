#!/usr/bin/env python3
"""Сторож канонических сегментов на время опыта.

Агентам сказано не применять патчи, но инструкция - не гарантия: их собственное
определение велит обратное, и модель может пойти привычным путём. Поэтому
состояние снимается до и сверяется после.

    python tools/guard_segments.py snapshot
    python tools/guard_segments.py verify
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

SNAPSHOT = Path("build/segments-snapshot.json")
SEG_DIR = Path("translation/segments")


def state() -> dict[str, str]:
    out = {}
    for path in sorted(SEG_DIR.glob("*.jsonl")):
        out[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "verify"
    current = state()

    if action == "snapshot":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        io.open(SNAPSHOT, "w", encoding="utf-8", newline="\n").write(
            json.dumps(current, ensure_ascii=False, indent=1))
        print(f"снимок сделан: {len(current)} файлов сегментов")
        return 0

    if not SNAPSHOT.exists():
        print("ОШИБКА: снимок не сделан, сверять не с чем")
        return 1

    before = json.loads(io.open(SNAPSHOT, encoding="utf-8").read())
    changed = [n for n in current if before.get(n) != current[n]]
    added = [n for n in current if n not in before]
    removed = [n for n in before if n not in current]

    if not (changed or added or removed):
        print(f"сегменты не тронуты: {len(current)} файлов совпадают")
        return 0

    print("СЕГМЕНТЫ ИЗМЕНЕНЫ, опыт загрязнён")
    for name in changed:
        print(f"  изменён: {name}")
    for name in added:
        print(f"  добавлен: {name}")
    for name in removed:
        print(f"  удалён: {name}")
    print("\nОткатить: git checkout -- translation/segments/")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
