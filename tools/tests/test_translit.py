"""Проверка транскриптора на именах, которые реально есть в игре."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translit import is_unsettled, translit  # noqa: E402


def test_real_names_from_the_game():
    cases = {
        "Hairi": "Хаири",
        "Umi": "Уми",
        "Shiroha": "Широха",
        "Ao": "Ао",
        "Shizuku": "Шизуку",
        "Tsumugi": "Цумуги",
        "Miki": "Мики",
        "Shiki": "Шики",
        "Ryoichi": "Рёичи",
        "Tenzen": "Тензен",
        "Kamome": "Камоме",
        "Kyoko": "Кёко",
        "Kobato": "Кобато",
        "Nanami": "Нанами",
        "Sagi": "Саги",
        "Ai": "Аи",
    }
    for romaji, expected in cases.items():
        assert translit(romaji) == expected, f"{romaji} -> {translit(romaji)}"


def test_decided_syllables():
    assert translit("shi") == "ши"
    assert translit("chi") == "чи"
    assert translit("ji") == "джи"
    assert translit("zu") == "зу"
    assert translit("te") == "те"


def test_long_vowels_are_not_marked():
    assert translit("Kyouko") == "Кёко"
    assert translit("Ryouichi") == "Рёичи"
    assert translit("Yuuko") == "Юко"


def test_case_is_preserved():
    assert translit("miki") == "мики"
    assert translit("Miki") == "Мики"


def test_unsettled_row_is_reported():
    assert is_unsettled("Shouko")
    assert is_unsettled("Sharu")
    assert not is_unsettled("Shizuku")
    assert not is_unsettled("Miki")


def test_empty_input():
    assert translit("") == ""
    assert translit("   ") == ""
