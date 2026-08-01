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

## One scene, one pass

```bash
python tools/vnctl.py work next -o build/work.md
```

Picks the next scene with untranslated segments and takes it whole. Whole,
because the process requires reading a scene before translating its first line —
a partial batch hides how the scene ends and what device holds it together. It
is also cheaper: the constant part of the package does not scale with the number
of lines, so a full scene costs about a third per line of what a thirty-line
batch costs.

Then:

1. Dispatch `vn-translator` with the package. It writes a patch, checks itself
   with `work check`, and applies it with `apply-translation`.
2. Dispatch `vn-reviewer` with the source and the result — never with the
   translator's notes.
3. Apply confirmed `critical`, `major` and supported `minor`. Arbitrate
   disagreements yourself.
4. Run `validate`, then move on.

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

GPT translates, Opus reviews — measured, not assumed (`DEC-0032`). Each role has
a spare on the other model for when one is unavailable: `vn-translator-alt`,
`vn-reviewer-alt`.

## Do not grow this file

Until a thousand segments are translated, no new rules, statuses or process
documents. A tool that catches an error is welcome; a document describing order
is not. The first fires by itself, the second needs someone to remember it.
