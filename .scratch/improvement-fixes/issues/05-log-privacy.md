# 05: Log privacy

**What to build:** no log line exposes a Merchant's personal data, while logs stay useful for debugging.

- One redactor applied centrally: to every structured event before it is written, and to every non-event log line and exception text in the JSON formatter.
- Masked, with typed placeholders (`[CPF]`, `[CNPJ]`, `[CARD]`, `[EMAIL]`, `[PHONE]`, `[PIX_KEY]`):
  - CPF, formatted or 11 bare digits;
  - CNPJ, formatted or 14 bare digits;
  - card numbers of 13–19 digits, optionally grouped by spaces or dashes, only when Luhn-valid;
  - email addresses;
  - Brazilian phone numbers;
  - Pix random keys (UUID with dashes).
  Longer identifiers are matched before shorter ones.
- Left intact: BRL amounts, ISO dates, `trace_id`, Terminal ids.
- The request line's `user_id` becomes `user_ref`: keyed HMAC-SHA256 of the user id, truncated to 16 hex characters, key from `LOG_HASH_KEY`. If empty, a random key is generated at startup with a warning.
- `LOG_MESSAGES` = `none | redacted | full`, default `redacted`. `none` logs the Message length instead of text; `redacted` applies the redactor then the 500-character cap; `full` logs raw text, still capped.
- Judge prompts tell the Judge not to quote personal data in its reason; the reason is redacted regardless.
- `.env.example` documents `LOG_HASH_KEY` and `LOG_MESSAGES`.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Each pattern (formatted and bare) is masked in captured log output; raw values absent
- [x] BRL amounts, ISO dates, `trace_id` and Terminal ids survive
- [x] Non-Luhn digit runs of card length are not masked as cards
- [x] Exception text in an error line is redacted
- [x] Judge reason is redacted
- [x] `user_ref`: same id + key gives the same ref, different keys differ, raw user id absent from the request line
- [x] Warning when `LOG_HASH_KEY` is empty
- [x] `LOG_MESSAGES` modes behave as specified on the request line
- [x] `.env.example` updated
