# Data Model

All JSONL files use UTF-8 and one JSON object per line.

## Source Record

Source records are local and ignored by Git.

```json
{"source_id":"SRC_000001","scene_id":"SCN0001","order":1,"speaker":"Narrator","texts":{"source":"Hello, {name}.","reference":"A greeting."},"protected_tokens":["{name}"],"meta":{}}
```

Required fields are `source_id`, `scene_id`, `order`, and `texts`. IDs are
opaque strings. `texts` must contain every configured source language.
`protected_tokens` records an exact ordered token sequence in addition to the
regular expressions in project configuration.

## Segment

Segments are canonical tracked translation state.

```json
{"id":"SEG_...","source_id":"SRC_000001","scene_id":"SCN0001","order":1,"speaker":"Narrator","source_hash":"sha256:...","translation":"","status":"todo","flags":[],"confidence":null,"last_actor":null,"authors":[]}
```

The pipeline may change only `translation`, `status`, `flags`, `confidence`,
and tool-owned `last_actor`/`authors`. `authors` is cumulative so a later editor
cannot erase translator provenance. `ingest` preserves those fields for an
existing `source_id` and refuses to remove existing records without a migration.

## Translation Patch

The first row binds the patch to the exact current scene and source hash:

```json
{"type":"translation_patch","scene_id":"SCN0001","base_sha256":"sha256:..."}
{"id":"SEG_...","translation":"Target text.","status":"draft","flags":[],"confidence":"high"}
```

Stale patches and patches that do not cover every editable row are rejected
without changing canonical files.

## Open Question

```json
{"id":"OQ-0001","kind":"terminology","scene_id":"SCN0001","segment_ids":["SEG_..."],"question":"Choose a stable form.","provisional":"Working form","status":"open"}
```

Every open question requires a nonempty `provisional` that matches the working
translation decision. Agents write proposals under ignored `build/`; the
orchestrator imports them through `vnctl questions --import-file`.

## Private Constraint

Private constraints are ignored by Git. Only `safe_rules` may enter generated
work or review packages.

```json
{"id":"PC-0001","reveal_after":"SCN0040","private_reason":"Hidden explanation.","safe_rules":["Keep the subject ambiguous."]}
```

## Review Files

An issue file starts with metadata and then one object per issue:

```json
{"type":"review","review_id":"REV-SCN0001-01","scene_id":"SCN0001","base_sha256":"sha256:...","verdict":"revise"}
{"issue_id":"REV-SCN0001-01-I001","segment_id":"SEG_...","severity":"major","message":"Meaning changed.","suggested_translation":"Corrected text."}
```

A resolution file starts with metadata and contains exactly the currently open
issue IDs:

```json
{"type":"resolutions","review_id":"REV-SCN0001-01","base_sha256":"sha256:..."}
{"issue_id":"REV-SCN0001-01-I001","disposition":"applied","reason":"Restores the source meaning.","changes":[{"id":"SEG_...","translation":"Corrected text.","flags":[]}]}
```
