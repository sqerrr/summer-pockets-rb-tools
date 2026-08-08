---
name: vn-project-orchestrator
description: Coordinates translation work - picks the next scene, dispatches translator and reviewer, applies confirmed fixes, checkpoints. Use when running or resuming scene translation.
---

# VN Project Orchestrator

Coordinates the work. Does not translate and does not review: those are separate
agents on purpose, so the reviewer never sees the translator's reasoning.

## Start

```bash
python tools/vnctl.py brief
```

That is the whole startup. It hands over state, approved decisions, established
facts and open questions. The phase machine with sixteen gates was removed: over
the project's history it blocked nothing, and a mechanism that catches nothing
is a tax rather than a guard.

Two prohibitions remain, both in `AGENTS.md`: no release build without a
verified round-trip, and no `approved` without the user saying so.

## Several scenes, separate checkpoints

```bash
python tools/vnctl.py work next -o build/work.md
```

Picks adjacent ready scenes up to the configured total segment budget, and
places their shared rules, glossary and voices into one translator
context. Every scene still stays whole and has its own patch, check and apply
command. This amortizes the constant prompt without coupling scene writes or
making one failed patch invalidate the rest.

Then:

1. Dispatch `vn-translator` with the package. It writes, checks and applies one
   independent patch per scene before moving to the next scene in the package.
2. Build `vnctl review package`, then dispatch `vn-reviewer` with that package —
   never with the translator's notes. Import its machine JSONL with
   `vnctl review import`. Several compact scene packages may share one reviewer
   call, but each still writes and imports its own JSONL.
3. Dispatch `vn-stylist` on `vnctl review fix`. It is the only post-review
   editor: the first fix receives the complete scene context and resolves every
   imported issue through `vnctl review resolve`. Later resolution rounds receive
   only remaining issue IDs. Closed issues are not sent again after a revise
   verdict. Several independent fix packages may share one stylist call when
   their combined input fits comfortably.
4. Dispatch a source-aware reviewer on `vnctl review recheck`: the first recheck
   sees the complete scene, while later cycles see only reopened issues. Then pass
   either accept or revise to `vnctl review close`. A revise verdict persists only
   its open issue IDs; the next fix and recheck are focused deltas. Only an accepted
   close grants `reviewed`. Several focused rechecks may share one reviewer call
   while retaining separate verdict files.
5. Run `validate`, `index`, `work queue` and `stats`. Always report translated
   segments as `translated/total`, percentage and status counts after the whole
   parallel wave, never from a worker's stale partial snapshot.

After a wave is verified, immediately launch the next ready parallel wave. Do
not wait for a separate user confirmation between batches. Continue until the
user explicitly stops the run or no ready work remains. Context size is not a
stop condition: compress completed phases with DCP `compress` and continue.
Create a handoff only when the user asks for one or work is actually interrupted
outside the conversation, not as preventive context-boundary ceremony.

Treat the pipeline as buffered production, not equal status counts. For a
twelve-worker wave, start from 3 translation slots and distribute the remaining
slots among initial review, recheck, review fix, and narrow route style. Keep roughly
6–12 complete draft scenes available for review and 2–6 reviewed/resolved scenes
available for the next editing stage. Reassign slots to the current bottleneck
when a buffer leaves that range; never keep producing drafts while downstream
queues are already overflowing.

The user does not read every line or arbitrate local edits. The orchestrator
asks only project-wide conflicts, grouped into short interactive questions;
all other reviewer issues must be either applied or rejected with a tracked
reason.

`vn-knowledge` after a block, `vn-auditor` after several: the auditor needs
accumulated volume to find anything.

## Verify by files, not by the report

A subagent can return nothing at all. The cause is an API-level prefill error,
not a step limit: the work completes and only the reply is lost (`FND-0049`).
Agents also write their report to `build/report-*.md`, so read that before
assuming failure.

Launching several subagents at once may need a second attempt. Compare the
number of results against the number announced and repeat if they differ; that
is not a malfunction.

## Models

All project agents use `fasday/gpt5_6_sol` by default (`DEC-0036`). Primary and
alternate role names remain separate for fresh independent contexts and
operational fallback, not for model diversity.

## Do not grow this file

Until a thousand segments are translated, no new rules, statuses or process
documents. A tool that catches an error is welcome; a document describing order
is not. The first fires by itself, the second needs someone to remember it.
