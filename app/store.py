"""Conversations and their Turns in SQLite, the single store (ADR 0004).

One short-lived connection per call, so the store is safe from FastAPI's
threadpool; WAL lets readers run alongside the single writer.
"""

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

Role = Literal["user", "assistant", "operator"]
# Human takeover (ADR 0006); only `bot` is used so far.
Mode = Literal["bot", "waiting_human", "human", "closed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'bot'
);
CREATE INDEX IF NOT EXISTS conversations_owner ON conversations (owner, updated_at);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'operator')),
    content TEXT NOT NULL,
    intent TEXT,
    sources TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS turns_conversation ON turns (conversation_id, id);
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Conversation:
    id: str
    owner: str
    created_at: datetime
    updated_at: datetime
    mode: Mode


@dataclass(frozen=True)
class NewTurn:
    """A Turn to append. `sources` are Sources (url, title); never raw tool output or Evidence."""

    role: Role
    content: str
    intent: str | None = None
    sources: Sequence[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Turn:
    id: int
    conversation_id: str
    role: Role
    content: str
    intent: str | None
    sources: list[dict]
    created_at: datetime


class Store:
    """`clock` stamps `created_at`/`updated_at` (UTC); injectable for retention tests."""

    def __init__(self, path: Path | str, clock: Callable[[], datetime] = utc_now):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection for one call; commits on success, rolls back on error, always closes."""
        with closing(sqlite3.connect(self.path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                yield conn

    def _now(self) -> str:
        return self.clock().astimezone(UTC).isoformat()

    def create_conversation(self, owner: str) -> str:
        """A new, empty Conversation in `bot` Mode; returns its random id."""
        cid, now = str(uuid.uuid4()), self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, owner, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cid, owner, now, now),
            )
        return cid

    def conversation(self, conversation_id: str, owner: str) -> Conversation | None:
        """The Conversation if it exists and belongs to `owner`; otherwise None (indistinguishable)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND owner = ?", (conversation_id, owner)
            ).fetchone()
        if row is None:
            return None
        return Conversation(
            id=row["id"],
            owner=row["owner"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            mode=row["mode"],
        )

    def append_turns(self, conversation_id: str, turns: Sequence[NewTurn]) -> None:
        """Append `turns` in order, in one transaction, and bump the Conversation's `updated_at`."""
        now = self._now()
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO turns (conversation_id, role, content, intent, sources, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (conversation_id, t.role, t.content, t.intent, json.dumps(list(t.sources), ensure_ascii=False), now)
                    for t in turns
                ],
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))

    def turns(self, conversation_id: str) -> list[Turn]:
        """All Turns of the Conversation, oldest first. No owner check: callers check first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM turns WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            ).fetchall()
        return [
            Turn(
                id=r["id"],
                conversation_id=r["conversation_id"],
                role=r["role"],
                content=r["content"],
                intent=r["intent"],
                sources=json.loads(r["sources"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def purge(self, retention: timedelta) -> int:
        """Delete Conversations not updated within `retention` of now, with their Turns; returns how many."""
        cutoff = (self.clock() - retention).astimezone(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM turns WHERE conversation_id IN (SELECT id FROM conversations WHERE updated_at < ?)",
                (cutoff,),
            )
            return conn.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,)).rowcount
