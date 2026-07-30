---
name: vn-reference-retriever
description: Selects up to three relevant external scene fragments after analysing the current VN scene by situation, line function, and translation problem. Use only when internal project context is insufficient; returning no external reference is valid.
compatibility: Requires curated local fragments under references/local/.
metadata:
  version: "1.0"
---

# VN Reference Retriever

External retrieval is optional. Its normal successful result may be: **no
external reference needed**.

## Lifecycle

Run as a substep of an already allowed context, translation or review block. Do
not request another gate decision.

## Procedure

1. Read the current scene and immediate context first.
2. Summarise in your own words:
   - what happens;
   - who participates;
   - what the difficult line or passage does;
   - the translation problem: humour, reaction, understatement, emotional
     transition, inner monologue, pause, group rhythm, or another function.
3. Check internal materials first: approved translations, glossary, decisions,
   written character manner, recurring jokes and formulations.
4. If those are enough, stop without external retrieval.
5. Otherwise query curated fragments by situation, function and technique.
   Lexical matches such as `ага`, `ого` or `вот это да` may only shortlist a
   candidate; read the fragment before selecting it.
6. Respect `workflow.external_reference_limit` from `config/project.yaml`
   (default 3) and return at most 1–3 `usable` or `gold` fragments. For each give:
   - fragment ID and status;
   - why its situation/function matches;
   - the transferable principle;
   - the limitation;
   - whether it is target-side-only because no source alignment exists;
   - its `context_dependency`: a `needs_history` fragment carries little weight
     for another work and must not be the only support for a choice.

Prefer a confirmed observation from `docs/style-profile.yaml` over raw
fragments. Pull fragments themselves only when the scene is hard enough that the
short rule does not settle it.

## Boundaries

- Parallel Japanese, English and Chinese texts of the current VN are source
  evidence, not external references.
- External Russian fragments may guide naturalness and rhythm, never accuracy.
- Do not copy wording or use another game's character as a voice model.
- Do not inspect or mention audio, voice files or actor performance.
