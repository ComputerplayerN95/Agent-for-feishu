"""SQLite 存储：事件去重 + 消息流水。

故意用同步 sqlite3：每次调用都在亚毫秒级，外层用 asyncio.to_thread 包一层，
比引入 aiosqlite 少一个依赖，也少一层连接池。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from .models import IncomingMessage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_events (
    event_id   TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT,
    channel     TEXT NOT NULL,
    chat_id     TEXT NOT NULL,
    sender_id   TEXT NOT NULL,
    text        TEXT NOT NULL,
    reply       TEXT,
    received_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (chat_id, id);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # --- lifecycle -------------------------------------------------
    def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        self._conn = conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def connected(self) -> bool:
        return self._conn is not None

    def ping(self) -> bool:
        try:
            with self._lock:
                if self._conn is None:
                    return False
                self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    # --- writes ----------------------------------------------------
    def mark_event(self, event_id: str) -> bool:
        """第一次见到这个 event_id 返回 True，重复事件返回 False。"""
        if not event_id:
            return True
        with self._lock:
            if self._conn is None:
                raise RuntimeError("store is not connected")
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO processed_events (event_id, created_at) VALUES (?, ?)",
                (event_id, time.time()),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def save_message(self, msg: IncomingMessage, reply: str | None) -> None:
        with self._lock:
            if self._conn is None:
                raise RuntimeError("store is not connected")
            self._conn.execute(
                "INSERT INTO messages"
                " (event_id, channel, chat_id, sender_id, text, reply, received_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    msg.event_id,
                    msg.channel,
                    msg.chat_id,
                    msg.sender_id,
                    msg.text,
                    reply,
                    time.time(),
                ),
            )
            self._conn.commit()

    # --- reads -----------------------------------------------------
    def recent(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            if self._conn is None:
                raise RuntimeError("store is not connected")
            return self._conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
