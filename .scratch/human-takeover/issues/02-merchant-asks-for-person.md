# 02: Merchant asks for a person → Escalator Agent → waiting

**What to build:** A logged-in Merchant who writes "I want to talk to a person" gets a transfer message in their language, and the Conversation waits for an Operator with a Handoff Brief ready. An anonymous visitor asking the same gets the "log in" reply instead.

- Intent gains `human` (Router prompt and the shared Intent policy, Merchant and anonymous identity). `agent` gains `escalator`.
- Escalator Agent: one structured model call (no tools). Input: recent history, escalation reason, Intent, current Turn's Evidence and Sources. Output: Handoff Brief (`reason`, `customer_ask`, `summary`, `attempted`, `category`, `priority` low/normal/high, `suggested_reply`, `language`) plus a transfer message. Missing message or unparseable output → fixed bilingual fallback.
- The graph routes `human` (Merchant) to the Escalator; the node returns the transfer message as `answer` and the brief as `handoff` in the state, and touches no store.
- Handoffs storage: one Handoff per Escalation (brief, created at, claimed by/at, outcome, ended at), at most one open per Conversation, deleted with its Conversation (retention purge included).
- `/chat`, in one transaction: stores the Turns (transfer message as the `assistant` Turn), opens the Handoff, sets Mode `waiting_human`. Works for a first Message without `conversation_id`.
- The brief is stored, never logged.
- Anonymous `human` goes to the deterministic login reply, like `support`. The login reply is reworded to cover both account data and talking to an agent (still bilingual); `agent` is `router`; nothing stored.
- GLOSSARY already has the terms; README graph/agents section mentions the Escalator.

**Blocked by:** 01

**Status:** done

- [x] Fake Router returns `human` → Escalator runs; response `agent: escalator`, `mode: waiting_human`, transfer message as `answer`
- [x] Handoff stored with all brief fields; Mode `waiting_human`; next `/chat` is queued (01 behaviour)
- [x] First Message without `conversation_id` creates the Conversation and escalates it
- [x] Fallback transfer message when the model omits it or the output is unparseable
- [x] Brief content absent from captured logs
- [x] Anonymous `human` → reworded login reply, `agent: router`, nothing stored; anonymous `support` gets the same reply
- [x] Router prompt and Intent policy mention `human`
- [x] Retention purge removes the Handoff with its Conversation
- [x] No real LLM calls in tests

## Comments

- `app/graph.py`: Intent gains `human`, Agent gains `escalator`. `HandoffBrief` TypedDict (`reason, customer_ask, summary, attempted, category, priority low|normal|high, suggested_reply, language`). `GraphState` gains `escalation_reason` (set by a specialist) and `handoff` (set by the Escalator). `agent_for(intent, anonymous, escalated)`: `escalated` → `escalator` whatever the Intent (ticket 05 keeps the specialist's Intent); anonymous `support`/`human` → `router`.
- Graph shape built for ticket 05: Router `human` (Merchant) → `escalator` node; anonymous `human` → `login`. Both specialists now have a conditional edge: non-empty `escalation_reason` (and a Merchant) → `escalator`, else END. `_never_empty` skips the empty-answer fallback when the specialist escalated. So 05 only has to return `escalation_reason` (plus its Evidence/Sources) from the specialist node; tested here with a fake specialist.
- `build_graph(..., escalator=fallback_escalator)`: keyword with a model-free default (fixed transfer message + `fallback_brief`: reason and the Merchant's Message, no invented content) so existing tests/callers didn't change; production passes `make_escalator(model)`.
- `app/escalator.py`: `make_escalator(model)` = one `with_structured_output(Escalation, include_raw=True, method="function_calling")` call, like the Router. System prompt carries reason (`escalation_reason` or `MERCHANT_ASKED`), Intent, Evidence (via `judge.format_evidence`, capped) and Sources; then history + current Message via `conversation_messages`. Empty `transfer_message` → `TRANSFER_FALLBACK` (brief kept); unparseable → fallback message + `fallback_brief`. Provider errors propagate (503 as for other Agents).
- Store: `handoffs` table (`brief` JSON, `created_at`, `claimed_by/at`, `outcome` handed_back|closed, `ended_at`), `ON DELETE CASCADE`, partial unique index `handoffs_open` (one open per Conversation; a second raises `IntegrityError`, whole transaction rolled back). `Store.escalate(conversation_id | None, owner, turns, brief)`: creates the Conversation if needed, appends Turns, opens the Handoff, sets `waiting_human`, all in one connection/transaction. `Store.handoffs(cid)` for reads. Purge deletes Handoffs explicitly too (alongside Turns).
- `/chat`: `result["handoff"]` present (Merchant only) → `store.escalate`; response `mode: waiting_human`, `agent: escalator`. The brief is not in the response or the request log; log line `agent` is `escalator`, `escalator` step isn't counted as a tool (it's in `Agent`).
- `LOGIN_REPLY` reworded (account data or talking to an agent), still PT + EN. Router `INTENT_POLICY` gains `human` (explicit requests only); anonymous identity text says requests for a person are `human` too.
- `scripts/scenarios.py` `INTENTS` gains `human` (kept in sync with the graph by a test); no scenarios added (ticket 07).
- Left out: README graph/agents section (user rule: README not edited by implementers).
- Unverified: real-model brief quality and transfer-message language; Judges still score an escalated Turn with the Intent rubric (`human` falls back to the knowledge rubric) until ticket 06.
