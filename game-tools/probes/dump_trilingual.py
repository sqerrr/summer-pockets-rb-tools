"""Выборка трёхъязычных строк из Steam/LUCA SCRIPT.PAK для калибровки.

Печатает японский, английский и китайский варианты одной записи рядом.
Рабочий инструмент переводчика: текст игры выводится только локально.

    python game-tools/probes/dump_trilingual.py --list
    python game-tools/probes/dump_trilingual.py --script 12 --from 0 --to 40
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from luca import Pak, iter_script_records, multilingual_strings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAK = ROOT / "Summer Pockets REFLECTION BLUE_Steam" / "files" / "SCRIPT.PAK"

LANGS = ("ja", "en", "zh")


def load(pak_path):
    pak = Pak(pak_path)
    scripts = []
    for entry in pak.entries:
        try:
            records = list(iter_script_records(pak.read_entry(entry)))
        except Exception:
            continue
        groups = []
        for record in records:
            try:
                strings, _rest = multilingual_strings(record)
            except Exception:
                continue
            texts = [(s.text if s else "") for s in strings[:3]]
            if any(texts):
                groups.append(texts)
        if groups:
            scripts.append((entry.name, groups))
    return scripts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pak", default=str(DEFAULT_PAK))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--script", type=int)
    ap.add_argument("--name")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="end", type=int, default=40)
    args = ap.parse_args()

    scripts = load(args.pak)

    if args.list or (args.script is None and not args.name):
        print(f"скриптов с текстом: {len(scripts)}")
        for i, (name, groups) in enumerate(scripts[:60]):
            print(f"  {i:3}  {name:<34} групп {len(groups)}")
        return

    if args.name:
        idx = next(i for i, (n, _) in enumerate(scripts) if args.name in n)
    else:
        idx = args.script
    name, groups = scripts[idx]
    print(f"=== {name}  групп {len(groups)} ===")
    for i in range(args.start, min(args.end, len(groups))):
        ja, en, zh = (groups[i] + ["", "", ""])[:3]
        print(f"[{i}]")
        print(f"  ja: {ja}")
        print(f"  en: {en}")
        print(f"  zh: {zh}")


if __name__ == "__main__":
    main()
