# Translation output contract

Each output line:

```json
{
  "id": "COMMON_001_SC01_0001",
  "translation": "Русский текст",
  "status": "draft",
  "flags": [],
  "translator_note_safe": "",
  "confidence": "high"
}
```

Allowed confidence values:

- `high`
- `medium`
- `low`

A `low` line must contain at least one review flag.

`translation` is always canonical direct-Unicode Russian. Never emit carrier
codes, packed bytes, or renderer-specific glyph substitutions here.

After the JSONL block, a separate safe report may list:

- new proposed terms;
- lines needing source or context review;
- humour decisions;
- technical risks.

Never put future-story explanations in the report.
