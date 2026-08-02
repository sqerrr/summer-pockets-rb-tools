---
name: vn-project-orchestrator
description: Coordinates autonomous VN scene translation, independent review, issue resolution, verification, and checkpoints. Use when starting or resuming translation work.
---

# VN Project Orchestrator

## Start

```powershell
python tools/vnctl.py brief
```

The command is safe for user-visible output and reports counts only.

## Scene Cycle

1. Generate a complete scene package with `work next`.
2. Dispatch `vn-translator` for that scene.
3. Check and apply the source-bound patch with `--actor vn-translator`; import
   any local question proposal sequentially.
4. Generate a source-aware package with `review package`.
5. Dispatch a fresh `vn-reviewer` without translator reasoning.
6. Import the machine issue file sequentially.
7. Generate `review fix` and dispatch `vn-editor`.
8. Resolve sequentially, then generate `review recheck`.
9. Dispatch a fresh source-aware reviewer.
10. Record the verdict through `review close`; only an accepted current hash
    grants `reviewed`.
11. Run `validate`, `questions`, `index`, and `stats`.

Prepare independent scenes and reports in parallel when the host supports it.
Put all parallel task calls in one host-level parallel block and compare the
number of returned results with the number announced. Shared ledgers, imports,
resolutions, closes, indexes, and question merges remain sequential.

Verify work by canonical files and required artifacts, not by a worker's final
message. Keep draft production bounded by review capacity.

Do not release a game build without a matching round-trip receipt and
independent read-back. Do not assign `approved` without explicit user approval.
