# CRM-ACC-FIN-CASHFLOW-003 — ledger DDS contract

Baseline: integration commit `9c2c1641ea5c77222bf4d6ca4b63f2a108f2846a`.

## Boundary

This packet derives actual DDS only from immutable accounting `Entry`/`Line` rows in
`modules/accounting/reports.py::report`.  It does not change the legacy
`modules/finance/cashflow_dds.py` report, database schema, routes, or any profit/cash
engine. `frontend/src/components/erp/finance-view.tsx` remains owned by Luna and must
not be changed. A standalone component is mount-ready only; integration is pending.

## Source facts

`report()` already uses `Entry.posting_date`, treats a row as opening when it predates
the selected `start` (or is an opening row through `start`), and accumulates cash
`debit` as positive and cash `credit` as negative.  A bank settlement in
`modules/accounting/documents.py::BankDocument.posting()` emits the cash bank line with
explicit activity and is `debit` for receipt / `credit` for payment.  It is ledger
fact; legacy `Payment.created_at/status` is not.

An internal transfer is excluded from external DDS only when a ledger cash line has
the explicit `cash_activity == "internal"`. Never infer it by netting debit/credit
lines within an Entry. Current FX revaluation policy explicitly rejects cash accounts,
so cash-FX valuation is not a supported scenario and must not be claimed or guessed.

## Additive report fields

Leave the existing `cashflow` object unchanged. `not before` is not sufficient to
identify an ordinary period movement: an `Entry.opening` may have a posting date inside
an arbitrarily selected range. Add two fields calculated in the existing report loop:

- `cash_movements`: exact source-backed rows with `entry_id`, `source`, `date`,
  `account`, `title`, `line_id`, `currency`, `side`, `amount`, `dimensions`, and
  `cash_activity` (nullable), selected only when `not before and not entry.opening`.
  Opening rows never appear here or in any gross inflow/outflow.
- `cashflow_ledger`: backend Decimal-string summary:
  `opening`, `external_inflow`, `external_outflow`, `external_net`, `internal_net`,
  `internal_count`, `unclassified_inflow`, `unclassified_outflow`, `unclassified_net`,
  `unclassified_count`, `opening_adjustment`, `opening_adjustment_count`, `closing`,
  plus `activities` for `operating`, `investing`, and `financing`, each with `inflow`,
  `outflow`, and `net`.

`inflow` is the sum of positive signed cash lines, `outflow` is the positive absolute
sum of negative signed cash lines, and each `net` retains ledger sign. Only the three
named activities contribute to external totals and activity buckets; `internal` and
missing/unknown activity remain separate. The required reconciliation is:

`opening + external_net + internal_net + unclassified_net + opening_adjustment == closing`.

`unclassified_count` is a review condition even where its net is zero (for example,
`+100` and `-100`). A non-zero `internal_net` is also review-visible, not hidden or
auto-corrected. `opening_adjustment_count` is always review-visible: it signals an
opening ledger entry whose posting date is inside the selected period, so the displayed
reconciliation stays honest without calling it an external cash flow.

## UI and tests

Create only `frontend/src/components/erp/finance-ledger-cashflow.tsx` and its test.
It follows the accepted P&L component pattern: explicit accessible organization
selection, draft dates applied by the user, stale-response protection, status/review,
source-row drilldown through the existing entry-detail API, and CSV from the displayed
snapshot. Render summary values returned by the backend; do not reproduce ledger
aggregation in JavaScript. Display external gross receipts/payments, net, opening and
closing, activity buckets, unresolved count/gross/rows, and a review for non-zero
internal net. No default organization or finance-view mount.

One bounded backend scenario covers a receipt, payment, explicit internal movement,
an unclassified cash row, and an in-period opening row; it proves opening rows are not
gross inflow, the exact summary/reconciliation, and review behaviour for unclassified
count even at zero net.
The UI test covers the displayed snapshot, access/error, stale responses, drilldown,
and matching escaped CSV. No full suite is required.

Run targeted backend and component tests, TypeScript checking, and a filled synthetic
render. Do not commit before acceptance; do not push or deploy.
