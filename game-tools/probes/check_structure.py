"""Есть ли в нашей сборке разрезанные предложения и переменные слоты.

В CLANNAD одно предложение резалось на три записи со вставкой между ними, а
подстановка обращения занимала 151 место. Ошибка в таком месте размазана по
сотням предложений и всплывает только в игре. У нас это не проверялось.

Сюжетный текст не печатаем: только структура и счётчики.
"""
import collections
import io
import json
import re

CATALOG = "source/parsed/steam-luca/source-records.jsonl"

rows = []
with io.open(CATALOG, encoding="utf-8") as fh:
    for line in fh:
        row = json.loads(line)
        if row.get("classification") != "translatable":
            continue
        slots = {s["language"]: s for s in row["slots"]}
        ja = slots.get("ja", {})
        rows.append({
            "entry": row["script_entry"]["index"],
            "ordinal": row["record"]["ordinal"],
            "ja": ja.get("text", ""),
            "en": slots.get("en", {}).get("text", ""),
            "speaker": ja.get("speaker"),
        })
rows.sort(key=lambda r: (r["entry"], r["ordinal"]))
print(f"переводимых записей: {len(rows)}")

# --- C1: разрезанные предложения ------------------------------------------
# Признак разреза: запись не заканчивается завершающим знаком, а следующая
# начинается не с заглавной или сразу со служебного знака.
TERMINAL = "。！？」』…♪"
no_end = [r for r in rows if r["ja"] and r["ja"][-1] not in TERMINAL]
print(f"\n=== C1: записи без завершающего знака ===")
print(f"  {len(no_end)} из {len(rows)}  ({len(no_end)/len(rows)*100:.1f}%)")

# Совсем короткие записи без знаков - кандидаты в заполнители слота.
filler = [r for r in rows if r["ja"] and len(r["ja"]) <= 8
          and not any(c in r["ja"] for c in TERMINAL)]
print(f"  короткие (<=8 знаков) без пунктуации: {len(filler)}")
lengths = collections.Counter(len(r["ja"]) for r in filler)
print(f"  их длины: {dict(sorted(lengths.items()))}")

# Запись, состоящая только из знака препинания - верный признак хвоста разреза.
punct_only = [r for r in rows if r["ja"].strip() and
              all(c in "。、！？…「」『』・ " for c in r["ja"])]
print(f"  записи только из знаков препинания: {len(punct_only)}")

# --- C2: переменные слоты --------------------------------------------------
# В CLANNAD подстановка выглядела как две формы обращения на одну позицию.
# Ищем управляющие последовательности и повторяющиеся короткие записи.
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]|%[A-Za-z0-9_]+%|\{[^{}]{1,20}\}")
with_ctrl = [r for r in rows if CTRL.search(r["ja"]) or CTRL.search(r["en"])]
print(f"\n=== C2: управляющие последовательности в тексте ===")
print(f"  записей с подозрением на подстановку: {len(with_ctrl)}")
if with_ctrl:
    found = collections.Counter()
    for r in with_ctrl[:200]:
        for m in CTRL.finditer(r["ja"] + " " + r["en"]):
            found[m.group(0)] += 1
    print(f"  что именно: {dict(found.most_common(8))}")

# --- C3: где текст выборов -------------------------------------------------
# Пункт выбора обычно короткий, без говорящего, без завершающего знака и идёт
# группой из двух-четырёх подряд.
cand = [r for r in rows if not r["speaker"] and r["ja"]
        and len(r["ja"]) <= 24 and r["ja"][-1] not in TERMINAL]
groups = []
current = [cand[0]] if cand else []
for prev, item in zip(cand, cand[1:]):
    close = (item["entry"] == prev["entry"]
             and 0 < item["ordinal"] - prev["ordinal"] <= 6)
    if close:
        current.append(item)
    else:
        if len(current) >= 2:
            groups.append(current)
        current = [item]
if len(current) >= 2:
    groups.append(current)

sizes = collections.Counter(len(g) for g in groups)
print(f"\n=== C3: кандидаты в блоки выбора ===")
print(f"  коротких записей без говорящего и без знака: {len(cand)}")
print(f"  групп по 2-6 подряд: {len(groups)}")
print(f"  размеры групп: {dict(sorted(sizes.items())[:8])}")
print(f"  скриптов с такими группами: {len({g[0]['entry'] for g in groups})}")

# --- C4: одинаковый японский с разным окружением ---------------------------
by_ja = collections.defaultdict(list)
for r in rows:
    if r["ja"]:
        by_ja[r["ja"]].append(r)
multi = {k: v for k, v in by_ja.items() if len(v) > 1}
diff_en = sum(1 for v in multi.values() if len({x["en"] for x in v}) > 1)
print(f"\n=== C4: повторы японского текста ===")
print(f"  текстов, встречающихся дважды и чаще: {len(multi)}")
print(f"  из них английский слот РАЗЛИЧАЕТСЯ: {diff_en}")
print("  (различие означает, что одинаковый японский не всегда переводится одинаково)")
