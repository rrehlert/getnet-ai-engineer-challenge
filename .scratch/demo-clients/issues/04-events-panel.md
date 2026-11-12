# 04: Live events for a Conversation

**What to build:** The Operator sees, next to a Conversation, the redacted log events of its traces, including Judge events that arrive later.

- A second logging handler keeps the last ~2000 formatted events in memory: the same redacted JSON that goes to stdout. stdout stays the source of record.
- `GET /operator/conversations/{id}/events` (role `operator`, same visibility rule as the detail, else 404): find the `request` events with this `conversation_id`, take their `trace_id`s, and return every buffered event with one of those `trace_id`s, oldest first.
- No global "tail all" view.
- Events panel in the Operator detail, polled with the Turns.
- README and `IMPROVEMENT_RUN_DIARY.md`: limits are lost on restart, per process (single instance), bounded so older events drop out.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Ring buffer handler, bounded, holds the redacted JSON
- [ ] Endpoint: Merchant 403; not visible → 404; only this Conversation's traces; a Judge event emitted after the request is included
- [ ] Events panel in the Operator view
- [ ] Limits written in the README and diary
