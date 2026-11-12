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

**Status:** done

- [x] New Merchants load through `load_merchants`
- [x] Original Merchants unchanged (test or hash check)
- [ ] Each new Merchant's path checked once live

## Comments

- `data/merchants.json`: three Merchants appended after `cliente2024`, same shape (`profile`, `settlements`, `terminals`, `transactions`) and `*_day_offset` convention. The tools dump the fixture JSON as-is (no status-specific code), so new values reach the model verbatim; terminal `status` stays `online`/`offline` (the tool docstring's values), and the new Settlement statuses `failed`/`held` each carry a `note` saying why and that only Getnet staff can resolve it.
- `cliente1975` (Restaurante Sabor da Serra, Belo Horizonte) → held Settlement → Escalation. Bank account on file (Itaú ****3380-1) is closed: D-2 debit R$ 2.452,63 and Pix R$ 636,80 `failed` (returned by the bank, money stays with Getnet); D-1 debit R$ 2.594,36 and Pix R$ 708,94 `held`, no release date; D-1 credit R$ 3.026,71 `scheduled` D+29. Fixing it needs a bank account change by staff, which `ESCALATION_RULE` lists as person-only (registration changes). Terminal fine.
- `cliente2010` (Farmácia Bem Viver, Recife) → defective Terminal. `GT-91B2-0208` "Caixa Principal" `offline` since yesterday 10:23 with `CARD_READER_FAULT` (hardware self-test failed); hints: restart once, if the fault repeats the reader is defective and only Getnet support can request a replacement; meanwhile use `GT-91B2-0231` "Caixa 2" (online, chip) or Pix. One decline yesterday 10:21 with `decline_code` `TERMINAL_ERROR` on the faulty Terminal. Settlements normal. Answer first (restart hint); a replacement request, or "still broken after restart", should escalate.
- `cliente2077` (Ateliê Linha & Agulha, Florianópolis) → quiet Merchant. One Terminal (online), three transactions in total (Pix R$ 60,00 three days ago; two debits yesterday, R$ 45,00 and R$ 50,00), two Settlements (Pix R$ 59,70 paid; debit R$ 93,70 scheduled today). No sales today.
- `cliente1988` / `cliente2024` byte-identical: `tests/test_merchants_fixture.py` hashes each entry's raw source text (located with `JSONDecoder.raw_decode`), so reformatting or reordering their fields fails too. The same file checks the new Merchants resolve through `load_merchants` (shape, net = gross - fee, Terminal serials, no leftover offsets) and their path facts. `evals/scenarios.json` untouched.
- Left out: README demo-user list (user rule), live check (ticket 06). `/dev/users` (ticket 01) lists fixture Merchants, so the new ones show up there without code changes.
