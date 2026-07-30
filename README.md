# Русский перевод Summer Pockets REFLECTION BLUE

Репозиторий содержит производственную систему перевода и два проверенных
движковых профиля. Активен Steam/LUCA; старая Siglus-сборка сохранена как
legacy.

Пакет не заменяет рабочие инструменты игры. Он добавляет минимальную производственную систему:

- единые правила для агента (`AGENTS.md`);
- спецификацию перевода;
- специализированные Agent Skills и управляющий оркестратор в `.agents/skills/`;
- шаблоны персонажей, глоссария, решений и спойлерных ограничений;
- JSONL-контракт для сцен и реплик;
- SQLite/FTS5-индекс;
- сборщик безопасного контекста сцены;
- автоматические проверки структуры данных.

## Почему здесь нет OpenSpec

На первом этапе OpenSpec добавил бы лишний слой документов. Обычная сцена должна проходить простой цикл:

`каталогизация → контекст → черновик → ревью → периодическая сборка → LQA`.

OpenSpec имеет смысл добавить позднее для крупных изменений архитектуры или массовой переработки правил, но не для каждой сцены.

## Текущее состояние

Технический аудит, round-trip, релокация и кириллица Steam/LUCA подтверждены.
Сейчас идёт каталогизация источников и логических сцен. Актуальные сведения:

- `config/project.yaml` — активный профиль и наборы источников;
- `docs/project/parser-audit.md` — состояние адаптеров;
- `source/manifest.jsonl` — spoiler-safe ревизия исходного сценария;
- `translation/project-status.yaml` — lifecycle.

## Быстрый старт

1. Установите Python 3.11+ и зависимость:

```bash
python -m pip install -r requirements.txt
```

2. Сгенерируйте локальный каталог источников из установленной игры:

```bash
python game-tools/export_luca_sources.py
```

3. Возобновите работу и выполните проверки:

```bash
python tools/validate_skills.py
python tools/vnctl.py resume
python tools/vnctl.py validate
python tools/vnctl.py findings
python tools/vnctl.py questions
python tools/vnctl.py index
python tools/vnctl.py stats
```

`resume` покажет фактический следующий шаг. Сборка контекста сцены
(`python tools/vnctl.py context <SCENE_ID>`) станет доступна после того, как
появятся каталог сцен и сегменты: пока `translation/scenes.jsonl` пуст, вызывать
её не с чем.

## Главные команды

```bash
python tools/vnctl.py validate                 # проверить данные
python tools/vnctl.py resume                   # продолжить с фактического прогресса
python tools/vnctl.py index                    # пересобрать SQLite/FTS5
python tools/vnctl.py stats                    # статистика проекта
python tools/vnctl.py context <SCENE_ID>       # безопасный контекст для перевода
python tools/vnctl.py context <SCENE_ID> -o build/context.md
```

## Движковые адаптеры

Steam/LUCA-инструменты находятся в `game-tools/luca.py`,
`game-tools/export_luca_sources.py` и skill `vn-engine-luca`. Legacy Siglus
остаётся в `legacy-siglus/siglus.py`, Delphi-утилитах и skill
`vn-engine-siglus`. Общий контракт описан в `game-tools/ADAPTER_CONTRACT.md`.

## Защита от спойлеров

- `docs/` содержит только раскрытые и безопасные сведения.
- `private/` может содержать полный анализ сюжета.
- `vnctl context` никогда не выводит `private_reason`; наружу попадают только `safe_rules`.
- названия файлов, коммитов и отчётов не должны раскрывать будущие события.

## Переводческие референсы

Полные сторонние тексты не входят в пакет. Внешний референс — короткий
проверенный фрагмент сцены, выбранный по ситуации и переводческому приёму, а не
строка с похожими словами. Подключение необязательно. Инструкции находятся в
`references/README.md` и `docs/reference-corpus-policy.md`.
