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

**Status:** ready-for-agent

- [ ] Fake Router returns `human` → Escalator runs; response `agent: escalator`, `mode: waiting_human`, transfer message as `answer`
- [ ] Handoff stored with all brief fields; Mode `waiting_human`; next `/chat` is queued (01 behaviour)
- [ ] First Message without `conversation_id` creates the Conversation and escalates it
- [ ] Fallback transfer message when the model omits it or the output is unparseable
- [ ] Brief content absent from captured logs
- [ ] Anonymous `human` → reworded login reply, `agent: router`, nothing stored; anonymous `support` gets the same reply
- [ ] Router prompt and Intent policy mention `human`
- [ ] Retention purge removes the Handoff with its Conversation
- [ ] No real LLM calls in tests
