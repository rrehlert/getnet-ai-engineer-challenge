# Improvement run diary

A second round of work on top of the submitted solution, following evaluator feedback. The core solution and its 60-minute clock are untouched; this diary records the improvement run on its own clock.

- **Baseline:** tag `v1-submitted` → `f22750d` (the state that was evaluated).
- **Core clock:** tag `clock-stop` (55m54s, see README "Development process").

## Rules

- The clock runs during implementation sessions only; pauses are recorded.
- Specs and tickets count on the clock (spec-driven development was inside the original 60 minutes too).
- README and diary edits are off the clock, committed separately.
- Never rebase, amend or squash; every branch is merged with `--no-ff`. Commit dates are the clock evidence.
- Annotated tags: `improve-sN-start` / `improve-sN-stop` per session, and `improve+30m`, `improve+60m`, … at cumulative checkpoints. Any checkpoint is a valid place to evaluate from.
- Eval results are saved at each checkpoint.

## Plan

Order: **A. Fixes → B. Core → C. QoL/extras**. One spec per feature under `.scratch/<feature>/`, tickets written just before each feature starts.

| Spec | Covers |
|---|---|
| `improvement-fixes` | A. Judge sees evidence, separate judge model, scenarios split routing vs answer quality, log privacy, judge events readable on their own, non-root container, Chroma volume, CI |
| `eval-expansion` | B1. Coverage judge, mixed-question scenarios, multiple runs + baseline, retrieval recall@k |
| `conversations-identity` | B2 + B3. SQLite persistence, multi-turn memory with ownership, dev login + JWT, roles. **Done** (session 3) |
| `human-takeover` | B4. Human takeover of conversations, Escalator agent, operator API, audit. **Done** (sessions 4–5) |
| `demo-clients` | C. Merchant and operator frontends, more mock data, CLI helper, SSE |
| `multi-intent-router` | B5. Only if coverage data shows enough mixed questions answered incompletely |

Decisions adopted at the start:

- Multi-intent router threshold, fixed before seeing data: ≥10% mixed questions **and** ≥50% of those incomplete.
- Memory keeps the last 10 turns; a rolling summary only if conversations get that long.
- Human-in-the-loop is live takeover; approval-style HITL waits until tools can change data.

## Clock

| Session | Start | Stop | Duration | Cumulative | Tags |
|---|---|---|---|---|---|
| 1 | 2026-11-10 19:13:42 | 20:45:52 | 1h32m10s | 1h32m10s | `improve-s1-start`, `improve-s1-stop` |
| 2 | 2026-11-11 19:46:30 | 20:04:49 | 18m19s | 1h50m29s | `improve-s2-start`, `improve-s2-stop` |
| 3 | 2026-11-11 21:06:46 | 21:58:52 | 52m06s | 2h42m35s | `improve-s3-start`, `improve-s3-stop` |
| 4 | 2026-11-11 22:22:54 | 23:05:33 | 42m39s | 3h25m14s | `improve-s4-start`, `improve-s4-stop` |

## Checkpoints

| Tag | Commit | Cumulative | Contents |
|---|---|---|---|
| `v1-submitted` | `f22750d` | 0 | Evaluated solution |
| `improve+30m` | `ebb6deb` | 0h27m | Spec, tickets, B specs/ADRs; CI workflow (ticket 01, not yet green) |
| `improve+60m` | `9aa02b2` | 0h53m | Tickets 01, 02 done; 03 implemented (marked done at `f926a78`) |
| `improve+90m`, `improve-s1-stop` | `d38faf7` | 1h32m | `improvement-fixes` 01–06 done (CI green). Scenarios: routing 13/13, facts 5/7 (ticket 04, 20:20) |
| `improve-s2-stop` | `f09a1ed` | 1h50m | `eval-expansion` tickets; 01 (shared scenario dataset, 4 Mixed questions) and 02 (coverage Judge) done, CI green. Live check: coverage Judge on 2 Messages (below) |
| `improve+120m` | `57d8d36` | 1h59m | `conversations-identity` tickets; 01 (token identity) done |
| `improve+150m` | `e78994c` | 2h16m | `conversations-identity` 01–06 merged; README for retention and Judges without history |
| `improve-s3-stop` | `2deb383` | 2h43m | 07: live check and eval re-run vs baseline (session 3, below) |
| `improve+180m` | `4306808` | 3h00m | `human-takeover` 01 (`/chat` by Mode), 02 (Intent `human`, Escalator Agent, Handoffs) merged |
| `improve-s4-stop` | `6a07d75` | 3h25m | `human-takeover` 01–06 merged, code review fixes, implementation report; 07 pending |
| `improve+210m` | `7a8d142` | 3h30m | 07 live check done (both paths); fixes: suggested_reply language, transfer-message wording |

## Sessions

### Session 1 — 2026-11-10

Goal: setup, `improvement-fixes` spec and tickets, then implement them.

Done (clock started 19:13:42):

| Time | Commit | What |
|---|---|---|
| 19:13:42 | `b7342e9` | Clock start: diary, plan, rules; tags `v1-submitted`, `improve-s1-start` |
| 19:19:57 | `cd40ea1` | `improvement-fixes` spec; glossary: Evidence |
| 19:24:15 | `58d4c32` | `improvement-fixes` tickets 01–07 |
| 19:35:05 | `e3b1783` | Specs `conversations-identity`, `human-takeover`, `eval-expansion`; ADRs 0004–0006 |

Decisions:

- Judge model defaults to Claude Haiku 5.5: same price as the reply model, different family (independence, not proven accuracy; calibration deferred).
- No LangGraph checkpointer: Turns table is the only history (ADR 0004).
- Anonymous chat allowed, Knowledge only; identity only from a verified token (ADR 0005).
- Human takeover as a Conversation Mode, not `interrupt()` (ADR 0006).
- B specs written up front, while the reasoning was fresh; their tickets are written when each feature starts, against the code as it is then.

Scenario runs (ticket 04, live compose stack, `scripts/scenarios.py`):

- 20:12, first run: routing 13/13, facts 6/7. [8] decline error missed `expired`: reply named only the latest decline (R$ 24,80, insufficient funds, today), a defensible answer to a present-tense question. Fact over-specified; changed to the latest decline's reason + amount.
- 20:14, rerun: routing 13/13, facts 7/7, exit 0.
- After code review, tightened facts: [4] dropped bare `chave`; [9] `48` → `48 installments`/`48x`/…; [8] added issuer hint (`issuer`/`emissor`). [8]'s revision was written after seeing a reply, so it's post-hoc.
- 20:20, third run: routing 13/13, facts 5/7, exit 1. [3] gave dates but no amounts (amount facts kept: the reply should state what lands). [9] `search_corpus` ×3, "couldn't find a confirmed installment limit", although the Corpus says 48x. Retrieval is nondeterministic: it passed in the two earlier runs.

Implementation (one commit per ticket plus a "mark done" commit after CI went green; committed on `main`):

| Time | Commit | What |
|---|---|---|
| 19:40:39 | `ebb6deb` | 01: CI test job + compose smoke test |
| 19:44:28 | `c49bafa` | 01 done (CI run 42917021769) |
| 19:46:41 | `cff8529` | CI: bump checkout v7, setup-uv v10.3.3 (Node 24) |
| 19:53:03 | `7290381` | 02: non-root user, named volume for the Corpus index |
| 19:55:24 | `9deb589` | 02 done (CI run 42918718443) |
| 19:56:39 | `9475c5a` | CI: `paths-ignore` for ticket/diary/docs-only changes |
| 20:04:40 | `50297b6` | 03: `answer` Judge rates against Evidence; Judge model defaults to Haiku 5.5 |
| 20:07:03 | `9aa02b2` | 03: model-independence warning at startup, only when Judges run |
| 20:08:54 | `f926a78` | 03 done (CI run 42920675704) |
| 20:18:42 | `30c00d6` | 04: scenarios check expected facts, routing and facts reported separately |
| 20:24:56 | `b1e6786` | 04 done (CI run 42922936015) |
| 20:31:48 | `8e21b8b` | 05: redactor, keyed `user_ref`, `LOG_MESSAGES` modes |
| 20:35:04 | `229c179` | 05: resolve log privacy at startup, not at import |
| 20:36:45 | `452c6b5` | 05 done (CI run 42924580566) |
| 20:42:37 | `77d4a6e` | 06: Judge lines carry `message` and `answer` |
| 20:45:52 | `d38faf7` | 06 done (CI run 42925792757). **Clock stop** |

Off the clock: ticket 07 README (`0dd3c7a`, `c432ea9`, 20:49:49): config table, Privacy section, Judge limitation marked fixed, scenario output, CI badge, container notes, diary link; glossary Judge Type `answer` updated to Evidence.

Checkpoint evals: only the ticket 04 scenario runs above (20:12–20:20); no separate eval run at +30m/+60m/+90m.

Next: `eval-expansion` (B1): write its tickets against the current code, then implement.

### Session 2 — 2026-11-11

Goal: `eval-expansion` tickets, then 01 and 02.

Done (clock started 19:46:30, tag on `22e087c`):

| Time | Commit | What |
|---|---|---|
| 19:47:17 | `0df12cf` | `eval-expansion` tickets 01–07; `evals/results/` gitignored |
| — | `266147c` | Spec status back to canonical `ready-for-agent` |
| 19:50:23 | `5e1e314` | 01: scenarios in `evals/scenarios.json` (13 original + 4 Mixed), validating loader; glossary: Mixed question |
| — | `046ad4d` | 01: import order |
| 19:52:03 | `7dcfd1a` | 02: `coverage` Judge Type; `run_judges` returns verdicts; glossary |
| 20:04:49 | `f09a1ed` | 01, 02 done (CI run 43116743942); live-check notes on ticket 03. **Clock stop** |

Decisions:

- The 13 original scenarios were checked identical to the old inline list by a one-off script (not a test: CI's shallow checkout has no history).
- `scripts/scenarios.py` keeps its own copy of the Intent values (test-synced) so it runs without importing `app`.
- Coverage Judge: `fully_answered` forces score 1 and empty `missing`.
- `--retrieval-only` added to ticket 05 (recall@4 needs no LLM key).

Live check (rebuilt compose stack, Judges on; the running image had been from 11-10 20:39, before ticket 06):

- Caixa 1 offline + Wi-Fi setup (Mixed): Router → `knowledge` (on 11-10, old image: `support`). Judges: route 0.0, answer 0.0, coverage 0.4 with `intents_needed: [support, knowledge]`, `fully_answered: false`, missing the terminal status check.
- Pix bank account: route 1.0, answer 0.0 (reply opened with "Yes"; Corpus only says a Pix key linked to the receiving account), coverage 1.0 fully answered.
- Follow-ups recorded on ticket 03: accept any needed Intent as routing-correct for Mixed scenarios; tell the `route` Judge that one needed Intent is correct for a Mixed question; watch `answer` harshness in the baseline.

Checkpoint evals: none beyond the live check; the eval runner is ticket 03.

Next: `eval-expansion` 03 (eval runner) with the ticket 03 notes, then 04–06.

Off the clock: `eval-expansion` 03 (`0ae8c99`, `3a443dd`), 04 (`1fdce61`), 05 (`ba2aa4f`), each closed with a green CI run.

#### Live baseline (ticket 06)

Ran `uv run python -m scripts.eval --save-baseline` on `ad0769b` (clean tree), started 20:40:58 (23:40:58Z). That run is saved as `evals/baseline.json`.

- Models: reply `openai:openai/gpt-6-luna`, Judge `openai:anthropic/claude-haiku-5.5`. 3 runs × 17 scenarios = 51 runs, 0 errors.
- Routing 100% (Mixed questions accept any needed Intent). Facts 82%. Judge mean/min: answer 0.44/0.00, coverage 0.81/0.20, route 0.91/0.20.
- Per Intent: knowledge facts 67%, answer 0.40. Support facts 88%, answer 0.33, route 0.81. Unsupported: all 1.00.
- Mixed questions 12/51 = 24% (threshold ≥10%). Incomplete 11/12 = 92% (threshold ≥50%). Verdict: **build multi-intent Router**. The coverage Judge agreed with the labelled Mixed scenarios 12/12.
- recall@4 12/14 = 86%. The 2 misses: "Como habilitar o recebimento de vendas via Pix no aplicativo" (the Pix sale page ranked above it) and "Quais as taxas da maquininha Getnet" (`/duvidas/taxas/` was not in the top 4).
- Tokens: 160,120.

Notable misses:

- 09 installments: the facts check failed 3/3 because "48 installments" was missing. The reply said no source was found, and the answer Judge still gave 1.0, so honest "not found" replies get full answer marks.
- 14 Caixa 1 offline + Wi-Fi (Mixed): routed to `knowledge` 2/3. Facts failed 2/3 because "2.4 GHz" was missing. route Judge 0.2–0.3.
- 13 and 17 (PT support, payout amounts): answer 0.0 on all 3 runs. In 17 the Judge flags a real error: the reply says credit "cai até o fim do dia", but it is scheduled D+30.
- The answer Judge looks harsh: 0.0 on 02 (weather), 05 (offline machine) and 16, even when facts pass. Its reasons often penalise omissions, which is the coverage Judge's job. This is a candidate for tightening the answer Judge prompt.

### Session 3 — 2026-11-11

Goal: `conversations-identity` (B2 + B3): tickets, then implement them.

Done (clock started 21:06:46, tag `improve-s3-start`):

| Time | Commit | What |
|---|---|---|
| 21:06:46 | `c71ff8d` | `conversations-identity` tickets 01–07 |
| 21:15:17 | `57d8d36` | 01: token identity on `/chat` (dev login, JWT verify, `/me`, login-first clients) |
| 21:25:13 | `8c52ff4` | 02 merged: anonymous visitors (Knowledge only, login reply) |
| 21:26:12 | `8c134a6` | 03 merged: Conversations persisted in SQLite (`STATE_DIR` volume) |
| 21:28:42 | `5b5e211` | 06 merged: retention purge at startup |
| 21:30:00 | `d324f00` | 05 merged: list Conversations, read Turns |
| 21:30:21 | `5b48b6a` | 04 merged: last 10 Turns reach Router and specialists |
| 21:32:14 | `e78994c` | README: retention at startup only; Judges don't see history |
| 21:44–21:57 | — | 07: live check and eval re-run (below) |
| — | `0eb6d6c` | 07: live check, eval vs baseline, diary entry, B2/B3 done |
| 21:58:52 | `2deb383` | 07: review fixes. **Clock stop** |

#### Live check (ticket 07)

Fresh `docker compose up --build` on `e78994c` with Judges on, healthy at 21:44:12. The Merchant is `cliente1988`, logged in through `/dev/login`.

- "My card machine is offline" (trace `fcf5a92671564cab830346e2988aa994`) → `support`, `get_terminal_status`, new Conversation `c4caac36-…`. Judges: route 1.0, coverage 1.0, answer 0.0 (it disliked "yesterday" for 2026-11-11 and the empty Sources).
- "It is the Smart one" in the same Conversation (trace `62d118cc788f4009b6ea977ac90fd183`) → `support`, answered in context: "Caixa 1 is the Getnet POS Smart (Android)". Judges: route 0.0, answer 0.0, coverage 1.0. The route Judge called the bare follow-up "likely knowledge", which is the known limitation (Judges don't see history).
- Anonymous "Quanto eu tenho para receber amanhã?" (trace `3d7f90a599664c42970e1f05154656b6`) → `support`, `agent` `router`, steps `router, login`, bilingual login reply, `conversation_id` null, `user_ref` `anonymous`. Live Judges: route 1.0, answer 1.0, coverage 0.2 ("only asks the user to log in"). The coverage Judge is not told the visitor is anonymous (only route and answer are), live or in the eval: the anonymous eval scenario 19 also scores 0.2–0.3.
- `docker compose restart` → `retention purge: deleted 0`. after a fresh `/dev/login`, `GET /conversations` still lists `c4caac36-…` with its 4 Turns (ids 5–8, in order). The old token got 401 because `JWT_SECRET` was empty in `.env`, so a new secret was generated. The README Quick start now says this.

#### Eval re-run (ticket 07)

Ran `uv run python -m scripts.eval` on `e78994c`, 21:45:12–21:56:45. The results metadata says `dirty: true`: it is read when the run ends, and the README Quick start note was edited mid-run (no code changed). Results are in `evals/results/20261112T004519Z.json`; the baseline was not replaced.

- 3 runs × 19 scenarios = 57 runs, 0 errors. The dataset hash differs from the baseline (2 anonymous scenarios added), so the deltas are not like-for-like.
- Overall: routing 100% (+0pp), facts 77% (−5pp), answer 0.46 (+0.02), coverage 0.79 (−0.02), route 0.93 (+0.02, min 0.20 → 0.40).
- Knowledge facts were 42% (−25pp). The drop is Get Clássica: scenario 01 passed 3/3 → 1/3 and the new anonymous 18 passed 1/3, both missing "4G" because the reply said no Clássica info was found. Corpus coverage is thin there (known limitation). Eval scenarios have empty history, so nothing here goes through the new history path. Smaller drops: 04 (Pix key) 3/3 → 2/3, 05 (offline machine) facts 3/3 → 2/3. 09 (48 installments) went 0/3 → 1/3.
- Support facts 93% (+5pp). The anonymous account scenario 19 passed 3/3 with answer 1.0.
- Mixed questions 12/57 = 21%, incomplete 9/12 = 75% (−17pp). The verdict is still **build multi-intent Router**. The coverage Judge agreed with the labelled Mixed scenarios 12/12.
- recall@4 12/14 = 86%, the same 2 misses. Tokens: 175,915 in total; the mean per scenario run is 3,086 (−53 vs 3,140).
- No regression attributable to `conversations-identity`. The facts drop is retrieval/LLM variance on a weak Corpus topic.

Checkpoint evals: no separate run at +120m/+150m; the ticket 07 eval re-run (above) is the session's eval.

Off the clock: README section "Login, Conversations and retention", the live coverage Judge limitation, and this clock entry.


Off the clock, after the session: the coverage Judge now gets the Merchant line and a login rule for anonymous visitors (`app/judge.py`, test in `tests/test_anonymous.py`). Live trace `af55e12ecc77453884f463136bc79b29`: an anonymous account question now scores coverage 1.0 (was 0.2). The eval was not re-run, so the scenario 19 coverage in the results above is still the old 0.2–0.3.
Next: `human-takeover` (B4).

### Session 4 — 2026-11-11

Goal: implement `human-takeover` tickets 01–06 (B4) with implementer subagents, one per ticket in its own worktree, merged `--no-ff` into the integration branch `human-takeover`. Ticket 07 (docker, real LLM calls, eval) was left for a session with the human at the keyboard.

Done (clock started 22:22:54, tag `improve-s4-start`):

| Time | Commit | What |
|---|---|---|
| 22:33:25 | `7aa8372` | 01 merged: `/chat` by Mode (queued in `waiting_human`/`human`, 409 when `closed`), `mode` in replies and Turns |
| 22:39:06 | `4306808` | 02 merged: Intent `human`, Escalator Agent, Handoffs table, one-transaction Escalation; anonymous login reply reworded |
| 22:43:35 | `00145a6` | 05 merged: `escalate_to_human` tool in both specialists (middleware stops the loop) |
| 22:46:26 | `dafd260` | 03 merged: Operator API (queue, detail, atomic claim, brief refresh), audit table |
| 22:50:26 | `6a95147` | 04 merged: reply, handback, close; `[Human agent]` history prefix; `operador2` |
| 22:51:27 | `ca5757a` | 06 merged: escalation rubric for the answer Judge, Review flag, review list |
| 22:58:48 | `1251d0d` | Code review fixes: anonymous empty answer bug, `/chat` Mode races (409 `mode_changed`), glossary names, dedup |
| 22:59:19 | `6a07d75` | Implementation report `.scratch/human-takeover/report.md` |
| 23:05:33 | — | **Clock stop** (tag `improve-s4-stop`) |

- Tests 274 → 377, all fakes, green after every merge. Lint: `uv run ruff check` doesn't run (ruff isn't a dev dependency); `uvx ruff check` (0.17.4) shows 28 errors already on `main`, and none were added.
- Decisions: tool Escalation ends the agent loop through a middleware, not `return_direct` (that only stops when every tool call in the turn is return_direct); a Handoff keeps `brief_turn_id` so the brief is rewritten on claim only if the Merchant wrote more; `/reviewed` on an unflagged Conversation → 409.
- Left out: README (written in session 5), live check and eval (ticket 07).

### Session 5 — 2026-11-12

Goal: `human-takeover` ticket 07: live check, eval scenarios and re-run, README.

Done (clock started 16:10:45, tag `improve-s5-start`):

| Time | Commit | What |
|---|---|---|
| 16:10:45 | — | Stack rebuilt from `ht-07-live-eval` (the running one was built from `main`), same `state` volume |
| 16:11–16:12 | — | Live check, both paths (below) |
| 16:13:11 | `8c52e22` | Escalator: `language` before `suggested_reply` (EN Merchant got a PT suggested reply) |
| 16:13:58 | `7a8d142` | Transfer message doesn't say "Operator" to the Merchant |
| 16:15:39 | `f355d3d` | Three takeover scenarios; scenarios check expected `agent`; eval passes the brief to the Judges |
| 16:20:14 | `2674b61` | Escalation is a last resort (live smoke: 4 specialist answers escalated, facts 8/13) |
| 16:23–16:37 | — | Eval re-run (below) |
| 16:38:05 | `b88e8bc` | README: Human takeover section, graph diagram, curl walkthrough (off the clock) |
| 16:38:23 | `e71eca4` | 07 ticket done |
| 16:38:28 | `4bedc49` | 07 merged into `human-takeover` |

#### Live check (ticket 07)

`docker compose -p attempt_current up --build` from the 07 worktree, Judges on, reusing the session-3 database (it got `needs_review`, `handoffs` and `audit` on open). Merchant `cliente1988`, Operators `operador1` and `operador2`.

- **Handback path** (Conversation `c84cf0d6-…`):
  - "Quero falar com um atendente humano…" (trace `e7cc32abeb654927968fd08c1d43d477`) → `human`, `agent` `escalator`, `mode` `waiting_human`, PT transfer message.
  - A Message while waiting was queued with `answer ""` (`19bad24479994a7587d636bb22e0c0e5`).
  - Queue showed the brief fields. The claim by `operador1` rewrote the brief with the new R$ 250 detail.
  - `operador2` reply → 403 `not_claimer`.
  - The Operator reply showed up in `turns?after=11` with `mode` `human`. Handback stored the fixed bilingual Turn and set `mode` `bot`.
  - The follow-up "Então quando exatamente esse dinheiro cai…" (`5cfbc890419f421caa1289e41e85c6f0`) → `support`, answered in context (11/12/2026). Its answer Judge Score was 0.0, so it got a Review flag and appeared in `GET /operator/review`.
- **Close path** (Conversation `b99313e3-…`):
  - EN chargeback (`aa73ce282ad54c5e9ef399346bd3eec9`) → `support`, steps `router, support, escalate_to_human, escalator`.
  - `operador2` closed it from `waiting_human` without a claim.
  - Fixed close Turn stored; the next `/chat` → 409 `conversation_closed` (`11b2f7dfdf354153a3ac3f09ecd660e7`).
- Anonymous "I want to talk to a human agent" (`875efbe4d9b0419f8a9605019a01dd57`) → `human`, `agent` `router`, login reply, nothing stored.
- Audit rows: claim, reply (`used_suggestion` 0), handback, close; no content. No brief field in the container logs.
- Found and fixed:
  - The EN brief's `suggested_reply` was in Portuguese. Fixed, re-checked live (`db774c81271841ffb1684b1d3304f639`).
  - The transfer message said "Operator" to the Merchant. Fixed.

#### Live smoke and eval re-run (ticket 07)

- `scripts/scenarios.py` before the escalation-rule fix: routing 22/22, facts 8/13. Customer Support escalated Mixed questions 14, 15 and 16 (and Knowledge escalated 9) instead of answering, throwing away the account facts. After the fix (`2674b61`): routing 22/22, facts 10/13. The remaining misses are the known Get Clássica "4G" (1, 18) and crediário (9, still escalated on a retrieval miss).
- A first eval run on the old prompt was stopped early to save tokens; the smoke run already showed the problem.
- `uv run python -m scripts.eval` on `2674b61`, 16:23–16:37. `dirty: true` because the README was edited mid-run (no code changed). Results are in `evals/results/20261112T192355Z.json`; the baseline was not replaced.
  - 3 runs × 22 scenarios = 66 runs, 0 errors. The dataset hash differs from the baseline (3 takeover scenarios), so the deltas are not like-for-like.
  - Overall: routing 100% (+0pp), facts 92% (+10pp), answer 0.54 (+0.10), coverage 0.84 (+0.03), route 0.94 (+0.03).
  - Takeover scenarios routing 9/9:
    - PT request for a person: answer 1.0, coverage 1.0.
    - Chargeback: answer 0.80–0.90; coverage 0.3–0.4, because the transfer message doesn't answer the question (known limitation).
    - Anonymous request: answer 1.0, coverage 1.0.
  - The specialists escalated only the chargeback, 3/3; no unwanted escalations.
  - Mixed questions 12/66 = 18%, incomplete 9/12 = 75%. Verdict still **build multi-intent Router**; coverage Judge agreed 12/12 with the labelled Mixed scenarios.
  - recall@4 12/14 = 86%, same misses. Tokens 225,604 in total, mean 3,418 per run (+279).
- No regression from `human-takeover`. B4 done.

Open:
- `used_suggestion` is reported by the client.
- The suggested reply sometimes reads like a transfer note.
- Knowledge escalates on retrieval misses.
- Ruff isn't a dev dependency, and `main` has 28 errors.

