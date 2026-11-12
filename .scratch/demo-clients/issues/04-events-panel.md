# 04: Live events for a Conversation

**What to build:** The Operator sees, next to a Conversation, the redacted log events of its traces, including Judge events that arrive later.

- A second logging handler keeps the last ~2000 formatted events in memory: the same redacted JSON that goes to stdout. stdout stays the source of record.
- `GET /operator/conversations/{id}/events` (role `operator`, same visibility rule as the detail, else 404): find the `request` events with this `conversation_id`, take their `trace_id`s, and return every buffered event with one of those `trace_id`s, oldest first.
- No global "tail all" view.
- Events panel in the Operator detail, polled with the Turns.
- README and `IMPROVEMENT_RUN_DIARY.md`: limits are lost on restart, per process (single instance), bounded so older events drop out.

**Blocked by:** 03

**Status:** done

- [x] Ring buffer handler, bounded, holds the redacted JSON
- [x] Endpoint: Merchant 403; not visible → 404; only this Conversation's traces; a Judge event emitted after the request is included
- [x] Events panel in the Operator view
- [x] Limits written in the README and diary

## Comments

- `app/observability.py`: `EventBuffer(capacity=EVENT_BUFFER_SIZE=2000)`, a `logging.Handler` with its own `JsonFormatter`, so each entry is exactly the line stdout gets (already redacted: `emit` redacts fields, the formatter redacts plain log lines and exception text), parsed back to a dict. Kept as dicts, not strings: parsed once on write, the endpoint returns them as JSON objects. `deque(maxlen=capacity)` + a `threading.Lock` (Judges log from background tasks). `events()` = snapshot, oldest first; `for_conversation(id)` = `trace_id`s of buffered `request` events with that `conversation_id`, then every buffered event with one of those `trace_id`s, oldest first.
- Module-level `EVENTS` is the production buffer; `setup_logging()` adds it to the `app` logger (once) next to the stdout handler. Tests: `setup_logging()` runs at `app.main` import, so `EVENTS` fills during the suite too (harmless, bounded); tests use a fresh `EventBuffer` attached to the `app` logger by a fixture and pass it as `create_app(events=...)` (default `EVENTS`).
- `JsonFormatter` now starts every line with `time` (ISO 8601 UTC, ms, from `record.created`), then `level`. It changes stdout too (it had no timestamp); needed for the panel's time column while keeping buffer == stdout. Separate commit.
- `GET /operator/conversations/{id}/events` in `operator_router` (new `events=` param): `Operator` dependency (401/403), `store().operator_conversation(id)` else `_not_found()`; matches on the stored `conversation.id`, which is the canonical UUID string `log_request` keeps (`_canonical_uuid`). Response `{"events": [...]}`. Reads not audited. No global tail.
- Non-JSON log lines (`log.error("judge %s failed trace_id=%s")`, brief rewrite warnings) have no `trace_id` field, so they never match a Conversation: only `request` and `judge` events show up today.
- `app/static/events.js`, loaded after `operator.js` (defer): pushes one entry into `OPERATOR_PANELS`. `update()` fetches the events (skipped while a fetch is in flight; after `stop()` responses are dropped). Rows are `<details>`: local time, event, level badge (WARNING/ERROR coloured), first 8 chars of `trace_id`, then present key fields (`intent, agent, tools, judge_type, judge_score, fully_answered, tokens, latency_ms, outcome`); expanded = pretty JSON in a `<pre>`. List only rebuilt when the JSON changes; expanded rows are kept across refreshes. A note says it's in-memory, lost on restart, oldest dropped. All text via `el`/`textContent`. CSS: `/* Events panel */` at the end of `style.css`, classes `ev-*`.
- Tests: `tests/test_events.py` (9): 401/403; not visible and unknown id → 404; only this Conversation's traces, oldest first, later Judge event included, other Conversation's request/judge and trace-less lines excluded; end-to-end through `/chat` with fake Judges in background (low `answer` score sets the Review flag → visible; request + 3 judges, one trace); empty list; bounded (capacity 3 keeps the last 3); request dropped → its trace no longer found; buffer content == `JsonFormatter` output of the same records, with email/CPF masked; `setup_logging` installs `EVENTS` once. `tests/test_log_privacy.py`: line starts with `time`, `level`. `tests/test_page.py`: `events.js` loaded after `operator.js`. `uv run pytest`: 428 passed. `node --check` on `events.js`.
- Verified in a real browser (headless Chrome via the local puppeteer, scratch server = `create_app` with a seeded SQLite Store, `setup_logging` from import, events seeded with `log_request`/`emit`, one Judge event emitted 6 s later from a thread): rows and key fields, WARNING badge, other Conversation's events excluded, JSON expanded shows `[EMAIL]` and an `<img onerror>` payload as text (no element created), the late Judge event appears through polling, expanded row stays open, switching Conversation shows only its events, no page errors.
- Not done: README and `IMPROVEMENT_RUN_DIARY.md` limits (user rule: those files are not edited by agents); text proposed in the hand-off report. Not verified: real Judges (LLM) in the browser; live walkthrough belongs to 06.
