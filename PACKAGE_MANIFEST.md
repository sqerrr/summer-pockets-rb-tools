# Состав стартового пакета

## Управление агентом

- `AGENTS.md` — постоянные правила репозитория.
- `START_AGENT_TASK.md` — готовая первая задача для агента.
- `.agents/skills/` — пять репозиторных Agent Skills.

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
- `translation/scenes.jsonl` — каталог сцен.
- `docs/glossary.yaml` — терминология.
- `docs/decisions.jsonl` — журнал решений.
- `docs/scene-summaries.jsonl` — безопасные резюме.
- `private/constraints.jsonl` — закрытые причины и безопасные правила.

## Инструменты

- `tools/vnctl.py` — validate/index/stats/context.
- `tools/validate_skills.py` — проверка структуры skills.
- `game-tools/ADAPTER_CONTRACT.md` — требования к подключению существующего парсера и сборщика.
- `schemas/` — JSON Schema для сегментов и сцен.
- `tools/tests/` — smoke-тесты, включая защиту от утечки `private_reason`.

## Внешние референсы

- `references/README.md` — локальное подключение CLANNAD/Rewrite.
- `references/local/` — игнорируемый Git каталог для пользовательских корпусов.

## Что намеренно не включено

- OpenSpec;
- Weblate/CAT/TMS;
- векторная база;
- полный текст сторонних переводов;
- игровой парсер/сборщик, поскольку они уже существуют в пользовательском репозитории и требуют адаптера к фактическому формату.
