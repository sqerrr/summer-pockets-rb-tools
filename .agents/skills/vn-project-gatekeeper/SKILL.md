---
name: vn-project-gatekeeper
description: Checks translation project phases, critical gates, permissions, and evidence and returns a machine-readable allow or block decision. Use only when invoked by vn-project-orchestrator before project work.
compatibility: Requires Python 3.11+, PyYAML, translation/project-status.yaml, and tools/vnctl.py.
metadata:
  version: "1.0"
---

# VN Project Gatekeeper

The gatekeeper is read-only. It checks facts and reports a decision; it never
changes gate status, phase, permissions, evidence, or history.

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
current_phase: bootstrap
blocking_gates:
  - parser_roundtrip_verified
  - stable_ids_created
  - scenes_segmented
  - pilot_completed
blocking_permissions: []
phase_allowed: false
policy_block: null
next_required_action:
  skill: vn-engine-siglus
  task: run_extended_roundtrip
  expected_evidence: docs/project/parser-audit.md
```

`blocking_gates` contains every required gate whose status is not `passed`.
`blocking_permissions` lists explicit permission switches that independently
deny the operation.
`phase_allowed: false` independently blocks an operation even if all listed
gates have evidence. `policy_block` is used for operations such as mass
translation that are forbidden by policy.

## Evidence rules

- A gate is passed only when its status is exactly `passed`.
- `passed` requires a non-empty evidence path that resolves to an existing file.
- `partial`, `in_progress`, and a prose claim are not substitutes for evidence.
- Invalid state is a hard failure, not permission to continue.
- Only the orchestrator may call `set-gate` after delegated work supplies and
  verifies evidence.
