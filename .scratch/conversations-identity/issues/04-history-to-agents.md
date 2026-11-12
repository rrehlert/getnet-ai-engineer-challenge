# 04: History reaches Router and specialists

**What to build:** Follow-up Messages make sense: "my card machine is offline" then "it's the Smart one" is routed to Customer Support and answered in context.

- Graph state gains `history`: the last 10 Turns before the current Message (role + content), loaded from the store for the Conversation.
- Router and both specialists receive the history as prior chat messages before the current Message. Router prompt: classify the latest Message in the light of the history.
- Account facts always come from fresh tool calls; old Turns are context only (no Evidence replayed).
- Anonymous requests have empty history.
- README CLI helper can carry a `conversation_id` across calls (arg / shell var).

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Second `/chat` in a Conversation passes previous Turns as `history` (fake graph captures state)
- [ ] History capped at 10 Turns, oldest dropped
- [ ] Scripted fake chat model: Router, Knowledge and Support each receive prior Turns as messages before the current Message
- [ ] Router prompt mentions classifying the latest Message using the history
- [ ] CLI helper documented with `conversation_id`
- [ ] No real LLM calls in tests
