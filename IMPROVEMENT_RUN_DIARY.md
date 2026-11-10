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
| 1 | 2026-11-10 | | | | `improve-s1-start` |

## Checkpoints

| Tag | Commit | Cumulative | Contents |
|---|---|---|---|
| `v1-submitted` | `f22750d` | 0 | Evaluated solution |

## Sessions

### Session 1 — 2026-11-10

Goal: setup, `improvement-fixes` spec and tickets.

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

Next: implement `improvement-fixes` ticket by ticket, starting with 01 (CI).
