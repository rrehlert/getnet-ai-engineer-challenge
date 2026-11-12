# 04: Operator reply, handback, close

**What to build:** The claiming Operator talks to the Merchant, then either hands the Conversation back to the bot or closes it. The Merchant sees Operator replies and the handover by polling, and after handback the bot knows what the Operator said.

- Reply `{content, used_suggestion}`: only the claiming Operator, Mode `human`; stored as an `operator` Turn; audit row records `used_suggestion`.
- Handback: claiming Operator only; `human` → `bot`; Handoff outcome `handed_back`; stores a fixed bilingual `assistant` Turn ("You're back with the virtual assistant…").
- Close: claiming Operator in `human`, or any Operator in `waiting_human` (no claim); → `closed`; Handoff outcome `closed`; stores a fixed bilingual `assistant` Turn ("This conversation was closed by the agent…").
- Every action audited.
- History after handback: Operator Turns reach the Agents as assistant messages prefixed `[Human agent]`.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Reply stored as `operator` Turn; visible to the Merchant via the Turns listing with `after`
- [ ] Reply without claim, by another Operator, or in `waiting_human` → 409/403
- [ ] Handback in `waiting_human` → 409; handback by a non-claiming Operator → 403
- [ ] Close of `waiting_human` by any Operator works; close of `human` by a non-claiming Operator → 403
- [ ] Fixed Turns stored on handback and close; Merchant's Turns listing shows the new Mode
- [ ] After handback, next `/chat` runs the graph; history has the Operator Turn with the `[Human agent]` prefix
- [ ] After close, `/chat` → 409 (01)
- [ ] Audit rows for reply (with `used_suggestion`), handback, close; no message text
- [ ] No real LLM calls in tests
