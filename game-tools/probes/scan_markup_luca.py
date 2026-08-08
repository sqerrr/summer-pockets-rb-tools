"""Есть ли в тексте активной сборки движковая разметка.

FND-0026 утверждала, что сценарные строки не содержат встроенной разметки, но
измерялась она на legacy-сборке Scene.pck. Для LUCA это не проверялось, а в
сравнительном опыте обе модели наткнулись на конструкции вида $[...], $C[...]
и $(...) - и обе их испортили, причём проверки этого не заметили.

Сюжетный текст не печатаем: только конструкции и счётчики.
"""
import collections
import io
import json
import re

CATALOG = "source/parsed/steam-luca/source-records.jsonl"

PATTERNS = {
    "ruby $[kanji$/kana$]": re.compile(r"\$\[[^\]]*\$/[^\]]*\$\]"),
    "выделение $[$b...$]": re.compile(r"\$\[\$b[^\]]*?\$\]"),
    "цвет $C[...]": re.compile(r"\$C\[[0-9a-fA-F]*\]"),
    "переменная $(N)": re.compile(r"\$\([0-9]+\)"),
    "прочее $X[...]": re.compile(r"\$[A-Za-z]\[[^\]]*\]"),
    "прочее $-конструкция": re.compile(r"\$[^\[\(A-Za-z/\]]"),
}

counts = collections.Counter()
records_with = collections.Counter()
samples: dict[str, list[str]] = collections.defaultdict(list)
total = 0

with io.open(CATALOG, encoding="utf-8") as fh:
    for line in fh:
        row = json.loads(line)
        if row.get("classification") != "translatable":
            continue
        total += 1
        text = " ".join(s.get("text", "") for s in row["slots"])
        hit_any = False
        for name, pat in PATTERNS.items():
            found = pat.findall(text)
            if found:
                counts[name] += len(found)
                records_with[name] += 1
                hit_any = True
                if len(samples[name]) < 5:
                    samples[name].extend(found[:2])
        if hit_any:
            records_with["ЛЮБАЯ"] += 1

print(f"переводимых записей: {total}\n")
print(f"{'конструкция':<24} {'вхождений':>10} {'записей':>9}")
for name in PATTERNS:
    print(f"{name:<24} {counts[name]:>10} {records_with[name]:>9}")
print(f"{'ИТОГО записей с разметкой':<24} {'':>10} {records_with['ЛЮБАЯ']:>9}"
      f"   ({records_with['ЛЮБАЯ']/total*100:.1f}%)")

print("\nобразцы конструкций:")
for name, items in samples.items():
    uniq = list(dict.fromkeys(items))[:4]
    print(f"  {name}: {uniq}")

# Отдельно: сколько разметки в японском против английского.
ja_hits = en_hits = 0
with io.open(CATALOG, encoding="utf-8") as fh:
    for line in fh:
        row = json.loads(line)
        if row.get("classification") != "translatable":
            continue
        slots = {s["language"]: s.get("text", "") for s in row["slots"]}
        if any(p.search(slots.get("ja", "")) for p in PATTERNS.values()):
            ja_hits += 1
        if any(p.search(slots.get("en", "")) for p in PATTERNS.values()):
            en_hits += 1
print(f"\nзаписей с разметкой в японском слоте : {ja_hits}")
print(f"записей с разметкой в английском слоте: {en_hits}")
print("Расхождение означает, что часть разметки локализация снимает или переносит.")
