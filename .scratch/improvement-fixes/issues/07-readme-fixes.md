# 07: README for the fixes

**What to build:** the README matches the behaviour after the fixes. Off the clock per the run rules; committed separately.

- Configuration table: `JUDGE_MODEL` default, `LOG_HASH_KEY`, `LOG_MESSAGES`.
- Privacy notes: what is redacted, pseudonymized user id, logging modes.
- The documented Judge limitation (no access to Evidence, same model as generator) marked as fixed.
- Scenario output: routing and facts reported separately.
- CI: what it checks and that it needs no secrets; non-root container and index volume.
- Link to `IMPROVEMENT_RUN_DIARY.md`.

**Blocked by:** 01, 02, 03, 04, 05, 06

**Status:** ready-for-agent

- [ ] Configuration table updated
- [ ] Privacy section added
- [ ] Judge limitation updated
- [ ] Scenario output format documented
- [ ] CI and container changes mentioned
- [ ] Diary linked
