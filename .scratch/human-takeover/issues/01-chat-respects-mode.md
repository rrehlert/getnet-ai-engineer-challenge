# 01: `/chat` respects the Mode

**What to build:** A Conversation that is not in `bot` Mode is not answered by the Agents. In `waiting_human` or `human` the Merchant's Message is kept for the Operator and the Merchant can see the Mode; a `closed` Conversation refuses new Messages. Groundwork for the rest of the takeover: Modes are set directly in the store here.

- Every `/chat` response carries `mode`; `intent` and `agent` become nullable.
- `waiting_human` / `human`: the Message is stored as a `user` Turn with no Intent; the graph does not run; response 200, `answer: ""`, `intent: null`, `agent: null`. Logged with outcome `queued`; no Judges run.
- `closed`: 409; the Merchant starts a new Conversation.
- The Turns listing (`GET /conversations/{id}/turns`) carries the Conversation's `mode`.
- The store gains a way to set a Conversation's Mode (used by tests now, by Escalation and Operators later).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `bot` Mode: behaviour unchanged, response has `mode: "bot"`
- [ ] `waiting_human` and `human`: a fake graph asserts it is never invoked; Message stored as a `user` Turn; response shape as above
- [ ] `closed` → 409, nothing stored
- [ ] Turns listing shows `mode`
- [ ] `queued` outcome logged with the usual redaction; no Judge run
- [ ] Anonymous behaviour unchanged
- [ ] No real LLM calls in tests
