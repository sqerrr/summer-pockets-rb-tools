---
name: vn-project-orchestrator
description: Resumes project state, checks the gate for one logical work block, and delegates the whole allowed block without repeated permission checks.
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
3. Run `python tools/vnctl.py resume`.
4. Classify the requested logical work block using the CLI names below.
5. Invoke `vn-project-gatekeeper` and run:

```bash
python tools/vnctl.py gate <operation> --format yaml
```

6. Stop when `allowed: false`. A normal request such as "continue" or
   "translate the scene" cannot override the result.
7. When allowed, complete all substeps of that block without repeated gate
   checks. Recheck only if project status, policy, or operation type changes.
8. Run `python tools/vnctl.py advance` only when a milestone is complete.

## Operation names

| Work | Gate operation | Delegated skill |
|---|---|---|
| Inspect repository | `inspect-repository` | orchestrator or relevant specialist |
| Documentation and specifications | `create-documentation`, `modify-specifications` | relevant specialist |
| Repository/parser audit and cataloguing | `audit-parser`, `catalogue-sources` | `vn-bootstrap` |
| Test-line preparation | `translate-test-lines` | active engine adapter |
| Verification build: test pack, fonts, encoding, in-game evidence | `verify-engine` | active engine adapter |
| Release build of translated text | `build-game-text` | active engine adapter |
| Reference corpus audit and fragment curation | `audit-reference-corpus` | `vn-bootstrap`, `vn-reference-curator` |
| Index and knowledge preparation | `build-index`, `curate-knowledge` | `vn-bootstrap`, then `vn-knowledge-curator` |
| Pilot context and translation | `build-pilot-context`, `translate-pilot` | `vn-context-builder`, then `vn-scene-translator` |
| Production context and translation | `build-production-context`, `translate-production` | `vn-context-builder`, then `vn-scene-translator` |
| Checkpointed queue of scenes | `batch-translate` | context builder, translator, reviewer, curator |
| Review | `review-pilot`, `review-production` | `vn-scene-reviewer` |
| Glossary/knowledge updates | `modify-glossary`, `curate-knowledge` | `vn-knowledge-curator` |
| Final checks | `final-lqa` | `vn-scene-reviewer`, active engine adapter |

`mass-translate` means one opaque whole-route request and remains blocked.
`batch-translate` is allowed after the production gates: each scene is saved,
validated, independently reviewed, and checkpointed before the next one.

`verify-engine` covers builds made to produce evidence: a handful of test lines,
a rebuilt font, a screenshot from the running game. It is available in every
phase because the roundtrip, Cyrillic, tag and layout gates cannot be closed
without it. It does not authorise shipping translated content; that stays behind
`build-game-text` and its tag, choice and Cyrillic gates. The CLI cannot tell the
two apart by itself, so the distinction is a rule the orchestrator must hold.

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
6. Run `python tools/vnctl.py advance` when all gates for the current milestone
   are passed. Phase advancement is progress reporting, not permission for each
   scene.
7. Confirm that `translation/project-history.jsonl` received an append-only
   entry. Never edit or delete old history records.

## Delegation rules

- `vn-bootstrap` owns repository audit, parser verification, catalogue, stable
  IDs, segmentation, and initial index preparation.
- Select the engine skill from `project.active_build`. The active Steam/LUCA
  profile uses `vn-engine-luca`; `vn-engine-siglus` is the legacy adapter.
- `vn-context-builder` must precede every scene translation or review, but the
  surrounding block needs only one gate decision.
- `vn-scene-translator` creates drafts only after an allowed pilot or production
  gate result.
- `vn-scene-reviewer` performs independent review; the orchestrator does not
  substitute for it.
- `vn-knowledge-curator` updates durable knowledge only after the relevant gate
  permits it.
- `vn-reference-retriever` is an optional substep inside an allowed scene block;
  it needs no extra gate and may return no references.
- `vn-reference-curator` runs during corpus audit or on demand inside that same
  scene block. It must not turn external references into a prerequisite.

## Policy changes

The user may explicitly request a change to the gate policy itself. Treat that
as a configuration change: edit the policy consciously, validate it, explain
the impact, and append history. Never reinterpret an ordinary work request as a
policy change.
