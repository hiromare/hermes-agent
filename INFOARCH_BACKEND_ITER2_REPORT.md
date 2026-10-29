# Backend iteration 2 report — 2026-10-30

## Implemented

- `POST /api/plugins/kanban/delegations?board=<slug>` explicitly submits long-running work using the existing dashboard plugin and its existing `/api/` authentication and plugin gates. Ordinary chat does not create tasks.
- Request JSON: `request_id` (UUID, generated and retained by the caller), `origin` (`chatgpt` or `external_client`), `title` (1–500 characters), optional `body` (up to 20,000 characters) and optional `assignee`. Unknown fields are rejected. The caller must not put credentials or secrets in any field. `body` is ordinary Kanban task content, visible to existing authorized Kanban consumers; `origin` is stored as the task's `created_by`.
- A board-local receipt stores only the UUID, SHA-256 of the canonical request fields, and task ID in the existing Kanban SQLite database. An immediate transaction covers receipt lookup, the existing task creation primitive, and receipt insertion. Simultaneous submissions serialize; failures roll back both. Receipts survive process restart with the board database, and remain even if a task is deleted. Existing task status, results, policy, and dispatcher are authoritative; no new task queue or task database is introduced.
- Same UUID and identical payload on the same board returns the same task and current status (`created: false`); different payload returns HTTP 409. If the original task has been deleted, retry returns 410 rather than creating a replacement. UUIDs are scoped to the selected board, so callers must keep the board and ID together. The board is required to prevent an active-board change from redirecting a retry. No per-client identity partition is claimed: authorized callers sharing a board share its UUID namespace.
- Response contains `task_id`, `status`, `created`, normalized `board`, and `task_url`. Authenticated clients GET that URL to retrieve the existing task, result, events, runs and run session links. A successful receipt means accepted into Kanban, not started or completed; a configured dispatcher and assignee are needed for execution. Retrying after a server restart must reuse the same board, UUID and payload.
- Prior verified worker-session association remains unchanged; legacy metadata alone is not treated as proof. Existing authenticated session detail is used for links. No production data was modified.

## Validation

Tests used the project's `scripts/run_tests.sh` with a temporary Python environment assembled from locally cached packages and isolated test homes. The runner's `/var/tmp` scratch location was temporarily changed to `/private/tmp` because the sandbox blocks `/var/tmp`; the runner was restored after testing. This is not the repository's pinned test environment.

- `tests/plugins/test_kanban_delegation_receipts.py`: 3 passed (concurrent retries, conflict, current status/result, deletion, validation, board isolation).
- `tests/hermes_cli/test_kanban_provenance_api.py`: 2 passed, including actual dashboard auth, delegation creation, verified run link and legacy missing link.
- `tests/plugins/test_kanban_dashboard_plugin.py`: 38 passed.
- `tests/hermes_cli/test_kanban_db.py`: 53 passed, 1 skipped (Windows), 1 failed: `test_infrastructure_spawn_refusal_never_charges_the_card` expected `auto_blocked == []` on this macOS sandbox. This was not established as caused by the patch or as a pre-existing failure; it remains unresolved.
- `python scripts/check` did not run its checks: pinned `ruff 0.15.22` is unavailable. The initial runner attempt also could not write `/var/tmp`, and `/usr/bin/python3` lacked `tomllib`; neither was counted as a pass.

## Remaining

- No new structured session provenance schema or migration was added. Existing `source`, session origin and the verified task-run association remain; visibility/purpose classification and safe population require a separately specified contract. No blanket hiding of `api_server` and no historical backfill was done.
- There is no ChatGPT connector/client integration, real long-running worker execution, deployment, cross-device end-to-end test, or full UX/non-regression acceptance in this batch. No live service or other worktree was changed. The local receipt endpoint alone does not grant an external client access or bypass existing authentication.
- Full pinned lint and test environments, a restart/process-level integration test, and the failed dispatcher regression need follow-up.
