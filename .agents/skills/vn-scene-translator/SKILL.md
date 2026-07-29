---
name: vn-scene-translator
description: Produces a coherent Russian draft for one catalogued visual-novel scene while preserving IDs, tags, character voices, ambiguity, humour, and technical structure. Use only after vn-context-builder has prepared a safe context package.
compatibility: Requires a scene context package and normalized segment JSONL.
metadata:
  version: "1.0"
---

# VN Scene Translator

## Read first

- `../../../docs/translation-spec.md`
- the context package created for the scene;
- [output contract](references/output-contract.md).

## Procedure

1. Read the entire scene before translating the first line.
2. Identify speakers, addressees, emotional changes, jokes, and ambiguous references.
3. Translate the scene as one conversation, not independent sentences.
4. Preserve every segment ID and every protected technical element.
5. Produce one main translation per segment.
6. Add alternatives only where a real semantic or stylistic decision remains unresolved.
7. Mark uncertain lines with allowed flags.
8. Do not approve new terminology. Suggest it as `proposed` or `temporary`.
9. Do not output spoiler explanations.
10. Set translated segments to `draft`.

## Translation rules

- Japanese is authoritative.
- Natural Russian is required, but no added information.
- Preserve deliberate repetition.
- Do not over-explain emotions.
- Keep character voice subtle and varied.
- Adapt humour by function when literal wording fails.
- Preserve uncertainty when the original is uncertain.

## Self-check before writing

- Does each line fit the speaker?
- Is the subject/addressate correct?
- Were any facts added?
- Were protected tokens changed?
- Did a term contradict the glossary?
- Did an early line become more revealing than the original?

## Output

Return machine-applicable JSONL plus a short issue list. Do not mix prose into JSONL.
