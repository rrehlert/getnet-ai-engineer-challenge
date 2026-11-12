# 07: Live check, eval and README

**What to build:** Evidence that the takeover works end to end on the real stack, and that it didn't regress the bot.

- Live check with `docker compose up --build`, two terminals with curl (Merchant and Operator tokens): escalate by asking for a person → queue → claim → reply → Merchant sees it → handback → bot answers with the Operator's reply in context. Then escalate → close. Record trace ids.
- Eval: three scenarios added (explicit request for a person, PT; specialist Escalation, EN, e.g. a chargeback dispute; anonymous request for a person). Expected Intent and `agent`; routing only, no facts. Re-run, compare with the baseline (dataset hash differs, note it); baseline not replaced.
- README: Escalator Agent as the challenge's fourth agent; takeover flow and Operator API; graph diagram.
- Diary: session 4 entry (clock, commits, live check, eval).

**Blocked by:** 04, 05, 06

**Status:** done

- [x] Live walkthrough done, both paths (handback and close), trace ids recorded
- [x] Three eval scenarios added; eval re-run; results saved
- [x] README updated
- [x] Diary entry with clock and evidence

## Comments

- **Live check** (session 5, 2026-11-12, stack rebuilt from this branch with `docker compose -p attempt_current up --build`, reusing the `state` volume: the session-3 DB got `needs_review` and the new tables on open).
  - Handback path, Conversation `c84cf0d6…`: PT request for a person → `agent: escalator`, `mode: waiting_human` (trace `e7cc32ab…`); Message while waiting queued, `answer ""` (`19bad244…`); queue shows category/priority/customer_ask; claim by `operador1` refreshed the brief with the R$ 250 detail; `operador2` reply → 403 `not_claimer` (`e5db4443…`); Operator reply seen by the Merchant via `turns?after=11` with `mode: human`; handback → fixed bilingual Turn, `mode: bot`; follow-up answered by Customer Support in context (11/12/2026, R$ 250) (`5cfbc890…`). That reply's answer Judge Score 0.0 set the Review flag; it appeared in `GET /operator/review`.
  - Close path, Conversation `b99313e3…`: EN chargeback → Customer Support called `escalate_to_human`, `intent: support`, `agent: escalator` (`aa73ce28…`); `operador2` closed it from `waiting_human` without a claim (`claimed_by` null); fixed close Turn; next `/chat` → 409 `conversation_closed` (`11b2f7df…`).
  - Anonymous request for a person → reworded login reply, `agent: router`, nothing stored (`875efbe4…`).
  - Audit rows for claim, reply (`used_suggestion` 0), handback and close, no content. No brief field in the container logs (the Merchant Message and Judge reasons are logged as before).
- **Fixes from the live check** (each with a test):
  - `8c52e22`: an EN Merchant got a PT `suggested_reply` (`language` came after it in the schema). `language` now comes first and the reply is "written in `language`". Re-checked live: EN (`db774c81…`).
  - `7a8d142`: the transfer message said "an Operator" to the Merchant (from the session 4 review rename). The prompt now says "a person/human attendant".
  - `2674b61`: the live smoke run had 4 specialist answers escalated (Mixed questions 14, 15, 16 and crediário 9), discarding account facts: facts 8/13. The escalation rule now says last resort, never for a partly answerable question. Re-run: facts 10/13, only 9 escalated (a known retrieval miss).
- **Scenarios** (`f355d3d`): 20 PT request for a person (`human`/`escalator`), 21 EN chargeback (`support`/`escalator`), 22 anonymous request (`human`/`router`); routing only. Scenarios can declare `agent`, which must match too. The eval computes `agent` as `/chat` does and passes the brief to the Judges, so escalated runs get the escalation rubric.
- **Eval** (`evals/results/20261112T192355Z.json`, gitignored; commit `2674b61`, `dirty: true` because README was edited mid-run, no code changed; 3 runs × 22 scenarios, 0 errors): routing 100%, facts 92% (+10pp), answer 0.54 (+0.10), coverage 0.84 (+0.03), route 0.94 (+0.03). Takeover scenarios: routing 9/9; answer 1.0 / 0.80–0.90 (chargeback) / 1.0. The specialists escalated only the chargeback (3/3). Coverage on the chargeback is 0.3–0.4 (the transfer message doesn't answer the question; known). Dataset hash differs from the baseline, so not like-for-like; baseline not replaced.
- **README** (`b88e8bc`): Human takeover section (Escalator as the fourth agent, Modes, Operator API, audit, Review flag), graph diagram, curl walkthrough, `operador2`, limitations.
- **Unverified / open:**
  - Knowledge still escalates when retrieval misses (crediário 48x), instead of saying it couldn't find it.
  - The suggested reply sometimes reads like a transfer note, not an answer the Operator would send.
  - `used_suggestion` is still client-reported.
