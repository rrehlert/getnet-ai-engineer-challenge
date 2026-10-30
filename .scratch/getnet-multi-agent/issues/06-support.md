# 06: Mock data and Customer Support Agent

Status: ready-for-agent
Blocked by: 03

- `data/merchants.json` (cliente1988, cliente2024) with day offsets relative to today.
- Tools `get_settlement_schedule`, `get_terminal_status`, `get_recent_transactions`; `user_id` from `ToolRuntime` context.
- `create_agent` with `context_schema` and a `dynamic_prompt` (date, weekday, Merchant; unknown user → no tools); R$ amounts and the Message's language.
- Tests: scripted fake → tools read context `user_id`, unknown user calls no tools, relative dates resolve.
