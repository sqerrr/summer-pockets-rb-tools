---
name: vn-knowledge-curator
description: Extracts durable translation knowledge from a reviewed or played scene and proposes minimal updates to glossary, character cards, scene summaries, decisions, and hidden constraints. Use after scene review and especially after the user has played the scene.
compatibility: Requires reviewed scene data and repository documentation files.
metadata:
  version: "1.0"
---

# VN Knowledge Curator

## Lifecycle prerequisite

Invoke this skill only through `vn-project-orchestrator`, after the gatekeeper
has allowed knowledge or glossary updates in the current phase.

## Principle

Store only knowledge that will materially improve future translation. Do not turn documentation into a plot encyclopedia.

## Inputs

- reviewed/approved scene;
- existing glossary;
- current character cards;
- existing decisions;
- user playtest notes;
- hidden constraints, when working in private mode.

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
