# Agent Rules

## Start

In a freshly extracted archive, initialize first. In an existing project, run:

```powershell
python tools/vnctl.py brief
```

The command is spoiler-safe and prints counts and readiness only.

## Non-Negotiable Rules

1. Do not release a game build without a verified unchanged round trip and an
   independent read-back check from the active engine adapter.
2. Do not assign `approved` without an explicit user decision.
3. Do not commit raw game files, extracted source text, private constraints,
   build artifacts, databases, credentials, or external corpora.
4. Do not change stable IDs or record counts without an explicit migration.
5. Do not remove, translate, reorder, or invent protected tokens.
6. Do not let a translator review its own scene.

## Working Unit

Translate one complete logical scene at a time. The translator writes a patch,
checks it, and applies it through `vnctl`; direct edits to canonical segment
files are not part of the workflow.

The reviewer receives the source-aware review package, never the translator's
reasoning. The editor resolves every issue. A fresh source-aware pass then
accepts or reopens the review. Only `review close` grants `reviewed`.

When a local decision is uncertain, put a usable provisional translation in
the text and add an open question. Questions without a provisional value fail
validation.

## Spoilers

Agents may use raw source and private constraints internally. User-visible
summaries contain counts, local non-spoiler notes, and already revealed facts.
Never output hidden reasons, future roles, unrevealed names, or future-scene
explanations.

## Git

Make small commits with one finished idea. Never commit, push, amend, or create
a release unless the user asks. Never revert unrelated worktree changes.
