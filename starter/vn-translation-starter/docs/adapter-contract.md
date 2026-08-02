# Engine Adapter Contract

The core pipeline is engine-neutral. An adapter owns all game-format details.

## Required Operations

```text
parse       pristine game data -> normalized source records
build       canonical target text -> rebuilt game data
read-back   rebuilt game data -> normalized source records
smoke       minimal game startup or equivalent runtime check
roundtrip   parse -> unchanged build -> independent read-back comparison
```

## Parse Requirements

- stable opaque `source_id` values that do not depend on text or mutable byte
  offsets;
- original order and logical `scene_id`;
- all aligned language slots with explicit language tags;
- speaker label when available;
- source-record hash;
- all control tokens, placeholders, choices, jumps, and metadata needed to
  rebuild without loss;
- no source text committed to Git.

## Build Requirements

- accept canonical Unicode target text;
- preserve all non-translatable fields;
- preserve protected tokens and control-flow structure;
- relocate references when the format requires it;
- fail on unknown, missing, duplicate, or extra IDs;
- write a machine-readable receipt;
- never patch the only pristine original in place.

## Round-Trip Gate

Before translating real text:

1. Hash the pristine input.
2. Parse it twice and compare deterministic catalog hashes.
3. Build without text changes.
4. Read the result independently.
5. Compare record count, order, every language payload, control tokens, choices,
   jumps, and adapter-owned metadata.
6. Run a smoke test.
7. Save a receipt containing the pristine hash, catalog hash, adapter version,
   counts, comparison result, and smoke-test result.

Set `project.pristine_sha256` in `config/project.yaml` to the exact pristine
input hash. The receipt must match that value, the active adapter, and the
current normalized source catalog. Translation and review commands remain
locked while any of those checks fail.

A release command must refuse to run when the receipt is missing, failed, or
does not match the configured pristine hash.
