"""Проверки правил русского текста.

Каждый случай взят из конкретного решения, а не придуман для полноты.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from textrules import check_length, check_line  # noqa: E402


def rules(text, *, is_dialogue=True):
    return {f.rule for f in check_line(text, is_dialogue=is_dialogue)}


def test_clean_line_passes():
    assert rules("Я щурюсь от ветра.") == set()


def test_missing_yo_caught():
    assert "yo" in rules("Он еще не пришел.")
    assert rules("Он ещё не пришёл.") == set()


def test_reduction_caught():
    assert "reduction" in rules("Щас разберёмся.")
    assert rules("Сейчас разберёмся.") == set()


def test_three_dots_caught():
    assert "ellipsis" in rules("Ну... ладно.")
    assert rules("Ну… ладно.") == set()


def test_question_ellipsis_form():
    assert "ellipsis" in rules("Правда…?")  # не тот порядок
    assert "ellipsis" in rules("Правда?…")
    assert rules("Правда?..") == set()


def test_interrobang_order():
    assert "ellipsis" in rules("Что!?")
    assert rules("Что?!") == set()


def test_stretch_by_doubling_caught():
    assert "stretch" in rules("Ааааа!")
    assert rules("А-а-а!") == set()


def test_double_bang_rejected_triple_allowed():
    assert "bangs" in rules("Стой!!")
    assert rules("Стой!!!") == set()
    assert rules("Стой!") == set()


def test_leading_dash_in_dialogue():
    assert "quotes" in rules("— Привет.")
    assert "quotes" not in rules("— Привет.", is_dialogue=False)


def test_silence_forms_differ_by_kind():
    assert rules("……") == set()
    assert "silence" in rules("…")
    assert rules("…", is_dialogue=False) == set()
    assert "silence" in rules("……", is_dialogue=False)


def test_empty_line_is_not_checked():
    assert check_line("", is_dialogue=True) == []
    assert check_line("   ", is_dialogue=False) == []


def test_length_uses_english_as_reference():
    short_en = "Yes."
    assert check_length("Да.", short_en) == []
    long_ru = "Очень длинная русская строка, которой неоткуда взяться при таком коротком английском."
    assert check_length(long_ru, short_en)


def test_length_ignores_missing_english():
    assert check_length("Что-то", "") == []
