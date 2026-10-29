"""The delegated-work receipt is durable, atomic, and board scoped."""
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def client(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db(board="default")
    path = Path(__file__).resolve().parents[2] / "plugins/kanban/dashboard/plugin_api.py"
    spec = importlib.util.spec_from_file_location("receipt_api_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/kanban")
    return TestClient(app)


def test_atomic_retries_conflict_and_live_status(client):
    payload = {"request_id": str(uuid4()), "origin": "chatgpt", "title": "Long work", "body": "Context"}
    url = "/api/plugins/kanban/delegations?board=default"
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post(url, json=payload), range(8)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    results = [r.json() for r in responses]
    assert len({r["task_id"] for r in results}) == 1
    assert sum(r["created"] for r in results) == 1
    task_id = results[0]["task_id"]
    assert client.post(url, json={**payload, "body": "different"}).status_code == 409
    with kbc.connect_closing(board="default") as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        conn.execute("UPDATE tasks SET status='done', result='finished' WHERE id=?", (task_id,))
        conn.commit()
    retry = client.post(url, json=payload).json()
    assert retry["task_id"] == task_id and retry["status"] == "done" and not retry["created"]
    detail = client.get(retry["task_url"])
    assert detail.status_code == 200 and detail.json()["task"]["result"] == "finished"
    with kbc.connect_closing(board="default") as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
    assert client.post(url, json=payload).status_code == 410


def test_requires_explicit_board_and_valid_payload(client):
    payload = {"request_id": str(uuid4()), "origin": "chatgpt", "title": "Work"}
    assert client.post("/api/plugins/kanban/delegations", json=payload).status_code == 422
    assert client.post("/api/plugins/kanban/delegations?board=%20", json=payload).status_code == 400
    assert client.post("/api/plugins/kanban/delegations?board=missing", json=payload).status_code == 404
    assert client.post("/api/plugins/kanban/delegations?board=default", json={**payload, "secret": "no"}).status_code == 422


def test_same_request_id_is_scoped_to_the_explicit_board(client):
    from hermes_cli.kanban_db_boards import create_board

    create_board("other")
    payload = {"request_id": str(uuid4()), "origin": "chatgpt", "title": "Work"}
    first = client.post("/api/plugins/kanban/delegations?board=default", json=payload)
    second = client.post("/api/plugins/kanban/delegations?board=other", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["task_id"] != second.json()["task_id"]
    assert client.get(first.json()["task_url"]).json()["task"]["id"] == first.json()["task_id"]
    assert client.get(second.json()["task_url"]).json()["task"]["id"] == second.json()["task_id"]
