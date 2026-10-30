#!/usr/bin/env python3
"""Optional stdio MCP adapter for the canonical Kanban delegation API."""

import os
from typing import Annotated
from urllib.error import HTTPError, URLError
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from kanban_delegate_client import _safe_base, call

mcp = MCPServer(
    "Hermes delegated Kanban",
    instructions=(
        "Submit only work explicitly requested by the user. Retain board, request_id "
        "and the exact payload; retries must use all the same values. Check status "
        "with the same board and request_id after an uncertain response."
    ),
)
Board = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")]
Title = Annotated[str, Field(min_length=1, max_length=500)]
Body = Annotated[str, Field(max_length=20000)]
Assignee = Annotated[str, Field(max_length=200)]


def _request(method, board, request_id, payload=None):
    token = os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN") or os.environ.get("HERMES_SESSION_TOKEN")
    safe_board = board.replace(token, "[REDACTED]") if token else board
    if not token or not os.environ.get("HERMES_BASE_URL"):
        return {"error": "server configuration missing", "request_id": request_id, "board": safe_board}
    try:
        base = _safe_base(os.environ["HERMES_BASE_URL"])
        data = call(base, token, method, board, request_id if method == "GET" else None,
                    payload=payload, timeout=20)
        if not isinstance(data, dict):
            raise ValueError("invalid API response")
        # Expose only the canonical receipt/status fields, never arbitrary upstream data.
        keys = ("task_id", "status", "created", "board", "last_activity_at", "result")
        result = {key: data[key] for key in keys if key in data}
        result["request_id"] = request_id
        # Upstream content is untrusted, including task results.
        def clean(value):
            if isinstance(value, str):
                return value.replace(token, "[REDACTED]")[:20000]
            if isinstance(value, (bool, int, float)) or value is None:
                return value
            return None
        return {key: clean(value) for key, value in result.items()}
    except HTTPError as exc:
        return {"error": "request rejected", "http_status": exc.code,
                "request_id": request_id, "board": safe_board}
    except (URLError, TimeoutError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return {"error": "request failed or response invalid", "retry_same_id": True,
                "request_id": request_id, "board": safe_board}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                      idempotentHint=True, openWorldHint=True))
def submit_delegation(board: Board, request_id: UUID, title: Title,
                      body: Body | None = None, assignee: Assignee | None = None) -> dict:
    """Submit explicit work. Reuse board, UUID and exact payload for every retry."""
    request_id = str(request_id)
    return _request("POST", board, request_id, {"request_id": request_id, "origin": "chatgpt",
                    "title": title, "body": body, "assignee": assignee})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                      idempotentHint=True, openWorldHint=True))
def get_delegation_status(board: Board, request_id: UUID) -> dict:
    """Read the current receipt and result using the original board and UUID."""
    return _request("GET", board, str(request_id))


if __name__ == "__main__":
    mcp.run(transport="stdio")
