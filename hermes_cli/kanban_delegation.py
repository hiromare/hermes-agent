"""Atomic receipts for explicitly delegated Kanban work, stored with the board."""

import hashlib
import json

from hermes_cli import kanban_db
from hermes_cli.kanban_db_connect import write_txn


class DelegationConflict(ValueError):
    pass


class DelegationTaskMissing(ValueError):
    pass


def lookup(conn, request_id):
    # Boards that have never accepted a delegation have no receipt table yet.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delegation_receipts'").fetchone():
        return None
    receipt = conn.execute("SELECT task_id FROM delegation_receipts WHERE request_id=?", (request_id,)).fetchone()
    if receipt is None:
        return None
    task = kanban_db.get_task(conn, receipt["task_id"])
    if task is None:
        raise DelegationTaskMissing("the original task no longer exists")
    return task


def submit(conn, *, board, request_id, origin, title, body, assignee):
    payload = {"origin": origin, "title": title, "body": body, "assignee": assignee}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode()).hexdigest()
    with write_txn(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS delegation_receipts (
            request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, task_id TEXT NOT NULL
        )""")
        receipt = conn.execute(
            "SELECT payload_hash, task_id FROM delegation_receipts WHERE request_id = ?", (request_id,)
        ).fetchone()
        if receipt:
            if receipt["payload_hash"] != digest:
                raise DelegationConflict("request_id already used with a different payload")
            task = kanban_db.get_task(conn, receipt["task_id"])
            if task is None:
                raise DelegationTaskMissing("the original task no longer exists")
            return task, False
        task_id = kanban_db.create_task(conn, title=title, body=body, assignee=assignee,
                                        created_by=origin, board=board)
        conn.execute("INSERT INTO delegation_receipts VALUES (?, ?, ?)", (request_id, digest, task_id))
        return kanban_db.get_task(conn, task_id), True
