---
name: vn-scene-reviewer
description: Independently reviews a drafted visual-novel scene against the aligned source texts of the active build, Russian quality, glossary, character voice, continuity, spoiler constraints, and technical integrity.
compatibility: Requires original and translated segments plus the same safe context package used for translation.
metadata:
  version: "1.0"
---

# VN Scene Reviewer

## Lifecycle prerequisite

Invoke this skill inside an already allowed pilot, production, batch, or LQA
block. Review does not require a separate gate check after translation of the
same declared block.

## Role

Act as a critical reviewer, not a second free-form translator. Report concrete problems and minimally sufficient corrections.

## Review passes

### 1. Technical integrity

- IDs preserved;
- segment count preserved;
- protected tokens preserved;
- no empty required translations;
- no accidental command translation.

### 2. Accuracy

Perform this pass from the current VN's source texts and scene context only.
External Russian localisations are not evidence of meaning.

- omissions;
- additions;
- wrong subject or object;
- wrong addressee;
- tense/aspect errors;
- incorrect polarity;
- lost uncertainty;
- mistranslated cultural or idiomatic expression.

### 3. Russian language

Selected external references may inform naturalness or rhythm in this pass, but
cannot justify a semantic change.

- calques;
- unnatural word order;
- bureaucratic or bookish register;
- incoherent dialogue;
- unnecessary pronouns and repetitions;
- punctuation problems.

### 4. Voice and continuity

- mismatch with character card;
- wrong relationship distance;
- inconsistent names/terms;
- broken callbacks;
- unjustified stylistic variation.

### 5. Humour and emotion

- lost joke mechanism;
- explanation instead of punchline;
- excessive drama;
- flattened emotional transition.

Judge the written sequence and visual context. Audio, actor intonation and voice
files are outside project scope.

### 6. Spoiler safety

- hidden subject made explicit;
- future term used too early;
- ambiguity removed;
- visible report contains future information.

See [review taxonomy](references/review-taxonomy.md).

## Severity

- `critical`: wrong meaning, broken script, spoiler, missing line;
- `major`: material voice/continuity/humour failure;
- `minor`: clear language defect with a safe correction;
- `preference`: subjective alternative, not an error.

Only `critical`, `major`, and well-supported `minor` findings require change. Do not force `preference` findings.

## Output

Return a structured issue list and corrected lines only. Do not rewrite unaffected segments.
