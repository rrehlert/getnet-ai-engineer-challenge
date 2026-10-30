# 03: Router Agent, graph, /chat, scenarios script

Status: closed
Blocked by: 02

- `init_chat_model` factory (ADR 0001; timeout and retries).
- Router: structured `Route` call with `include_raw=True`; unparseable → knowledge; refusal reply for unsupported.
- `build_graph(route_fn, knowledge, support)` with conditional edges on `intent`; stub specialists for now.
- `POST /chat` with the spec's response shape, `trace_id`, and 422/503/500 mapping.
- `scripts/scenarios.py` with the 10 examples + 3 edge cases.
- Tests: graph branches with fakes, Router parse fallback, API status codes.
