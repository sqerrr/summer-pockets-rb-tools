# Движковый инструментарий активной сборки

Всё, что работает с файлами Steam-сборки на LucaSystem. Управление проектом
перевода живёт отдельно, в `tools/` (`vnctl.py`, `validate_skills.py`).
Инструменты снятой с выпуска сборки — в `legacy-siglus/`, см. `DEC-0015`.

Контракт слоя — [ADAPTER_CONTRACT.md](ADAPTER_CONTRACT.md), формат —
[luca-format.md](../docs/project/luca-format.md), порядок работы — skill
`vn-engine-luca`.

## Рабочий слой

| Файл | Назначение |
|------|------------|
| `luca.py` | PAK, байткод, строки, LZW, глобальная релокация и валидация ссылок |
| `export_luca_sources.py` | Детерминированный каталог `ja`/`en`/`zh-Hans` и безопасный манифест |
| `build_luca_test.py` | Диагностическая сборка русских строк; **не** release builder |
| `luca_image.py` | Строгий декодер CZ0-CZ3 и lossless encoder CZ0 |
| `build_luca_opening_images.py` | Сборка одобренных стартовых интертитров из `translation/ui/opening-titles.json` |
| `game_steam.ps1` | Запуск, загрузка тестового сейва, capture вступления, скриншот и штатный UI-выход |

Полный исходный текст создаётся только в игнорируемом `source/parsed/`.
Канонический русский хранится прямым Unicode и попадает в PAK только через
relocation-safe сборку.

Стартовые интертитры собираются отдельно из hash-pinned pristine
`build/steam/OTHCG.pristine.PAK`. Канонический файл содержит все 17 строк,
точные entry ID, статус пользовательского одобрения и render profile:

```bash
python game-tools/build_luca_opening_images.py
python game-tools/build_luca_opening_images.py --install
```

Результат: `build/steam/OTHCG.russian-opening.PAK` и
`build/steam/opening-images-receipt.json`. Перед `--install` игра должна быть
закрыта; установленный архив можно безопасно вернуть командой
`python game-tools/build_luca_opening_images.py --restore-installed`.

## probes/

Воспроизводимые опыты, подтверждающие конкретные утверждения о движке. Не для
повседневной работы.

| Скрипт | Назначение |
|--------|------------|
| `scan_luca_scripts.py` | покрытие языковых слотов и типы текстовых опкодов |
| `scan_luca_fonts.py` | покрытие символов в INFO-таблицах шрифтов |
| `validate_luca_relocation.py` | стресс-тест релокации: удлинение всех записей |
| `dump_trilingual.py` | выборка японского, английского и китайского рядом |

Признак принадлежности проверяется импортом, а не названием: здешние зонды
импортируют `luca`, зонды старой сборки — `paths` и `siglus`.

## Порядок при правке

1. Экспортировать и проверить источники: `python game-tools/export_luca_sources.py`.
2. После изменения формата прогнать `validate_luca_relocation.py`.
3. Проверить PAK независимым `Pak` и `validate_script_references()`.
4. Для визуального свойства использовать `game_steam.ps1` и сохранить evidence.
5. Записать новую находку в `docs/project/findings.jsonl`.

Собирать только из `Summer Pockets REFLECTION BLUE_Steam/files/SCRIPT.PAK.orig`
с хэшем из `source/manifest.jsonl`. Число, ID, имена и порядок записей PAK не
менять; изменение длины допустимо только через глобальную релокацию.

Отладочные скриншоты пишутся в `shots-steam/` и в Git не идут. Доказательные
кадры кладутся осознанно в `docs/project/evidence/` и сжимаются.
