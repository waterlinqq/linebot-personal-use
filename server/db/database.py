from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from server.engine.matcher import MatchConfig

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "linebot.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS message_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            sender TEXT,
            raw_text TEXT NOT NULL,
            is_order INTEGER NOT NULL DEFAULT 0,
            should_reply INTEGER NOT NULL DEFAULT 0,
            replied INTEGER NOT NULL DEFAULT 0,
            matched_regions TEXT,
            reason TEXT
        );
        """
    )
    conn.commit()


def load_match_config(conn: sqlite3.Connection) -> MatchConfig | None:
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'match_config'"
    ).fetchone()
    if not row:
        return None
    data = json.loads(row["value"])
    return MatchConfig(**data)


def save_match_config(conn: sqlite3.Connection, config: MatchConfig) -> None:
    payload = json.dumps(config.__dict__, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO settings (key, value) VALUES ('match_config', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (payload,),
    )
    conn.commit()


def insert_message_log(
    conn: sqlite3.Connection,
    *,
    sender: str,
    raw_text: str,
    is_order: bool,
    should_reply: bool,
    replied: bool,
    matched_regions: list[str],
    reason: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO message_logs
            (sender, raw_text, is_order, should_reply, replied, matched_regions, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sender,
            raw_text,
            int(is_order),
            int(should_reply),
            int(replied),
            json.dumps(matched_regions, ensure_ascii=False),
            reason,
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def list_message_logs(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, created_at, sender, raw_text, is_order, should_reply, replied,
               matched_regions, reason
        FROM message_logs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["matched_regions"] = json.loads(item["matched_regions"] or "[]")
        item["is_order"] = bool(item["is_order"])
        item["should_reply"] = bool(item["should_reply"])
        item["replied"] = bool(item["replied"])
        result.append(item)
    return result
