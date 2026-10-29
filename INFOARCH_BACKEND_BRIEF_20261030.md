# Hermes Backend: task/run/session provenance 2026-10-30

This is an independent clean upstream worktree. Do not touch production ~/.hermes, another worktree, deploy, or merge/push. Follow AGENTS.md. Owner requests implementation of HomeVault spec "Hermes 情報構造・UIUX再設計 20261030".

Observed production: Kanban tasks + task_runs in kanban.db. Worker launch passes HERMES_KANBAN_RUN_ID and HERMES_SESSION_SOURCE=kanban, but reliable run-to-session foreign key / API navigation is lacking. Some past run.metadata has worker_session_id; old backlog can't be assumed complete. Standard Kanban remains sole task source of truth, no second task database. Human conversations and system executions should remain distinguishable. source alone isn't sufficient to classify api_server sessions.

Mission implement a small, correctly-scoped backend provenance vertical slice:
1. Inspect actual current code schema and worker launch/session creation, existing task_runs / session DB and APIs. Propose and implement a durable explicit run_id -> worker_session_id association for NEW worker runs; reuse existing run metadata / columns/migration patterns and log tail if possible. Do not rely on guessed title/cwd matches. Capture idempotently even if worker starts asynchronously; don't turn the whole job into a new task or duplicate data.
2. Expose existing task/run/session correlation in relevant existing API (or narrow new read-only API), keeping auth policy intact, avoiding new public unauth endpoints, and making the linked session openable by clients; no fake links for historical missing associations.
3. Include tests: worker startup/link write, idempotency/no wrong run assignment, not-found historical, read API auth. Existing test suite regression. Prefer scoped implementation over sweeping refactor.
4. If strong code-level constraints prevent safe implementation, implement the largest verified useful slice and write clear documented remaining work. Do not change user data.
5. Do not commit secrets, don't push/merge/deploy. Existing semantics for authorization, user sessions, privacy, status must not regress. Run tests and report.
