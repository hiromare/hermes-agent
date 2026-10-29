"""Read-only projection of significant events on one Kanban board."""

import sqlite3
from urllib.parse import quote


def activity(conn: sqlite3.Connection, board: str, limit: int) -> list[dict]:
    rows = conn.execute(
        """SELECT e.id AS event_id, e.kind, e.created_at, t.id AS task_id,
                  t.title, t.status, t.result
           FROM task_events AS e JOIN tasks AS t ON t.id = e.task_id
           WHERE e.kind IN ('completed', 'gave_up')
           ORDER BY e.created_at DESC, e.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [
        {**dict(row), "board": board,
         "task_url": f"/api/plugins/kanban/tasks/{quote(row['task_id'], safe='')}?board={quote(board, safe='')}"}
        for row in rows
    ]
