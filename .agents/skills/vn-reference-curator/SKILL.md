---
name: vn-reference-curator
description: Curates short scene fragments from local Russian localisation corpora, verifies context and alignment, and assigns raw, usable, gold, or rejected. Use during reference-corpus audit or when a translation block needs a newly found external example.
compatibility: Requires a local corpus under references/local/.
metadata:
  version: "1.0"
---

# VN Reference Curator

Catalogues **scene fragments**, not isolated lines and not character voices for
Summer Pockets.

## Lifecycle

Run inside an allowed `audit-reference-corpus` block, or as an optional substep
of an already allowed translation/review block when that scene genuinely needs
a new example. It creates no gate and never blocks translation.

## Procedure

1. Read `docs/reference-corpus-policy.md` and the corpus manifest.
2. Start from a concrete need or a promising scene episode. Metrics may shortlist
   candidates; grep matches never establish relevance.
3. Read enough surrounding text to understand participants, setup and result.
4. Cut a coherent fragment, normally 3–15 lines.
5. Record available source-language text, Russian translation, speakers,
   situation, function, technique, selection reason and applicability in
   `references/local/<corpus>/fragments.jsonl`.
6. Assign one status manually:
   - `raw`: discovered, not verified;
   - `usable`: context understood and scope limited;
   - `gold`: aligned source and Russian verified, context clear, Russian strong,
     technique transferable;
   - `rejected`: false match, poor translation, bad alignment or plot-specific.

A Russian-only fragment cannot be `gold`; it can only support target-side rhythm
or naturalness.

## Against forced classification

`function` is a description, not a slot. Registers mix: a scene can be funny and
tense at once, a joke can carry the emotional turn, and the interesting move is
often the transition rather than either state. Write what the fragment actually
does, use several descriptions when several are true, and say plainly when a
fragment resists categories. A fragment that does not fit the existing
vocabulary is a reason to widen the vocabulary, not to discard the fragment or
bend it into the nearest label.

## How to read

Metric shortlists only surface what the metric can already see. A candidate list
is a starting point, never the reading itself, and a technique the filter cannot
detect is not absent from the material.

Read continuous stretches as well, including scenes no rule flagged. In practice
the strongest observations come from ordinary passages read in sequence, because
an effect usually lives in the move between lines rather than in any one line.

Record coverage locally in `references/local/<corpus>/reading-log.jsonl`: scene,
line range, date, what came out of it. A later session must be able to see what
was actually read instead of assuming the corpus was surveyed.

## From fragment to rule

Three layers, and skipping one produces false confidence:

1. **Fragment** — one concrete place, with your reading of it.
2. **Observation** — a technique seen in at least two independent fragments,
   preferably from different routes. Lives in `observations` in
   `docs/style-profile.yaml` with fragment IDs as evidence. Never built from a
   single fragment, and never from `needs_history` fragments alone.
3. **Decision** — a project rule in `docs/decisions.jsonl`, only after the user
   approves it.

A counter-example does not delete an observation. Record it in
`counter_examples` and lower `confidence`; a technique with known limits is more
useful than one that pretends to be universal.

Store corpus text locally; commit only IDs and own-word conclusions.

## Never

- analyse voice acting, audio files or actor intonation;
- copy a ready-made Russian line into the translation;
- infer meaning for Summer Pockets from another game's localisation;
- promote `gold` automatically;
- pre-annotate the whole corpus without a demonstrated need.
