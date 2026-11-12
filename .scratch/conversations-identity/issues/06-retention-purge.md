# 06: Retention purge

**What to build:** Stored Conversations are deleted after a retention period, so Merchant data isn't kept forever.

- `CONVERSATION_RETENTION_DAYS` (default 30).
- At startup, Conversations not updated within the window are deleted together with their Turns.
- Clock injectable for tests. README env table and privacy notes mention the retention window.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Store test with injected clock: stale Conversation and its Turns deleted, fresh one kept
- [ ] Purge runs at app startup
- [ ] Setting documented
