# Spec: Human takeover

Status: ready-for-agent

Run: improvement run, see `IMPROVEMENT_RUN_DIARY.md`. Vocabulary: `GLOSSARY.md` (Mode, Escalation, Handoff, Handoff Brief, Escalator Agent, Operator, Review flag). Decisions: `docs/adr/` (0004 SQLite, 0005 identity, 0006 takeover via Conversation Mode).
Builds on: `.scratch/conversations-identity/spec.md` (Conversations, Turns, tokens, roles), done in session 3. Challenge bonus: a fourth agent that requests help from a human operator.

## Problem Statement

When the assistant can't help (the Merchant asks for a person, or the tools and Corpus don't cover the case), the Merchant is stuck. There is no way to reach a human, and no human could see the case anyway.

A human picking up a case cold would need to re-read everything and re-ask questions. Without a summary of what happened and what the bot already tried, takeover is slow and frustrating for both sides.

## Solution

- A Conversation can be taken over by an Operator. It moves through **Modes**: `bot` → `waiting_human` → `human` → back to `bot` (handback) or `closed`.
- An **Escalation** starts in two ways: the Merchant asks for a person (new Intent `human`), or a specialist Agent decides it can't resolve the case and calls an escalation tool. Each Escalation opens a **Handoff**, which lasts until handback or close.
- A fourth agent, the **Escalator Agent**, writes a **Handoff Brief** for the Operator: why it escalated, what the Merchant wants, what the bot already tried, category, priority, and a suggested reply. It also tells the Merchant, in their language, that they're being transferred.
- While a Conversation is not in `bot` Mode, the graph doesn't run: Merchant Messages are stored for the Operator, and Operator replies are stored for the Merchant, who picks them up by polling.
- Operators see a queue, claim a Conversation, reply, and hand back or close it. Account facts shown to Operators come from the fixture, never from the model. Every Operator action is audited.
- Low-scored bot replies set a **Review flag**; Operators review flagged Conversations after the fact, without changing the Mode.

## User Stories

1. As a Merchant, I want to ask to talk to a person, so that I can get help the bot can't give.
2. As a Merchant, I want the bot to escalate on its own when it can't resolve my problem, so that I don't have to know to ask.
3. As a Merchant, I want to be told, in my language, that I'm being transferred, so that I know what's happening.
4. As a Merchant, I want to keep writing while I wait, so that I can add details.
5. As a Merchant, I want my Messages while waiting not answered by the bot, so that I don't get conflicting answers.
6. As a Merchant, I want to see the Operator's replies as they arrive, so that the Conversation feels live.
7. As a Merchant, I want the bot to know what the Operator said after handback, so that I don't have to repeat myself.
8. As a Merchant, I want to know when the Conversation is handed back or closed, so that I know who is answering and when the case is finished.
9. As an Operator, I want a queue of Conversations waiting for a human, so that I know what needs attention.
10. As an Operator, I want each queued Conversation to show a Handoff Brief, so that I understand the case without reading everything.
11. As an Operator, I want the brief to include what the bot already tried, so that I don't repeat it.
12. As an Operator, I want the Merchant's account data shown from the system, so that I can trust amounts and dates.
13. As an Operator, I want a suggested reply I can edit, so that I can answer faster.
14. As a Merchant, I want the suggested reply never sent without an Operator choosing to, so that a human really answers me.
15. As an Operator, I want to claim a Conversation, so that no other Operator answers the same Merchant.
16. As an Operator, I want claiming an already claimed Conversation to fail clearly, so that I pick another.
17. As an Operator, I want to read the whole Conversation, including Messages sent while waiting, so that I have full context.
18. As an Operator, I want to reply to the Merchant, so that I can resolve the case.
19. As an Operator, I want to hand the Conversation back to the bot, so that routine follow-ups don't need me.
20. As an Operator, I want to close the Conversation, so that finished cases leave my view.
21. As an Operator, I want the brief refreshed when I claim if the Merchant wrote more while waiting, so that it's current.
22. As a security reviewer, I want Operator endpoints to require the operator role, so that Merchants can't act as Operators.
23. As a security reviewer, I want Operators to write only to Conversations they claimed, so that actions are attributable.
24. As an auditor, I want every Operator action recorded with who, what and when, so that takeovers can be reviewed.
25. As an evaluator, I want the Escalator Agent's brief judged for faithfulness to the Conversation, so that invented claims are caught.
26. As an evaluator, I want Operator Turns excluded from the answer Judge, so that human replies don't distort bot quality scores.
27. As an evaluator, I want low-scored bot replies flagged for review without interrupting the Merchant, so that quality issues surface without blocking anyone.
28. As an evaluator, I want to know how often Operators send the suggested reply unchanged, so that I can spot cases the bot could have handled.
29. As an anonymous visitor, I want a clear "log in" reply when I ask for a person, so that I know how to get help.
30. As an Operator, I want to close an unclaimed waiting Conversation (spam, Merchant gave up), so that junk leaves the queue without a fake claim.
31. As a Merchant, I want my chats visible to Operators only when escalated or flagged, so that my other Conversations stay private.
32. As a Merchant whose account isn't found, I want the bot to still be able to escalate, so that I can reach a person.

## Implementation Decisions

**Modes and Handoffs (ADR 0006)**
- Mode on a Conversation: `bot | waiting_human | human | closed` (column exists since session 3).
- `bot` → `waiting_human` on Escalation; `waiting_human` → `human` on claim; `human` → `bot` on handback; `human` → `closed` on close by the claiming Operator; `waiting_human` → `closed` on close by any Operator (no claim needed). Every other transition → 409.
- A Handoff is one Escalation episode: Handoff Brief, created at, claimed by/at, outcome (`handed_back | closed`), ended at. A Conversation has zero or more Handoffs, at most one open (the current one while Mode is `waiting_human` or `human`).
- Claim is one atomic conditional update (`… WHERE mode = 'waiting_human'`), so two Operators can't both claim; the loser gets 409.
- Handback and close each store a fixed bilingual `assistant` Turn ("You're back with the virtual assistant…" / "This conversation was closed by the agent…"), so the polling Merchant and the bot's history both see the handover.

**`/chat` by Mode**
- `bot`: runs the graph as today.
- `waiting_human` or `human`: the Message is stored as a `user` Turn (no Intent), the graph does not run. Response 200 with `answer: ""`, `intent: null`, `agent: null`. Log outcome `queued`; no Judges.
- `closed`: 409; the Merchant starts a new Conversation.
- `ChatResponse` gains `mode` (always present); `intent` and `agent` become nullable.
- `GET /conversations/{id}/turns` response gains `mode`. Merchants poll it with `?after=<turn id>` (exists). The Conversation listing already has `mode`.

**Escalation triggers**
- Intent gains `human`. The Router classifies explicit requests for a person as `human` (Router prompt and the shared `INTENT_POLICY` gain it, for Merchant and anonymous identity).
- Anonymous visitor: `human` goes to the existing deterministic `login` node, like `support`. `LOGIN_REPLY` is reworded to cover both ("log in to see your account or talk to an agent; without logging in I can help with Getnet products"), still bilingual. `agent_for` maps anonymous `human` to `router`. No Escalation, nothing stored.
- Both specialists gain a tool `escalate_to_human(reason)` with `return_direct=True`, so the agent loop ends on the call and the specialist's draft is discarded. Its reason travels as the tool artifact; the specialist node returns it as `escalation_reason`, and the graph routes to the Escalator Agent instead of END. The Knowledge node collects Sources only from the search tools' artifacts, never from this one.
- Prompts say when to use it: the Merchant is stuck after the bot's best answer, the tools or Corpus don't cover the case, or the case needs a human decision.
- A Merchant missing from the fixture: the Customer Support Agent runs with `escalate_to_human` as its only tool (still no account tool).
- `agent` in responses gains `escalator`.

**Escalator Agent**
- One structured model call (no tool loop). Input: recent history, escalation reason (the Merchant's request or the specialist's reason), Intent, and the current Turn's Evidence and Sources.
- Output Handoff Brief: `reason`, `customer_ask`, `summary`, `attempted`, `category`, `priority` (`low | normal | high`), `suggested_reply`, `language`; plus a short transfer message to the Merchant in their language (fixed bilingual fallback if missing or the output is unparseable).
- The node returns `answer` (the transfer message) and `handoff` (the brief) in the graph state; it touches no store. `main.py`, in one transaction: stores the Turns (transfer message as the `assistant` Turn), opens the Handoff with the brief, sets Mode `waiting_human`. This includes a first Message without `conversation_id` (the Conversation is created first).
- On claim, if the Merchant added Turns after the brief, the Escalator Agent runs again and the brief is replaced. If that call fails, the claim still succeeds with the old brief (logged).
- The brief is stored, never logged.

**Operator API** (role `operator` required, else 403)
- Visibility: Operators see only Conversations that had a Handoff or carry a Review flag; any other id → 404. Reads are not audited.
- `GET /operator/queue`: Conversations in `waiting_human`, oldest first, with brief summary fields (category, priority, customer_ask, created at).
- `GET /operator/review`: Conversations with a Review flag (any Mode), newest first.
- `GET /operator/conversations/{id}`: Turns, current Handoff Brief, Mode, claim, Review flag, and the Merchant's account data from the fixture (`load_merchants(today).get(owner)`, resolved by software, never by the model).
- `POST /operator/conversations/{id}/claim`: `waiting_human` → `human`, records the claiming Operator; already claimed or wrong Mode → 409.
- `POST /operator/conversations/{id}/reply {content, used_suggestion}`: only by the claiming Operator in `human` Mode; stored as an `operator` Turn.
- `POST /operator/conversations/{id}/handback`: only by the claiming Operator.
- `POST /operator/conversations/{id}/close`: by the claiming Operator in `human`, or by any Operator in `waiting_human`.
- `POST /operator/conversations/{id}/reviewed`: clears the Review flag (any Mode).
- The store gains a Conversation lookup without an owner (Operator side only).

**Storage** (SQLite, ADR 0004)
- `handoffs` table (above), `ON DELETE CASCADE` with the Conversation.
- `audit` table: operator, action (`claim | reply | handback | close | reviewed`), conversation id, timestamp, `used_suggestion` (reply only). No message text or brief content.
- `conversations` gains `needs_review` (the Review flag).
- Retention purge deletes Handoffs with their Conversation; audit rows are kept (no personal data in them).

**History after takeover**
- Operator Turns reach the graph as assistant messages prefixed `[Human agent]` (`app/agents.py`), so the model knows a human said them. Consecutive `user` Turns from the waiting period pass through unchanged.

**Quality**
- Escalated Turns (Intent `human` or tool Escalation): the answer Judge uses an escalation rubric instead of the Intent rubric: the brief is faithful to the Conversation with no invented claims, and the transfer message is in the Merchant's language. The Judge gets the brief.
- Route and coverage Judges learn Intent `human` via `INTENT_POLICY`; the anonymous rubric and coverage rule cover `human` as well as `support`.
- Operator Turns never go through `/chat`, so no Judge scores them.
- An `answer` Judge Score below 0.7 sets the Review flag on the Conversation (no Mode change). Route and coverage scores never set it. The background Judge task gets the `conversation_id` and the store; anonymous requests have no Conversation and set nothing.
- `used_suggestion` (sent unchanged) is stored on the audit row of each reply, as the input for "could the bot have answered?".

**Eval**
- Three scenarios in `evals/scenarios.json`: explicit request for a person (PT, Merchant), specialist Escalation (EN, Merchant, a case the tools can't solve, e.g. a chargeback dispute), anonymous request for a person. Expected: Intent and `agent` (`escalator`, or `router` for the anonymous one). Routing only, no expected facts.
- The dataset hash changes; deltas vs the baseline are not like-for-like (as in session 3).

## Testing Decisions

- Through `create_app` with TestClient, a temporary SQLite store, fixed secret, fake graph and fake models. No real LLM calls.
- **Mode transitions:** each valid transition; invalid ones (claim twice, reply without claim, reply by another Operator, handback in `waiting_human`, close of `human` by a non-claiming Operator) → 409 or 403. Close of `waiting_human` by any Operator works.
- **Graph bypass:** in `waiting_human` and `human`, a fake graph asserts it is never invoked; the Message is stored as a `user` Turn; the response has `mode`, empty `answer`, null `intent`/`agent`. `closed` → 409.
- **Escalation via Intent:** fake Router returns `human` → Escalator node runs → Mode `waiting_human`, Handoff opened with the brief, transfer message returned and stored, `agent = escalator`. Also for a first Message without `conversation_id`.
- **Escalation via tool:** scripted fake chat model calls `escalate_to_human` in each specialist → graph routes to the Escalator, the specialist's draft is discarded, the reason is not a Source. Unknown Merchant can call it. Prior art: `tests/test_knowledge.py`, `tests/test_support.py`.
- **Escalator Agent:** fake structured model; brief fields stored; fallback transfer message when missing; re-run on claim only when new Turns exist; failure on claim keeps the old brief and the claim succeeds.
- **Operator API:** role enforcement; visibility (Conversation with no Handoff and no flag → 404); queue order; review list; account data equals fixture data; `used_suggestion` stored; audit row per action with no message text.
- **Handback and close:** fixed Turns stored; `/turns` shows `mode`; after handback the next `/chat` runs the graph and the history has the Operator Turn with the `[Human agent]` prefix.
- **Anonymous:** `human` Intent without a token → login reply, nothing stored.
- **Quality:** escalation rubric used for escalated Turns; low answer score sets the Review flag; low route/coverage score does not; `reviewed` clears it. Prior art: `tests/test_observability.py`.
- **Retention:** purge removes Handoffs with the Conversation, keeps audit rows.
- Live check: two terminals with curl (Merchant and Operator tokens) walk through escalate → claim → reply → handback, then escalate → close; eval re-run with the new scenarios.

## Out of Scope

- Approval-style HITL (approve/reject an Agent action): no tools change data yet.
- Merchant cancelling a waiting Handoff (the Operator sees the Message and closes).
- Operator UI (demo-clients spec); push delivery (SSE).
- Routing to Operators by skill, SLAs, timeouts, notifications.
- Multiple Operators collaborating on one Conversation.
- Auditing Operator reads.

## Further Notes

- The Escalator Agent counts as the challenge's fourth agent; the README should say so.
- Decisions from the session 4 grilling (2026-11-11) are folded in above; terms are in `GLOSSARY.md`.
- Tickets are written when this feature starts.
