# 06: Escalation Judge and Review flag

**What to build:** Escalations are judged on whether the Handoff Brief is faithful to the Conversation, and bot replies that score low are flagged for an Operator to review afterwards, without changing the Mode or blocking the Merchant.

- Escalated Turns (Intent `human` or tool Escalation): the answer Judge uses an escalation rubric instead of the Intent rubric (brief faithful to the Conversation, no invented claims; transfer message in the Merchant's language) and gets the brief.
- Route and coverage Judges know Intent `human` (via the Intent policy); the anonymous rubric and coverage rule cover `human` as well as `support`.
- An `answer` Judge Score below 0.7 sets the Review flag on the Conversation. Route and coverage scores never do. Anonymous requests have no Conversation and set nothing.
- Operators: a review list (flagged Conversations, any Mode, newest first); flagged Conversations are readable through the detail view; marking one reviewed clears the flag and is audited.

**Blocked by:** 03

**Status:** done

- [x] Escalated Turn → answer Judge uses the escalation rubric and sees the brief
- [x] Answer score < 0.7 sets the flag; route/coverage < 0.7 do not; Mode unchanged
- [x] Anonymous low score sets nothing
- [x] Flagged `bot` Conversation (no Handoff) readable by Operators; appears in the review list, newest first
- [x] Reviewed clears the flag; audit row written
- [x] Anonymous `human` login reply judged with the anonymous rubric
- [x] No real LLM calls in tests

## Comments

- `app/judge.py`: `ESCALATION_RUBRIC` (brief faithful to the Conversation: earlier Turns, Message, Evidence; no invented claims/amounts/dates/actions; transfer message in the Message's language). `run_judges(..., handoff=None, history=())`: with a `handoff`, the `answer` Judge uses that rubric and its input gains `Earlier Turns:` (role: content, via `format_history`) and `Handoff Brief:` (JSON). Neither is logged; route/coverage inputs unchanged. Escalated = a brief came back (Intent `human` or tool Escalation), so the tool case keeps the specialist's Intent but still gets the escalation rubric.
- Judges now see history only for escalated Turns (the brief can't be checked for faithfulness without it); bot Turns still judged without history, as before.
- Anonymous: `LOGIN_INTENTS = ("support", "human")` → `ANONYMOUS_SUPPORT_RUBRIC` (reworded: log in to see the account or talk to an agent). `ANONYMOUS_COVERAGE_RULE` and `ANONYMOUS_MERCHANT` cover `human`. Route/coverage already get `human` via `INTENT_POLICY` (ticket 02); nothing else needed.
- `app/main.py`: background `judge(trace_id, message, result, history, brief, conversation_id)`; `brief`/`conversation_id` passed explicitly from `/chat` (None for anonymous), not read from the graph result. `answer` verdict < `FLAG_BELOW` (0.7) → `Store.flag_for_review(cid)`. A failure there is logged, never raised. A failed `answer` Judge (no verdict) sets nothing.
- `Store.flag_for_review` doesn't touch Mode or `updated_at` (not Merchant activity; keeps the Merchant's listing order). `Store.clear_review(cid, operator)`: conditional update + `reviewed` audit row in one transaction; False if not flagged. `Store.review_list()`: flagged, any Mode, `updated_at DESC`.
- `app/operator.py` (separate block at the end of `operator_router`): `GET /operator/review` → `{conversations: [{conversation_id, mode, created_at, updated_at}]}`, newest (by `updated_at`) first. `POST /operator/conversations/{id}/reviewed` → detail view with `needs_review: false`; not visible → 404; visible but not flagged → 409 `not_flagged`, no audit. A never-escalated Conversation becomes invisible (404) once reviewed, per the visibility rule. Flagged `bot` detail worked already via 03's SQL rule; now tested.
- Tests: `tests/test_review_flag.py` (18), fake Judge models (`RecordingJudgeModel`) and fake graphs only.
- Decision: "newest first" read as most recently updated (no separate flagged-at column). A Conversation flagged long after its last Turn sorts by its last activity.
- Unverified: real Judge model's behaviour on the escalation rubric (ticket 07's eval). Coverage Judge on an escalated Turn still sees just the transfer message (may score it as not covering the question; never flags, so left as is).
- Left out: README (user rule).
