# 01: Shared scenario dataset with mixed questions

**What to build:** the scenarios move out of `scripts/scenarios.py` into one data file (`evals/scenarios.json`) that both the live smoke script and the eval runner (ticket 03) read. 3–4 Mixed question scenarios are added.

- Each scenario: `message`, `user_id` (the Merchant; field kept so conversations-identity can map it to a login later), `intent` (expected), `facts` (list of facts, each a list of accepted alternatives), and for Mixed questions `intents_needed` (≥2 Intents).
- BRL amounts are written once as `{"brl": "1817.26"}` and expanded to spellings by the loader (today's `brl()`), so the file stays readable.
- Loader validates: every scenario has a valid expected Intent; `intents_needed`, when present, has ≥2 distinct valid Intents; facts are non-empty lists of strings. Invalid file → clear error naming the scenario.
- Mixed scenarios (cliente1988, facts from `data/merchants.json` + stable Corpus facts only), e.g.: Terminal offline + how to fix its Wi-Fi; pending Settlement + how receivables advance works; a decline + whether the Get Smart avoids it. Expected `intent` is what today's single-intent Router should pick (the dominant part); `intents_needed` lists both.
- `scripts/scenarios.py` reads the file; output and exit code unchanged (routing + facts).
- `GLOSSARY.md`: **Mixed question**.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Existing 13 scenarios load from the file with identical messages, Intents and facts (BRL expansion matches today's `brl()`)
- [ ] Loader rejects: missing/unknown Intent; `intents_needed` with <2 Intents; empty fact
- [ ] 3–4 Mixed scenarios added with `intents_needed`
- [ ] `scripts/scenarios.py` uses the file; `tests/test_scenarios.py` still passes
- [ ] Glossary: Mixed question
- [ ] No real LLM calls in tests
