#!/usr/bin/env python3
"""Каталог сцен и сегменты из каталога источников.

Схема идентификаторов намеренно отвязывает сегмент от сцены:

    скрипт   S0007                        - код из реестра, выдаётся один раз
    сегмент  SEG_S0007_R000123_G00        - выводится из source_id
    сцена    SCN0042                      - непрозрачный сквозной номер

`scene_id` у сегмента - обычное поле. Границы сцен можно двигать сколько угодно,
ни один ID при этом не меняется. Это единственная причина, по которой допустимо
начать с грубого деления по скриптам и уточнить его позже.

Текст источника в сегменты не копируется: он живёт в каталоге и подставляется
при сборке контекста. Иначе двести мегабайт удвоились бы.

Запуск идемпотентен: реестр скриптов переиспользуется, коды не переназначаются.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

REGISTRY = ROOT / "translation" / "script-registry.jsonl"
SCENES = ROOT / "translation" / "scenes.jsonl"
SEGMENTS_DIR = ROOT / "translation" / "segments"


def read_jsonl(path):
    if not path.exists():
        return []
    with io.open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_config():
    import yaml
    with io.open(ROOT / "config" / "project.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def catalog_path(config):
    active = config["project"]["active_build"]
    for source_set in config.get("source_sets", {}).values():
        if source_set.get("build_id", "").replace("-", "_") == active.replace("-", "_"):
            return ROOT / source_set["catalog"]
    raise SystemExit(f"не найден набор источников для сборки {active}")


def load_registry(entries, dry_run=False):
    """Код скрипта закрепляется за хэшем имени, а не за порядковым номером:
    обновление игры может сдвинуть индексы в PAK."""
    rows = read_jsonl(REGISTRY)
    by_hash = {r["name_sha256"]: r for r in rows}
    next_code = len(rows)
    added = 0
    for name_sha256, entry_index in entries:
        if name_sha256 in by_hash:
            continue
        rows.append({
            "code": f"S{next_code:04d}",
            "name_sha256": name_sha256,
            "first_seen_entry_index": entry_index,
        })
        by_hash[name_sha256] = rows[-1]
        next_code += 1
        added += 1
    if added and not dry_run:
        write_jsonl(REGISTRY, rows)
    return {h: r["code"] for h, r in by_hash.items()}, added


def source_hash(record):
    """Хэш параметров записи целиком.

    Значение обязано совпадать с тем, что подставляет vnctl при сверке с
    каталогом (`record.params_sha256`), иначе валидация отвергнет сегмент.
    Хэш покрывает все три языковых слота сразу, поэтому изменение любого из
    исходников будет замечено.
    """
    return record["record"]["params_sha256"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-scripts", type=int, default=0,
                    help="обработать только первые N скриптов (для пробы)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config = load_config()
    max_per_scene = int(config.get("workflow", {}).get("max_scene_segments", 400))
    catalog = catalog_path(config)
    if not catalog.exists():
        raise SystemExit(f"нет каталога источников: {catalog}\n"
                         f"сначала: python game-tools/export_luca_sources.py")

    by_script = {}
    order_of_entry = []
    with io.open(catalog, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("classification") != "translatable":
                continue
            entry = row["script_entry"]
            key = entry["name_sha256"]
            if key not in by_script:
                by_script[key] = []
                order_of_entry.append((key, entry["index"]))
            by_script[key].append(row)

    order_of_entry.sort(key=lambda kv: kv[1])
    codes, added = load_registry(order_of_entry, dry_run=args.dry_run)
    print(f"скриптов с переводимым текстом: {len(by_script)}, новых кодов: {added}")

    if args.limit_scripts:
        order_of_entry = order_of_entry[:args.limit_scripts]

    scenes = []
    scene_no = 0
    total_segments = 0

    for name_sha256, entry_index in order_of_entry:
        records = sorted(by_script[name_sha256],
                         key=lambda r: (r["record"]["ordinal"],
                                        r["layout"].get("group_ordinal", 0)))
        code = codes[name_sha256]

        for start in range(0, len(records), max_per_scene):
            chunk = records[start:start + max_per_scene]
            scene_no += 1
            scene_id = f"SCN{scene_no:04d}"
            segments = []
            for order, row in enumerate(chunk, start=1):
                ordinal = row["record"]["ordinal"]
                group = row["layout"].get("group_ordinal", 0)
                ja = next((s for s in row["slots"] if s["language"] == "ja"), {})
                segments.append({
                    "id": f"SEG_{code}_R{ordinal:06d}_G{group:02d}",
                    "source_set_id": row["source_set_id"],
                    "source_id": row["source_id"],
                    "source_hash": source_hash(row),
                    "file_id": code,
                    "scene_id": scene_id,
                    "order": order,
                    "speaker": ja.get("speaker"),
                    "translation": "",
                    "status": "todo",
                    "flags": [],
                })
            scenes.append({
                "scene_id": scene_id,
                "file_id": code,
                "order": scene_no,
                "route": "",
                "title_safe": "",
                "segment_ids": [s["id"] for s in segments],
                "previous_scene": None,
                "next_scene": None,
                "status": "todo",
                "source_range": {
                    "script_entry_index": entry_index,
                    "first_record": chunk[0]["record"]["ordinal"],
                    "last_record": chunk[-1]["record"]["ordinal"],
                },
            })
            total_segments += len(segments)
            if not args.dry_run:
                write_jsonl(SEGMENTS_DIR / f"{scene_id}.jsonl", segments)

    for i, scene in enumerate(scenes):
        if i:
            scene["previous_scene"] = scenes[i - 1]["scene_id"]
        if i + 1 < len(scenes):
            scene["next_scene"] = scenes[i + 1]["scene_id"]

    if not args.dry_run:
        write_jsonl(SCENES, scenes)

    sizes = sorted(len(s["segment_ids"]) for s in scenes)
    print(f"сцен: {len(scenes)}, сегментов: {total_segments}")
    if sizes:
        print(f"размер сцены: минимум {sizes[0]}, медиана {sizes[len(sizes) // 2]}, "
              f"максимум {sizes[-1]}")
    if args.dry_run:
        print("dry-run: ничего не записано")


if __name__ == "__main__":
    main()
