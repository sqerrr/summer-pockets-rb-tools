# Модель данных

## Сегмент

Одна переводимая реплика или повествовательный блок.

```json
{
  "id": "COMMON_001_SC01_0001",
  "file_id": "COMMON_001",
  "scene_id": "COMMON_001_SC01",
  "order": 1,
  "speaker": "HAIRI",
  "source": "……なんだ、それ。",
  "translation": "…Это ещё что?",
  "status": "draft",
  "flags": [],
  "notes": [],
  "decision_ids": [],
  "source_hash": "sha256:...",
  "metadata": {
    "voice": "voice/file.ogg",
    "tags": []
  }
}
```

Обязательные поля определены в `config/qa-rules.yaml`.

## Сцена

```json
{
  "scene_id": "COMMON_001_SC01",
  "file_id": "COMMON_001",
  "order": 1,
  "route": "common",
  "title_safe": "Прибытие на остров",
  "segment_ids": ["COMMON_001_SC01_0001"],
  "previous_scene": null,
  "next_scene": "COMMON_001_SC02",
  "status": "todo"
}
```

## Решение

```json
{
  "id": "DEC-0001",
  "type": "terminology",
  "scope": "global",
  "segment_ids": [],
  "decision": "...",
  "reason_safe": "...",
  "status": "approved",
  "supersedes": null
}
```

## Резюме сцены

```json
{
  "scene_id": "COMMON_001_SC01",
  "safe_summary": "...",
  "participants": ["HAIRI"],
  "revealed_facts": [],
  "relationship_changes": [],
  "status": "approved"
}
```

## Правила идентификаторов

- ID устойчивы после создания.
- ID не содержат сюжетных спойлеров.
- ID используют ASCII, цифры и `_`/`-`.
- Перемещение сцены не должно автоматически менять ID.
- Если исходник обновился, сохранить ID и обновить `source_hash`.
