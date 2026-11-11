# 02: Coverage Judge; `run_judges` returns verdicts

**What to build:** a third Judge Type, `coverage`, that records which specialists a Message needed and whether the reply covered all of it. `run_judges` returns the verdicts it logged so the eval runner can aggregate them.

- Structured output: `intents_needed: list[Intent]` (excluding nothing; `unsupported` allowed alone), `fully_answered: bool`, `missing: str` (empty when fully answered), `score` (1.0 when fully answered, else 0–1 judged), `reason`.
- Prompt gets Message, Intent chosen, reply, and the Intent policy (same text the `route` Judge uses) so "needed" means the same Intents the Router knows.
- Judge line for `coverage` carries the extra fields (`intents_needed`, `fully_answered`, `missing`); `missing` goes through the redactor like `reason`.
- Runs on live traffic with the other Judges (no new flag).
- `run_judges` returns `dict[judge_type, verdict]`; a failed Judge is absent from the dict (still logged as an error, never raised).
- `GLOSSARY.md`: Judge Type gains `coverage`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Fake Judge model returning coverage output: verdict parsed, logged with the extra fields, returned
- [ ] `run_judges` returns verdicts for `route`, `answer`, `coverage`; still emits one line each
- [ ] A Judge that raises is missing from the result, others still returned
- [ ] Personal data in `missing` is redacted in the log line
- [ ] `/chat` path unchanged apart from the extra Judge line (existing tests pass)
- [ ] Glossary updated
- [ ] No real LLM calls in tests
