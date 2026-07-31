"""Проверка check_names на конкретных случаях, включая склонение."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path("tools").resolve()))
from textrules import check_names  # noqa: E402

NAMES = {"しろは": "Широха", "静久": "Шизуку", "鏡子": "Кёко"}

cases = [
    ("しろはが笑った。", None, "Широха улыбнулась.", 0, "прямая форма"),
    ("しろはに言った。", None, "Я сказал Широхе.", 0, "дательный падеж"),
    ("しろはを見た。", None, "Я посмотрел на Широху.", 0, "винительный падеж"),
    ("しろはが笑った。", None, "Сироха улыбнулась.", 1, "чужое написание ловится"),
    ("しろはが笑った。", None, "Она улыбнулась.", 1, "местоимение - предупреждение"),
    ("静久と鏡子。", None, "Шизуку и Кёко.", 0, "два имени сразу"),
    ("静久と鏡子。", None, "Шидзуку и Кёко.", 1, "одно из двух неверно"),
    ("空を見上げる。", None, "Смотрю в небо.", 0, "имён нет вовсе"),
    ("しろはが笑った。", None, "", 0, "пустой перевод не проверяется"),
    ("", "しろは", "Широха улыбнулась.", 0, "имя только в поле говорящего"),
]

bad = 0
for ja, speaker, ru, expected, label in cases:
    found = check_names(ja, speaker, ru, NAMES)
    mark = "ok " if len(found) == expected else "СБОЙ"
    if len(found) != expected:
        bad += 1
    print(f"  {mark} {label:34} замечаний {len(found)}, ждали {expected}")
    for f in found:
        print(f"        {f.message}")

print("\nитог:", "OK" if bad == 0 else f"ПРОБЛЕМ: {bad}")
