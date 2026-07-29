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
`translation/project-status.yaml` and `vn-project-gatekeeper` has allowed the
requested bootstrap, parser-audit, or cataloguing operation.

## Read first

- `../../../AGENTS.md`
- `../../../game-tools/ADAPTER_CONTRACT.md`
- `../../../docs/data-model.md`
- [Bootstrap checklist](references/bootstrap-checklist.md)

## Procedure

1. Inspect the repository and identify the current parser, builder, input files, outputs, encoding, and runtime dependencies.
2. Preserve working tools. Add wrappers or adapters instead of rewriting them.
3. Run a no-translation round-trip test.
4. Record the result in `docs/project/parser-audit.md`.
5. Determine natural scene boundaries from labels, transitions, choices, participants, and event structure.
6. Produce normalized segment JSONL under `translation/segments/`.
7. Produce `translation/scenes.jsonl`.
8. Ensure IDs are stable, ASCII-only, unique, and spoiler-neutral.
9. Run:

```bash
python tools/vnctl.py validate
python tools/vnctl.py index
python tools/vnctl.py stats
```

10. Select one small pilot scene. Do not start mass translation.

## Required outputs

- successful or clearly documented round-trip result;
- normalized segments;
- scene catalogue;
- updated `config/project.yaml`;
- pilot-scene recommendation;
- concise list of unresolved technical risks.

## Stop conditions

Stop and report rather than mass-translating when:

- the builder cannot recreate a runnable game;
- Cyrillic is not displayed;
- tags or branches are lost;
- IDs cannot be mapped reliably;
- the parser output does not distinguish text from commands.

## Style calibration after the technical pilot

Do not delay the first round-trip for external corpora. After the pilot works:

1. Read `docs/example-policy.md` and `docs/reference-corpus-policy.md`.
2. If local CLANNAD/Rewrite corpora are available, derive abstract style observations only.
3. Update `docs/style-profile.yaml` with status `proposed`.
4. Build character examples primarily from reviewed Summer Pockets lines, not external games.
5. Do not approve the style profile without user review.
