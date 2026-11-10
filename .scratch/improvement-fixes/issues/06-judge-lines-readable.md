# 06: Judge lines readable on their own

**What to build:** someone reading a Judge line can see what was scored without joining other lines. The Judge line gains `message` and `answer`, both following `LOG_MESSAGES` and the redactor, capped like the request line's Message.

**Blocked by:** 05 (Log privacy): the new fields must never be written unredacted

**Status:** ready-for-agent

- [x] Judge line contains `message` and `answer`
- [x] Both are redacted under the default mode
- [x] Each `LOG_MESSAGES` mode applies (`none` omits text and logs lengths, `full` logs raw, capped)
- [x] Both are capped at the same length as the request line's Message
