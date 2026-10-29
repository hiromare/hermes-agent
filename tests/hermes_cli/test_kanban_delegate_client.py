"""Safe external delegation client: bounded transport and replay identity."""

import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest


def _client():
    spec = importlib.util.spec_from_file_location(
        "delegate_client",
        Path(__file__).resolve().parents[2] / "scripts/kanban_delegate_client.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "value",
    [
        "http://remote.example:9000",
        "file:///tmp/socket",
        "https://user:pass@example.org",
        "https://example.org/?token=danger",
        "https://example.org/#secret",
    ],
)
def test_refuses_unsafe_base_urls(value):
    with pytest.raises(ValueError):
        _client()._safe_base(value)


def test_allows_loopback_and_secure_hosts_only():
    client = _client()
    assert client._safe_base("http://127.0.0.1:19473/") == "http://127.0.0.1:19473"
    assert client._safe_base("https://example.org/") == "https://example.org"


def test_submit_and_status_use_auth_header_not_query(monkeypatch):
    client = _client()
    observed = []

    class FakeResponse:
        def __enter__(self):
            return io.BytesIO(b'{"task_id":"t_1","board":"default","status":"ready"}')

        def __exit__(self, *_):
            pass

    def fake_open(request, timeout):
        observed.append(
            (request.full_url, request.get_method(), request.headers, request.data)
        )
        return FakeResponse()

    monkeypatch.setattr(client, "urlopen", fake_open)
    payload = {"request_id": "uuid", "origin": "chatgpt", "title": "Task"}
    assert client.call(
        "https://example.org", "secret-token", "POST", "default", payload=payload
    )
    assert client.call(
        "https://example.org", "secret-token", "GET", "default", request_id="uuid"
    )
    assert observed[0][0].endswith("/api/plugins/kanban/delegations?board=default")
    assert observed[1][0].endswith("/api/plugins/kanban/delegations/uuid?board=default")
    assert observed[0][1] == "POST" and observed[1][1] == "GET"
    assert all("secret-token" not in url for url, *_ in observed)
    assert all(
        any(
            k.lower() == "x-hermes-session-token" and v == "secret-token"
            for k, v in headers.items()
        )
        for _, _, headers, _ in observed
    )
    assert json.loads(observed[0][3]) == payload


def test_rejected_http_never_prints_response_body_or_token(monkeypatch, capsys):
    client = _client()
    monkeypatch.setenv("HERMES_SESSION_TOKEN", "private-token")
    monkeypatch.setattr(
        client,
        "call",
        lambda *a, **k: (_ for _ in ()).throw(
            HTTPError(
                "https://example.org",
                409,
                "secret-error",
                {},
                io.BytesIO(b"private-body"),
            )
        ),
    )
    code = client.main(
        [
            "--base-url",
            "https://example.org",
            "--board",
            "default",
            "--request-id",
            "123e4567-e89b-12d3-a456-426614174000",
            "submit",
            "--title",
            "Task",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert '"http_status": 409' in captured.err
    assert "private-token" not in captured.out + captured.err
    assert "private-body" not in captured.out + captured.err
