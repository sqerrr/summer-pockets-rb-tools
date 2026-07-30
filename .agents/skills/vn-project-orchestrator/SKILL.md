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
5. Ask the gate directly. There is no separate gatekeeper skill: the rules live
   in `tools/vnctl.py`, and a wrapper that only forwards output adds ceremony
   without adding a check.

```bash
python tools/vnctl.py gate <operation> --format yaml
```

6. Stop when `allowed: false`. A normal request such as "continue" or
   "translate the scene" cannot override the result.

### Record the state you decided on

Before the first write of the block, capture what the decision was based on:

```bash
git rev-parse --short HEAD
python -c "import hashlib,pathlib;[print(p,hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:12]) for p in ['translation/project-status.yaml','config/project.yaml']]"
```

Compare again before writing. If any of the three changed, someone edited the
project underneath you: re-read the files and re-check the gate. The rule to
recheck on changed state is useless without a way to notice the change.
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

## Subagents versus skills

A skill is instructions loaded into the current context. It runs here, in
sequence, and its reading stays in this context afterwards. A subagent is a
separate process with a fresh context, invoked through `Task`, and several can
run at once.

That difference is not cosmetic. While translation and review were both skills,
the reviewer read the translator's reasoning because they shared one context, so
its independence was a claim rather than a fact. And a single context cannot
carry hundreds of scenes.

Defined subagents, in `.opencode/agent/`:

| Agent | Why it must be isolated |
|---|---|
| `vn-translator` | fresh context per scene; several scenes in parallel |
| `vn-reviewer` | must not receive the translator's reasoning |
| `vn-knowledge` | reads far more source than it reports; spoiler risk concentrated |
| `vn-auditor` | reads across scenes, which per-scene review cannot do |
| `second-opinion` | different model; independent judgement on process |

Skills stay: they hold the instructions an agent follows. This is not agents
instead of skills.

New agent definitions are files and are picked up only when opencode restarts.
An agent cannot create another agent mid-session; it can only invoke the ones
already defined.

## Verify by files, never by the agent's report

A subagent can finish and return nothing at all: no result, no error, no partial
work. This happened twice on the first pilot, and the empty answer looked exactly
like a successful silent run. Had the orchestrator trusted it, the queue would
have reported progress while nothing was written.

So after every dispatch, read the artefacts before believing anything:

```bash
python tools/vnctl.py validate
python tools/vnctl.py questions
```

plus the file the agent was supposed to change. A report is a claim; the file is
the fact. This holds even when the report is detailed and convincing.

Keep each dispatch small enough to finish. The pilot completed five segments and
silently died on sixty, so the working batch is tens of segments, not hundreds.
Split a large scene across several calls rather than hoping one call survives.

## How to run a scene queue

1. Build the context package once and pass its path to both the translator and
   the reviewer, so they judge the same material:
   `python tools/vnctl.py context <SCENE_ID> -o build/context-<SCENE_ID>.md`
2. Dispatch translators, one scene per call, several calls in one message.
3. Dispatch reviewers on the finished scenes. Give them source, translation and
   the package. Never forward the translator's notes.
4. Apply confirmed `critical`, `major` and supported `minor` findings; arbitrate
   disagreements yourself.
5. Validate, set `reviewed`, checkpoint, and only then take the next batch.
6. Run `vn-auditor` after a block, not after every scene: it needs accumulated
   volume to find anything.

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
