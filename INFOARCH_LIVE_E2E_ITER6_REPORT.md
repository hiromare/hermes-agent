# Hermes Mobile × Backend — Iteration 6 real HTTP verification (2026-10-30 JST)

## Scope and observations
- Isolated Mac HERMES_HOME `/private/tmp/hermes-infoarch-live-e2e-20261030/home`, local branch FastAPI server `127.0.0.1:19473`; no production server modification.
- Session token stored outside repo, file mode 0600. Emulator `emulator-5554` used `adb reverse tcp:19473 tcp:19473` to access loopback. Unauthenticated API 401, authenticated Kanban boards 200.
- Actual on-device Android instrumentation against real HTTP routes passed: `OK (1 test)`. Checked delegation POST with UUID/board, idempotent retry, changed-payload 409, unknown ID 404, status lookup, task completion through authenticated PATCH, completed activity referencing same task/result.
- The completion was performed by the test client, NOT an autonomous worker or model-backed Gateway. Worker owner/admission and history contract have separate in-process tests.
- Fixed actual incompatibility: Mobile's required `origin` had been serialized away due to an implicit default. New `DelegatedTaskBody` requires explicit origin, with MockWebServer regression and emulator E2E successful.
- `scripts/kanban_delegate_client.py` submits and checks receipt with the canonical authenticated API; scratch HTTP submit with origin `chatgpt` and status lookup succeeded. This is a command-line bridge over connected Mac, NOT a registered native ChatGPT connector.
- Local Python SQLite is 3.50.4; Hermes guard uses DELETE journal because of SQLite WAL-reset bug.

## Remaining gates
- Real LLM/Gateway autonomous Worker run and Mobile UI notification tapping remain unverified.
- Complete G0–G5 UX contract and 24–72 hour resilience check not complete.
- No main merge, GitHub push, official PR, production Gateway deployment, Flip7 changes or Proxmox operations.
