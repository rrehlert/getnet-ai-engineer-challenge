# 03: Operator view

**What to build:** A logged-in Operator works the Queue and the Review list from the page: opens a Conversation, reads the Turns, the Handoff Brief and the account, and claims, replies, hands back, closes or marks it reviewed.

- Tabs: **Queue** (`GET /operator/queue`, oldest first: category, priority, customer_ask, age) and **Review** (`GET /operator/review`, newest first).
- Detail (`GET /operator/conversations/{id}`): Turns, Handoff Brief card, account panel (from the API's `account`), Mode, claim, Review flag.
- Reply textarea prefilled with `suggested_reply`. `used_suggestion = true` only when the sent text is byte-identical to it.
- Buttons by Mode and claim: Claim (`waiting_human`); Close (`waiting_human`, or `human` claimed by me); Reply and Handback (`human`, claimed by me); Mark reviewed (flagged).
- 409/403 show the error message and refresh the detail.
- Polling: open detail every 2 s, lists every 5 s, paused while the tab is hidden.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Queue and Review tabs
- [ ] Detail with Turns, brief, account
- [ ] Suggested reply prefilled; `used_suggestion` only when unchanged
- [ ] Buttons follow Mode and claim; conflicts shown and refreshed
