"""Проверка разметки на случаях из сравнительного опыта.

Обе модели испортили строки с разметкой, и ни одна проверка этого не заметила.
Случаи взяты дословно оттуда.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from textrules import check_markup, strip_ruby  # noqa: E402


def rules(ja, ru):
    return {f.rule for f in check_markup(ja, ru)}


def test_ruby_must_be_stripped():
    ja = "$[鳥白島$/とり_しろ_じま$]、か。"
    assert rules(ja, "Торисиро, значит.") == set()
    # Ровно то, что сделала модель B.
    assert "markup" in rules(ja, "$[Торисиро$/とり_しろ_じま$], значит.")


def test_ruby_stripping_preserves_visible_text_only():
    assert strip_ruby("$[鳥白島$/とり_しろ_じま$]、か。") == "鳥白島、か。"
    assert strip_ruby("Обычные [скобки]") == "Обычные [скобки]"


def test_variable_must_survive():
    ja = "$(101)に仕掛けた$(102)に島モンが引っかかっていた。"
    assert rules(ja, "В $(102), поставленной у $(101), попался островомон.") == set()
    # Ровно то, что сделали обе модели: переменные исчезли.
    assert "markup" in rules(ja, "Тогда я…")


def test_variable_must_not_be_invented():
    assert "markup" in rules("普通の行。", "Обычная строка $(101).")


def test_colour_codes_are_paired():
    ja = "$C[00ff00]зелёное$C[] обычное"
    assert rules(ja, "$C[00ff00]зелёное$C[] обычное") == set()
    assert "markup" in rules(ja, "зелёное обычное")


def test_branch_separator_count_must_match():
    ja = "選択肢A$d選択肢B$d選択肢C$d選択肢D"
    assert rules(ja, "Вариант А$dВариант Б$dВариант В$dВариант Г") == set()
    # Потеря разделителя склеивает два варианта в один.
    assert "markup" in rules(ja, "Вариант А$dВариант Б$dВариант В Вариант Г")
    # И лишний разделитель тоже ломает блок.
    assert "markup" in rules(ja, "А$dБ$dВ$dГ$dД")


def test_control_token_sequence_must_match():
    ja = "選択肢A$d$w選択肢B"
    assert rules(ja, "Вариант А$d$wВариант Б") == set()
    assert "markup" in rules(ja, "Вариант А$dВариант Б")
    assert "markup" in rules(ja, "Вариант А$w$dВариант Б")


def test_speed_and_song_codes_must_survive_exactly():
    assert rules("$S(044,1)歌♪", "$S(044,1)Песня♪") == set()
    assert "markup" in rules("$S(044,1)歌♪", "Песня♪")
    assert rules("$S(060)歌$S", "$S(060)Песня$S") == set()
    assert "markup" in rules("$S(060)歌$S", "$S(060)Песня")
    assert rules("$S056歌$S000", "$S056Песня$S000") == set()


def test_emphasis_span_keeps_wrappers_but_translates_content():
    ja = "知りませんか？　$[$bって$]"
    assert rules(ja, "Не видели? $[$bВот так.$]") == set()
    assert "markup" in rules(ja, "Не видели? Вот так.")
    assert "markup" in rules(ja, "$[$bНе видели? Вот так.")


def test_plain_text_untouched():
    assert rules("潮風が顔に吹き付ける。", "Морской ветер бьёт в лицо.") == set()


def test_empty_translation_not_checked():
    assert check_markup("$(101)あり", "") == []
