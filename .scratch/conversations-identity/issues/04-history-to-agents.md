# 04: History reaches Router and specialists

**What to build:** Follow-up Messages make sense: "my card machine is offline" then "it's the Smart one" is routed to Customer Support and answered in context.

- Graph state gains `history`: the last 10 Turns before the current Message (role + content), loaded from the store for the Conversation.
- Router and both specialists receive the history as prior chat messages before the current Message. Router prompt: classify the latest Message in the light of the history.
- Account facts always come from fresh tool calls; old Turns are context only (no Evidence replayed).
- Anonymous requests have empty history.
- README CLI helper can carry a `conversation_id` across calls (arg / shell var).

**Blocked by:** 03

**Status:** done

- [x] Second `/chat` in a Conversation passes previous Turns as `history` (fake graph captures state)
- [x] History capped at 10 Turns, oldest dropped
- [x] Scripted fake chat model: Router, Knowledge and Support each receive prior Turns as messages before the current Message
- [x] Router prompt mentions classifying the latest Message using the history
- [x] CLI helper documented with `conversation_id`
- [x] No real LLM calls in tests

## Comments

- `history` is `NotRequired[list[HistoryTurn]]` (`{role, content}`) on `GraphState`; `HISTORY_TURNS = 10` in `app/graph.py`. A "Turn" is one row (user or assistant), so 10 Turns ≈ 5 exchanges. `/chat` loads `store.turns(cid)[-10:]` after the owner check, before the graph runs; new Conversation and anonymous → `[]`. No new Store method (slicing in Python; fine at this size).
- One helper, `conversation_messages(state)` in `app/agents.py`, used by Router, Knowledge and Support: `user` → `HumanMessage`, `assistant`/`operator` → `AIMessage`, then the current Message. Text only; no tool calls or Evidence replayed, so account facts come from fresh tool calls. Missing `history` (e.g. `scripts/eval.py`, Judges) means empty.
- Router prompt: "Classify the Merchant's latest Message" plus a paragraph to classify it in the light of the history; identity rules still apply to every Message.
- README `chat` helper keeps `$CID` across calls (or takes it as 2nd arg); `login` / `unset CID` starts fresh.
- Unverified: real-model behaviour on follow-ups ("it's the Smart one" → support) not run live; eval scenarios remain single-Message.
