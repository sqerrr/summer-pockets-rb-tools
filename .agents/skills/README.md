# Репозиторные Agent Skills

Эти skills расположены в `.agents/skills`, чтобы Codex мог обнаруживать их на уровне репозитория. Каждый навык соответствует открытому формату Agent Skills и содержит обязательный `SKILL.md`.

Каждый новый логический рабочий блок проходит через управляющий слой один раз:

1. `vn-project-orchestrator`
2. Один или несколько специализированных skills, нужных для завершения блока:
   `vn-bootstrap`, `vn-context-builder`, `vn-scene-translator`,
   `vn-scene-reviewer`, `vn-knowledge-curator`, `vn-engine-luca`,
   `vn-engine-siglus`,
   `vn-reference-curator` или `vn-reference-retriever`.

Движковый слой выбирается по `project.active_build`: `vn-engine-luca` обслуживает
активную Steam-версию и `SCRIPT.PAK`, а `vn-engine-siglus` сохраняет отдельный
legacy-профиль `Scene.pck`, TTF и carrier encoding.

Референсный слой необязателен: `vn-reference-curator` каталогизирует локальные
фрагменты, а `vn-reference-retriever` подключает не более 1–3 примеров только
после анализа конкретной сцены. Отсутствие референса не блокирует перевод.

Оркестратор не заменяет специализированные навыки. Повторная проверка между
подшагами одного разрешённого блока не нужна, пока не изменились политика,
состояние проекта или тип операции.
