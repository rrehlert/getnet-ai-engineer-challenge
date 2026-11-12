# 05: Specialists escalate via tool

**What to build:** When the Knowledge or Customer Support Agent can't resolve the case, it escalates on its own: the Merchant gets the Escalator's transfer message instead of a dead-end answer, and the Conversation waits for an Operator. A Merchant whose account isn't found can still be escalated.

- Both specialists gain `escalate_to_human(reason)`. Calling it ends the agent loop immediately; the specialist's draft is discarded.
- The reason reaches the Escalator Agent as the escalation reason, with the specialist's Intent, Evidence and Sources so far.
- The reason is never a Source.
- Customer Support for a Merchant missing from the fixture runs with `escalate_to_human` as its only tool (still no account tool).
- Prompts say when to escalate: the Merchant is stuck after the bot's best answer, the tools or Corpus don't cover the case, or the case needs a human decision.
- The response's Intent stays the specialist's Intent; `agent` is `escalator`.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Scripted fake chat model calls the tool in Knowledge → Escalator runs, Mode `waiting_human`, draft discarded
- [ ] Same for Customer Support
- [ ] Unknown Merchant: the tool is available and works; no account tool is
- [ ] Escalation reason passed to the Escalator; not in `sources`
- [ ] Evidence gathered before the call reaches the Escalator
- [ ] Prompts mention when to escalate
- [ ] No real LLM calls in tests
