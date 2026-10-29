# Synthetic zero-sale histories

These five fixtures contain synthetic accounting records captured from root
`e3ffab79c3e1c233267a7373f97e1c2c62b3cf01` and the ten module commits listed in
each file. Its original five historical scenarios passed with unchanged
application code and assertions. The obsolete database bootstrap was replaced
with the current guarded fixture lifecycle and real Alembic registration at
0142,0143 and0148. No production records are included.

Each transaction records only inserted rows and the original generation changes.
`historical_zero_sale.py` replays them on a fresh database at the declared revision,
uses the native period lifecycle and database-assigned registration tokens, and
checks complete stored-row representations after every commit. Historical
sessions explicitly use Europe/Minsk for reproducible timestamp rendering even
when the connection default is UTC; the local setting ends with the transaction. JSON fields are
projected from the original raw record without reserialization. Financial guards
and immutable-history triggers remain enabled. The0142->0143 transition also
compares authenticated legacy issue receipts before and after the upgrade.

These fixtures test historical data admission and preservation. The two separate
current-schema scenarios execute the actual owned-output workflow, HTTP sale
preview, concurrent confirmation retries and late-cost allocation. Fixture replay
alone does not prove current application idempotency or production acceptance.

Run the historical matrix and legacy transition with the existing isolated
PostgreSQL test configuration:

```text
pytest tests/accounting/test_zero_value_sale_postgres.py::test_zero_sale_persists_revenue_and_quantity_once tests/accounting/test_zero_value_sale_postgres.py::test_0143_preserves_legacy_issue_history
```
