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

## Several files, one agent context

```bash
python tools/vnctl.py work next SCN0043 SCN0044 --output-dir build
```

The multi-output mode invokes the existing one-scene renderer once per selected
scene and prints several ordinary work-file paths. Pass those paths to one
translator call. Batching belongs to dispatch, not to the package format: every
scene keeps its original package, patch, check and apply command, while the
agent reads project documents only once.

Then:

1. Dispatch `vn-translator` with a short ordered list of ordinary work-file
   paths. It fully writes, checks and applies one independent patch before
   opening the next work file.
2. Generate separate files with
   `vnctl review package SCENE... --output-dir build`, then dispatch
   `vn-reviewer` with the printed paths — never with the translator's notes.
   Import each machine JSONL with its own `vnctl review import`. Do not concatenate
   packages and do not create a wrapper manifest; the reviewer closes one file
   before reading the next.
3. Dispatch `vn-stylist` on `vnctl review fix`. It is the only post-review
   editor: the first fix receives the complete scene context and resolves every
   imported issue through `vnctl review resolve`. Later resolution rounds receive
   only remaining issue IDs. Closed issues are not sent again after a revise
   verdict. Generate several ordinary files with
   `vnctl review fix REVIEW... --output-dir build`; their printed paths may share
   one stylist call when the combined input fits comfortably.
4. Dispatch a source-aware reviewer on `vnctl review recheck` exactly once per
   run. Accept verdicts close normally. A revise verdict must give final text for
   every reopened issue; `vn-stylist` applies that focused delta, then
   `vnctl review finalize` closes it without another reviewer. A tooling or policy
   conflict goes through `vnctl review block` to `review wait`, never into a
   fix/recheck loop. Generate several ordinary files with
   `vnctl review recheck REVIEW... --output-dir build`; their printed paths may
   share one reviewer call while retaining separate verdict files.
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

Review ordering is local to a review run, not global by scene ID. Use the
separate `review initial`, `review fix`, `review recheck`, `review finalize`, and `review wait`
queue buckets. A user-blocked run stays in `review wait` while independent
ready work from the other buckets continues.

Enforce the measured dispatch budgets from `config/project.yaml`: 1125 pending
segments for translation, 750 scene segments for initial review, 80 open issues
for review fix, and 63 resolutions for recheck, plus the configured file-count
caps. Issue/resolution count is the primary sizing signal for fix and recheck,
but repeated scene-specific context makes file count independently relevant.
Multiple files over budget require `--allow-oversize`; a single whole scene or
run is never split.

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
