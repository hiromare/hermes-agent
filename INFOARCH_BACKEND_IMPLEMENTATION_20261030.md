# Task/run/session provenance backend slice (2026-10-30)

## Implemented in this worktree

- `task_runs.worker_session_id` is a nullable, unique, additive column. Existing rows remain null.
- The Gateway owner records the session ID in the same Kanban write transaction as its verified `owner_admitted` event. The write checks the run ID, task ID, claim lock, and existing link. On a retry, an existing admission marker and saved request prove ownership even if the run's claim lock was subsequently cleared. A different link or a session already linked to another run is refused. Closing the run does not erase the column.
- The existing authenticated Kanban task-detail and run-detail APIs return `worker_session_id` and `worker_session_url`. The URL points to the existing authenticated session-detail API with the run's profile. A run without an explicit column link returns null fields, including when legacy metadata happens to contain `worker_session_id`.

## Outside this slice

- No backfill or guessed association for historical runs. Legacy metadata and `owner_admitted` events remain available for a separately validated migration.
- No Mobile/Desktop UI changes or chat-list classification, search/pagination changes, session visibility changes, or automatic opening of the returned URL.
- No model for the full origin/initiator/purpose taxonomy, ChatGPT delegation receipts, Cron/oneshot provenance, Subagent links, notification policy, or task-granularity decisions.
- A session deleted after admission may leave a run link whose session-detail route returns 404. Session retention and repair policy are separate decisions.
- No production data, deployment, merge, or push was performed.

## Verification

The new tests cover owner admission and retry, conflicting links, a stale claim, legacy missing links, the authenticated API, and the session-detail URL. On 2026-10-30 the canonical `scripts/run_tests.sh` was run for `tests/gateway/test_kanban_finite_admission.py`, `tests/gateway/test_session_kanban.py`, `tests/hermes_cli/test_kanban_db.py`, and `tests/hermes_cli/test_kanban_provenance_api.py`, using a temporary Python 3.13 environment assembled from cached packages and an isolated home. A temporary runner-only shim moved its scratch directory into the writable temp area. No tests passed: four files stopped at collection/fixture setup because `ruamel.yaml` was unavailable, and uv could not download it due to DNS failure. This environment was not the pinned test environment. A separate in-memory SQLite smoke check of the actual link helper passed for idempotency, retry after a cleared claim, wrong task/claim, replacement and duplicate-session rejection. Python syntax compilation and `git diff --check` passed; migration, HTTP authentication, worker integration, concurrency and the full regression suite remain unverified by runtime tests.
