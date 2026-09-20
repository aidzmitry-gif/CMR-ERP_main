# Zero-value inventory disposals — foundation

This package persistently supports one deliberately narrow case: an immutable,
entryless `inventory_issue` for one already-authenticated production-output
layer whose selected **specific** valuation is exactly zero. Migration 0140
derives its evidence in PostgreSQL (source output, latest effective policy and
accounts, ordered ledger history, and prior same-layer receipts), then binds it
to a shared registration sequence. The Python and SQL digest envelopes are
checked to match in the PostgreSQL acceptance test.

It does not yet provide a route, UI confirmation, mixed-money
issue, weighted valuation, or sale binding. Those paths fail closed rather than
creating synthetic zero-money ledger entries.

Internal database-authenticated valuation replay is implemented. Migration 0141
adds specific-cost entryless issue destinations to output-cost revisions, with
typed receipt identities and independent SQL evidence validation. PostgreSQL
acceptance covers 2 units reduced to zero value, disposal of 0.5, late cost 100
allocated 75 to stock and 25 to the disposal destination, durable confirmation,
idempotent retry, another 100 allocated with cumulative values 150/50, and no
new postings for unchanged inputs. Historical registration cutoffs reproduce
the earlier evidence. Forged SQL previews and corrections of a closed period
are rejected. This is synthetic evidence, not a real monthly close.

The loader revalidates historical metadata and fails on a basis mismatch;
full version-evolution acceptance and public issue/sale integration remain open.

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

1. Extend weighted, FIFO and mixed-disposal SQL paths beyond the implemented
   single-origin specific-cost receipt, preserving chronological replay.
2. Integrate `inventory_issues.py` and sales separately: a zero issue can be
   entryless; a zero-COGS sale cannot be entryless because revenue/VAT remain.
3. Add PostgreSQL acceptance evidence for idempotency, conflict with a monetary
   issue, partial/full disposal, late cost and historical reconstruction.
4. Extend the UI to consume the typed destination identities now returned by
   output-cost revision preview: a zero-value receipt is a `receipt_id`, never
   an `entry_id`/`line_id`. Public enablement still requires UI verification.

The current API/UI contract also assumes every preview has `posting.lines` and
every confirmation has a ledger `entry_id`: `routes.py` serializes the posted
entry, `accounting-inventory-issue.tsx` reads those lines and `entry_id`, and
`production_material_cost.py` expects `inventory_issues.confirm` to return an
entry. The integration stage must introduce an explicit discriminated receipt
result (`posted_entry` versus `quantity_only_receipt`), preserve existing money
responses, and never substitute a receipt id for an accounting entry id.

## Accountant issue API (local implementation)
The existing inventory/issues/posting-preview and confirm routes support a zero-value receipt for a specific-cost lot with one authenticated production-output origin. Source ledger IDs are derived by the server. The UI receives quantity_only_receipt, posting:null and receipt.source_layer; confirmation uses cost.basis_digest and digest. Ordinary expense-account and production-workflow restrictions still apply. Receipt registration invalidates affected period evidence and records an audit event exactly once. Monetary entries keep their existing response contract.
PostgreSQL replay requires migration0140; public zero commands additionally require the0142 date guard (release all migrations0140–0142 together). Missing schema is an explicit error. Historical issue replay uses the shared registration cutoff. Local HTTP/PostgreSQL evidence covers concurrent duplicate confirmation, dates conflict, organization membership, insufficient quantity, first-lot selection, late costs, exhausted monetary retry and historical verification after subsequent costs. This does not certify weighted/FIFO zero disposal, zero-cost sales, mixed origins, production material zero issues, deployment or a real monthly close.
