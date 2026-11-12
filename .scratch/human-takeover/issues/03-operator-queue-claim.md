# 03: Operator queue, read, claim

**What to build:** An Operator logs in, sees the Conversations waiting for a human (oldest first, with the brief's key fields), opens one to read the whole Conversation, its Handoff Brief and the Merchant's account data from the system, and claims it so no other Operator answers the same Merchant.

- All Operator endpoints need role `operator` (no token 401, Merchant 403).
- Visibility: Operators see only Conversations that had a Handoff or carry a Review flag; any other id → 404 (Review flag arrives in 06; the rule is written for both now).
- Queue: Conversations in `waiting_human`, oldest first, with category, priority, customer_ask, created at.
- Detail: Turns (including those sent while waiting), current brief, Mode, claim, and the Merchant's account data from the fixture (never from the model).
- Claim: `waiting_human` → `human`, records the Operator; one atomic conditional update, so a second claim (or wrong Mode) → 409.
- On claim, if the Merchant added Turns after the brief, the Escalator Agent runs again and replaces the brief; if that call fails the claim still succeeds with the old brief (logged without content).
- Audit storage: operator, action, conversation id, timestamp (+ `used_suggestion` for replies later). No message text or brief content. Kept by the retention purge.
- The store gains an owner-less Conversation lookup, used only on the Operator side.

**Blocked by:** 02

**Status:** done

- [x] Role enforcement on every Operator endpoint
- [x] Conversation with no Handoff → 404 for Operators
- [x] Queue lists only `waiting_human`, oldest first, with brief fields
- [x] Detail account data equals the fixture's data for the owner
- [x] Claim moves to `human`; second claim → 409; claim of a `bot` Conversation → 409
- [x] Brief re-run only when new Turns exist since it was written; failing re-run keeps old brief, claim succeeds
- [x] Audit row for claim, without content
- [x] Retention purge keeps audit rows
- [x] No real LLM calls in tests

## Comments

- New `app/operator.py`: `operator_router(principal=, store=, today=, escalator=)` returns an `APIRouter` (prefix `/operator`) that `create_app` includes. Role check is one `operator` dependency (no token 401 via the app's `principal`, Merchant 403 `forbidden`). Tickets 04/06 add their endpoints inside the same factory (reuse `Operator`, `view()`, `_not_found()`, `store().operator_conversation`). Pydantic models: `Queue`/`QueueItem`, `ConversationDetail` (`conversation_id, merchant, mode, needs_review, created_at, updated_at, handoff, account, turns`), `HandoffOut`, `OperatorTurn`.
- `app/errors.py`: `error_response` (was `main._error`) and `AuthError` moved out of `main.py` so the Operator module shares them without a circular import; `main.py` imports them under the old names.
- `GET /operator/queue`: open Handoffs of `waiting_human` Conversations, ordered by Handoff `created_at` (when the Merchant started waiting), with `category`, `priority`, `customer_ask`, `created_at`.
- `GET /operator/conversations/{id}`: all Turns (incl. those sent while waiting), the latest Handoff (brief, claimed_by/at, outcome, ended_at), Mode, `needs_review`, and `account = load_merchants(today).get(owner)` (`today` from the auth clock, as `/me`); null for a Merchant missing from the fixture. Reads not audited.
- Visibility: `Store.operator_conversation(id)` is the owner-less lookup, and it carries the rule in SQL: visible only if `needs_review` or any Handoff exists; else None → 404 (same as unknown id). Claim checks it too (404 before 409).
- `POST /operator/conversations/{id}/claim`: `Store.claim(id, operator)` = one transaction: `UPDATE conversations SET mode='human' … WHERE id=? AND mode='waiting_human'`; only if that changed a row, the open Handoff gets `claimed_by/at` and an audit row is written. False → 409 `not_waiting` (already claimed, `bot`, `closed`). Returns the detail view.
- Brief refresh: Handoffs gain `brief_turn_id` (max Turn id when the brief was written; set in `Store.escalate`). After a successful claim (outside the claim transaction, so the model call holds no DB lock), if the last Turn id > `brief_turn_id`, the Escalator runs with: last Turn as `message`, previous Turns (last 10) as `history`, the escalated Turn's Intent, the old brief's `reason` as `escalation_reason`, empty Evidence/Sources (not stored). New brief replaces the old (`Store.replace_brief`, also bumps `brief_turn_id`); the transfer message is discarded. Exception → old brief kept, warning with conversation id + exception type only (no message, no traceback). Unparseable output (the Escalator's `fallback_brief`) is also treated as unusable → old brief kept.
- `create_app(escalator=...)`: injectable Escalator node for the claim refresh; default built lazily (`make_escalator(make_chat_model(settings))`), only when a refresh is actually needed.
- Audit: `audit` table (operator, action CHECK claim|reply|handback|close|reviewed, conversation_id, created_at, used_suggestion), no foreign key, so `purge` leaves it. `Store._audit(conn, …)` for 04/06 to write in their own transactions (`used_suggestion` param ready); `Store.audit_log(cid)` reads; `AuditEntry` dataclass.
- Schema: `conversations.needs_review` (Review flag column, default 0) added now so the visibility rule is complete; 06 sets/clears it. `Conversation.needs_review` field. Older DB files get the new columns via `ADDED_COLUMNS` (`ALTER TABLE ADD COLUMN` if missing); tested.
- Tests: `tests/test_operator.py` (19), fakes only (spy Escalator, `fallback_escalator`); no model built.
- Left out: README (user rule). Not tested: a Review-flagged, never-escalated Conversation being visible (no flag setter until 06; the SQL rule is there). Only one mock Operator (`operador1`) exists, so the "second claim" test uses the same Operator twice; the conditional update is what makes it safe for any two.
