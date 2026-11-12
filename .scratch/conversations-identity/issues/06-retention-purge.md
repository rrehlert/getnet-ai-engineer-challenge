# 06: Retention purge

**What to build:** Stored Conversations are deleted after a retention period, so Merchant data isn't kept forever.

- `CONVERSATION_RETENTION_DAYS` (default 30).
- At startup, Conversations not updated within the window are deleted together with their Turns.
- Clock injectable for tests. README env table and privacy notes mention the retention window.

**Blocked by:** 03

**Status:** done

- [x] Store test with injected clock: stale Conversation and its Turns deleted, fresh one kept
- [x] Purge runs at app startup
- [x] Setting documented

## Comments

- `Store.purge(retention: timedelta) -> int` (end of class): deletes Turns then Conversations with `updated_at < clock() - retention`, one transaction; returns the count. A Conversation updated exactly at the window edge is kept. ISO-8601 UTC strings compare correctly as text.
- `CONVERSATION_RETENTION_DAYS` (`PositiveInt`, default 30) in `app/settings.py`, read at startup via `get_settings()`.
- `app/main.py`: lifespan calls `purge_stale_conversations(get_store())` instead of bare `get_store()`; logs `retention purge: deleted N conversation(s) not updated in D days` (no ids/owners). Startup only, no periodic job.
- Tests: `tests/test_store.py` (stale/fresh with Turns, edge), `tests/test_retention.py` (startup default 30, env override, no purge without startup). README (config table, Conversations, Privacy, Testing; 253 tests) and `.env.example` updated; compose needs no change (`.env` passes through).
