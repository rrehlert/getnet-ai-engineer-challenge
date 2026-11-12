# 01: `/chat` respects the Mode

**What to build:** A Conversation that is not in `bot` Mode is not answered by the Agents. In `waiting_human` or `human` the Merchant's Message is kept for the Operator and the Merchant can see the Mode; a `closed` Conversation refuses new Messages. Groundwork for the rest of the takeover: Modes are set directly in the store here.

- Every `/chat` response carries `mode`; `intent` and `agent` become nullable.
- `waiting_human` / `human`: the Message is stored as a `user` Turn with no Intent; the graph does not run; response 200, `answer: ""`, `intent: null`, `agent: null`. Logged with outcome `queued`; no Judges run.
- `closed`: 409; the Merchant starts a new Conversation.
- The Turns listing (`GET /conversations/{id}/turns`) carries the Conversation's `mode`.
- The store gains a way to set a Conversation's Mode (used by tests now, by Escalation and Operators later).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] `bot` Mode: behaviour unchanged, response has `mode: "bot"`
- [x] `waiting_human` and `human`: a fake graph asserts it is never invoked; Message stored as a `user` Turn; response shape as above
- [x] `closed` → 409, nothing stored
- [x] Turns listing shows `mode`
- [x] `queued` outcome logged with the usual redaction; no Judge run
- [x] Anonymous behaviour unchanged
- [x] No real LLM calls in tests

## Comments

- `ChatResponse` gains `mode: Mode` (always present; `"bot"` for anonymous too); `intent`/`agent` are `| None`. `TurnList` gains `mode`, read from the same owner-checked Conversation lookup.
- `/chat` order: owner check (another Merchant's Conversation stays 404 in any Mode, so Mode never leaks) → `closed` → 409 `conversation_closed`, nothing stored, logged with outcome `conversation_closed` → `waiting_human`/`human` → one `user` Turn with no Intent, response `answer: ""`, `sources: []`, `steps: []`, logged `queued` via the usual `log_request` (redacted Message, `intent`/`agent` null), no Judge task → `bot` as before. History is not loaded for the bypass.
- `Store.set_mode(conversation_id, mode)`: plain update that also bumps `updated_at` (a Mode change is activity for retention). No transition rules in the store; Escalation and Operator tickets enforce them (claim needs its own conditional update anyway).
- Tests in `tests/test_chat_mode.py` (12): fake graphs only; `NeverInvokedGraph` raises if invoked; queued test enables Judges with a fake Judge model that fails on any call and asserts no `judge` line.
- Left out: README not touched (user rule); API docs for `mode` / 409 there come with a later ticket.
- `ruff` is not a project dependency; ran `uvx ruff check`. Repo has pre-existing findings in untouched files (I001 in `app/main.py`, F811 in `tests/test_listing.py`, RUF012 etc. under ruff 0.17 defaults); new/changed code adds none.
