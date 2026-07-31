#!/usr/bin/env python3
"""Сравнение двух переводов одной порции, сделанных разными моделями.

Сравниваются патчи, а не записанные сегменты: канонические файлы в опыте не
участвуют вовсе. Механические числа считаются здесь, качество судит человек -
поэтому вывод устроен как параллельное чтение, а не как оценка.
"""
from __future__ import annotations

import argparse
import io
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from textrules import check_length, check_line  # noqa: E402


def load(path: Path) -> dict[str, dict]:
    out = {}
    for line in io.open(path, encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            out[str(row["id"])] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("left", type=Path)
    ap.add_argument("right", type=Path)
    ap.add_argument("--labels", default="A,B")
    ap.add_argument("--sources", type=Path,
                    default=Path("source/parsed/steam-luca/source-records.jsonl"))
    args = ap.parse_args()
    la, lb = args.labels.split(",", 1)

    left, right = load(args.left), load(args.right)
    ids = sorted(set(left) | set(right))
    both = [i for i in ids if i in left and i in right]

    print(f"сегментов: {la} {len(left)}, {lb} {len(right)}, общих {len(both)}")
    only_a = sorted(set(left) - set(right))
    only_b = sorted(set(right) - set(left))
    if only_a or only_b:
        print(f"  только у {la}: {len(only_a)}, только у {lb}: {len(only_b)}")

    # Исходники нужны и для длины, и для чтения.
    wanted = set(both)
    src: dict[str, dict] = {}
    with io.open(args.sources, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            sid = row.get("source_id", "")
            key = sid.replace("SRC_LUCA_E", "").split("_R")
            src[sid] = row
    by_seg = {}
    for i in both:
        # SEG_S0003_R000043_G00 -> ищем запись с тем же хвостом R000043_G00
        tail = i.split("_", 2)[2]
        for sid, row in src.items():
            if sid.endswith(tail):
                slots = {s["language"]: s.get("text", "") for s in row["slots"]}
                by_seg[i] = {"ja": slots.get("ja", ""), "en": slots.get("en", ""),
                             "speaker": next((s.get("speaker") for s in row["slots"]
                                              if s["language"] == "ja"), None)}
                break

    print("\n=== механические замечания ===")
    for label, patch in ((la, left), (lb, right)):
        problems = 0
        for i in both:
            text = str(patch[i].get("translation", ""))
            info = by_seg.get(i, {})
            findings = check_line(text, is_dialogue=bool(info.get("speaker")))
            findings += check_length(text, info.get("en", ""))
            problems += len(findings)
        print(f"  {label}: {problems}")

    print("\n=== длина перевода ===")
    for label, patch in ((la, left), (lb, right)):
        lengths = [len(str(patch[i].get("translation", ""))) for i in both]
        print(f"  {label}: медиана {statistics.median(lengths):.0f}, "
              f"среднее {statistics.mean(lengths):.0f}, максимум {max(lengths)}")
    en_len = [len(by_seg.get(i, {}).get("en", "")) for i in both]
    print(f"  английский: медиана {statistics.median(en_len):.0f}")

    identical = sum(1 for i in both
                    if str(left[i].get("translation", "")).strip()
                    == str(right[i].get("translation", "")).strip())
    print(f"\nсовпало дословно: {identical} из {len(both)}")

    print("\n=== построчно ===")
    for i in both:
        info = by_seg.get(i, {})
        who = info.get("speaker") or "—"
        print(f"\n{i[-12:]}  [{who}]")
        print(f"  ja  {info.get('ja','')}")
        print(f"  {la:<3} {str(left[i].get('translation',''))}")
        print(f"  {lb:<3} {str(right[i].get('translation',''))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
