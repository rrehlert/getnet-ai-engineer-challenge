# 04: Scenarios check expected facts

**What to build:** the scenario script checks that replies contain the right facts, not only the right Intent, and reports the two separately.

- Each scenario gains optional expected facts: a list of facts, each a list of accepted alternatives, matched as case-insensitive substrings; a fact passes if any alternative appears in the reply.
- Facts for Customer Support scenarios come from the fixture (amounts, decline reasons, Terminal status); Knowledge scenarios get facts only where the fact is stable on the Corpus; refusals and web-search scenarios get none.
- A pure checking function takes the response body and the scenario and returns routing pass/fail and facts pass/fail/not-applicable, with the missing facts.
- The report prints `routing X/13` and `facts Y/N` (N = scenarios with facts) and lists missing facts per scenario. Exit code is non-zero if either is below 100%.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Checking function unit-tested: correct Intent with a missing fact, wrong Intent with facts present, alternatives, case-insensitivity, scenario without facts
- [ ] Support scenarios declare fixture-backed facts; stable Knowledge facts where they exist
- [ ] Report shows routing and facts as separate totals and lists missing facts
- [ ] Non-zero exit when routing or facts fail
- [ ] Run once against a live stack; result recorded in the diary
