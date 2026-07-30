---
name: vn-bootstrap
description: Audits an existing visual-novel parser and builder, catalogues extracted scripts, creates stable scene and segment IDs, and prepares the translation repository. Use at project start, after receiving new source files, or when the source game version changes.
compatibility: Requires Python 3.11+, git, and local access to the game parser/builder.
metadata:
  version: "1.0"
---

# VN Bootstrap

Use this skill before translating substantial text.

## Lifecycle prerequisite

Invoke this skill only after `vn-project-orchestrator` has read
`translation/project-status.yaml` and `vnctl gate` has allowed the
requested bootstrap, parser-audit, or cataloguing operation.

## Read first

- `../../../AGENTS.md`
- `../../../game-tools/ADAPTER_CONTRACT.md`
- `../../../docs/data-model.md`
- [Bootstrap checklist](references/bootstrap-checklist.md)

## Procedure

1. Inspect the repository and identify the current parser, builder, input files, outputs, encoding, and runtime dependencies.
2. Preserve working tools. Add wrappers or adapters instead of rewriting them.
3. Inventory and align every available internal source-language slot.
4. Generate a deterministic local source catalogue plus a spoiler-safe manifest.
5. Run a no-translation round-trip test.
6. Record the result in `docs/project/parser-audit.md`.
7. Determine natural scene boundaries from labels, transitions, choices, participants, and event structure.
8. Produce normalized source-by-reference segment JSONL under `translation/segments/`.
9. Produce `translation/scenes.jsonl`.
10. Ensure IDs are stable, ASCII-only, unique, spoiler-neutral, and independent
    of mutable byte offsets.
11. Run:

```bash
python tools/vnctl.py validate
python tools/vnctl.py index
python tools/vnctl.py stats
```

12. Select one small pilot scene. Do not start an opaque whole-route request;
    checkpointed scene batches are allowed after the pilot.

## Required outputs

- successful or clearly documented round-trip result;
- source-language coverage report and deterministic source manifest;
- normalized segments;
- scene catalogue;
- updated `config/project.yaml`;
- pilot-scene recommendation;
- concise list of unresolved technical risks.

## Build blockers

The following block a game build or `playable`, but do not block cataloguing,
indexing, reference preparation, or draft translation:

- the builder cannot recreate a runnable game;
- Cyrillic is not displayed;
- tags or branches are lost;
- IDs cannot be mapped reliably;
- the parser output does not distinguish text from commands.

## Style calibration after the technical pilot

Do not delay the first round-trip for external corpora. After the pilot works:

1. Read `docs/example-policy.md` and `docs/reference-corpus-policy.md`.
2. If local corpora are available, let `vn-reference-curator` catalogue only
   fragments that demonstrate a real need; do not pre-annotate the whole corpus.
3. Derive abstract style observations from repeated checked fragments, not grep
   matches or isolated lines.
4. Update `docs/style-profile.yaml` with status `proposed`.
5. Build character examples from reviewed Summer Pockets lines, never external
   games.
6. Do not approve the style profile without user review.
