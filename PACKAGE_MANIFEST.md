# Состав стартового пакета

## Управление агентом

- `AGENTS.md` — постоянные правила репозитория.
- `START_AGENT_TASK.md` — готовая первая задача для агента.
- `.agents/skills/` — репозиторные Agent Skills, включая управляющий оркестратор и gatekeeper.

## Спецификации и документация

- `docs/translation-spec.md` — полная начальная политика перевода.
- `docs/workflow.md` — жизненный цикл сцены.
- `docs/spoiler-policy.md` — разделение безопасных и закрытых знаний.
- `docs/data-model.md` — JSONL-контракты.
- `docs/example-policy.md` — работа с few-shot примерами.
- `docs/reference-corpus-policy.md` — CLANNAD/Rewrite как локальный стилевой корпус.
- `docs/style-profile.yaml` — будущая калибровка общего русского стиля.
- `docs/characters/_template.md` — карточка персонажа.

## Данные

- `translation/segments/` — переводимые сегменты.
- `source/manifest.jsonl` — spoiler-safe манифест внутренних источников.
- `source/parsed/` — локальный игнорируемый полный каталог источников.
- `translation/scenes.jsonl` — каталог сцен.
- `docs/glossary.yaml` — терминология.
- `docs/decisions.jsonl` — журнал решений.
- `docs/scene-summaries.jsonl` — безопасные резюме.
- `private/constraints.jsonl` — закрытые причины и безопасные правила.

## Инструменты

- `tools/vnctl.py` — validate/index/stats/context.
- `tools/validate_skills.py` — проверка структуры skills.
- `game-tools/ADAPTER_CONTRACT.md` — требования к подключению существующего парсера и сборщика.
- `game-tools/luca.py`, `export_luca_sources.py` — активный Steam/LUCA-адаптер и каталог источников.
- `game-tools/siglus.py`, `SPTranslate/` — legacy Siglus-адаптер.
- `schemas/` — JSON Schema для сегментов и сцен.
- `tools/tests/` — smoke-тесты, включая защиту от утечки `private_reason`.

## Внешние референсы

- `references/README.md` — локальное подключение CLANNAD/Rewrite.
- `references/local/` — игнорируемый Git каталог для пользовательских корпусов.
- `schemas/reference-fragment.schema.json` — формат короткого сценового
  фрагмента со статусами `raw`/`usable`/`gold`/`rejected`.

## Что намеренно не включено

- OpenSpec;
- Weblate/CAT/TMS;
- векторная база;
- полный текст сторонних переводов;
- игровые архивы, исполняемые файлы и полный извлечённый текст текущей ВН.
