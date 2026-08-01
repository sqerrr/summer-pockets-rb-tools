"""Проверка транскриптора на именах, которые реально есть в игре."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translit import translit  # noqa: E402


def test_real_names_from_the_game():
    cases = {
        "Hairi": "Хаири",
        "Umi": "Уми",
        "Shiroha": "Сироха",
        "Ao": "Ао",
        "Shizuku": "Сидзуку",
        "Tsumugi": "Цумуги",
        "Miki": "Мики",
        "Shiki": "Сики",
        "Ryoichi": "Рёити",
        "Tenzen": "Тэндзэн",
        "Kamome": "Камомэ",
        "Kyoko": "Кёко",
        "Kobato": "Кобато",
        "Nanami": "Нанами",
        "Sagi": "Саги",
        "Ai": "Аи",
    }
    for romaji, expected in cases.items():
        assert translit(romaji) == expected, f"{romaji} -> {translit(romaji)}"


def test_decided_syllables():
    assert translit("shi") == "си"
    assert translit("chi") == "ти"
    assert translit("ji") == "дзи"
    assert translit("zu") == "дзу"
    assert translit("te") == "тэ"
    assert translit("sha") == "ся"
    assert translit("shu") == "сю"
    assert translit("sho") == "сё"


def test_long_vowels_are_not_marked():
    assert translit("Kyouko") == "Кёко"
    assert translit("Ryouichi") == "Рёити"
    assert translit("Yuuko") == "Юко"


def test_case_is_preserved():
    assert translit("miki") == "мики"
    assert translit("Miki") == "Мики"


def test_empty_input():
    assert translit("") == ""
    assert translit("   ") == ""
