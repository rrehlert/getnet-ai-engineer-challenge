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
| `conversations-identity` | B2 + B3. SQLite persistence, multi-turn memory with ownership, dev login + JWT, roles |
| `human-takeover` | B4. Human takeover of conversations, Escalator agent, operator API, audit |
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

## Checkpoints

| Tag | Commit | Cumulative | Contents |
|---|---|---|---|
| `v1-submitted` | `f22750d` | 0 | Evaluated solution |
| `improve+30m` | `ebb6deb` | 0h27m | Spec, tickets, B specs/ADRs; CI workflow (ticket 01, not yet green) |
| `improve+60m` | `9aa02b2` | 0h53m | Tickets 01, 02 done; 03 implemented (marked done at `f926a78`) |
| `improve+90m`, `improve-s1-stop` | `d38faf7` | 1h32m | `improvement-fixes` 01–06 done (CI green). Scenarios: routing 13/13, facts 5/7 (ticket 04, 20:20) |

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
