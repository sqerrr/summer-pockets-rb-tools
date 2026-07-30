---
name: vn-engine-luca
description: Handles the active Steam/LUCA build - SCRIPT.PAK source extraction, multilingual records, relocation-safe rebuilding, direct-Unicode Russian, and automated in-game verification. Use for Steam SCRIPT.PAK, LUCA PAK files, source export, test builds, or runtime language integration.
compatibility: Requires Python 3.11+, PyYAML, Windows, and the local Steam/LUCA installation identified in config/project.yaml.
metadata:
  version: "1.0"
---

# VN Engine LUCA

Engine-specific layer for the active `steam_luca` profile. Translation content
decisions belong to the translation skills; this skill moves canonical text in
and out of the game without changing its meaning.

## Lifecycle prerequisite

Invoke only through `vn-project-orchestrator` after `vnctl gate` has allowed
the operation.

- `catalogue-sources` may export and validate original multilingual records.
- `verify-engine` may build diagnostic packs and collect read-back/screenshots.
- `build-game-text` is reserved for actual reviewed translation content.

## Read first

- `../../../AGENTS.md`
- `../../../config/project.yaml`
- `../../../game-tools/ADAPTER_CONTRACT.md`
- `../../../docs/project/luca-format.md`
- `../../../docs/project/parser-audit.md`

## Invariants

1. Build only from `files/SCRIPT.PAK.orig` whose SHA-256 matches the source
   manifest.
2. Never edit the installed PAK in place; create a build artifact, validate it,
   then copy it while the game is closed.
3. Persistent IDs use PAK entry ID plus full record ordinal, never byte offsets
   or source text.
4. Canonical Russian is direct Unicode. Do not introduce Siglus carrier codes.
5. Text records contain exactly three original slots: Japanese, English and
   Simplified Chinese. A fourth user-facing Russian mode requires runtime/EXE
   integration and is not implemented by appending a fourth script string.
6. Any changed record length requires global relocation of numeric opcodes
   15/17/18/19/21/22 and `_scr_label`.
7. Validate every rebuilt target with a fresh `Pak` instance and
   `validate_script_references()`.
8. Preserve entry count, IDs, names, order, opcode/flag sequence and all
   untouched metadata.

## Source Catalogue

```bash
python game-tools/export_luca_sources.py
python tools/vnctl.py validate
```

The exporter prints only counts and hashes. Full source text stays under the
ignored `source/parsed/`; only `source/manifest.jsonl` is committed.

Unexpected opcode 36/40 layouts are hard failures. Do not silently skip them or
guess that they are dialogue.

## Verification Build

```bash
python game-tools/probes/validate_luca_relocation.py
python game-tools/build_luca_test.py --save-test relocation
powershell -File game-tools/game_steam.ps1 -Action resume -Out build/steam/check.png
powershell -File game-tools/game_steam.ps1 -Action exit
```

Claims about rendering require a screenshot. Claims about structure require an
independent read-back and exact counts of scripts, records and references.

## Production Lookup

For each segment:

1. Resolve `source_set_id` and `source_id` through the local source catalogue.
2. Verify entry ID/name hash, record ordinal, opcode, flag, fixed parameters,
   `source_hash`, prefix, tail and original slot hashes.
3. Convert the record ordinal to the current byte offset.
4. Apply Russian only through `relocate_script_records()`.
5. Rebuild from the pristine archive and validate all references.

The production segment-to-PAK adapter is not yet implemented. Do not represent
the diagnostic `build_luca_test.py` as a release builder.

## Fonts And Punctuation

The regular LUCA font maps all 66 Russian letters plus `—`, `…`, `❝` and `❞`.
It does not map `«»`. Canonical translation retains standard Unicode; any
display substitution or INFO-table patch belongs to build configuration and
must be verified separately.

## Fourth-Language Boundary

Preserving Japanese, English and Chinese while adding Russian is a recorded
delivery requirement. The implementation remains undecided:

- native language value 3 requires extensive executable patching;
- a presentation shim still requires runtime interception and persistence but
  can reuse English/base non-text assets.

Do not choose either architecture implicitly during ordinary source, translation
or build work.

## Required Outputs

- pristine input path and hash;
- source/record/reference counts before and after;
- independent read-back result;
- screenshot evidence for visual claims;
- updated findings/specification when format understanding changes;
- a clear statement of unresolved runtime/EXE work.
