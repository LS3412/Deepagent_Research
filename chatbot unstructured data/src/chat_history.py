"""SQLite-backed chat history with automatic 2-day retention."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import get_settings

log = logging.getLogger(__name__)

_DB_NAME = "chat_history.db"


def _db_path() -> Path:
    return get_settings().data_dir / _DB_NAME


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT    NOT NULL,
            tenant_id  TEXT    NOT NULL,
            role       TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            trace      TEXT,
            created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages (created_at)"
    )
    conn.commit()
    return conn


def prune_old_messages(days: int = 2) -> int:
    """Delete messages older than *days* days. Returns count of deleted rows."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
        conn.commit()
        deleted = cur.rowcount
        if deleted:
            log.info("pruned %d messages older than %d days", deleted, days)
        return deleted
    finally:
        conn.close()


def save_message(
    session_id: str,
    tenant_id: str,
    role: str,
    content: str,
    trace: list[str] | None = None,
) -> None:
    """Persist a single chat message."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO messages (session_id, tenant_id, role, content, trace)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                tenant_id,
                role,
                content,
                json.dumps(trace) if trace else None,
            ),
        )
        conn.commit()
        log.debug("saved message  session=%s  role=%s", session_id, role)
    finally:
        conn.close()


def load_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Load all messages for a session (within the retention window)."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT role, content, trace, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()
        messages: list[dict[str, Any]] = []
        for role, content, trace_json, created_at in rows:
            msg: dict[str, Any] = {"role": role, "content": content}
            if trace_json:
                msg["trace"] = json.loads(trace_json)
            msg["created_at"] = created_at
            messages.append(msg)
        return messages
    finally:
        conn.close()


def load_recent_sessions(tenant_id: str, days: int = 2) -> list[dict[str, Any]]:
    """Return a list of recent sessions with their first user message as preview."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT session_id,
                   MIN(created_at) AS started,
                   MAX(created_at) AS last_msg,
                   COUNT(*)        AS msg_count
            FROM messages
            WHERE tenant_id = ? AND created_at >= ?
            GROUP BY session_id
            ORDER BY last_msg DESC
            """,
            (tenant_id, cutoff),
        ).fetchall()
        sessions: list[dict[str, Any]] = []
        for sid, started, last_msg, count in rows:
            # Grab first user message as preview
            preview_row = conn.execute(
                """
                SELECT content FROM messages
                WHERE session_id = ? AND role = 'user'
                ORDER BY id ASC LIMIT 1
                """,
                (sid,),
            ).fetchone()
            preview = (preview_row[0][:80] + "...") if preview_row and len(preview_row[0]) > 80 else (preview_row[0] if preview_row else "")
            sessions.append({
                "session_id": sid,
                "started": started,
                "last_message": last_msg,
                "message_count": count,
                "preview": preview,
            })
        return sessions
    finally:
        conn.close()
