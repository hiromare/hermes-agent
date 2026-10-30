"""Stdio delegation bridge contracts, including its MCP wire interface."""

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scripts import kanban_delegate_client as client

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/kanban_chatgpt_mcp.py"


async def _session(env, action):
    import sys
    params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT)], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await action(session)


def test_protocol_metadata_and_malicious_base(monkeypatch):
    async def exercise(session):
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert set(tools) == {"submit_delegation", "get_delegation_status"}
        submit, status = tools["submit_delegation"], tools["get_delegation_status"]
        assert submit.annotations.idempotentHint and not submit.annotations.readOnlyHint
        assert status.annotations.readOnlyHint
        assert {"board", "request_id", "title"} <= set(submit.inputSchema["required"])
        assert "base_url" not in submit.inputSchema["properties"]
        invalid = await session.call_tool("submit_delegation", {"board": "default", "title": "Task"})
        assert invalid.isError
        invalid = await session.call_tool("submit_delegation", {"board": "default", "request_id": "123e4567-e89b-12d3-a456-426614174000", "title": "x" * 501})
        assert invalid.isError
        return await session.call_tool("get_delegation_status", {"board": "default", "request_id": "123e4567-e89b-12d3-a456-426614174000"})
    result = anyio.run(_session, {"HERMES_BASE_URL": "http://evil.example", "HERMES_SESSION_TOKEN": "private-token"}, exercise)
    assert "request failed" in str(result)
    assert "private-token" not in str(result)


def test_no_redirect_forwards_credentials(monkeypatch):
    from urllib.request import Request
    request = Request("https://example.org", headers={"X-Hermes-Session-Token": "secret"})
    assert client._NoRedirect().redirect_request(request, None, 302, "redirect", {}, "https://evil.example") is None


def test_replay_identity_and_redacted_errors(monkeypatch):
    import sys
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        from scripts import kanban_chatgpt_mcp as bridge
    finally:
        sys.path.pop(0)
    monkeypatch.setenv("HERMES_BASE_URL", "https://example.org")
    monkeypatch.setenv("HERMES_SESSION_TOKEN", "private-token")
    calls = []
    def fake_call(*args, **kwargs):
        calls.append((args, kwargs))
        return {"task_id": "t_1", "result": "private-token", "unknown": "private-token"}
    monkeypatch.setattr(bridge, "call", fake_call)
    uid = bridge.UUID("123e4567-e89b-12d3-a456-426614174000")
    first = bridge.submit_delegation("default", uid, "Task")
    second = bridge.submit_delegation("default", uid, "Task")
    assert calls[0] == calls[1]
    assert calls[0][1]["payload"]["origin"] == "chatgpt"
    assert first == second and first["result"] == "[REDACTED]"
    assert "private-token" not in json.dumps(first)
    def fail(*args, **kwargs):
        raise HTTPError("https://private-token", 409, "private-token", {}, io.BytesIO(b"private-token"))
    monkeypatch.setattr(bridge, "call", fail)
    result = bridge.get_delegation_status("default", uid)
    assert result["http_status"] == 409 and "private-token" not in str(result)
    monkeypatch.setattr(bridge, "call", lambda *args, **kwargs: [])
    assert bridge.get_delegation_status("default", uid)["retry_same_id"]
