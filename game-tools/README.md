# Движковый инструментарий

Всё, что работает с файлами игры. Управление проектом перевода живёт отдельно, в `tools/` (`vnctl.py`, `validate_skills.py`).

Контракт слоя описан в [ADAPTER_CONTRACT.md](ADAPTER_CONTRACT.md). Активный
Steam/LUCA-профиль документирован в [luca-format.md](../docs/project/luca-format.md)
и skill `vn-engine-luca`; старый профиль отдельно описан в
[siglus-format.md](../.agents/skills/vn-engine-siglus/references/siglus-format.md).

## Active Steam/LUCA

| Файл | Назначение |
|------|------------|
| `luca.py` | PAK, байткод, строки, LZW, глобальная релокация и валидация ссылок |
| `export_luca_sources.py` | Детерминированный локальный каталог `ja`/`en`/`zh-Hans` и безопасный манифест |
| `build_luca_test.py` | Диагностическая сборка русских строк; не release builder |
| `game_steam.ps1` | Запуск, загрузка тестового сейва, скриншот и штатный UI-выход |

Полный исходный текст создаётся только в игнорируемом `source/parsed/`.
Канонический русский хранится прямым Unicode и передаётся в PAK только через
relocation-safe сборку.

## Legacy Siglus

| Файл | Назначение |
|------|------------|
| `paths.py` | Корень репозитория и пути к игре из `config/project.yaml`. Абсолютных путей в скриптах быть не должно |
| `siglus.py` | Библиотека формата: заголовки, XOR, LZSS, чтение строк. Эталонная реализация, рабочая — `SPTranslate/uSiglus.pas` |
| `encode_ru.py` | Кодек кириллицы, зеркало `EncodeRussian`/`DecodeRussian`. Запуск без аргументов рисует образец через Pillow |
| `build_font.py` | Сборка шрифтов из `.orig`: сжатие кириллицы, несущие коды, ёлочки |
| `verify_all.py` | Проверка, что все сцены распаковываются и строки читаются |
| `game.ps1` | Запуск игры, навигация по меню, скриншоты, корректный выход |

## delphi/

Консольные харнессы на рабочем коде `uSiglus.pas`, а не на прототипе.

- `TestSiglus.dpr` — round-trip на всём пакете. Регрессионный тест: после правки формата гонять обязательно.
- `MakeTestPck.dpr` — сборка `Scene.pck` с подменёнными строками для проверки на игре.
- `uPaths.pas` — поиск корня репозитория со стороны Delphi.
- `dfm_escape.py` — перевод русских литералов в `.dfm` в `#NNNN`, если файл правился как UTF-8.

Сборка:

```bash
cd game-tools/delphi
dcc32 -B -U<delphi>\lib\win32\release -E. -Ndcu TestSiglus.dpr
```

Относительный путь к `uSiglus.pas` в `uses` резолвится от текущего каталога, поэтому запускать компилятор нужно именно отсюда.

## probes/

В каталоге лежат зонды обеих сборок. Различать обязательно: часть относится к
активной Steam/LUCA, часть — к legacy Siglus. Удалять каталог целиком нельзя.

### Активные, Steam/LUCA

| Скрипт | Назначение |
|--------|------------|
| `scan_luca_scripts.py` | покрытие языковых слотов и типы текстовых опкодов |
| `scan_luca_fonts.py` | покрытие символов в INFO-таблицах шрифтов |
| `validate_luca_relocation.py` | стресс-тест релокации: удлинение всех записей |
| `dump_trilingual.py` | выборка японского, английского и китайского рядом |

Признак принадлежности проверяется импортом, а не названием: активные зонды
импортируют `luca`, legacy — `paths` и `siglus`.

### Legacy Siglus

Доказательная база находок, помеченных `applies_to_build: siglus`. Не для
повседневной работы: это воспроизводимые опыты под старую сборку.

| Скрипт | Находка |
|--------|---------|
| `find_decomp.py` | FND-0003, извлечение 256-байтового ключа из exe |
| `dump_decomp.py` | FND-0004, снятие алгоритма LZSS |
| `check_layout.py` | FND-0006, инвариант пересборки на всех 517 сценах |
| `control_font.py` | FND-0009, контрольный опыт с испорченными метриками |
| `fix_font.py` | FND-0010, опровергнутая гипотеза про шрифты |
| `probe_ranges.py` | FND-0011, проверка диапазонов на игре |
| `check_sjis.py` | FND-0011, сверка модели с cp932 |
| `scan_markup.py` | FND-0026, разметка внутри строк `Scene.pck` |
| `scan_scripts.py` | FND-0031, языковой состав `Scene.pck` |
| `scan_binary_scripts.py` | FND-0032, содержимое `dat/*.dbs` |

`control_font.py` и `fix_font.py` намеренно портят шрифты — это их работа. После них собирать шрифты заново через `build_font.py`.

## Порядок при правке Steam/LUCA

1. Экспортировать и проверить источники: `python game-tools/export_luca_sources.py`.
2. После изменения формата прогнать `validate_luca_relocation.py`.
3. Проверить PAK независимым `Pak` и `validate_script_references()`.
4. Для визуального свойства использовать `game_steam.ps1` и сохранить evidence.
5. Записать новую находку в `docs/project/findings.jsonl`.

Исходник: `Summer Pockets REFLECTION BLUE_Steam/files/SCRIPT.PAK.orig` с хэшем
из `source/manifest.jsonl`.

## Порядок при правке legacy Siglus

1. Закрыть игру: она держит `Scene.pck` и шрифты открытыми, и запись падает с ошибкой доступа.
2. Менять `uSiglus.pas`, при необходимости зеркалить в `siglus.py`.
3. Прогнать `TestSiglus.exe` — round-trip обязан остаться без расхождений.
4. Проверить на игре через `game.ps1 -Action resume`.
5. Записать находку в `docs/project/findings.jsonl`.

Оригиналы, от которых всегда идёт сборка: `Scene.pck.orig`, `dat/font01.ttf.orig`, `dat/font02.ttf.orig`.
