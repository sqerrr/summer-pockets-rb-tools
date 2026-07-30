---
name: vn-engine-siglus
description: Handles the legacy SiglusEngine profile - unpacking and rebuilding Scene.pck, the Russian carrier encoding, font preparation, and in-game verification. Use only for the legacy Siglus build, Scene.pck, its TTF fonts, or its encoding table.
compatibility: Requires Python 3.12+ with fontTools and Pillow, Delphi 37.0 (dcc32) for the Delphi tools, Windows with the game installed.
metadata:
  version: "1.0"
---

# VN Engine Siglus

Engine-specific layer for the inactive `legacy_siglus` profile. Translation
content decisions belong to the other skills; this one only moves text in and
out of the old game build safely. Never apply its carrier rules to Steam/LUCA.

## Lifecycle prerequisite

Invoke this skill only through `vn-project-orchestrator`, after
`vn-project-gatekeeper` has allowed the operation.

Two operations map here, and they are not interchangeable:

- `verify-engine` — building a test pack, rebuilding fonts, changing the carrier
  table, taking in-game evidence. Allowed in every phase once
  `parser_extraction_verified` is passed, because the roundtrip, Cyrillic, tag
  and layout gates are closed with exactly this work.
- `build-game-text` — building the pack that carries the actual translation.
  Restricted to pilot, production and final LQA.

Test lines and a screenshot fall under the first. A pack meant to be played
through falls under the second.

## Read first

- `../../../AGENTS.md`
- `../../../game-tools/ADAPTER_CONTRACT.md`
- `../../../docs/project/parser-audit.md`
- [Format reference](references/siglus-format.md)

## Invariants

Breaking any of these produces a broken build, usually without an error:

1. Never edit `Scene.pck` in place. Build from `Scene.pck.orig`.
2. Never edit the fonts in place. Build from `font01.ttf.orig` and
   `font02.ttf.orig`.
3. The string count of a scene must not change. The bytecode addresses strings
   by index. Lengths may change freely.
4. Russian text must pass through `EncodeRussian` before it reaches the pack.
   Raw Cyrillic renders one letter per ideograph cell.
5. The encoding table, the font builder and both codecs change together or not
   at all.
6. The LZ back-reference copy stays byte-by-byte. Blocks overlap.

## Procedure

### Preparing a build

1. Close the game. It holds the fonts and the pack open, and writes fail with a
   sharing violation that is easy to misread as a permissions problem.
2. Build the fonts:

```bash
python game-tools/build_font.py
```

3. Build the pack from the pristine original, applying translations through the
   codec. Report the resulting size; growth to about 76 MB is expected until
   the compressor exists.
4. Verify independently of the tool that produced the file, for example by
   reading the strings back with `game-tools/siglus.py` and decoding them.

### Verifying on the game

```bash
powershell -File game-tools/game.ps1 -Action resume -Out shots/check.png
powershell -File game-tools/game.ps1 -Action click -X 960 -Y 700
powershell -File game-tools/game.ps1 -Action shot -Out shots/next.png
powershell -File game-tools/game.ps1 -Action close
```

`resume` starts the game, clicks through the attract screen, opens LOAD, takes
slot 000 and confirms. Screen state is detected by pixel probes, not by timing.

Read the screenshot. Do not trust a low-resolution glance: crop and enlarge the
text line before judging letter spacing, because scaled-down text hides the very
gaps this project is fighting.

### Checking a font without the game

```bash
python game-tools/encode_ru.py
```

Renders a sample line through Pillow with the built font. Use it for every font
change; it is faster than a game round-trip and catches missing glyphs.

## Recording what was learned

Every verified statement about the engine goes into
`../../../docs/project/findings.jsonl` in the same session it was obtained,
not reconstructed from memory later. Format and rules live in
`../../../docs/project/README.md`.

- `verified` requires a `method` field describing how to reproduce the check.
- A disproved hypothesis is kept with status `refuted`. This engine has already
  produced two plausible explanations for the same screenshot; the dead end is
  worth more than the silence.
- If the finding changes how a build is made, update `parser-audit.md` and the
  format reference in the same pass.

Validate with `python tools/vnctl.py findings`.

## Required outputs

- name of the source file the build started from;
- number of scenes and strings, before and after;
- resulting pack size;
- independent read-back confirmation;
- screenshot evidence when a visual property is claimed;
- new or updated findings;
- updated `docs/project/parser-audit.md` when the format understanding changes.

## Stop conditions

Stop and report instead of continuing when:

- the string count of any scene changes;
- round-trip produces any mismatch;
- the game fails to start or the text stays untranslated;
- a glyph renders as an empty box, which means the font lacks it;
- letters render spaced out, which means text reached the pack without the
  carrier encoding.

## Diagnostic method

The engine ignores font metrics, so font edits cannot be judged by reasoning
about advances. When layout behaviour is in question, run a control experiment
that separates the variables: change one property deliberately and predict both
outcomes before looking at the result. Two competing explanations that predict
the same screenshot are not a conclusion.
