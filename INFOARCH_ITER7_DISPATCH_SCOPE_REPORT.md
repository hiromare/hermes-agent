# Hermes info architecture Iteration 7 — dispatcher eligibility and scoped Mobile activity (2026-10-30)

## Real Dispatcher / Worker boundary
- New `tests/hermes_cli/test_kanban_delegated_dispatch_contract.py` uses actual authenticated `POST /api/plugins/kanban/delegations` and `hermes_cli.kanban_db_dispatch.dispatch_once` on an isolated `HERMES_HOME`. A deliberately inert spawn callback records the **real dispatcher** claim and run ID; status becomes `running`, task/receipt identities agree, and `worker_session_id` remains `NULL` until an authenticated Gateway owner admission occurs.
- This tests the real dispatch decision/DB transition, **not** an LLM-powered autonomous worker or an actual child process. Existing finite-admission tests exercise Gateway owner admission, and the prior mobile HTTP test simulates completion via PATCH.
- No configured local Ollama listener was found on the Mac; scratch home has no seeded model credentials. No production Hermes Agent credentials, Gateway processes or LLM billing were reused.

## Mobile UI data isolation
- `KanbanActivitySection` now observes the canonical `AuthManager.dataScopeFlow` (connection, server, active profile, auth generation). The remote snapshot, loading/error state and effect lifecycle are keyed to that scope, with a stale response rejected if the current scope no longer matches. This prevents prior-account Kanban activity appearing after a connection, profile, or login switch.
- `DelegationDialog` now keys board, UUID input and result to that same scope; stale responses cannot update the new connection's receipt view, and lookup is disabled without an active data scope.
- These are UI scope protections; they do not represent a successful cross-account, multi-device acceptance test. Android-generated push notifications and external OS notifications are a separate lifecycle not modified here.

## Remaining acceptance
- A real LLM Worker completion in an isolated/sandboxed environment with test credentials and the real Gateway dispatcher remains unverified.
- A production ChatGPT-hosted connector is not registered. The local `kanban_delegate_client.py` CLI is the supported current bridge.
- G0–G5 interactive UX acceptance, alert-to-task lifecycle on a real device, 24–72h run, GitHub merges and deployment remain incomplete.
