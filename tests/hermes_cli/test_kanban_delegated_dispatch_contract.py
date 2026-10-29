"""A delegated HTTP task is claimed by the real dispatcher, without starting an LLM.

The spawn callback is intentionally inert so this can run on CI without
credentials or an actual worker process. Owner admission is tested separately.
"""

from fastapi.testclient import TestClient

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect_closing
from hermes_cli.kanban_db_dispatch import dispatch_once


def test_delegated_http_task_is_eligible_for_real_dispatcher_tick(_isolate_hermes_home):
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    kb.init_db(board="default")
    client = TestClient(app)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    submit = client.post(
        "/api/plugins/kanban/delegations?board=default",
        json={
            "request_id": "a77592d3-e671-4aab-85de-4825e7a36abd",
            "origin": "chatgpt",
            "title": "Dispatcher integration probe",
            "body": "Only scratch data",
            "assignee": "default",
        },
    )
    assert submit.status_code == 200, submit.text
    task_id = submit.json()["task_id"]
    captured = []

    def fake_worker(task, workspace, *, board):
        # Record the real dispatcher selection without starting a model process.
        captured.append((task.id, task.current_run_id, workspace, board))

    with connect_closing(board="default") as conn:
        result = dispatch_once(
            conn,
            spawn_fn=fake_worker,
            board="default",
            max_spawn=1,
            max_in_progress=1,
            reconcile_orphans=False,
        )
        task = kb.get_task(conn, task_id)
        assert task.status == "running", result
        assert task.current_run_id is not None
        assert len(captured) == 1
        assert captured[0][0] == task_id
        assert captured[0][1] == task.current_run_id
        assert captured[0][3] == "default"
        assert any(row[0] == task_id for row in result.spawned)
        run = kb.get_run(conn, task.current_run_id)
        assert run.worker_session_id is None, (
            "A dispatch claim is not owner session admission"
        )

    receipt = client.get(
        "/api/plugins/kanban/delegations/a77592d3-e671-4aab-85de-4825e7a36abd?board=default"
    )
    assert receipt.status_code == 200
    assert receipt.json()["task_id"] == task_id
    assert receipt.json()["status"] == "running"
    detail = client.get(submit.json()["task_url"])
    assert detail.status_code == 200
    assert detail.json()["runs"][0]["worker_session_id"] is None
