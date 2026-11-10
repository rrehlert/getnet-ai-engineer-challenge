# Spec: Improvement fixes

Status: ready-for-agent

Run: improvement run, see `IMPROVEMENT_RUN_DIARY.md`. Baseline: tag `v1-submitted`. Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/`.
Previous spec (closed): `.scratch/getnet-multi-agent/spec.md`.

## Problem Statement

The submitted solution works, but several existing pieces are less trustworthy than they look:

- The `answer` Judge rates groundedness without seeing what the Agent saw. It gets the Message, Intent, reply and the Sources' URLs and titles, never the Chunks or the account tool data. It can't tell a grounded reply from a plausible invented one.
- The Judges run on the same model that writes the replies, so a Judge Score may partly reflect the model preferring its own output, and both share the same blind spots.
- The scenario script reports "13/13 passed" when it only checks HTTP status and Intent. That is routing accuracy, but it reads like answer quality.
- The logs carry personal data. Every request line has the Merchant's user id in clear text and up to 500 characters of the Message, which in practice is the whole Message. Merchants type CPF/CNPJ, phone numbers, emails, Pix keys and sometimes card numbers. The Judge's free-text reason can quote the Message or reply, and error lines print exception details that may include payload content.
- Judge log lines carry no Message or reply. Someone reading a low Judge Score from the logs can't see what was scored without joining on `trace_id`, and the reply isn't logged anywhere.
- The container runs as root, the Corpus index is rebuilt every time the container is recreated, and nothing automatically checks that the tests pass and the image builds and starts.

## Solution

- Each specialist Agent records its **Evidence** (the tool output it actually saw), and the `answer` Judge rates the reply against that Evidence.
- The Judges default to a model from a different family than the one that writes replies.
- The scenario script checks expected facts in the replies as well as the Intent, and reports routing accuracy and fact accuracy as two separate numbers.
- All log output passes through one redactor that masks personal data. The Merchant's user id is pseudonymized, and how much Message text is logged is configurable, defaulting to redacted.
- Judge log lines include the (redacted) Message and reply, so each line can be read on its own.
- The container runs as a non-root user, the index survives container recreation, and CI runs the tests and a container smoke test on every push.

## User Stories

1. As an evaluator, I want the `answer` Judge to see the Chunks the Knowledge Agent retrieved, so that its groundedness rating reflects whether claims are supported.
2. As an evaluator, I want the `answer` Judge to see the account tool data the Customer Support Agent received, so that it can tell real amounts and dates from invented ones.
3. As an evaluator, I want Evidence passed to the Judge to be capped in size, so that a Knowledge turn with several searches doesn't make judging expensive.
4. As an evaluator, I want the Judges to use a model from a different family than the reply model by default, so that Judge Scores are less biased toward the generator's own output.
5. As a maintainer, I want a warning logged when the Judge model is set to the same model as the reply model, so that I notice when Judge independence is lost.
6. As a maintainer, I want the Judge model to stay configurable, so that I can use a stronger model for offline evaluation runs.
7. As an evaluator, I want each scenario to declare the facts its reply must contain, so that a correct Intent with a wrong answer is caught.
8. As an evaluator, I want an expected fact to accept alternative spellings, so that "R$ 1.817,26" and "R$1.817,26" both count.
9. As an evaluator, I want the scenario report to show routing accuracy and fact accuracy separately, so that I don't mistake one for the other.
10. As an evaluator, I want the scenario script to fail when either routing or facts fail, so that it can gate a checkpoint.
11. As a Merchant, I want my CPF, CNPJ, card numbers, phone, email and Pix keys masked in any log line, so that operational logs don't expose my personal data.
12. As a Merchant, I want my user id pseudonymized in the logs, so that a log reader can't directly tell which account wrote a Message.
13. As a log reader, I want the pseudonym to stay the same for the same Merchant, so that I can still correlate events from one account.
14. As a security reviewer, I want the pseudonym to be keyed, so that it can't be reversed by hashing every possible user id.
15. As a maintainer, I want a warning when no pseudonym key is configured, so that I know pseudonyms will change on restart.
16. As a maintainer, I want to choose whether Message text is logged not at all, redacted, or in full, so that I can debug locally without changing production behaviour.
17. As a maintainer, I want redacted logging to be the default everywhere, so that personal data is safe unless I explicitly opt out.
18. As a log reader, I want monetary amounts, dates, trace ids and Terminal ids left intact by the redactor, so that the logs stay useful.
19. As a security reviewer, I want error lines and exception details to pass through the same redactor, so that personal data can't leak through stack traces.
20. As a Merchant, I want the Judges told not to quote personal data in their reasons, and their reasons redacted anyway, so that Judge output can't leak what the redactor would mask.
21. As a log reader, I want each Judge line to include the redacted Message and reply, so that I can understand a low Judge Score without joining other lines.
22. As a log reader, I want the Judge line's Message and reply to follow the same logging mode as the request line, so that one setting controls all Message text in the logs.
23. As a security reviewer, I want the container process to run as a non-root user, so that a compromise of the app doesn't give root inside the container.
24. As a maintainer, I want the Corpus index stored on a volume, so that recreating the container doesn't rebuild the index.
25. As a maintainer, I want the index volume to be writable by the non-root user, so that the first startup can build the index.
26. As a maintainer, I want CI to run the test suite on every push and pull request, so that regressions are caught without relying on memory.
27. As a maintainer, I want CI to build the image, start it with compose and check `/health`, so that a broken Dockerfile or startup is caught.
28. As a maintainer, I want CI to need no LLM key, so that it runs on forks and costs nothing.
29. As an evaluator, I want the README to describe the new settings and the fixed Judge limitation, so that the documentation matches the behaviour.

## Implementation Decisions

**Evidence (A1)**
- New domain term **Evidence**: the tool output an Agent actually saw while answering, as opposed to a Source (URL and title only). Added to `GLOSSARY.md`.
- Graph state gains `evidence`: an ordered list of `{tool, content}` items, one per tool call. The Knowledge Agent records `search_corpus` and `web_search` outputs, including Chunks below the relevance threshold, since the model saw them. The Customer Support Agent records its account tool outputs. The Router and unknown-Merchant runs record none.
- Evidence is internal: it is not added to the `/chat` response.
- The `answer` Judge receives Evidence and is asked whether every claim in the reply is supported by it. Total Evidence passed to the Judge is capped at ~6,000 characters, truncating items in order with a marker that text was cut.
- The `route` Judge is unchanged.

**Judge model (A2)**
- `JUDGE_MODEL` defaults to `openai:anthropic/claude-haiku-5.5` (same OpenRouter key and price as the default reply model, different family). The "empty means same as `LLM_MODEL`" fallback is removed.
- When `JUDGE_MODEL` equals `LLM_MODEL`, a warning is logged at startup.
- A stronger model (e.g. Sonnet) is a configuration choice for offline evaluation, not the default.

**Scenarios (A3)**
- Each scenario gains optional expected facts: a list of facts, each a list of accepted alternatives (case-insensitive substring match). A fact passes if any alternative appears in the reply.
- Facts are written for Customer Support scenarios (from the fixture: amounts, decline reasons, Terminal status) and for Knowledge scenarios only where the fact is stable on the Corpus. Refusals and web-search scenarios get none.
- A pure checking function takes the response body and the scenario and returns routing pass/fail and facts pass/fail/not-applicable.
- The report prints `routing X/13` and `facts Y/N` (N = scenarios with facts) and lists missing facts per scenario. Exit code is non-zero if either is below 100%.
- Judge Score aggregation is out of scope here (eval-expansion spec).

**Log privacy (A4)**
- One redactor applied centrally: to every structured event before it is written, and to every non-event log line and exception text in the JSON formatter.
- Masked patterns, replaced by typed placeholders such as `[CPF]`, `[CNPJ]`, `[CARD]`, `[EMAIL]`, `[PHONE]`, `[PIX_KEY]`:
  - CPF, formatted or 11 bare digits;
  - CNPJ, formatted or 14 bare digits;
  - card numbers of 13–19 digits, optionally grouped by spaces or dashes, masked only when Luhn-valid;
  - email addresses;
  - Brazilian phone numbers;
  - Pix random keys (UUID with dashes).
  Longer identifiers are matched before shorter ones (CNPJ before CPF, card before phone).
- Must not mask: BRL amounts, ISO dates, `trace_id` (32 hex characters, no dashes), Terminal ids.
- The request line's `user_id` field is replaced by `user_ref`: a keyed HMAC-SHA256 of the user id, truncated to 16 hex characters. Key from a new `LOG_HASH_KEY` setting. If empty, a random key is generated at startup with a warning (pseudonyms then change per process).
- New `LOG_MESSAGES` setting, `none | redacted | full`, default `redacted`. `none` omits Message text and logs its length instead. `redacted` applies the redactor, then the existing 500-character cap. `full` logs raw text (still capped).
- Judge prompts add an instruction not to quote personal data in the reason. The reason is redacted regardless.
- `.env.example` documents `LOG_HASH_KEY` and `LOG_MESSAGES`.

**Judge lines (A8)**
- The Judge line gains `message` and `answer`, both following `LOG_MESSAGES` and the redactor, capped like the request line's Message.
- Depends on A4: the new fields must never be written unredacted.

**Container (A5, A6)**
- The image creates a non-root user and runs as it. The app directory, the index directory and the embedding model cache are readable (and the index directory writable) by that user.
- Compose mounts a named volume at the index directory. The directory exists in the image, owned by the non-root user, so a fresh named volume inherits that ownership.

**CI (A7)**
- GitHub Actions workflow on push and pull request:
  1. install with `uv sync --locked`, run pytest;
  2. build and start with compose, wait for `/health` to return 200, POST an empty body to `/chat` and expect 422, tear down.
- No secrets. With no LLM key the app still starts and builds the index; `/chat` is not called with a valid body.

**Docs**
- README: configuration table (`JUDGE_MODEL`, `LOG_HASH_KEY`, `LOG_MESSAGES`), privacy notes, the Judge limitation marked as fixed, the scenario output format, CI badge or mention. Off the clock per the run rules, committed separately.

## Testing Decisions

- Test external behaviour at existing seams; no new seams. No real LLM calls in pytest (unchanged rule).
- **Evidence:** drive the Knowledge and Customer Support Agents with the existing scripted fake chat model that emits tool calls. Assert the node's result contains Evidence items with the tool name and its output, and none for an unknown Merchant. Prior art: `tests/test_knowledge.py`, `tests/test_support.py`.
- **Judge sees Evidence:** run the Judges with the existing fake Judge model and assert the `answer` Judge's prompt contains the Evidence text, and that it is cut at the cap. End to end: `create_app` with an injected graph returning Evidence and a fake Judge model. Prior art: `tests/test_observability.py`.
- **Judge model setting:** default value, explicit override, and a warning when equal to the reply model. Prior art: `tests/test_settings.py`.
- **Scenario check:** unit-test the pure checking function: correct Intent with missing fact, wrong Intent with facts present, alternatives, case-insensitivity, scenarios without facts.
- **Redaction:** captured log output for a Message containing each pattern (formatted and bare): placeholders present, raw values absent. Negative cases: BRL amounts, dates, `trace_id` and Terminal ids survive. Exception text in an error line is redacted. Prior art: `tests/test_observability.py` (`caplog` + JSON line parsing).
- **Pseudonym:** same user id gives the same `user_ref` within a key, different keys give different refs, raw user id absent from the request line.
- **`LOG_MESSAGES`:** each mode on the request line and the Judge line.
- **Judge line:** contains redacted `message` and `answer`.
- **Container and CI:** no pytest; the CI run is the test. Verify locally once with `docker compose up --build` (process user is not root, index reused after `docker compose down && up`).

## Out of Scope

- Judge Score aggregation, multiple runs, baselines, the coverage Judge, retrieval metrics (eval-expansion spec).
- Storing conversations, retention policy (conversations-identity spec).
- Calling `/chat` with a real model in CI.
- Calibrating the Judges against human labels.
- Removing personal data from the mock fixture (it is mock data, and tool output is not logged).

## Further Notes

- Tickets come from this spec via `/to-tickets`, one file per ticket under `.scratch/improvement-fixes/issues/`, branches `fixes/NN-slug`, commits `fixes-NN: …`, merged with `--no-ff`.
- Order constraints: redaction before Judge lines (A4 → A8). Evidence, Judge model and scenario facts before the eval-expansion baseline.
- The Judge model choice is about independence, not accuracy. Accuracy needs human calibration, which is deferred.
