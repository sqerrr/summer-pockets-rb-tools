"""Заполнить русские формы имён говорящих транскриптором."""
import collections
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("tools").resolve()))
from translit import is_unsettled, translit  # noqa: E402

CATALOG = "source/parsed/steam-luca/source-records.jsonl"

# Английское имя говорящего даёт чтение.
pairs = collections.Counter()
with io.open(CATALOG, encoding="utf-8") as fh:
    for line in fh:
        row = json.loads(line)
        if row.get("classification") != "translatable":
            continue
        slots = {s["language"]: s for s in row["slots"]}
        ja = slots.get("ja", {}).get("speaker")
        en = slots.get("en", {}).get("speaker")
        if ja and en and en != ja:
            pairs[(ja, en)] += 1

best: dict[str, str] = {}
for (ja, en), n in sorted(pairs.items(), key=lambda kv: -kv[1]):
    best.setdefault(ja, en)

PATH = "translation/speakers.jsonl"
rows = [json.loads(l) for l in io.open(PATH, encoding="utf-8") if l.strip()]

filled = unsettled = skipped = 0
for row in rows:
    if row["kind"] != "person":
        continue
    en = best.get(row["source"])
    if not en or not en.isascii():
        skipped += 1
        continue
    row["preferred_ru"] = translit(en)
    row["romaji"] = en
    if is_unsettled(en):
        row["status"] = "needs_decision"
        row["note"] = "задевает ряд ша/шу/шо, решение отложено"
        unsettled += 1
    else:
        row["status"] = "provisional"
        filled += 1

io.open(PATH, "w", encoding="utf-8", newline="\n").write(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

again = [json.loads(l) for l in io.open(PATH, encoding="utf-8") if l.strip()]
print(f"файл разобран заново: {len(again)} записей")
print(f"заполнено имён: {filled}, требуют решения: {unsettled}, пропущено: {skipped}")

print("\nтоп-16:")
for r in again:
    if r["kind"] == "person" and r.get("preferred_ru"):
        print(f"  {r['source']:<10} {r.get('romaji',''):<12} -> {r['preferred_ru']:<14} "
              f"[{r['status']}]  {r['lines']} реплик")
        if r["lines"] < 500:
            break

need = [r for r in again if r.get("status") == "needs_decision"]
if need:
    print("\nждут решения по ряду ша/шу/шо:")
    for r in need[:10]:
        print(f"  {r['source']:<10} {r.get('romaji','')} -> {r['preferred_ru']}")
