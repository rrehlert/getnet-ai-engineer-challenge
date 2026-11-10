# Spec: Human takeover

Status: ready-for-agent

Run: improvement run, see `IMPROVEMENT_RUN_DIARY.md`. Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/` (0004 SQLite, 0005 identity, 0006 takeover via Conversation Mode).
Builds on: `.scratch/conversations-identity/spec.md` (Conversations, Turns, tokens, roles). Challenge bonus: a fourth agent that requests help from a human operator.

## Problem Statement

When the assistant can't help (the Merchant asks for a person, or the tools and Corpus don't cover the case), the Merchant is stuck. There is no way to reach a human, and no human could see the case anyway.

A human picking up a case cold would need to re-read everything and re-ask questions. Without a summary of what happened and what the bot already tried, takeover is slow and frustrating for both sides.

## Solution

- A Conversation can be taken over by a human operator. It moves through **Modes**: `bot` → `waiting_human` → `human` → back to `bot` (handback) or `closed`.
- Escalation starts in two ways: the Merchant asks for a person (new Intent `human`), or a specialist Agent decides it can't resolve the case and calls an escalation tool.
- A fourth agent, the **Escalator Agent**, writes a **Handoff Brief** for the operator: why it escalated, what the Merchant wants, what the bot already tried, category, priority, and a suggested reply. It also tells the Merchant, in their language, that they're being transferred.
- While a Conversation is not in `bot` Mode, the graph doesn't run: Merchant Messages are stored for the operator, and operator replies are stored for the Merchant, who picks them up by polling.
- Operators see a queue, claim a Conversation, reply, and hand back or close it. Account facts shown to operators come from the fixture, never from the model. Every operator action is audited.

## User Stories

1. As a Merchant, I want to ask to talk to a person, so that I can get help the bot can't give.
2. As a Merchant, I want the bot to escalate on its own when it can't resolve my problem, so that I don't have to know to ask.
3. As a Merchant, I want to be told, in my language, that I'm being transferred, so that I know what's happening.
4. As a Merchant, I want to keep writing while I wait, so that I can add details.
5. As a Merchant, I want my Messages while waiting not answered by the bot, so that I don't get conflicting answers.
6. As a Merchant, I want to see the operator's replies as they arrive, so that the Conversation feels live.
7. As a Merchant, I want the bot to know what the operator said after handback, so that I don't have to repeat myself.
8. As a Merchant, I want to know when the Conversation is closed, so that I know the case is finished.
9. As an operator, I want a queue of Conversations waiting for a human, so that I know what needs attention.
10. As an operator, I want each queued Conversation to show a Handoff Brief, so that I understand the case without reading everything.
11. As an operator, I want the brief to include what the bot already tried, so that I don't repeat it.
12. As an operator, I want the Merchant's account data shown from the system, so that I can trust amounts and dates.
13. As an operator, I want a suggested reply I can edit, so that I can answer faster.
14. As a Merchant, I want the suggested reply never sent without an operator choosing to, so that a human really answers me.
15. As an operator, I want to claim a Conversation, so that no other operator answers the same Merchant.
16. As an operator, I want claiming an already claimed Conversation to fail clearly, so that I pick another.
17. As an operator, I want to read the whole Conversation, including Messages sent while waiting, so that I have full context.
18. As an operator, I want to reply to the Merchant, so that I can resolve the case.
19. As an operator, I want to hand the Conversation back to the bot, so that routine follow-ups don't need me.
20. As an operator, I want to close the Conversation, so that finished cases leave my view.
21. As an operator, I want the brief refreshed when I claim if the Merchant wrote more while waiting, so that it's current.
22. As a security reviewer, I want operator endpoints to require the operator role, so that Merchants can't act as operators.
23. As a security reviewer, I want operators to write only to Conversations they claimed, so that actions are attributable.
24. As an auditor, I want every operator action recorded with who, what and when, so that takeovers can be reviewed.
25. As an evaluator, I want the Escalator Agent's brief judged for faithfulness to the Conversation, so that invented claims are caught.
26. As an evaluator, I want operator Turns excluded from the answer Judge, so that human replies don't distort bot quality scores.
27. As an evaluator, I want low-scored bot replies flagged for review without interrupting the Merchant, so that quality issues surface without blocking anyone.
28. As an evaluator, I want to know how often operators send the suggested reply unchanged, so that I can spot cases the bot could have handled.
29. As an anonymous visitor, I want a clear "log in to talk to an agent" reply when I ask for a person, so that I know how to get help.

## Implementation Decisions

**Modes (ADR 0006)**
- New domain term **Mode** on a Conversation: `bot | waiting_human | human | closed`.
- `bot` → `waiting_human` on escalation; `waiting_human` → `human` on claim; `human` → `bot` on handback; `waiting_human` or `human` → `closed` on close.
- `/chat` in `bot` Mode runs the graph as today. In `waiting_human` or `human`, the Message is stored as a user Turn and the graph does not run; the response carries no new assistant answer. In `closed`, `/chat` with that `conversation_id` returns 409; the Merchant starts a new Conversation.
- `/chat` responses carry `mode`. Merchants poll `GET /conversations/{id}/turns?after=<turn id>` for operator replies; the Conversation listing includes `mode`.
- Takeover is a Mode switch at the API level, not a LangGraph `interrupt()`: a takeover spans many Turns, interrupt/resume fits a single pause (it is kept for future approval-style HITL), and the Mode already lives in the database (ADR 0006).

**Escalation triggers**
- Intent gains `human`. The Router classifies explicit requests for a person as `human`. Anonymous visitors get a fixed bilingual "log in to talk to an agent" reply.
- Both specialists gain a tool `escalate_to_human(reason)`. Prompts say when to use it (the Merchant is stuck after the bot's best answer, the tools or Corpus don't cover the case, the case needs a human decision). Its reason travels as a tool artifact, like Sources. The node reads it and the graph routes to the Escalator Agent instead of ending; the specialist's draft answer is discarded.
- `agent` in responses gains `escalator`.

**Escalator Agent**
- New domain terms **Escalator Agent**, **Operator**, **Handoff Brief**.
- One structured model call (no tool loop). Input: recent history, escalation reason (the Merchant's request or the specialist's reason), Intent, and the current Turn's Evidence and Sources.
- Output Handoff Brief: `reason`, `customer_ask`, `summary`, `attempted`, `category`, `priority` (`low | normal | high`), `suggested_reply`, `language`; plus a short transfer message to the Merchant in their language (fixed bilingual fallback if missing).
- The Conversation moves to `waiting_human`; the brief is stored.
- On claim, if the Merchant added Turns after the brief, the Escalator Agent runs again and the brief is replaced.

**Operator API** (role `operator` required, else 403)
- `GET /operator/queue`: Conversations in `waiting_human`, oldest first, with brief summary fields.
- `GET /operator/conversations/{id}`: Turns, Handoff Brief, Mode, claim, and the Merchant's account data from the fixture (resolved by software, never by the model).
- `POST /operator/conversations/{id}/claim`: `waiting_human` → `human`, records the claiming operator; already claimed or wrong Mode → 409.
- `POST /operator/conversations/{id}/reply {content, used_suggestion}`: only by the claiming operator in `human` Mode; stored as an operator Turn.
- `POST /operator/conversations/{id}/handback` and `/close`: only by the claiming operator.
- Storage: a handoffs table (Conversation, brief, created, claimed by/at, outcome, closed at) and an audit table (operator, action, Conversation, timestamp, details). SQLite per ADR 0004.

**History after takeover**
- Operator Turns are part of the history passed to the graph after handback, shown to the model as messages marked as coming from a human agent.

**Quality**
- New Judge rubric for Intent `human` and escalated Turns: the brief is faithful to the Conversation, with no invented claims; the transfer message is in the Merchant's language.
- The answer Judge skips operator Turns.
- A bot reply scored below 0.7 sets `needs_review` on the Conversation (no Mode change). The operator queue can filter flagged Conversations.
- `used_suggestion` (sent unchanged) is stored on operator replies and counted in the audit, as the input for "could the bot have answered?".

## Testing Decisions

- Through `create_app` with TestClient, a temporary SQLite store, fixed secret, fake graph and fake models. No real LLM calls.
- **Mode transitions:** each valid transition; invalid ones (claim twice, reply without claim, reply by another operator, handback in `waiting_human`) → 409 or 403.
- **Graph bypass:** in `waiting_human` and `human`, a fake graph asserts it is never invoked and the Message is stored as a user Turn.
- **Escalation via Intent:** fake Router returns `human` → Escalator node runs → Mode `waiting_human`, brief stored, transfer message returned, `agent = escalator`.
- **Escalation via tool:** scripted fake chat model calls `escalate_to_human` in a specialist → graph routes to the Escalator, the specialist's draft is discarded. Prior art: `tests/test_knowledge.py`, `tests/test_support.py`.
- **Escalator Agent:** fake structured model; brief fields stored; fallback transfer message when missing; re-run on claim only when new Turns exist.
- **Operator API:** role enforcement, queue order, account data equals fixture data, `used_suggestion` stored, audit rows for each action.
- **Handback:** after handback, the next `/chat` runs the graph and the history includes the operator Turn marked as a human agent.
- **Anonymous:** `human` Intent without a token → login reply, nothing stored.
- **Quality:** escalation rubric selected for escalated Turns; operator Turns not judged; low score sets `needs_review`. Prior art: `tests/test_observability.py`.
- Live check: two terminals with curl (Merchant and operator tokens) walk through escalate → claim → reply → handback.

## Out of Scope

- Approval-style HITL (approve/reject an Agent action): no tools change data yet.
- Operator UI (demo-clients spec); push delivery (SSE).
- Routing to operators by skill, SLAs, timeouts, notifications.
- Multiple operators collaborating on one Conversation.

## Further Notes

- Depends on conversations-identity being done (Conversations, Turns, roles, store).
- The Escalator Agent counts as the challenge's fourth agent; the README should say so.
- Tickets are written when this feature starts.
