"""Проверка, что список ё больше не ловит законные слова.

Дефект нашёл переводчик в сравнительном опыте: он обходил слово «все», потому
что проверка считала его ошибкой. То есть валидатор влиял на текст, а не
проверял его.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path("tools").resolve()))
from textrules import check_line  # noqa: E402

LEGAL = [
    "Все смотрят на берег.",
    "Чем это пахнет?",
    "О нём я ничего не знаю.",
    "Тем лучше.",
    "Он нем от удивления.",
    "Зачем ты это сделал?",
    "Он узнает об этом завтра.",
]
MUST_CATCH = [
    ("Он еще не пришел.", "еще и пришел"),
    ("Ее зовут иначе.", "ее"),
    ("Черный кот.", "черный"),
    ("Ребенок спит.", "ребенок"),
]

bad = 0
print("законные слова не должны ловиться:")
for text in LEGAL:
    found = [f for f in check_line(text, is_dialogue=False) if f.rule == "yo"]
    mark = "ok  " if not found else "СБОЙ"
    if found:
        bad += 1
    print(f"  {mark} {text}")
    for f in found:
        print(f"        {f.message}")

print("\nнастоящие пропуски ё должны ловиться:")
for text, what in MUST_CATCH:
    found = [f for f in check_line(text, is_dialogue=False) if f.rule == "yo"]
    mark = "ok  " if found else "СБОЙ"
    if not found:
        bad += 1
    print(f"  {mark} {text:<26} ({what})")

print("\nитог:", "OK" if bad == 0 else f"ПРОБЛЕМ: {bad}")
