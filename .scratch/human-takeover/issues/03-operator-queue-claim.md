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

**Status:** ready-for-agent

- [ ] Role enforcement on every Operator endpoint
- [ ] Conversation with no Handoff → 404 for Operators
- [ ] Queue lists only `waiting_human`, oldest first, with brief fields
- [ ] Detail account data equals the fixture's data for the owner
- [ ] Claim moves to `human`; second claim → 409; claim of a `bot` Conversation → 409
- [ ] Brief re-run only when new Turns exist since it was written; failing re-run keeps old brief, claim succeeds
- [ ] Audit row for claim, without content
- [ ] Retention purge keeps audit rows
- [ ] No real LLM calls in tests
