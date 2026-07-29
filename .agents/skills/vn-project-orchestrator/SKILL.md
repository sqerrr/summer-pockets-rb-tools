---
name: vn-project-orchestrator
description: Enforces translation project phases and critical gates before parser, catalogue, reference, knowledge, translation, review, build, glossary, or specification work. Use before every operation that changes or advances the VN translation project.
compatibility: Requires Python 3.11+, PyYAML, and tools/vnctl.py.
metadata:
  version: "1.0"
---

# VN Project Orchestrator

This is the mandatory entry point for project work. It coordinates the process
but never translates text and never performs literary review itself.

## Mandatory startup

1. Read `../../../AGENTS.md`.
2. Read `../../../translation/project-status.yaml`.
3. Classify the requested operation using the CLI names below.
4. Invoke `vn-project-gatekeeper` and run:

```bash
python tools/vnctl.py gate <operation> --format yaml
```

5. Stop when `allowed: false`. A normal request such as "continue" or
   "translate the scene" cannot override the result.
6. Run `python tools/vnctl.py advance` when the user asks what comes next or
   when the current phase appears complete.

## Operation names

| Work | Gate operation | Delegated skill |
|---|---|---|
| Repository/parser audit and cataloguing | `audit-parser`, `catalogue-sources` | `vn-bootstrap` |
| Scene pack, fonts, encoding, game build | `build-game-text` | `vn-engine-siglus` |
| Reference corpus audit | `audit-reference-corpus` | `vn-bootstrap` |
| Index and knowledge preparation | `build-index`, `curate-knowledge` | `vn-bootstrap`, then `vn-knowledge-curator` |
| Pilot context and translation | `build-pilot-context`, `translate-pilot` | `vn-context-builder`, then `vn-scene-translator` |
| Production context and translation | `build-production-context`, `translate-production` | `vn-context-builder`, then `vn-scene-translator` |
| Review | `review-pilot`, `review-production` | `vn-scene-reviewer` |
| Glossary/knowledge updates | `modify-glossary`, `curate-knowledge` | `vn-knowledge-curator` |
| Final checks | `final-lqa` | `vn-scene-reviewer`, `vn-engine-siglus` |

`mass-translate` and premature `approve-translation` remain blocked even when
requested directly.

## Evidence and completion

Before treating delegated work as complete:

1. Require a concrete artifact or reproducible command result.
2. Verify that a file used as evidence exists.
3. Never infer `passed` from prose, confidence, or an agent assertion alone.
4. Update a gate only through:

```bash
python tools/vnctl.py set-gate <gate> <status> --evidence <path>
```

5. Run the relevant validation and build checks.
6. Run `python tools/vnctl.py advance` when all gates for the current phase are
   passed. The command records any phase and permission transition.
7. Confirm that `translation/project-history.jsonl` received an append-only
   entry. Never edit or delete old history records.

## Delegation rules

- `vn-bootstrap` owns repository audit, parser verification, catalogue, stable
  IDs, segmentation, and initial index preparation.
- `vn-engine-siglus` owns Scene.pck, fonts, carrier encoding, and in-game
  evidence.
- `vn-context-builder` must precede every allowed scene translation or review.
- `vn-scene-translator` creates drafts only after an allowed pilot or production
  gate result.
- `vn-scene-reviewer` performs independent review; the orchestrator does not
  substitute for it.
- `vn-knowledge-curator` updates durable knowledge only after the relevant gate
  permits it.

## Policy changes

The user may explicitly request a change to the gate policy itself. Treat that
as a configuration change: edit the policy consciously, validate it, explain
the impact, and append history. Never reinterpret an ordinary work request as a
policy change.
