#!/usr/bin/env python3
"""Механические проверки русского текста по утверждённым решениям проекта.

Смысл модуля в одном: правило, которое можно проверить кодом, не должно жить в
инструкции. Модель забывает на длинной дистанции, проверка не забывает.

Каждая проверка ссылается на решение, из которого она следует. Если решение
отозвано, проверка снимается вместе с ним, а не остаётся жить своей жизнью.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --- DEC-0019: сплошная ё --------------------------------------------------
# Слова, где по-русски пишется е, но легко ошибиться в другую сторону,
# здесь не нужны: мы ловим только пропуск ё там, где она обязана быть.
# Список замкнутый и покрывает самые частые случаи; расширяется по мере находок.
YO_REQUIRED = {
    "все": "всё", "еще": "ещё", "ее": "её", "чем": "чём", "нем": "нём",
    "тем": "тём", "зачем": "зачём", "причем": "причём", "черт": "чёрт",
    "черный": "чёрный", "черная": "чёрная", "черное": "чёрное",
    "желтый": "жёлтый", "зеленый": "зелёный", "теплый": "тёплый",
    "легкий": "лёгкий", "темный": "тёмный", "серьезно": "серьёзно",
    "надежный": "надёжный", "далекий": "далёкий", "веселый": "весёлый",
    "тяжелый": "тяжёлый", "идем": "идём", "нашел": "нашёл", "пришел": "пришёл",
    "ушел": "ушёл", "прошел": "прошёл", "ребенок": "ребёнок", "сестренка": "сестрёнка",
    "почему": None,  # исключение: здесь ё не нужна, стоит как напоминание
}
YO_REQUIRED = {k: v for k, v in YO_REQUIRED.items() if v}

# --- DEC-0027: фонетические редукции запрещены -----------------------------
REDUCTIONS = {
    "щас", "ща", "чо", "чё", "ваще", "чёт", "чет", "тя", "те6я",
    "щя", "скока", "тока", "када", "ниче", "ничё", "хош", "хошь",
}

# --- DEC-0026: молчание ----------------------------------------------------
SILENCE_LINE = re.compile(r"^[…\.\s]+$")
SILENCE_DIALOGUE = "……"
SILENCE_NARRATION = "…"

# --- DEC-0029: многоточие и знаки ------------------------------------------
THREE_DOTS = re.compile(r"\.\.\.")
SPACE_BEFORE_ELLIPSIS = re.compile(r"\s…")
WRONG_QUESTION_ELLIPSIS = re.compile(r"\?…|\?\.\.\.|…\?")
WRONG_BANG_ELLIPSIS = re.compile(r"!…|!\.\.\.|…!")
WRONG_INTERROBANG = re.compile(r"!\?")

# --- DEC-0030: растяжение --------------------------------------------------
# Три и более одинаковые буквы подряд - признак удвоения вместо дефиса.
LETTER_TRIPLE = re.compile(r"([а-яёА-ЯЁ])\1{2,}")

# --- DEC-0031: восклицания и капс ------------------------------------------
DOUBLE_BANG = re.compile(r"(?<!!)!!(?!!)")
MANY_BANGS = re.compile(r"!{4,}")
CAPS_RUN = re.compile(r"[А-ЯЁ]{4,}")

# --- DEC-0022: реплика без кавычек -----------------------------------------
LEADING_DASH = re.compile(r"^\s*[-–—]\s")
GUILLEMETS = re.compile(r"[«»]")


@dataclass(frozen=True)
class Finding:
    rule: str
    decision: str
    message: str
    severity: str = "error"


def check_line(text: str, *, is_dialogue: bool) -> list[Finding]:
    """Проверить одну переведённую строку. Пустая строка проверок не требует."""
    out: list[Finding] = []
    if not text.strip():
        return out

    lowered = text.lower()

    for bare, correct in YO_REQUIRED.items():
        if re.search(rf"\b{bare}\b", lowered):
            out.append(Finding("yo", "DEC-0019",
                               f"пропущена ё: {bare} -> {correct}"))

    for word in REDUCTIONS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            out.append(Finding("reduction", "DEC-0027",
                               f"фонетическая редукция: {word}"))

    if THREE_DOTS.search(text):
        out.append(Finding("ellipsis", "DEC-0029", "три точки вместо знака …"))
    if SPACE_BEFORE_ELLIPSIS.search(text):
        out.append(Finding("ellipsis", "DEC-0029", "пробел перед многоточием"))
    if WRONG_QUESTION_ELLIPSIS.search(text):
        out.append(Finding("ellipsis", "DEC-0029", "должно быть ?.. а не ?…"))
    if WRONG_BANG_ELLIPSIS.search(text):
        out.append(Finding("ellipsis", "DEC-0029", "должно быть !.. а не !…"))
    if WRONG_INTERROBANG.search(text):
        out.append(Finding("ellipsis", "DEC-0029", "должно быть ?! а не !?"))

    if LETTER_TRIPLE.search(text):
        out.append(Finding("stretch", "DEC-0030",
                           "растяжение удвоением букв вместо дефиса"))

    if DOUBLE_BANG.search(text):
        out.append(Finding("bangs", "DEC-0031", "ступень !! не используется"))
    if MANY_BANGS.search(text):
        out.append(Finding("bangs", "DEC-0031", "более трёх восклицательных знаков"))
    if CAPS_RUN.search(text):
        out.append(Finding("caps", "DEC-0031",
                           "серия заглавных: допустима только для крика или скандирования",
                           severity="warning"))

    if is_dialogue and LEADING_DASH.match(text):
        out.append(Finding("quotes", "DEC-0022", "тире в начале реплики"))
    if GUILLEMETS.search(text):
        out.append(Finding("quotes", "DEC-0022",
                           "ёлочки не отображаются в активной сборке (FND-0039)",
                           severity="warning"))

    if SILENCE_LINE.match(text):
        expected = SILENCE_DIALOGUE if is_dialogue else SILENCE_NARRATION
        if text.strip() != expected:
            out.append(Finding("silence", "DEC-0026",
                               f"молчание записывается как {expected!r}"))

    return out


def check_length(ru: str, en: str, *, margin: float = 1.35) -> list[Finding]:
    """Длина русской строки против английской.

    Английский слот отображается в игре, значит он и есть проверенный предел.
    Русский обычно длиннее английского примерно на пятую часть; запас берём с
    поправкой на то, что мера грубая.
    """
    if not ru.strip() or not en.strip():
        return []
    limit = max(40, int(len(en) * margin))
    if len(ru) > limit:
        return [Finding("length", "FND-0037",
                        f"длина {len(ru)} против английской {len(en)}, предел {limit}",
                        severity="warning")]
    return []
