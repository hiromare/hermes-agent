# Hermes information architecture — autonomous model-backed E2E (2026-10-30 JST)

## Verified end-to-end in an isolated home

**Real, not a stub:** on Mac, LM Studio served the locally stored model `gemma-4-e4b-uncensored-hauhaucs-aggressive` (Gemma 4 E4B GGUF Q4_K_M) through the OpenAI-compatible endpoint at `127.0.0.1:1234/v1`. Model identifier `hermes-e2e-gemma-local`, runtime context length 65,536, temporary TTL, no hosted API/token or billing.

- Isolated Hermes source: `feat/hermes-session-run-link-20261030` (base `088f657ecf`), fresh scratch `HERMES_HOME=/private/tmp/hermes-infoarch-llm-clean-e2e-20261030/home`. Gateway used the repository's actual `hermes_cli.main gateway run`, embedded Kanban dispatcher at 3-second interval and default assignee `default`. The actual dashboard server was on loopback `127.0.0.1:19473` with a temporary token file outside git.
- **Real ChatGPT-origin authenticated delegation POST** registered `t_13217c04`; receipt UUID was retained in scratch. Actual dispatcher claimed run **1**, launched a real subprocess, and Gateway admitted a real Worker session `local-41a9c41b59ea5ce1b3bdf5cbf95ca77e1a66d5d09d5f2d3fce2ea5c660c0710b`.
- The local model made several actual inference calls and finished the Kanban task **without the test client PATCHing completion**. Receipt and task state both `done`; run status `done`, outcome **`completed`**. Run started at Unix 1793325162 and ended at 1793325220 (58 seconds).
- The model-written result was exactly `LOCAL_LLM_WORKER_PASS_20261030`; authenticated Activity API returned **one canonical `completed`** event with the same task ID and result.
- Authenticated session detail confirmed `provenance={origin:kanban,purpose:worker,board:default,task_id:t_13217c04,run_id:1,evidence:validated_creation_claim}`; no claim lock leaked in this projection. Scratch evidence was stored without credentials in `verified-proof.json`.
- **Actual Android emulator** consumed the completed live task via Mobile Retrofit, read receipt and task/Run link, fetched the authenticated Gateway session provenance, and used Mobile's actual `loadActivity` Notices projection. Opt-in read-only instrumentation **OK (1 test)**. No simulated completion in this final test.

## Preparatory issues and limitations

- An early model load used context 8,192, which Hermes properly rejected against its minimum 64,000; reloaded with context 65,536 and matched the *isolated* Hermes config.
- The throwaway Python 3.13 test virtualenv lacked `snowballstemmer` and `prompt_toolkit` because upstream's lock marks these runtime dependencies Python 3.14+; install only the pinned `snowballstemmer==3.1.1` and `prompt_toolkit==3.0.53` into **/private/tmp/infoarch-test313**, not into production. The earlier failed scratch run was blocked and not mistaken for success. A reused dirty scratch home had boot recovery/liveness stalls; the final clean isolated home started normally.
- The isolated Python 3.13 uses SQLite journal DELETE due Hermes' native WAL-reset safety guard. `nemo_relay` emitted an optional runtime import warning but did not prevent the final Worker result.
- The Android result verifies real **network DTO, session and Notices data projection**, not tapping the actual Compose notice or an Android OS push notification. User phone Flip7 untouched.
- **No native hosted ChatGPT connector registration**, no G0–G5 product-wide interactive acceptance or 24–72h endurance, no Linux entire-suite tests, no production deployment, no upstream pull request, push or main merge.
- The previous backend suite stands at **74/74 targeted** and `scripts/check 14/14`; this iteration adds only this evidence report and no production backend code modifications.

## Operator safeguards

- Only scratch `HERMES_HOME` and localhost HTTP were used, not production credentials or accounts. Stop the test-owned Gateway/dashboard, remove adb port reverse and temporary HTTP token, unload only `hermes-e2e-gemma-local`. Preserve isolated session/task logs and sanitized proof for verification. Never stop the user's LM Studio service indiscriminately.
