"""Сборка русского текста из сегментов в Steam/LUCA SCRIPT.PAK.

Продакшн-адаптер, которого раньше не было: `build_luca_test.py` подменял две
зашитые строки и сборщиком не является. Здесь берутся канонические сегменты,
находятся по стабильному `source_id`, и русский пишется в языковой слот сборки
(DEC-0024 - английский, индекс 1). Японский и китайский слоты не трогаются.

Сборка идёт только из pristine-архива с проверенным хэшем: правка установленного
PAK на месте запрещена.

    python game-tools/build_luca_release.py
    python game-tools/build_luca_release.py --status reviewed playable
    python game-tools/build_luca_release.py --reviewed-route BLK0002
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from luca import (  # noqa: E402
    Pak,
    classify_source_record,
    encode_luca_string,
    iter_script_records,
    make_source_id,
    relocate_script_records,
    validate_script_references,
)

ROOT = Path(__file__).resolve().parents[1]
SPEAKER_MARKER = re.compile(r"^@([^@\r\n]+)@")
DEFAULT_STATUSES = ("reviewed", "playable", "lqa", "approved")


def digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            value.update(chunk)
    return "sha256:" + value.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def write_jsonl_atomic(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def text_hash(rows: list[dict]) -> str:
    payload = [{"id": row["id"], "translation": row.get("translation", "")} for row in rows]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def style_build_preflight(config: dict, seg_dir: Path,
                          included_scene_ids: set[str]) -> dict[str, str]:
    scenes = read_jsonl(ROOT / config.get("paths", {}).get(
        "scenes", "translation/scenes.jsonl"))
    route_by_scene = {str(row["scene_id"]): str(row.get("route", "")) for row in scenes}
    service = set(config.get("workflow", {}).get("style_service_routes") or [])
    required_routes = {route_by_scene.get(scene_id, "") for scene_id in included_scene_ids} - service
    if "" in required_routes:
        raise SystemExit("ОШИБКА: у собираемой сцены нет непрозрачного style block ID")

    rows_by_route: dict[str, list[dict]] = {route: [] for route in required_routes}
    for path in sorted(seg_dir.glob("*.jsonl")):
        for row in read_jsonl(path):
            route = route_by_scene.get(str(row["scene_id"]), "")
            if route in rows_by_route:
                rows_by_route[route].append(row)

    ledger_path = ROOT / config.get("paths", {}).get(
        "style_ledger", "translation/style-ledger.jsonl")
    events = read_jsonl(ledger_path)
    route_by_run: dict[str, str] = {}
    latest_run_by_route: dict[str, str] = {}
    receipts_by_run: dict[str, str] = {}
    retired_runs: set[str] = set()
    for event in events:
        if event.get("event") == "run_started":
            run_id = str(event["run_id"])
            route = str(event["route"])
            route_by_run[run_id] = route
            latest_run_by_route[route] = run_id
        elif event.get("event") in {"run_completed", "route_audited"}:
            receipts_by_run[str(event.get("run_id", ""))] = str(
                event.get("route_sha256", ""))
        elif event.get("event") == "style_run_retired":
            retired_runs.add(str(event.get("run_id", "")))

    selected_runs: dict[str, str] = {}
    failures = []
    for route, rows in sorted(rows_by_route.items()):
        current = text_hash(rows)
        run_id = latest_run_by_route.get(route)
        completion_hash = None if run_id in retired_runs else receipts_by_run.get(run_id or "")
        if not run_id or not completion_hash:
            failures.append(f"{route}: художественная вычитка не завершена")
        elif completion_hash != current:
            failures.append(f"{route}: текст изменился после завершения вычитки")
        else:
            selected_runs[route] = run_id
    if failures:
        raise SystemExit("ОШИБКА: production build заблокирован:\n  " + "\n  ".join(failures))
    return selected_runs


def promote_built_segments(seg_dir: Path, source_ids: set[str]) -> int:
    promoted = 0
    for path in sorted(seg_dir.glob("*.jsonl")):
        rows = read_jsonl(path)
        changed = False
        for row in rows:
            if row.get("source_id") in source_ids and row.get("status") == "reviewed":
                row["status"] = "playable"
                promoted += 1
                changed = True
        if changed:
            write_jsonl_atomic(path, rows)
    return promoted


def load_scene_routes(config: dict) -> dict[str, str]:
    scenes = read_jsonl(ROOT / config.get("paths", {}).get(
        "scenes", "translation/scenes.jsonl"))
    return {str(row["scene_id"]): str(row.get("route", "")) for row in scenes}


def load_translations(seg_dir: Path, statuses: set[str],
                      route_by_scene: dict[str, str] | None = None,
                      reviewed_routes: set[str] | None = None
                      ) -> tuple[dict[str, dict], int, int]:
    if reviewed_routes is not None:
        if route_by_scene is None:
            raise ValueError("route_by_scene is required with reviewed_routes")
        unknown = reviewed_routes - set(route_by_scene.values())
        if unknown:
            raise SystemExit(
                "ОШИБКА: неизвестный route для --reviewed-route: "
                + ", ".join(sorted(unknown)))

    out: dict[str, dict] = {}
    skipped_status = 0
    skipped_reviewed_by_route = 0
    included_reviewed_routes: set[str] = set()
    for path in sorted(seg_dir.glob("*.jsonl")):
        for line in io.open(path, encoding="utf-8"):
            row = json.loads(line)
            text = str(row.get("translation") or "").strip()
            if not text:
                continue
            if row["status"] not in statuses:
                skipped_status += 1
                continue
            if row["status"] == "reviewed" and reviewed_routes is not None:
                scene_id = str(row["scene_id"])
                route = route_by_scene.get(scene_id, "")
                if not route:
                    raise SystemExit(
                        f"ОШИБКА: у reviewed-сегмента {row['id']} нет route в scenes.jsonl")
                if route not in reviewed_routes:
                    skipped_reviewed_by_route += 1
                    continue
                included_reviewed_routes.add(route)
            out[row["source_id"]] = {
                "text": row["translation"],
                "speaker": row.get("speaker"),
                "segment_id": row["id"],
                "scene_id": row["scene_id"],
                "status": row["status"],
            }
    if reviewed_routes is not None:
        empty_routes = reviewed_routes - included_reviewed_routes
        if empty_routes:
            raise SystemExit(
                "ОШИБКА: --reviewed-route не включает reviewed-строк: "
                + ", ".join(sorted(empty_routes)))
    return out, skipped_status, skipped_reviewed_by_route


def load_speaker_labels(path: Path) -> dict[str, str]:
    labels = {}
    for line in io.open(path, encoding="utf-8"):
        row = json.loads(line)
        if row.get("preferred_ru"):
            labels[row["source"]] = row["preferred_ru"]
    return labels


def slot_text(original: str, translation: str, speaker: str | None,
              labels: dict[str, str]) -> str:
    """Собрать текст языкового слота.

    Ярлык говорящего живёт ведущим маркером `@…@` (FND-0041), а в сегментах он
    вынесен в отдельное поле. Маркер ставится тогда и только тогда, когда он был
    в исходном слоте: его появление или пропажа меняет разметку записи, а не
    перевод. Если русской формы ярлыка нет, остаётся исходная - пустая подпись
    хуже чужой.
    """
    marker = SPEAKER_MARKER.match(original)
    if not marker:
        return translation
    label = labels.get(speaker or "") or marker.group(1)
    return f"@{label}@{translation}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "project.yaml")
    parser.add_argument("--source-set", default="steam_luca")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "build" / "steam" / "SCRIPT.russian.PAK")
    parser.add_argument("--status", nargs="+", default=list(DEFAULT_STATUSES))
    parser.add_argument(
        "--reviewed-route", nargs="+", metavar="ROUTE",
        help=("включать status=reviewed только из указанных route; "
              "остальные выбранные статусы остаются глобальными"))
    parser.add_argument("--receipt", type=Path,
                        default=ROOT / "build" / "steam" / "release-receipt.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    source_config = config["source_sets"][args.source_set]
    archive = ROOT / source_config["archive"]
    build_slot = int(source_config["build_slot"])

    actual_hash = digest_file(archive)
    if actual_hash != source_config["archive_sha256"].lower():
        raise SystemExit(f"ОШИБКА: хэш pristine-архива не совпал: {actual_hash}")

    seg_dir = ROOT / config.get("paths", {}).get("segments", "translation/segments")
    reviewed_routes = (set(args.reviewed_route)
                       if args.reviewed_route is not None else None)
    route_by_scene = load_scene_routes(config) if reviewed_routes is not None else None
    translations, skipped_status, skipped_reviewed_by_route = load_translations(
        seg_dir, set(args.status), route_by_scene, reviewed_routes)
    labels = load_speaker_labels(ROOT / "translation" / "speakers.jsonl")
    if not translations:
        raise SystemExit("ОШИБКА: нечего собирать, подходящих сегментов нет")
    style_runs = style_build_preflight(
        config, seg_dir, {str(item["scene_id"]) for item in translations.values()})

    pak = Pak(archive)
    metadata_index = next(
        (entry.index for entry in pak.entries if entry.name == "_build_time"),
        pak.entry_count,
    )

    edits: dict[tuple[int, int], bytes] = {}
    expected: list[tuple[int, int, str]] = []
    written_reviewed_source_ids: set[str] = set()
    grew = 0
    for entry in pak.entries[:metadata_index]:
        data = pak.read_entry(entry)
        for ordinal, record in enumerate(iter_script_records(data)):
            source_id = make_source_id(entry.entry_id, ordinal)
            item = translations.get(source_id)
            if item is None:
                continue
            classified = classify_source_record(record)
            if classified.classification != "translatable":
                raise SystemExit(
                    f"ОШИБКА: {item['segment_id']} указывает на запись "
                    f"{classified.classification}, а не на переводимую")
            value = classified.strings[build_slot]
            text = slot_text(value.text, item["text"], item["speaker"], labels)
            replacement = encode_luca_string(text, value.encoding)
            if len(replacement) > value.end_offset - value.offset:
                grew += 1
            edits[(entry.index, record.offset)] = (
                record.params[:value.offset]
                + replacement
                + record.params[value.end_offset:]
            )
            if item["status"] == "reviewed":
                written_reviewed_source_ids.add(source_id)
            expected.append((entry.index, record.offset, text))

    missing = len(translations) - len(edits)
    if missing:
        raise SystemExit(f"ОШИБКА: {missing} сегментов не нашли свою запись в архиве")

    relocation = relocate_script_records(pak, edits)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pak.build(args.output, relocation.replacements)

    built = Pak(args.output)
    validation = validate_script_references(built)

    # Независимая обратная вычитка: текст читается из собранного архива заново,
    # а не сверяется с тем, что мы туда положили в памяти.
    by_index = {entry.index: entry for entry in built.entries}
    readback = 0
    for entry_index, record_offset, text in expected:
        entry = by_index[entry_index]
        records = list(iter_script_records(built.read_entry(entry)))
        wanted = relocation.offset_maps[entry_index][record_offset]
        record = next(r for r in records if r.offset == wanted)
        if classify_source_record(record).strings[build_slot].text != text:
            raise SystemExit(f"ОШИБКА: обратная вычитка разошлась на {entry_index}:{wanted}")
        readback += 1

    output_hash = digest_file(args.output)
    promoted = promote_built_segments(seg_dir, written_reviewed_source_ids)
    receipt = {
        "schema_version": 1,
        "output": str(args.output.relative_to(ROOT)),
        "output_sha256": output_hash,
        "statuses": sorted(args.status),
        "reviewed_routes": (sorted(reviewed_routes)
                            if reviewed_routes is not None else None),
        "skipped_reviewed_by_route": skipped_reviewed_by_route,
        "segments_written": len(edits),
        "readback": readback,
        "style_runs": style_runs,
        "promoted_to_playable": promoted,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    ledger_path = ROOT / config.get("paths", {}).get(
        "style_ledger", "translation/style-ledger.jsonl")
    ledger = read_jsonl(ledger_path)
    for route, run_id in sorted(style_runs.items()):
        ledger.append({
            "schema_version": 1,
            "event": "build_readback",
            "run_id": run_id,
            "route": route,
            "output_sha256": output_hash,
            "written": len(edits),
            "readback": readback,
            "receipt": str(args.receipt.relative_to(ROOT)),
        })
    write_jsonl_atomic(ledger_path, ledger)

    print(f"pristine: {archive}")
    print(f"pristine sha256: {actual_hash}")
    print(f"output: {args.output}")
    print(f"output sha256: {output_hash}")
    print(f"output size: {args.output.stat().st_size}")
    print(f"статусы в сборке: {', '.join(sorted(args.status))}")
    reviewed_scope = (", ".join(sorted(reviewed_routes))
                      if reviewed_routes is not None else "all")
    print(f"reviewed_routes: {reviewed_scope}")
    print(f"reviewed пропущено по route: {skipped_reviewed_by_route}")
    print(f"сегментов записано: {len(edits)} (пропущено по статусу: {skipped_status})")
    print(f"строк длиннее исходной: {grew}")
    print(f"слот: {build_slot} ({source_config['slots'][build_slot]['language']})")
    print(f"проверено: records={validation['records']} "
          f"references={validation['references']} labels={validation['labels']}")
    print(f"обратная вычитка совпала: {readback}/{len(expected)}")
    print(f"статус playable присвоен: {promoted}")
    print(f"receipt: {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
