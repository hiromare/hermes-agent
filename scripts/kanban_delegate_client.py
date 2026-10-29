#!/usr/bin/env python3
"""Bounded authenticated delegated-work CLI for external ChatGPT/Work callers.

This is a client for the existing canonical Kanban API, not a second scheduler.
Pass a stable request UUID on retries. Never pass session tokens as CLI arguments.
"""

import argparse
import json
import os
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


def _safe_base(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (
            parsed.scheme == "http"
            and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        )
    ):
        raise ValueError(
            "HTTPS required for non-loopback servers; URL must not contain credentials, query or fragment"
        )
    return value.rstrip("/")


def call(base, token, method, board, request_id=None, payload=None, timeout=20):
    url = base + "/api/plugins/kanban/delegations"
    if request_id is not None:
        url += "/" + quote(request_id, safe="")
    url += "?" + urlencode({"board": board})
    headers = {"X-Hermes-Session-Token": token}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    request = Request(url, headers=headers, data=data, method=method)
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=os.environ.get("HERMES_BASE_URL"), required=False
    )
    parser.add_argument(
        "--board", required=True, help="Explicit board slug (never inferred)"
    )
    parser.add_argument("--request-id", help="Stable UUID for retries and tracking")
    parser.add_argument("--timeout", type=float, default=20)
    actions = parser.add_subparsers(dest="action", required=True)
    post = actions.add_parser("submit")
    post.add_argument("--title", required=True)
    post.add_argument("--body")
    post.add_argument("--assignee")
    post.add_argument(
        "--origin", choices=("chatgpt", "external_client"), default="chatgpt"
    )
    actions.add_parser("status")
    args = parser.parse_args(argv)
    token = os.environ.get("HERMES_DASHBOARD_SESSION_TOKEN") or os.environ.get(
        "HERMES_SESSION_TOKEN"
    )
    if not token:
        parser.error(
            "set HERMES_SESSION_TOKEN in the caller environment (never CLI arguments)"
        )
    if not args.base_url:
        parser.error("provide --base-url or HERMES_BASE_URL")
    if not args.board.strip():
        parser.error("board is required")
    try:
        base = _safe_base(args.base_url)
        if args.request_id:
            request_id = str(uuid.UUID(args.request_id))
        elif args.action == "submit":
            request_id = str(uuid.uuid4())
        else:
            parser.error("status requires --request-id")
    except ValueError as exc:
        parser.error(str(exc))
    if args.action == "submit":
        payload = {
            "request_id": request_id,
            "origin": args.origin,
            "title": args.title,
            "body": args.body,
            "assignee": args.assignee,
        }
        # Durable key must be visible before sending: caller must retain and
        # reuse this ID+board+payload when the HTTP response is lost.
        print(
            json.dumps(
                {"request_id": request_id, "board": args.board, "phase": "submitting"}
            ),
            flush=True,
        )
        method = "POST"
    else:
        payload = None
        method = "GET"
    try:
        data = call(
            base,
            token,
            method,
            args.board,
            request_id if method == "GET" else None,
            payload=payload,
            timeout=args.timeout,
        )
        print(
            json.dumps(
                {"request_id": request_id, **data}, ensure_ascii=False, sort_keys=True
            )
        )
    except HTTPError as exc:
        print(
            json.dumps(
                {
                    "request_id": request_id,
                    "board": args.board,
                    "http_status": exc.code,
                    "error": "request rejected",
                }
            ),
            file=sys.stderr,
        )
        return 2
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        # Never log URLs, headers, raw response bodies or secret-laden payloads.
        print(
            json.dumps(
                {
                    "request_id": request_id,
                    "board": args.board,
                    "error": type(exc).__name__,
                    "retry_same_id": True,
                }
            ),
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
