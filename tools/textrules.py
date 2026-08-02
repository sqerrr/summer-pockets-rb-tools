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
# Только однозначные случаи. Слово, у которого есть законный омограф без ё,
# сюда попадать не должно: ложное срабатывание хуже пропуска, потому что
# переводчик начинает обходить слово, и проверка деформирует текст вместо того
# чтобы его проверять. Так и случилось со словом «все» - оно снято.
# Исключены как омографы: все/всё, чем/чём, нем/нём, тем/тём, небе/нёбе,
# осел/осёл, совершенный/совершённый, узнает/узнаёт.
YO_REQUIRED = {
    "еще": "ещё", "ее": "её", "причем": "причём", "черт": "чёрт",
    "черный": "чёрный", "черная": "чёрная", "черное": "чёрное",
    "желтый": "жёлтый", "зеленый": "зелёный", "теплый": "тёплый",
    "легкий": "лёгкий", "темный": "тёмный", "серьезно": "серьёзно",
    "надежный": "надёжный", "далекий": "далёкий", "веселый": "весёлый",
    "тяжелый": "тяжёлый", "идем": "идём", "нашел": "нашёл", "пришел": "пришёл",
    "ушел": "ушёл", "прошел": "прошёл", "ребенок": "ребёнок",
    "сестренка": "сестрёнка", "тетя": "тётя", "звезды": "звёзды",
    "полет": "полёт", "берет": "берёт", "несет": "несёт", "живет": "живёт",
}

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
        # A hyphen is a word boundary to \b, but `тя` is also part of the
        # approved suffix `-тян` and phonetic stretches such as `тя-а-ан`.
        pattern = rf"(?<![\w-]){re.escape(word)}(?![\w-])" if word == "тя" else rf"\b{re.escape(word)}\b"
        if re.search(pattern, lowered):
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
        out.append(Finding("quotes", "DEC-0033",
                           "ёлочки не отображаются в активной сборке (FND-0039): "
                           "кавычки записываются прямыми знаками"))

    if SILENCE_LINE.match(text):
        expected = SILENCE_DIALOGUE if is_dialogue else SILENCE_NARRATION
        if text.strip() != expected:
            out.append(Finding("silence", "DEC-0026",
                               f"молчание записывается как {expected!r}"))

    return out


# --- FND-0050: движковая разметка ------------------------------------------
RUBY = re.compile(r"\$\[([^\]]*?)\$/[^\]]*?\$\]")
VARIABLE = re.compile(r"\$\([0-9]+\)")
COLOUR = re.compile(r"\$C\[[0-9a-fA-F]*\]")
# Разделитель веток выбора: 1002 вхождения в 217 записях. Потеря одного
# разделителя склеивает два варианта в один, и блок выбора ломается молча.
BRANCH = re.compile(r"\$d")
# Управление скоростью/пением встречается в двух физических формах:
# `$S(044,1)…$S` и `$S056…$S000`. Потеря кода не портит JSONL, но меняет
# подачу в игре, поэтому сравниваются сами токены и их параметры.
SPEED = re.compile(r"\$S(?:\([^)]*\)|[0-9]+)?")


def strip_ruby(text: str) -> str:
    """Remove a LUCA reading annotation but keep its visible base text."""
    return RUBY.sub(lambda match: match.group(1), text)


def check_markup(source_ja: str, ru: str) -> list[Finding]:
    """Движковая разметка: что обязано уцелеть, а что обязано исчезнуть.

    Переменная подставляется движком - её удаление ломает строку молча, и
    увидеть это можно только в игре. Цветовой код парный. Рубиновая аннотация,
    наоборот, даёт чтение иероглифа и в русском бессмысленна: остаётся основа,
    а кана и сама конструкция снимаются.
    """
    if not ru.strip():
        return []
    out: list[Finding] = []

    src_vars = VARIABLE.findall(source_ja)
    ru_vars = VARIABLE.findall(ru)
    if sorted(src_vars) != sorted(ru_vars):
        out.append(Finding("markup", "FND-0050",
                           f"переменные подстановки не совпадают: "
                           f"в исходнике {src_vars or 'нет'}, в переводе {ru_vars or 'нет'}"))

    if len(COLOUR.findall(source_ja)) != len(COLOUR.findall(ru)):
        out.append(Finding("markup", "FND-0050",
                           "число цветовых кодов не совпадает с исходником"))

    src_branches = len(BRANCH.findall(source_ja))
    ru_branches = len(BRANCH.findall(ru))
    if src_branches != ru_branches:
        out.append(Finding("markup", "FND-0050",
                           f"разделителей веток выбора {ru_branches}, "
                           f"в исходнике {src_branches}: блок выбора сломан"))

    src_speed = SPEED.findall(source_ja)
    ru_speed = SPEED.findall(ru)
    if src_speed != ru_speed:
        out.append(Finding("markup", "FND-0050",
                           f"коды скорости/пения не совпадают: "
                           f"в исходнике {src_speed or 'нет'}, "
                           f"в переводе {ru_speed or 'нет'}"))

    if RUBY.search(ru):
        out.append(Finding("markup", "FND-0050",
                           "рубиновая аннотация оставлена в переводе: "
                           "она даёт чтение иероглифа и в русском не нужна"))

    return out


def check_names(source_ja: str, speaker: str | None, ru: str,
                names: dict[str, str]) -> list[Finding]:
    """Имя из справочника должно писаться утверждённой формой.

    Русские падежи не позволяют сравнивать целиком, поэтому сверяется основа:
    отбрасываются два последних знака, что покрывает обычное склонение и не
    даёт ложных срабатываний на «Широхе» или «Шизуку».

    Проверка мягкая: имя может быть заменено местоимением или опущено вовсе,
    и это нормальный перевод. Ошибкой считается только другое написание.
    """
    if not ru.strip() or not names:
        return []
    # Имя говорящего выводит движок отдельным полем, внутри строки его нет.
    # Включать его в поиск - гарантированное ложное срабатывание на каждой
    # реплике рассказчика: его имя стоит в поле, но в тексте не упоминается.
    haystack = source_ja
    out: list[Finding] = []
    for source, russian in names.items():
        if source not in haystack:
            continue
        # У составной записи проверяется последнее слово: родовая часть по
        # DEC-0021 называется один раз, дальше в тексте стоит только имя.
        head = russian.split()[-1] if russian.split() else russian
        stem = head[:-2] if len(head) > 4 else head
        if stem.lower() in ru.lower():
            continue
        # Имя упомянуто в исходнике, но его формы в переводе нет. Это законно,
        # если оно заменено местоимением; сообщаем, но не блокируем.
        out.append(Finding("names", "DEC-0035",
                           f"имя {source} -> ожидалась форма {russian}",
                           severity="warning"))
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
