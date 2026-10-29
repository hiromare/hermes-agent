"""Activity is an authenticated, board-scoped view of durable task events."""

from fastapi.testclient import TestClient

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_boards import create_board
from hermes_cli.kanban_db_connect import connect_closing


def test_activity_projection_and_auth(_isolate_hermes_home):
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    kb.init_db(board="default")
    create_board("other")
    with connect_closing(board="default") as conn:
        done = kb.create_task(conn, title="Finished")
        abandoned = kb.create_task(conn, title="Stopped")
        deleted = kb.create_task(conn, title="Deleted")
        conn.execute("UPDATE tasks SET status='done', result='actual result' WHERE id=?", (done,))
        conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (abandoned,))
        conn.executemany(
            "INSERT INTO task_events(task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            [(done, "completed", "private log", 100), (abandoned, "gave_up", "private log", 200),
             (done, "completed", "private log", 200), (deleted, "gave_up", "private log", 300)]
            + [(done, "retry", "private log", 400 + i) for i in range(200)],
        )
        conn.execute("DELETE FROM tasks WHERE id=?", (deleted,))
        conn.commit()
    with connect_closing(board="other") as conn:
        other = kb.create_task(conn, title="Other board")
        conn.execute("INSERT INTO task_events(task_id, kind, created_at) VALUES (?, 'completed', 999)", (other,))
        conn.commit()

    client = TestClient(app)
    url = "/api/plugins/kanban/activity"
    assert client.get(url, params={"board": "default"}).status_code == 401
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    response = client.get(url, params={"board": "default"})
    assert response.status_code == 200, response.text
    items = response.json()["activity"]
    assert [(item["task_id"], item["kind"], item["created_at"]) for item in items] == [
        (done, "completed", 200), (abandoned, "gave_up", 200), (done, "completed", 100)]
    assert items[0]["event_id"] > items[1]["event_id"]
    assert items[0]["title"] == "Finished" and items[0]["status"] == "done"
    assert items[0]["result"] == "actual result" and items[0]["board"] == "default"
    assert "private log" not in response.text
    assert client.get(items[0]["task_url"]).json()["task"]["id"] == done
    assert client.get(url, params={"board": "default", "limit": 1}).json()["activity"] == items[:1]
    assert [item["task_id"] for item in client.get(url, params={"board": "other"}).json()["activity"]] == [other]

    assert client.get(url).status_code == 422
    assert client.get(url, params={"board": " "}).status_code == 400
    assert client.get(url, params={"board": "missing"}).status_code == 404
    for limit in ("0", "51", "1.5", "1.0", "01", "abc", ""):
        assert client.get(url, params={"board": "default", "limit": limit}).status_code == 422
