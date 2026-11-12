# 04: Operator reply, handback, close

**What to build:** The claiming Operator talks to the Merchant, then either hands the Conversation back to the bot or closes it. The Merchant sees Operator replies and the handover by polling, and after handback the bot knows what the Operator said.

- Reply `{content, used_suggestion}`: only the claiming Operator, Mode `human`; stored as an `operator` Turn; audit row records `used_suggestion`.
- Handback: claiming Operator only; `human` → `bot`; Handoff outcome `handed_back`; stores a fixed bilingual `assistant` Turn ("You're back with the virtual assistant…").
- Close: claiming Operator in `human`, or any Operator in `waiting_human` (no claim); → `closed`; Handoff outcome `closed`; stores a fixed bilingual `assistant` Turn ("This conversation was closed by the agent…").
- Every action audited.
- History after handback: Operator Turns reach the Agents as assistant messages prefixed `[Human agent]`.

**Blocked by:** 03

**Status:** done

- [x] Reply stored as `operator` Turn; visible to the Merchant via the Turns listing with `after`
- [x] Reply without claim, by another Operator, or in `waiting_human` → 409/403
- [x] Handback in `waiting_human` → 409; handback by a non-claiming Operator → 403
- [x] Close of `waiting_human` by any Operator works; close of `human` by a non-claiming Operator → 403
- [x] Fixed Turns stored on handback and close; Merchant's Turns listing shows the new Mode
- [x] After handback, next `/chat` runs the graph; history has the Operator Turn with the `[Human agent]` prefix
- [x] After close, `/chat` → 409 (01)
- [x] Audit rows for reply (with `used_suggestion`), handback, close; no message text
- [x] No real LLM calls in tests

## Comments

- `app/operator.py`: new block "Reply, handback, close (ticket 04)" at the end of `operator_router`, kept apart from 06's endpoints. One `act(conversation_id, action)` helper: 404 if not visible (`operator_conversation`), then runs the Store action and maps its result: `not_claimer` → 403 `not_claimer`, `wrong_mode` → 409 `wrong_mode`, `done` → the detail view (`ConversationDetail`, same as claim).
  - `POST …/reply {content (min 1), used_suggestion (required bool)}` → `operator` Turn.
  - `POST …/handback` → `bot`, Handoff `handed_back`, fixed `HANDBACK_TURN`.
  - `POST …/close` → `closed`, Handoff `closed`, fixed `CLOSE_TURN`. Any Operator from `waiting_human` (Handoff `claimed_by` stays null); claiming Operator only from `human`.
  - Fixed Turns are bilingual (PT first, then EN, like `TRANSFER_FALLBACK`), stored as `assistant` Turns, constants in `app/operator.py`.
- `app/store.py`: `Store.reply`, `Store.hand_back`, `Store.close` return `ActionResult = "done" | "not_claimer" | "wrong_mode"`. Each is one transaction that starts with a conditional `UPDATE conversations … WHERE mode … AND <open Handoff claimed_by = operator>`; only if it changed a row are the Turn, Handoff end and audit row written (so two racing actions can't both pass). If no row changed, the current Mode decides the error: `human` → `not_claimer` (403), anything else → `wrong_mode` (409). So reply in `waiting_human`/`bot`/`closed`, handback outside `human`, and close in `bot`/`closed` are 409.
- Audit: `reply` (with `used_suggestion`), `handback`, `close` via `Store._audit` inside the same transaction. Refused actions write nothing. No text in the rows (tested against reply text and both fixed Turns).
- History: `conversation_messages` (`app/agents.py`) turns `operator` Turns into `AIMessage("[Human agent] …")` (`HUMAN_AGENT_PREFIX`); the graph state's `history` still has `role: operator` with raw content, so every Agent (Router, specialists, Escalator) gets the prefix from one place. Consecutive `user` Turns pass through unchanged.
- Second mock Operator: `operador2` added to `app/auth.OPERATORS`, used by the "another Operator" tests (403s, close of `waiting_human` by a non-claimer).
- Tests: `tests/test_operator_actions.py` (21), fakes only (`CapturingGraph`, `NeverInvokedGraph`); no model built.
- Left out: README (user rule). README still names only `operador1` as the mock Operator and doesn't document the new endpoints.
