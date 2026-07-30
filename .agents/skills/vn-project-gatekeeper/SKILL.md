---
name: vn-project-gatekeeper
description: Checks critical gates for one logical project work block and returns a machine-readable allow or block decision.
compatibility: Requires Python 3.11+, PyYAML, translation/project-status.yaml, and tools/vnctl.py.
metadata:
  version: "1.0"
---

# VN Project Gatekeeper

The gatekeeper is read-only. It checks facts and reports a decision; it never
changes gate status, phase, evidence, or history.

## Procedure

1. Read `../../../translation/project-status.yaml`.
2. Normalize the requested operation to a CLI operation name.
3. Run:

```bash
python tools/vnctl.py gate <operation> --format yaml
```

4. Return the YAML result unchanged to `vn-project-orchestrator`.
5. Treat any non-zero exit code as blocked or invalid. Do not work around it.

## Output contract

```yaml
allowed: false
requested_operation: production_translation
current_phase: cataloguing
blocking_gates:
  - stable_ids_created
  - scenes_segmented
  - knowledge_index_built
  - pilot_completed
blocking_permissions: []
phase_allowed: true
policy_block: null
next_required_action:
  skill: vn-bootstrap
  task: create_stable_ids
  expected_evidence: translation/segments/<scene>.jsonl
```

`blocking_gates` contains every required gate whose status is not `passed`.
`blocking_permissions` is retained as an empty compatibility field. There is no
second permissions layer: gates and the small number of terminal phase limits
are the source of truth. `policy_block` is used for an opaque whole-route
translation; checkpointed `batch-translate` is a separate allowed operation.

One gate decision covers the complete declared block. Do not require a fresh
decision for indexing, searches, validation, context generation, review, or
knowledge updates that are substeps of the same block.

## Evidence rules

- A gate is passed only when its status is exactly `passed`.
- `passed` requires a non-empty evidence path that resolves to an existing file.
- `partial`, `in_progress`, and a prose claim are not substitutes for evidence.
- Invalid state is a hard failure, not permission to continue.
- Only the orchestrator may call `set-gate` after delegated work supplies and
  verifies evidence.
