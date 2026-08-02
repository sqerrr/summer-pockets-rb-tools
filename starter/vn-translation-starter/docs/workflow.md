# Workflow

1. Initialize an empty project.
2. Implement or select an engine adapter.
3. Prove unchanged round trip and smoke test.
4. Export normalized source records and run `ingest`.
5. Translate one complete scene through a checked, source-bound patch that
   records its actor.
6. Import an independent source-aware review.
7. Resolve every open issue through a checked resolution file.
8. Recheck against source and close only an accepted current hash.
9. Rebuild indexes and run validation after each parallel wave.
10. Build from a pristine original and independently read back the result.
11. Mark content `playable` only after it enters a verified build.
12. Use gameplay LQA before any explicit user approval.

Parallel workers may prepare independent build artifacts. Shared ledgers,
question queues, indexes, accepts, closes, and imports should be updated
sequentially by the orchestrator.
