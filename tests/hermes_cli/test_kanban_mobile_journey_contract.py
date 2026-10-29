"""Authenticated Mobile-facing journey over the real HTTP routes, with an isolated DB.

The task completion and owner-created session are explicitly simulated in the
test: this is a wire/contract test, NOT a live gateway worker or device E2E.
"""
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect_closing


def test_authenticated_receipt_run_session_and_activity_contract(monkeypatch, _isolate_hermes_home):
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
    from hermes_constants import get_hermes_home
    from hermes_state import SessionDB
    import hermes_state

    home = get_hermes_home()
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    kb.init_db()
    client = TestClient(app)
    request_id = str(uuid4())
    submit_url = "/api/plugins/kanban/delegations?board=default"
    receipt_url = f"/api/plugins/kanban/delegations/{request_id}?board=default"
    request = {
        "request_id": request_id, "origin": "chatgpt",
        "title": "Mobile tracking compatibility", "body": "Only isolated test data",
        "assignee": "default",
    }

    assert client.post(submit_url, json=request).status_code == 401
    assert client.get(receipt_url).status_code == 401
    assert client.get("/api/plugins/kanban/activity?board=default").status_code == 401
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    accepted = client.post(submit_url, json=request)
    assert accepted.status_code == 200, accepted.text
    initial = accepted.json()
    assert initial["created"] is True
    task_id = initial["task_id"]
    assert client.post(submit_url, json=request).json()["created"] is False
    assert client.get(receipt_url).json()["task_id"] == task_id

    with connect_closing() as conn:
        kb.recompute_ready(conn)
        claimed = kb.claim_task(conn, task_id)
        assert claimed is not None
        run_id = claimed.current_run_id
        assert run_id is not None
        # Test harness stands in for the gateway owner's verified admission.
        conn.execute("UPDATE task_runs SET worker_session_id=? WHERE id=?",
                     ("mobile-contract-session", run_id))
        conn.commit()

    with SessionDB(db_path=home / "state.db") as db:
        db.create_session(session_id="mobile-contract-session", source="kanban")
        db._write_sql("INSERT INTO state_meta(key,value) VALUES(?,?)",
            ("gateway.local_policy.v1:mobile-contract-session", json.dumps({
                "session_id": "mobile-contract-session",
                "policy": {
                    "source": "kanban",
                    "request_json": json.dumps({
                        "source": "kanban", "board": "default",
                        "task_id": task_id, "run_id": run_id,
                        "claim_lock": "private-do-not-project",
                    }),
                },
            })))

    running = client.get(receipt_url)
    assert running.status_code == 200 and running.json()["status"] == "running"
    task = client.get(initial["task_url"])
    assert task.status_code == 200
    linked = task.json()["runs"][0]
    assert linked["worker_session_id"] == "mobile-contract-session"
    assert linked["worker_session_url"].endswith("?profile=default")
    session = client.get(linked["worker_session_url"])
    assert session.status_code == 200
    assert session.json()["provenance"]["purpose"] == "worker"
    assert session.json()["provenance"]["task_id"] == task_id
    assert "private-do-not-project" not in session.text

    with connect_closing() as conn:
        assert kb.complete_task(
            conn, task_id, result="Mobile-visible final result",
            summary="Done", expected_run_id=run_id,
        )

    finished = client.get(receipt_url).json()
    assert finished["task_id"] == task_id
    assert finished["result"] == "Mobile-visible final result"
    assert finished["status"] == "done"
    activity = client.get("/api/plugins/kanban/activity?board=default")
    assert activity.status_code == 200
    events = [event for event in activity.json()["activity"] if event["task_id"] == task_id]
    assert len(events) == 1
    assert events[0]["kind"] == "completed"
    assert events[0]["result"] == finished["result"]
    assert events[0]["task_url"] == initial["task_url"]
    assert client.get(events[0]["task_url"]).json()["task"]["result"] == finished["result"]
    assert client.get(initial["task_url"]).json()["runs"][0]["worker_session_id"] == "mobile-contract-session"
