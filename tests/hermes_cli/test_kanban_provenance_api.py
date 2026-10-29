"""The existing authenticated Kanban API exposes only owner-admitted run links."""

import json
from fastapi.testclient import TestClient


def test_run_session_link_and_missing_history_use_dashboard_auth(monkeypatch, _isolate_hermes_home):
    from hermes_constants import get_hermes_home
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_db_connect import connect_closing
    from hermes_state import SessionDB
    import hermes_state

    home = get_hermes_home()
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    with SessionDB(db_path=home / "state.db") as sessions:
        sessions.create_session(session_id="worker-1", source="kanban")
        receipt = {"session_id": "worker-1", "policy": {"source": "kanban", "request_json": json.dumps(
            {"source": "kanban", "board": "default", "task_id": "task-1", "run_id": 12,
             "claim_lock": "private-secret"})}}
        sessions._write_sql("INSERT INTO state_meta(key,value) VALUES(?,?)",
                            ("gateway.local_policy.v1:worker-1", json.dumps(receipt)))

    kb.init_db()
    with connect_closing() as conn:
        task_id = kb.create_task(conn, title="linked", assignee="default")
        old_task_id = kb.create_task(conn, title="unlinked history", assignee="default")
        kb.recompute_ready(conn)
        task = kb.claim_task(conn, task_id)
        old_run = kb.claim_task(conn, old_task_id)
        assert task is not None and old_run is not None
        conn.execute("UPDATE task_runs SET worker_session_id=? WHERE id=?", ("worker-1", task.current_run_id))
        conn.execute("UPDATE task_runs SET metadata=? WHERE id=?",
                     (json.dumps({"worker_session_id": "legacy-unverified"}), old_run.current_run_id))

    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN
    client = TestClient(app)
    run_path = f"/api/plugins/kanban/runs/{task.current_run_id}"
    assert client.get(run_path).status_code == 401
    assert client.get(f"/api/plugins/kanban/tasks/{task_id}").status_code == 401
    assert client.get('/api/sessions/worker-1?profile=default').status_code == 401

    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    linked = client.get(run_path)
    assert linked.status_code == 200, linked.text
    run = linked.json()["run"]
    assert run["worker_session_id"] == "worker-1"
    assert run["worker_session_url"] == "/api/sessions/worker-1?profile=default"
    detail = client.get(run["worker_session_url"])
    assert detail.status_code == 200
    expected = {"origin": "kanban", "purpose": "worker", "board": "default", "task_id": "task-1",
                "run_id": 12, "evidence": "validated_creation_claim"}
    assert detail.json()["provenance"] == expected
    assert 'private-secret' not in json.dumps(detail.json()["provenance"])
    listed = client.get('/api/sessions?min_messages=0').json()['sessions']
    assert next(row for row in listed if row['id'] == 'worker-1')['provenance'] == expected
    search = client.get('/api/sessions/search?q=worker-1').json()['results']
    assert search[0]['provenance'] == expected
    assert client.get(f"/api/plugins/kanban/tasks/{task_id}").json()["runs"][0]["worker_session_url"] == run["worker_session_url"]

    historical = client.get(f"/api/plugins/kanban/runs/{old_run.current_run_id}").json()["run"]
    assert historical["worker_session_id"] is None
    assert historical["worker_session_url"] is None
    assert client.get("/api/plugins/kanban/runs/99999999").status_code == 404


def test_delegation_route_uses_dashboard_auth(_isolate_hermes_home):
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    client = TestClient(app)
    url = "/api/plugins/kanban/delegations?board=default"
    payload = {"request_id": "7f00b3a2-6485-4fd4-b0a0-cd85f21d4f2b", "origin": "chatgpt", "title": "Work"}
    assert client.post(url, json=payload).status_code == 401
    lookup = f'/api/plugins/kanban/delegations/{payload["request_id"]}?board=default'
    assert client.get(lookup).status_code == 401
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    created = client.post(url, json=payload)
    assert created.status_code == 200, created.text
    assert client.get(created.json()["task_url"]).status_code == 200
    assert client.get(lookup).json()["task_id"] == created.json()["task_id"]
