# Human takeover: implementation report (session 4)

Integration branch `human-takeover` (off `main` e270a21), not pushed, not merged to main. Tickets 01–06 done; 07 (live check + eval) left for the human.

## Merges (all `--no-ff` into `human-takeover`, 2026-11-11, -0300)

| Ticket | Branch | Merge commit | Time | Tests after |
|---|---|---|---|---|
| 01 `/chat` respects the Mode | ht-01-chat-mode | 7aa8372 | 22:33:25 | 286 |
| 02 Merchant asks for a person → Escalator | ht-02-escalator | 4306808 | 22:39:06 | 303 |
| 05 Specialists escalate via tool | ht-05-specialist-escalate | 00145a6 | 22:43:35 | 310 |
| 03 Operator queue, read, claim | ht-03-operator-claim | dafd260 | 22:46:26 | 329 |
| 04 Operator reply, handback, close | ht-04-reply-handback-close | 6a95147 | 22:50:26 | 350 |
| 06 Escalation Judge, Review flag | ht-06-judge-review | ca5757a | 22:51:27 | 368 |
| Code-review fixes | ht-review-fixes | 1251d0d | 22:58:48 | 377 |

Baseline on main: 274 tests. All suites green after every merge; no real LLM calls (fakes only).

Lint: `uv run ruff check` doesn't work (ruff isn't a project dependency). Used `uvx ruff check` (0.17.4, no repo config): main has 28 existing errors; the gate was "no new errors", and every merge stayed at 28. Those 28 were not fixed.

## Notable decisions (details in each ticket's Comments)

- 05: escalation ends the agent loop through a `stop_on_escalation` middleware, not `return_direct=True` as the spec says. `return_direct` only stops the loop when every tool call in that model turn is return_direct.
- 03: `brief_turn_id` on Handoffs decides whether to rewrite the brief on claim. The rewrite gets empty Evidence and Sources because they aren't stored.
- 04: added a second mock Operator, `operador2` (app/auth.py), for the "another Operator" tests.
- 06: "newest first" in the review list means most recently updated (there's no flagged-at column). A Conversation that was flagged but never escalated returns 404 to Operators once it is marked reviewed.

## Code review (`main...human-takeover`)

Spec findings fixed:
- Bug: an anonymous visitor could get a 200 with an empty answer if Knowledge called `escalate_to_human`. Fix: anonymous Knowledge no longer gets the tool or the escalation rule, and the graph applies the fallback answer if an escalation reason has no Merchant.
- Races in `/chat`: a concurrent escalation could produce a bot answer while `waiting_human`, a double escalation gave a 500 (IntegrityError), and a queued Turn could be stored on a `closed` Conversation. Fix: all writes are conditional on the Mode that was read. A lost race returns 409 (`conversation_closed` or `mode_changed`), never 500, and nothing is stored.

Standards findings fixed:
- Glossary: renamed `Escalation` to `EscalatorOutput` and `escalation()` to `escalation_update()`. Model-facing text now says Operator.
- Removed a ticket reference from a code comment.
- Duplicated code: one `LOGIN_INTENTS`, `specialist_reason`, `HandoffOutcome`.
- Primitive obsession: briefs are typed as `HandoffBrief`.
- One `Store.current_handoff`.
- Feature envy: moved the rewrite-state builder into `app/escalator.py`.
- Renamed the `escalated` dict.

Left as is:
- `Store.set_mode`: ticket 01 asked for it.
- `used_suggestion` is whatever the client sends; the spec makes it a request field and the server never checks it.
- The transfer Turn carries Sources after a Knowledge escalation.
- Operator error `trace_id` is a fresh uuid not tied to any log line.
- Small scope additions: `/reviewed` returns 409 when the Conversation isn't flagged; ALTER-TABLE migration for older DB files; `app/errors.py` split out; actions return the detail view.

## Open questions

1. README not edited (user rule), even though tickets 02–04 asked for README notes on the Escalator as fourth agent, `mode`/409, Operator endpoints and `operador2`. Do this in 07 or later?
2. Should `used_suggestion` be computed on the server (compare `content` to `suggested_reply`) so the metric can be trusted?
3. Ruff: add it as a dev dependency with a config, and fix or ignore the 28 existing errors?
4. Coverage Judge on escalated Turns sees only the transfer message and may score it low. It never sets the Review flag, but it may pull eval coverage down in 07.
5. Not checked against a real model: brief quality, transfer-message language, how often specialists escalate, Judge scores on the escalation rubric. All of this is for 07.
