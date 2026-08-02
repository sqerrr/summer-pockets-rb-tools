# VN Translation Starter

This archive is an engine-neutral starting point for an autonomous visual-novel
translation project. It contains no game files, extracted script, existing
translation, character knowledge, private plot data, model credentials, or
engine-specific reverse engineering.

## Requirements

- Python 3.11 or newer
- Git
- SQLite with FTS5 support (included in normal CPython builds)
- Optional: OpenCode for the included agent roles

## First Start

```powershell
git init
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python tools/vnctl.py init --title "My Project" `
  --source-language source --source-language reference `
  --target-language target
.venv\Scripts\python tools/vnctl.py brief
```

Extract into a new directory, not inside another Git/OpenCode project. A parent
project can merge its agents, permissions, providers, and instructions into the
starter. Restart OpenCode after extraction or after changing agent files.

`init` creates empty canonical ledgers and `config/project.yaml`. Source text is
kept in ignored `source/records.jsonl`; translation state is kept in tracked
`translation/` files.

## Connect an Engine

1. Read `docs/adapter-contract.md`.
2. Keep legally obtained game files outside Git or under ignored `source/raw/`.
3. Implement an adapter that exports normalized JSONL records.
4. Prove an unchanged parse/build/read-back round trip before real translation.
5. Store the receipt under `build/`; do not release a build without it.

The normalized source-record format is documented in
`docs/data-model.md`. `adapters/mock.py` is a synthetic example only:

```powershell
python adapters/mock.py seed source/records.jsonl
python adapters/mock.py roundtrip source/records.jsonl build/mock-roundtrip
python tools/vnctl.py ingest
python tools/vnctl.py validate
```

## Scene Pipeline

```powershell
python tools/vnctl.py work next -o build/work.md
python tools/vnctl.py work check build/patch-SCN0001.jsonl
python tools/vnctl.py apply-translation SCN0001 build/patch-SCN0001.jsonl --actor vn-translator

python tools/vnctl.py review package SCN0001 -o build/review-SCN0001.md
python tools/vnctl.py review import SCN0001 build/issues-SCN0001.jsonl --reviewer reviewer
python tools/vnctl.py review fix REV-SCN0001-01 -o build/fix-SCN0001.md
python tools/vnctl.py review resolve REV-SCN0001-01 build/resolutions-SCN0001.jsonl --actor editor
python tools/vnctl.py review recheck REV-SCN0001-01 -o build/recheck-SCN0001.md
python tools/vnctl.py review close REV-SCN0001-01 build/verdict-SCN0001.jsonl --reviewer reviewer
python tools/vnctl.py questions --import-file build/questions-SCN0001.jsonl --actor vn-translator
```

Only `review close` can grant `reviewed`. Translation patches can only grant
`draft`; `approved` is never assigned by the CLI.

## Routine Checks

```powershell
python tools/vnctl.py validate
python tools/vnctl.py questions
python tools/vnctl.py index
python tools/vnctl.py stats
python -m pytest -q
```

`brief`, `stats`, and `questions` print counts only. They do not print source
lines, speaker names, question text, or private reasons.

## OpenCode

`opencode.json`, `.opencode/agent/`, and `.opencode/skills/` contain optional
roles. They deliberately omit a provider/model so they inherit the user's
configuration. Restart OpenCode after changing agent or skill files.

## Handoff Terms

See `PRIVATE_HANDOFF_NOTICE.md`. The intended recipient may freely use and
modify this starter for personal projects. It is not a public redistribution
license, and it grants no rights to game content.
