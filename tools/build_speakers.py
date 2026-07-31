"""Собрать справочник говорящих.

В русском CLANNAD поле говорящего было свободным текстом и поехало: «Ребёнок» и
«Ребенок» как два персонажа, одна и та же группа записана тремя порядками имён.
Ловить это нечем, если справочник не замкнут.

Здесь справочник выводится из исходника, а не заводится вручную: японское поле
говорящего уже замкнуто движком, нам нужно лишь закрепить русские соответствия.
"""
import collections
import io
import json
import re

CATALOG = "source/parsed/steam-luca/source-records.jsonl"
OUT = "translation/speakers.jsonl"

counts = collections.Counter()
with io.open(CATALOG, encoding="utf-8") as fh:
    for line in fh:
        row = json.loads(line)
        if row.get("classification") != "translatable":
            continue
        for slot in row["slots"]:
            if slot["language"] == "ja" and slot.get("speaker"):
                counts[slot["speaker"]] += 1
            break

# Роль или имя: роль содержит служебные слова и переводится, имя транскрибируется.
ROLE_MARKERS = ("の", "少女", "少年", "子供", "男", "女", "おっさん", "おばー",
                "アナウンス", "記者", "漁師", "店員", "先生", "母", "父")


def kind(name: str) -> str:
    if re.fullmatch(r"[？?]+", name):
        return "unknown"
    if any(m in name for m in ROLE_MARKERS):
        return "role"
    return "person"


rows = []
for i, (name, n) in enumerate(counts.most_common(), start=1):
    rows.append({
        "id": "SPK-%04d" % i,
        "source": name,
        "kind": kind(name),
        "lines": n,
        "preferred_ru": None,
        "status": "provisional",
    })

io.open(OUT, "w", encoding="utf-8", newline="\n").write(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

by_kind = collections.Counter(r["kind"] for r in rows)
print(f"говорящих: {len(rows)}, реплик: {sum(counts.values())}")
print("по типу:", dict(by_kind))
print(f"\nна первые 12 приходится "
      f"{sum(r['lines'] for r in rows[:12]) / sum(counts.values()) * 100:.0f}% реплик")
print("\nимена, требующие решения о транскрипции:")
for r in rows[:14]:
    if r["kind"] == "person":
        print(f"  {r['id']}  {r['source']:<10} {r['lines']:>6} реплик")

again = [json.loads(l) for l in io.open(OUT, encoding="utf-8") if l.strip()]
print(f"\nфайл разобран заново: {len(again)} записей")
