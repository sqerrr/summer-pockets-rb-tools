#!/usr/bin/env python3
"""Лист выбора: два перевода одной порции с чекбоксами.

Пользователь отмечает предпочтение по каждой строке, файл читается обратно.
Метки A и B намеренно не расшифрованы внутри листа.
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
from pathlib import Path


def load(path: Path) -> dict[str, str]:
    out = {}
    for line in io.open(path, encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            out[str(row["id"])] = str(row.get("translation", ""))
    return out


def sources(db: Path, wanted: set[str]) -> dict[str, dict]:
    """Исходники берём из индекса по точному идентификатору сегмента.

    Сопоставлять по хвосту идентификатора нельзя: номера записей повторяются в
    разных скриптах, и совпадение приходит из чужой сцены. Эта ошибка уже была
    допущена здесь однажды и дала чужих говорящих в листе выбора.
    """
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    out: dict[str, dict] = {}
    for seg in wanted:
        row = con.execute(
            "SELECT speaker, sources_json FROM segments WHERE id=?", (seg,)).fetchone()
        if row:
            out[seg] = {"ja": json.loads(row["sources_json"]).get("ja", ""),
                        "speaker": row["speaker"]}
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("left", type=Path)
    ap.add_argument("right", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("build/choice.md"))
    ap.add_argument("--db", type=Path, default=Path("database/knowledge.db"))
    args = ap.parse_args()

    a, b = load(args.left), load(args.right)
    ids = [i for i in a if i in b]
    src = sources(args.db, set(ids))

    out: list[str] = [
        "# Лист выбора",
        "",
        "Отметьте предпочтительный вариант в каждой строке. Если оба годятся —",
        "отметьте «оба». Если не годится ни один — «ни один», и я разберу отдельно.",
        "",
        f"Строк: {len(ids)}. Совпало дословно: "
        f"{sum(1 for i in ids if a[i].strip() == b[i].strip())}.",
        "",
    ]

    for n, seg in enumerate(ids, start=1):
        info = src.get(seg, {})
        who = info.get("speaker")
        head = f"### {n}. " + (f"реплика — {who}" if who else "повествование")
        out.append(head)
        out.append("")
        if info.get("ja"):
            out.append(f"`{info['ja']}`")
            out.append("")
        if a[seg].strip() == b[seg].strip():
            out.append(f"Совпало: {a[seg]}")
            out.append("")
            continue
        out.append(f"- [ ] **A** — {a[seg]}")
        out.append(f"- [ ] **B** — {b[seg]}")
        out.append("- [ ] оба годятся")
        out.append("- [ ] ни один")
        out.append("")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    io.open(args.output, "w", encoding="utf-8", newline="\n").write("\n".join(out))
    print(f"{args.output}: {len(ids)} строк")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
