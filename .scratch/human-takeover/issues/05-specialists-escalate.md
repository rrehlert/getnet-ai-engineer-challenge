# 05: Specialists escalate via tool

**What to build:** When the Knowledge or Customer Support Agent can't resolve the case, it escalates on its own: the Merchant gets the Escalator's transfer message instead of a dead-end answer, and the Conversation waits for an Operator. A Merchant whose account isn't found can still be escalated.

- Both specialists gain `escalate_to_human(reason)`. Calling it ends the agent loop immediately; the specialist's draft is discarded.
- The reason reaches the Escalator Agent as the escalation reason, with the specialist's Intent, Evidence and Sources so far.
- The reason is never a Source.
- Customer Support for a Merchant missing from the fixture runs with `escalate_to_human` as its only tool (still no account tool).
- Prompts say when to escalate: the Merchant is stuck after the bot's best answer, the tools or Corpus don't cover the case, or the case needs a human decision.
- The response's Intent stays the specialist's Intent; `agent` is `escalator`.

**Blocked by:** 02

**Status:** done

- [x] Scripted fake chat model calls the tool in Knowledge → Escalator runs, Mode `waiting_human`, draft discarded
- [x] Same for Customer Support
- [x] Unknown Merchant: the tool is available and works; no account tool is
- [x] Escalation reason passed to the Escalator; not in `sources`
- [x] Evidence gathered before the call reaches the Escalator
- [x] Prompts mention when to escalate
- [x] No real LLM calls in tests

## Comments

- `app/agents.py`: `escalate_to_human(reason)` tool + `stop_on_escalation` (`@after_model(tools=[escalate_to_human], can_jump_to=["end"])`). The middleware adds the tool to the agent and ends its loop the moment the model's reply calls it: the tool body never runs, other tool calls in that reply aren't run, any text in that reply (or later) is never produced/used. Chosen over `return_direct=True`, which only exits when *every* tool in the reply is return_direct.
- `escalation(messages)`: if the run ended on the call → `{"answer": "", "escalation_reason": reason}` (empty reason → a fixed placeholder; it still escalates). Spread last into the node's update, so the draft is dropped; the graph from 02 routes to the Escalator and keeps the specialist's Intent. `run_summary` appends `escalate_to_human` to `steps` (logged as a tool). Evidence and Sources gathered before the call are returned as usual and reach the Escalator via state. The reason is only in `escalation_reason`, never a ToolMessage artifact, so never a Source.
- Middleware order: `stop_on_escalation` is last in the list so its after_model hook runs before `ToolCallLimitMiddleware`'s: an escalation is never refused by the tool limit.
- Customer Support, unknown Merchant: still `agent([])` (no account tools); the middleware makes `escalate_to_human` its only tool. Consequence: a hallucinated account call now gets an error ToolMessage and the loop continues (before: no ToolNode, run ended). `NOT_FOUND` fallback still applies when the final reply is empty and it didn't escalate. Updated `test_support.py::test_unknown_merchant_cannot_call_account_tools` and `test_auth.py::test_unknown_id_reaches_the_account_not_found_reply` (`bound == ["escalate_to_human"]`).
- Prompts: shared `ESCALATION_RULE` (stuck after the best answer / tools or Corpus don't cover it / needs a human decision; reason is a short English note for the Operator) appended to Knowledge and Support `PROMPT`; Knowledge's "suggest official channels" line replaced by "escalate"; `UNKNOWN_PROMPT` tells it to escalate if the Merchant still needs account help.
- Tests: `tests/test_specialist_escalation.py` (scripted fake chat models; Knowledge and Support through `/chat` → `waiting_human`, `agent: escalator`, specialist Intent; Evidence/Sources reach Escalator, reason not in `sources`, draft text alongside the call discarded; unknown Merchant escalates; prompts). No real LLM calls.
- Unverified: real-model escalation judgement (over/under-escalating) not run live; ticket 07's eval covers it.
