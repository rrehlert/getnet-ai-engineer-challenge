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
# Human takeover (ADR 0006): only `bot` runs the graph.
Mode = Literal["bot", "waiting_human", "human", "closed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'bot',
    needs_review INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    brief TEXT NOT NULL,
    -- The last Turn the brief was written from: later Turns mean it is stale.
    brief_turn_id INTEGER,
    created_at TEXT NOT NULL,
    claimed_by TEXT,
    claimed_at TEXT,
    outcome TEXT CHECK (outcome IN ('handed_back', 'closed')),
    ended_at TEXT
);
-- At most one open Handoff per Conversation (ADR 0006).
CREATE UNIQUE INDEX IF NOT EXISTS handoffs_open ON handoffs (conversation_id) WHERE ended_at IS NULL;
-- Operator actions: who, what, when. No message text or brief content; no foreign key,
-- so the retention purge keeps these rows after their Conversation is gone.
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('claim', 'reply', 'handback', 'close', 'reviewed')),
    conversation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_suggestion INTEGER  -- replies only
);
"""

# Columns added after a table was first created: (table, column, definition), for older database files.
ADDED_COLUMNS = [
    ("conversations", "needs_review", "INTEGER NOT NULL DEFAULT 0"),
    ("handoffs", "brief_turn_id", "INTEGER"),
]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Conversation:
    id: str
    owner: str
    created_at: datetime
    updated_at: datetime
    mode: Mode
    needs_review: bool = False  # the Review flag (set by low answer Judge Scores)


@dataclass(frozen=True)
class NewTurn:
    """A Turn to append. `sources` are Sources (url, title); never raw tool output or Evidence."""

    role: Role
    content: str
    intent: str | None = None
    sources: Sequence[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Handoff:
    """One Escalation episode (ADR 0006): open while `ended_at` is None."""

    id: int
    conversation_id: str
    brief: dict  # the Handoff Brief; stored, never logged
    created_at: datetime
    claimed_by: str | None
    claimed_at: datetime | None
    outcome: Literal["handed_back", "closed"] | None
    ended_at: datetime | None
    brief_turn_id: int | None = None  # the last Turn the brief was written from


class ModeChanged(Exception):  # noqa: N818 - a refusal, not a failure
    """A conditional write refused: the Conversation is no longer in a Mode the caller read
    (another request escalated it, or an Operator acted). `mode` is its Mode now (None: gone)."""

    def __init__(self, mode: Mode | None):
        super().__init__(f"conversation is now in mode {mode!r}")
        self.mode = mode


AuditAction = Literal["claim", "reply", "handback", "close", "reviewed"]
# An Operator action's outcome: done; refused because another Operator holds the claim; or refused by the Mode.
ActionResult = Literal["done", "not_claimer", "wrong_mode"]


@dataclass(frozen=True)
class AuditEntry:
    """One Operator action: who, what, when. Never message text or brief content."""

    operator: str
    action: AuditAction
    conversation_id: str
    created_at: datetime
    used_suggestion: bool | None  # replies only: the suggested reply sent unchanged


def _when(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _conversation(r: sqlite3.Row) -> Conversation:
    return Conversation(
        id=r["id"],
        owner=r["owner"],
        created_at=datetime.fromisoformat(r["created_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
        mode=r["mode"],
        needs_review=bool(r["needs_review"]),
    )


def _handoff(r: sqlite3.Row) -> Handoff:
    return Handoff(
        id=r["id"],
        conversation_id=r["conversation_id"],
        brief=json.loads(r["brief"]),
        created_at=datetime.fromisoformat(r["created_at"]),
        claimed_by=r["claimed_by"],
        claimed_at=_when(r["claimed_at"]),
        outcome=r["outcome"],
        ended_at=_when(r["ended_at"]),
        brief_turn_id=r["brief_turn_id"],
    )


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
            for table, column, definition in ADDED_COLUMNS:
                if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
        with self._connect() as conn:
            return self._create(conn, owner, self._now())

    @staticmethod
    def _create(conn: sqlite3.Connection, owner: str, now: str) -> str:
        cid = str(uuid.uuid4())
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
        return None if row is None else _conversation(row)

    def operator_conversation(self, conversation_id: str) -> Conversation | None:
        """Operator side only: the Conversation whoever owns it, if Operators may see it
        (it had a Handoff or carries the Review flag); otherwise None, like an unknown id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations c WHERE id = ? AND (needs_review"
                " OR EXISTS (SELECT 1 FROM handoffs h WHERE h.conversation_id = c.id))",
                (conversation_id,),
            ).fetchone()
        return None if row is None else _conversation(row)

    def set_mode(self, conversation_id: str, mode: Mode) -> None:
        """Set the Conversation's Mode and bump `updated_at`. No transition rules here: callers decide (ADR 0006)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET mode = ?, updated_at = ? WHERE id = ?", (mode, self._now(), conversation_id)
            )

    def flag_for_review(self, conversation_id: str) -> None:
        """Set the Review flag. Mode and `updated_at` are untouched: a flag is not Merchant activity."""
        with self._connect() as conn:
            conn.execute("UPDATE conversations SET needs_review = 1 WHERE id = ?", (conversation_id,))

    def clear_review(self, conversation_id: str, operator: str) -> bool:
        """Clear the Review flag and audit it (`reviewed`), in one transaction; Mode untouched.
        False, with nothing changed or audited, when the flag was not set."""
        with self._connect() as conn:
            cleared = conn.execute(
                "UPDATE conversations SET needs_review = 0 WHERE id = ? AND needs_review", (conversation_id,)
            ).rowcount == 1
            if cleared:
                self._audit(conn, operator, "reviewed", conversation_id, self._now())
        return cleared

    def review_list(self) -> list[Conversation]:
        """Conversations with the Review flag, any Mode, most recently updated first (Operator side only)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE needs_review ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [_conversation(r) for r in rows]

    def append_turns(
        self, conversation_id: str, turns: Sequence[NewTurn], while_in: Sequence[Mode] | None = None,
    ) -> None:
        """Append `turns` in order, in one transaction, and bump the Conversation's `updated_at`.
        With `while_in`, only if the Mode is one of them; else `ModeChanged` and nothing is stored."""
        with self._connect() as conn:
            now = self._now()
            if while_in is not None:
                self._require_mode(conn, conversation_id, while_in, now)
            self._append(conn, conversation_id, turns, now)

    @staticmethod
    def _require_mode(conn: sqlite3.Connection, conversation_id: str, modes: Sequence[Mode], now: str) -> None:
        """One conditional update decides, inside the caller's transaction, so a racing Mode
        change can't slip in between the check and the writes; raises `ModeChanged` (rolls back)."""
        marks = ", ".join("?" for _ in modes)
        if conn.execute(
            f"UPDATE conversations SET updated_at = ? WHERE id = ? AND mode IN ({marks})",
            (now, conversation_id, *modes),
        ).rowcount != 1:
            row = conn.execute("SELECT mode FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            raise ModeChanged(None if row is None else row["mode"])

    @staticmethod
    def _append(conn: sqlite3.Connection, conversation_id: str, turns: Sequence[NewTurn], now: str) -> None:
        conn.executemany(
            "INSERT INTO turns (conversation_id, role, content, intent, sources, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (conversation_id, t.role, t.content, t.intent, json.dumps(list(t.sources), ensure_ascii=False), now)
                for t in turns
            ],
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))

    def escalate(self, conversation_id: str | None, owner: str, turns: Sequence[NewTurn], brief: dict) -> str:
        """An Escalation in one transaction: create the Conversation if `conversation_id` is None,
        append `turns`, open a Handoff with `brief` and set Mode `waiting_human`; returns the id.

        Only from `bot`: in any other Mode (e.g. a racing Escalation got there first) it raises
        `ModeChanged` and nothing is stored. Callers check ownership first (as for `append_turns`).
        """
        now = self._now()
        with self._connect() as conn:
            if conversation_id is None:
                cid = self._create(conn, owner, now)
            else:
                cid = conversation_id
                self._require_mode(conn, cid, ("bot",), now)
            self._append(conn, cid, turns, now)
            conn.execute(
                "INSERT INTO handoffs (conversation_id, brief, brief_turn_id, created_at)"
                " VALUES (?, ?, (SELECT MAX(id) FROM turns WHERE conversation_id = ?), ?)",
                (cid, json.dumps(brief, ensure_ascii=False), cid, now),
            )
            conn.execute("UPDATE conversations SET mode = 'waiting_human' WHERE id = ?", (cid,))
        return cid

    def handoffs(self, conversation_id: str) -> list[Handoff]:
        """The Conversation's Handoffs, oldest first. No owner check: callers check first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM handoffs WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            ).fetchall()
        return [_handoff(r) for r in rows]

    def claim(self, conversation_id: str, operator: str) -> bool:
        """`waiting_human` → `human` for `operator`, in one transaction: one conditional update
        (so of two Operators only one wins), the open Handoff's claim, and an audit row.
        False, with nothing changed, when the Conversation is not `waiting_human`."""
        now = self._now()
        with self._connect() as conn:
            won = conn.execute(
                "UPDATE conversations SET mode = 'human', updated_at = ? WHERE id = ? AND mode = 'waiting_human'",
                (now, conversation_id),
            ).rowcount == 1
            if won:
                conn.execute(
                    "UPDATE handoffs SET claimed_by = ?, claimed_at = ? WHERE conversation_id = ? AND ended_at IS NULL",
                    (operator, now, conversation_id),
                )
                self._audit(conn, operator, "claim", conversation_id, now)
        return won

    # Operator actions in `human` Mode (ADR 0006). Each runs in one transaction: a conditional
    # update decides (so a racing action can't slip past the check), then its writes and audit row.

    _CLAIMED_BY = (
        "EXISTS (SELECT 1 FROM handoffs h WHERE h.conversation_id = conversations.id"
        " AND h.ended_at IS NULL AND h.claimed_by = ?)"
    )

    @staticmethod
    def _refused(conn: sqlite3.Connection, conversation_id: str) -> ActionResult:
        """Why a conditional update changed nothing: another Operator's claim, or the wrong Mode."""
        row = conn.execute("SELECT mode FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return "not_claimer" if row is not None and row["mode"] == "human" else "wrong_mode"

    def reply(self, conversation_id: str, operator: str, turn: NewTurn, used_suggestion: bool) -> ActionResult:
        """Append the claiming Operator's `turn`; only in `human` Mode, only by `operator` holding the claim."""
        now = self._now()
        with self._connect() as conn:
            if conn.execute(
                f"UPDATE conversations SET updated_at = ? WHERE id = ? AND mode = 'human' AND {self._CLAIMED_BY}",
                (now, conversation_id, operator),
            ).rowcount != 1:
                return self._refused(conn, conversation_id)
            self._append(conn, conversation_id, [turn], now)
            self._audit(conn, operator, "reply", conversation_id, now, used_suggestion)
        return "done"

    def hand_back(self, conversation_id: str, operator: str, turn: NewTurn) -> ActionResult:
        """`human` → `bot` by the claiming Operator: the Handoff ends `handed_back` and `turn` is appended."""
        return self._end(conversation_id, operator, "bot", "handed_back", turn,
                         f"mode = 'human' AND {self._CLAIMED_BY}", (operator,))

    def close(self, conversation_id: str, operator: str, turn: NewTurn) -> ActionResult:
        """→ `closed`: from `human` by the claiming Operator, or from `waiting_human` by any Operator
        (no claim needed). The Handoff ends `closed` and `turn` is appended."""
        return self._end(conversation_id, operator, "closed", "closed", turn,
                         f"(mode = 'waiting_human' OR (mode = 'human' AND {self._CLAIMED_BY}))", (operator,))

    def _end(
        self, conversation_id: str, operator: str, mode: Mode, outcome: Literal["handed_back", "closed"],
        turn: NewTurn, allowed: str, allowed_params: tuple,
    ) -> ActionResult:
        now = self._now()
        with self._connect() as conn:
            if conn.execute(
                f"UPDATE conversations SET mode = ?, updated_at = ? WHERE id = ? AND {allowed}",
                (mode, now, conversation_id, *allowed_params),
            ).rowcount != 1:
                return self._refused(conn, conversation_id)
            conn.execute(
                "UPDATE handoffs SET outcome = ?, ended_at = ? WHERE conversation_id = ? AND ended_at IS NULL",
                (outcome, now, conversation_id),
            )
            self._append(conn, conversation_id, [turn], now)
            self._audit(conn, operator, "handback" if outcome == "handed_back" else "close", conversation_id, now)
        return "done"

    def replace_brief(self, handoff_id: int, brief: dict, brief_turn_id: int) -> None:
        """A rewritten Handoff Brief, written from the Turns up to `brief_turn_id`."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE handoffs SET brief = ?, brief_turn_id = ? WHERE id = ?",
                (json.dumps(brief, ensure_ascii=False), brief_turn_id, handoff_id),
            )

    @staticmethod
    def _audit(
        conn: sqlite3.Connection, operator: str, action: AuditAction, conversation_id: str, now: str,
        used_suggestion: bool | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO audit (operator, action, conversation_id, created_at, used_suggestion) VALUES (?, ?, ?, ?, ?)",
            (operator, action, conversation_id, now, used_suggestion),
        )

    def audit_log(self, conversation_id: str) -> list[AuditEntry]:
        """The audit rows for a Conversation id, oldest first (kept after the Conversation is purged)."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM audit WHERE conversation_id = ? ORDER BY id", (conversation_id,)).fetchall()
        return [
            AuditEntry(
                operator=r["operator"],
                action=r["action"],
                conversation_id=r["conversation_id"],
                created_at=datetime.fromisoformat(r["created_at"]),
                used_suggestion=None if r["used_suggestion"] is None else bool(r["used_suggestion"]),
            )
            for r in rows
        ]

    def queue(self) -> list[Handoff]:
        """The open Handoffs of Conversations in `waiting_human`, oldest first (Operator side only)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT h.* FROM handoffs h JOIN conversations c ON c.id = h.conversation_id"
                " WHERE c.mode = 'waiting_human' AND h.ended_at IS NULL ORDER BY h.created_at, h.id"
            ).fetchall()
        return [_handoff(r) for r in rows]

    def turns(self, conversation_id: str, after: int = 0) -> list[Turn]:
        """Turns of the Conversation with id > `after` (default: all), oldest first. No owner check: callers check first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM turns WHERE conversation_id = ? AND id > ? ORDER BY id", (conversation_id, after)
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
        """Delete Conversations not updated within `retention` of now, with their Turns and Handoffs; returns how many."""
        cutoff = (self.clock() - retention).astimezone(UTC).isoformat()
        with self._connect() as conn:
            for child in ("turns", "handoffs"):
                conn.execute(
                    f"DELETE FROM {child} WHERE conversation_id IN (SELECT id FROM conversations WHERE updated_at < ?)",
                    (cutoff,),
                )
            return conn.execute("DELETE FROM conversations WHERE updated_at < ?", (cutoff,)).rowcount

    def conversations(self, owner: str) -> list[Conversation]:
        """`owner`'s Conversations, most recently updated first (ties: newest created first)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE owner = ? ORDER BY updated_at DESC, rowid DESC", (owner,)
            ).fetchall()
        return [_conversation(r) for r in rows]
