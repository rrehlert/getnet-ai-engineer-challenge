# 07: Provider error mapping and end-to-end check

Status: ready-for-agent
Blocked by: 05, 06

- Map provider errors and rate limits (OpenAI-compatible 429/APIError/timeouts) raised inside agents to 503; everything else to a generic 500, with `trace_id` in both.
- Run `scripts/scenarios.py` against compose; tune `RELEVANCE_THRESHOLD` and the prompts until all 13 cases pass ✓.
