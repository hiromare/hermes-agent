# Hermes Mobile ↔ Hermes backend: upstream update compatibility gate

Status: local implementation branch only; **not deployed, merged, or pushed**. Verified on 2026-10-30 JST.

## Authority and minimal integration seams

- Gateway owner admission in `gateway/session_kanban.py` persists the verified worker session ID on exactly one Kanban run. It checks task/run/claim ownership and does not create a second worker scheduler.
- `hermes_cli/kanban_db.py` and `kanban_db_connect.py` add nullable `task_runs.worker_session_id` with a partial unique index and idempotent legacy migration. Old rows intentionally remain `NULL`; never infer owner admission from legacy free-text metadata.
- `hermes_cli/session_provenance.py` now uses existing `hermes_state_local.local_receipt`, **not** private `SessionDB._read_one` or a hard-coded `state_meta` SQL query. The projection is an optional additive `provenance` field on existing authenticated session list/detail/search responses. The receipt is a creation claim; the committed run link is later admission evidence. No secrets or claim lock are exposed.
- `hermes_cli/kanban_delegation.py` stores an idempotent UUID+request-digest+task-ID receipt in the **same board database** and existing task transaction. Same ID+different payload gives 409; deleted task gives 410; successful acceptance does not imply a worker has started.
- `hermes_cli/kanban_activity_feed.py` projects only canonical `completed`/`gave_up` events, without creating a second notification or task database. The existing Kanban dashboard plugin serves the new authenticated endpoints.
- Mobile lists and searches now honor authenticated provenance `origin=kanban,purpose=worker` **in addition to** known internal sources; no blanket hiding of `api_server` or title heuristics. Older gateways may omit the field and still decode.

These are intentionally additive. They do **not** make the changes zero-conflict against future upstream rewrites: the Gateway admission path, two Kanban database source files, the existing session HTTP router and the Kanban plugin API still have patch points.

## Grounded upstream reference

On 2026-10-30 JST, the public origin `https://github.com/NousResearch/hermes-agent.git` answered `refs/heads/main = 088f657ecf77674c7b8e2ededf4e3576d82e042c` via `git ls-remote`, matching the branch's base commit. The local original checkout was a detached and older `818c13be1d`; do not mistake it for current upstream.

## Mandatory before any Hermes upgrade or merge

1. Use a **separate clean worktree** for each candidate upstream version. Compare `git ls-remote origin refs/heads/main` with the recorded base; review conflicts before any cherry-pick/rebase. Do not force-reset, fast-forward, or deploy production blindly.
2. Compare Gateway run/admission code, Kanban `task_runs` schema and migration order, `hermes_state_local.local_receipt`, and `web_routers/sessions.py`. A change in their contracts is an integration review blocker, not a reason to silently drop the feature.
3. With the repository's pinned Python environment, run:
   ```bash
   python scripts/check --commit HEAD --base <actual-upstream-merge-base>
   HERMES_PYTHON=<isolated-test-python> scripts/run_tests.sh \
      tests/gateway/test_kanban_finite_admission.py \
      tests/plugins/test_kanban_dashboard_plugin.py \
      tests/plugins/test_kanban_delegation_receipts.py \
      tests/hermes_cli/test_kanban_provenance_api.py \
      tests/hermes_cli/test_kanban_provenance_migration.py \
      tests/hermes_cli/test_kanban_activity_api.py \
      tests/hermes_cli/test_session_provenance_adapter.py
      tests/hermes_cli/test_kanban_mobile_journey_contract.py
      tests/hermes_cli/test_kanban_delegate_client.py
   ```
   Also run the full repository tests on a compatible Linux CI host; targeted Mac tests do not substitute for the full regression suite.
4. From Mobile, run its `:app:testDebugUnitTest`, `:app:assembleDebug` and matching `ktlint 1.8.0` checks. Verify optional provenance decode, search-to-history conversion, legacy source filtering, receipt status/error handling, worker session paging and profile scoping.
5. Run a **real authenticated integration test** from the Mobile network context before deploying: board-specific POST delegation (same UUID retry), GET receipt, Kanban run → profile-scoped session, finish/failure event → notice → same task, disconnection/reconnect and account/profile isolation. No request UUID reuse on another payload.
6. Validate G0–G5 non-regression gates against 2026-10-15 Mobile UX contract. Do not call full E2E complete based on unit tests or an emulator without backend credentials.

## Local ChatGPT/Work bridge

The additive `scripts/kanban_delegate_client.py` calls the canonical authenticated delegation POST/GET via the connected Mac. Set `HERMES_BASE_URL` and `HERMES_SESSION_TOKEN` privately; never pass credentials as CLI arguments. Retain and reuse board, UUID, and identical payload on lost responses. The bridge requires HTTPS for non-loopback connections and does not install a native ChatGPT connector.

Android opt-in real HTTP test `KanbanLiveBackendContractTest` only accepts an isolated loopback `127.0.0.1:19473` via adb reverse. It creates and completes SCRATCH tasks; never point it at production.

## Deferred/non-goals

- ChatGPT connector action that exposes the delegated POST/GET flow is still missing; existing connector chat does not equal the new Kanban API.
- Production update, GitHub push/main merge, physical Flip7 install and Proxmox changes are not approved as part of this branch work.
- Desktop transcript WIP is **stashed**, not merged or active; revisit after Mobile UX acceptance.
- The local HTTP journey contract test intentionally simulates a verified owner admission and a Kanban completion inside a fresh isolated test home. It verifies actual authenticated route shapes and cross-route identity, **not** the real dispatcher/Gateway worker lifecycle or a network-connected Android device.
- A remote Hermes version newer than the reference commit must pass this gate again. Future upstream compatibility cannot be guaranteed indefinitely by passing today's tests.
