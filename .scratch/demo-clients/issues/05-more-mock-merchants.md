# 05: More mock Merchants (C3)

**What to build:** 2–3 new Merchants in `data/merchants.json`, so the demo shows more account and Escalation paths.

- `cliente1988` and `cliente2024` stay byte-identical (eval expected facts depend on them).
- Each new Merchant targets a path:
  - a failed or held Settlement, which should lead to an Escalation;
  - an inactive or defective Terminal;
  - a quiet Merchant with few transactions.
- Same shape and day-offset convention as the existing entries.
- No new eval scenarios; the dataset hash is unchanged.
- The README's list of demo users is updated.

**Blocked by:** none

**Status:** ready-for-agent

- [ ] New Merchants load through `load_merchants`
- [ ] Original Merchants unchanged (test or hash check)
- [ ] Each new Merchant's path checked once live
