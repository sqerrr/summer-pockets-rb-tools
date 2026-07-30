---
name: vn-scene-translator
description: Produces a coherent Russian draft for one catalogued visual-novel scene while preserving IDs, tags, character voices, ambiguity, humour, and technical structure. Use only after vn-context-builder has prepared a safe context package.
compatibility: Requires a scene context package and normalized segment JSONL.
metadata:
  version: "1.0"
---

# VN Scene Translator

## Lifecycle prerequisite

Invoke this skill inside an allowed `translate-pilot`, `translate-production`,
or `batch-translate` block. A batch uses one gate decision and checkpoints every
scene separately.

## Read first

- `../../../docs/translation-spec.md`
- the context package created for the scene;
- [output contract](references/output-contract.md).

## Procedure

1. Read the entire scene before translating the first line.
2. Identify speakers, addressees, emotional changes, jokes, and ambiguous references.
3. Identify the function of difficult passages before considering an external
   reference. Use a retriever report only if the context builder included one.
4. Translate the scene as one conversation, not independent sentences.
5. Preserve every segment ID and every protected technical element.
6. Produce one main translation per segment.
7. Add alternatives only where a real semantic or stylistic decision remains unresolved.
8. Mark uncertain lines with allowed flags.
9. Do not approve new terminology. Suggest it as `proposed` or `temporary`.
10. Do not output spoiler explanations.
11. Set translated segments to `draft`.

## Translation rules

- Use the aligned current-VN sources. Japanese is the original-language
  authority; English and Simplified Chinese are independent supporting evidence.
- Natural Russian is required, but no added information.
- Preserve deliberate repetition.
- Do not over-explain emotions.
- Keep character voice subtle and varied.
- Adapt humour by function when literal wording fails.
- Preserve uncertainty when the original is uncertain.
- External Russian references may suggest rhythm or technique, but never meaning
  or ready-made wording.
- Analyse text only. Actor delivery and audio synchronisation are outside scope;
  character voice means written manner.

## Self-check before writing

- Does each line fit the speaker?
- Is the subject/addressate correct?
- Were any facts added?
- Were protected tokens changed?
- Did a term contradict the glossary?
- Did an early line become more revealing than the original?

## Output

Return machine-applicable JSONL plus a short issue list. Do not mix prose into JSONL.
