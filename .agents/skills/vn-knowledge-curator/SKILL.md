---
name: vn-knowledge-curator
description: Extracts durable translation knowledge from a reviewed or played scene and proposes minimal updates to glossary, character cards, scene summaries, decisions, and hidden constraints. Use after scene review and especially after the user has played the scene.
compatibility: Requires reviewed scene data and repository documentation files.
metadata:
  version: "1.0"
---

# VN Knowledge Curator

## Lifecycle prerequisite

Invoke this skill inside an allowed work block or as an independent knowledge
block. Proposed and temporary updates are allowed in every phase.

## Principle

Store only knowledge that will materially improve future translation. Do not turn documentation into a plot encyclopedia.

## Inputs

- reviewed, playable, or approved scene;
- existing glossary;
- current character cards;
- existing decisions;
- user playtest notes;
- hidden constraints, when working in private mode.

## Cold start: nothing is reviewed yet

At the beginning there are no reviewed scenes, so the loop above has no input.
Bootstrap it from the source instead, once, before the first translation.

Read the earliest scripts in story order and build:

1. **Character cards** for whoever actually speaks there. Fill only the written
   manner: sentence length, formality, how they address others, recurring
   constructions, what they never say. Take it from the Japanese line with the
   English and Chinese as a check; do not infer manner from a translation alone.
   Status `proposed`. A card built from a handful of lines is a hypothesis.
2. **Glossary** for names, places and terms that recur. Transcription is a
   project-wide decision, so record it as `provisional` and stop: a name changed
   later costs a rewrite of every scene that used it.
3. **Safe scene summaries** for what has already been shown.
4. **Hidden constraints** in `private/constraints.jsonl` when an early line only
   makes sense with later knowledge. The reason stays private; only `safe_rules`
   travel outward.

Hard limits at this stage:

- read only as far ahead as the current task needs, and never paste plot into a
  user-facing report;
- prefer an empty card to an invented one: absence is visible, a wrong voice is
  not;
- everything produced here is `proposed` or `temporary`, without exception.

Once real scenes are reviewed, they supersede these cards. Bootstrap material is
a starting point, not a baseline to defend.

## Extract

- newly recurring terms;
- stable speech patterns;
- changed forms of address;
- relationship-stage changes;
- reusable humour/callback decisions;
- important deliberate ambiguities;
- safe scene summary;
- unresolved items to verify later.

## Do not store

- one-off trivial facts;
- generic personality adjectives without translation effect;
- AI guesses presented as canon;
- future information in safe docs;
- every sentence as a separate rule.

## Status policy

- `proposed`: new inference not yet confirmed;
- `temporary`: needed now but may change after future context;
- `approved`: confirmed durable decision;
- `deprecated`: replaced but retained for history.

## Procedure

1. Generate a delta according to [the update contract](references/update-contract.md).
2. Compare against existing records and avoid duplicates.
3. Apply safe updates only when permitted by `AGENTS.md`.
4. Put spoiler reasons only in `private/`.
5. Rebuild the index and validate.
6. Report exactly which files changed and why.

## Output

A small patch, not a complete rewrite of documentation.
