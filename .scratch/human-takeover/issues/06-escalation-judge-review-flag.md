# 06: Escalation Judge and Review flag

**What to build:** Escalations are judged on whether the Handoff Brief is faithful to the Conversation, and bot replies that score low are flagged for an Operator to review afterwards, without changing the Mode or blocking the Merchant.

- Escalated Turns (Intent `human` or tool Escalation): the answer Judge uses an escalation rubric instead of the Intent rubric (brief faithful to the Conversation, no invented claims; transfer message in the Merchant's language) and gets the brief.
- Route and coverage Judges know Intent `human` (via the Intent policy); the anonymous rubric and coverage rule cover `human` as well as `support`.
- An `answer` Judge Score below 0.7 sets the Review flag on the Conversation. Route and coverage scores never do. Anonymous requests have no Conversation and set nothing.
- Operators: a review list (flagged Conversations, any Mode, newest first); flagged Conversations are readable through the detail view; marking one reviewed clears the flag and is audited.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Escalated Turn → answer Judge uses the escalation rubric and sees the brief
- [ ] Answer score < 0.7 sets the flag; route/coverage < 0.7 do not; Mode unchanged
- [ ] Anonymous low score sets nothing
- [ ] Flagged `bot` Conversation (no Handoff) readable by Operators; appears in the review list, newest first
- [ ] Reviewed clears the flag; audit row written
- [ ] Anonymous `human` login reply judged with the anonymous rubric
- [ ] No real LLM calls in tests
