# 07: Live check, eval re-run, diary

**What to build:** Evidence that the feature works end to end on the real stack, and that answer quality didn't regress against the eval baseline.

- Compose up (fresh build), log in via `/dev/login`, two-Turn follow-up resolved in context, account question anonymously gets the login reply, restart container, Conversation still listed with its Turns.
- Re-run the eval and compare with `evals/baseline.json`; note regressions or improvements.
- README: short section on login, anonymous access, Conversations, retention; consistent with ADR 0004/0005.
- `IMPROVEMENT_RUN_DIARY.md` session entry; roadmap B2/B3 marked done.

**Blocked by:** 02, 04, 05, 06

**Status:** done

- [x] Live check steps executed, trace ids recorded
- [x] Conversation survives container restart
- [x] Eval re-run compared with baseline, result recorded
- [x] README and diary updated

## Comments

Results: `IMPROVEMENT_RUN_DIARY.md`, session 3 (live check traces, restart, eval vs baseline). README: login, anonymous access, Conversations and retention were already covered by tickets 01–06; added a Quick start note that tokens need `JWT_SECRET` set to survive a restart.
