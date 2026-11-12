# 07: Live check, eval and README

**What to build:** Evidence that the takeover works end to end on the real stack, and that it didn't regress the bot.

- Live check with `docker compose up --build`, two terminals with curl (Merchant and Operator tokens): escalate by asking for a person → queue → claim → reply → Merchant sees it → handback → bot answers with the Operator's reply in context. Then escalate → close. Record trace ids.
- Eval: three scenarios added (explicit request for a person, PT; specialist Escalation, EN, e.g. a chargeback dispute; anonymous request for a person). Expected Intent and `agent`; routing only, no facts. Re-run, compare with the baseline (dataset hash differs, note it); baseline not replaced.
- README: Escalator Agent as the challenge's fourth agent; takeover flow and Operator API; graph diagram.
- Diary: session 4 entry (clock, commits, live check, eval).

**Blocked by:** 04, 05, 06

**Status:** ready-for-agent

- [ ] Live walkthrough done, both paths (handback and close), trace ids recorded
- [ ] Three eval scenarios added; eval re-run; results saved
- [ ] README updated
- [ ] Diary entry with clock and evidence
