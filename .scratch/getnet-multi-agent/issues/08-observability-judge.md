# 08: Request log line and Judges (B4)

Status: closed
Blocked by: 07

- One JSON log line per request with the spec's fields (tokens summed from `usage_metadata`).
- Background `route` and `answer` judges (`JUDGE_ENABLED`, `JUDGE_MODEL`), one `event:"judge"` line per Judge Type, WARNING when the score is below 0.7.
- Tests: log line fields, judges off in tests, judge type selection with a fake model.
