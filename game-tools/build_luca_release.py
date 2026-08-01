"""Сборка русского текста из сегментов в Steam/LUCA SCRIPT.PAK.

Продакшн-адаптер, которого раньше не было: `build_luca_test.py` подменял две
зашитые строки и сборщиком не является. Здесь берутся канонические сегменты,
находятся по стабильному `source_id`, и русский пишется в языковой слот сборки
(DEC-0024 - английский, индекс 1). Японский и китайский слоты не трогаются.

Сборка идёт только из pristine-архива с проверенным хэшем: правка установленного
PAK на месте запрещена.

    python game-tools/build_luca_release.py
    python game-tools/build_luca_release.py --status reviewed playable
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


def load_translations(seg_dir: Path, statuses: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    skipped_status = 0
    for path in sorted(seg_dir.glob("*.jsonl")):
        for line in io.open(path, encoding="utf-8"):
            row = json.loads(line)
            text = str(row.get("translation") or "").strip()
            if not text:
                continue
            if row["status"] not in statuses:
                skipped_status += 1
                continue
            out[row["source_id"]] = {
                "text": row["translation"],
                "speaker": row.get("speaker"),
                "segment_id": row["id"],
                "scene_id": row["scene_id"],
            }
    return out, skipped_status


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "project.yaml")
    parser.add_argument("--source-set", default="steam_luca")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "build" / "steam" / "SCRIPT.russian.PAK")
    parser.add_argument("--status", nargs="+", default=list(DEFAULT_STATUSES))
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    source_config = config["source_sets"][args.source_set]
    archive = ROOT / source_config["archive"]
    build_slot = int(source_config["build_slot"])

    actual_hash = digest_file(archive)
    if actual_hash != source_config["archive_sha256"].lower():
        raise SystemExit(f"ОШИБКА: хэш pristine-архива не совпал: {actual_hash}")

    seg_dir = ROOT / config.get("paths", {}).get("segments", "translation/segments")
    translations, skipped_status = load_translations(seg_dir, set(args.status))
    labels = load_speaker_labels(ROOT / "translation" / "speakers.jsonl")
    if not translations:
        raise SystemExit("ОШИБКА: нечего собирать, подходящих сегментов нет")

    pak = Pak(archive)
    metadata_index = next(
        (entry.index for entry in pak.entries if entry.name == "_build_time"),
        pak.entry_count,
    )

    edits: dict[tuple[int, int], bytes] = {}
    expected: list[tuple[int, int, str]] = []
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

    print(f"pristine: {archive}")
    print(f"pristine sha256: {actual_hash}")
    print(f"output: {args.output}")
    print(f"output sha256: {digest_file(args.output)}")
    print(f"output size: {args.output.stat().st_size}")
    print(f"статусы в сборке: {', '.join(sorted(args.status))}")
    print(f"сегментов записано: {len(edits)} (пропущено по статусу: {skipped_status})")
    print(f"строк длиннее исходной: {grew}")
    print(f"слот: {build_slot} ({source_config['slots'][build_slot]['language']})")
    print(f"проверено: records={validation['records']} "
          f"references={validation['references']} labels={validation['labels']}")
    print(f"обратная вычитка совпала: {readback}/{len(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
