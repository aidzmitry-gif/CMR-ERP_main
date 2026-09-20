# Zero-value inventory disposals — foundation

This package persistently supports one deliberately narrow case: an immutable,
entryless `inventory_issue` for one already-authenticated production-output
layer whose selected **specific** valuation is exactly zero. Migration 0140
derives its evidence in PostgreSQL (source output, latest effective policy and
accounts, ordered ledger history, and prior same-layer receipts), then binds it
to a shared registration sequence. The Python and SQL digest envelopes are
checked to match in the PostgreSQL acceptance test.

It does not yet provide a route, UI confirmation, valuation replay, mixed-money
issue, weighted valuation, or sale binding. Those paths fail closed rather than
creating synthetic zero-money ledger entries.

## Invariants

- The command contains every source layer separately: source entry/line,
  account, full warehouse/SKU/lot identity and exact positive quantity. It
  never collapses mixed FIFO layers into one lot or scalar quantity.
- `source`, `source_version`, and `operation` form the identity, matching the
  existing entry uniqueness. Issue and sale are distinct operations.
- The digest is SHA-256 over canonical JSON of organization, actor and the full
  command; `basis_digest` remains present even though a layer has zero BYN.
- An entryless receipt is allowed only for `inventory_issue`. A sale keeps its
  real revenue/VAT entry and later binds the zero-cost receipt to that entry.
- Registration token is allocated from the entry sequence. It provides a stable
  cutoff order for entryless receipts without manufacturing a zero-money entry.

## Mandatory next stage

1. Extend `inventory_cost.py` and the SQL 0139 weighted/specific evidence paths
   to replay authenticated receipt layers chronologically by posting date,
   registration token and receipt id.
2. Integrate `inventory_issues.py` and sales separately: a zero issue can be
   entryless; a zero-COGS sale cannot be entryless because revenue/VAT remain.
3. Add PostgreSQL acceptance evidence for idempotency, conflict with a monetary
   issue, partial/full disposal, late cost and historical reconstruction.
4. Extend output-cost revision preview and UI with typed destination identities:
   a zero-value receipt is a `receipt_id`, never an `entry_id`/`line_id`. The
   current SQL key parser expects ledger ids and must not be enabled unchanged.

The current API/UI contract also assumes every preview has `posting.lines` and
every confirmation has a ledger `entry_id`: `routes.py` serializes the posted
entry, `accounting-inventory-issue.tsx` reads those lines and `entry_id`, and
`production_material_cost.py` expects `inventory_issues.confirm` to return an
entry. The integration stage must introduce an explicit discriminated receipt
result (`posted_entry` versus `quantity_only_receipt`), preserve existing money
responses, and never substitute a receipt id for an accounting entry id.
