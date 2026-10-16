# CRM-ACC-FIN-PNL-002 — standalone P&L component contract

Baseline: `57943460c6b2ae8d3a4b099733e56654648a1c21`.

## Boundary

This is a mount-ready, standalone accounting P&L component.  Its import and mount in
`frontend/src/components/erp/finance-view.tsx` remain explicitly pending the Luna
release; this packet must not modify that file.  It does not change an accounting
schema, routes, the existing report calculation, or introduce a profit engine.

## Report response extension

`modules/accounting/reports.py` adds `pnl_movements` without changing any current
response field or calculation.  It is populated in the same branch that accumulates
`pnl`: only lines where the entry is authenticated/non-technical, is not before the
selected period, is not an opening entry, and has category `income` or `expense`.

Each row is a source-backed ledger line with `entry_id`, `source`, `date`, `account`,
`title`, `line_id`, `currency`, `side`, `amount`, `dimensions`, and `category`.  The
component must not infer category from the chart of accounts or present the broad
`movements` field as a P&L breakdown.  A targeted backend test proves that a purchase
asset is absent, income and expense are present, a technical close is absent, and
category totals reconcile with the returned P&L values.

## Frontend contract

Create only:

- `frontend/src/components/erp/finance-ledger-pnl.tsx`
- `frontend/src/components/erp/finance-ledger-pnl.test.tsx`

The component fetches the member-scoped organization list from
`/api/accounting/organizations`, but never selects a default organization.  The user
selects an organization and applies draft start/end dates.  Only those applied filters
are used for `GET /api/accounting/organizations/{org}/reports?start={start}&end={end}`.
Late responses from an old organization or date request must not replace the current
display.  The UI renders income, expenses, and profit (not COGS or operating profit),
preliminary/closed-period status, review items, pending documents, and a drilldown
from exact `pnl_movements`.

Entry details may be requested only from the existing
`/api/accounting/organizations/{org}/entries/{entry_id}` API; do not invent navigation
or URL-query conventions.  CSV is generated from the currently displayed response and
the applied filters, preserves backend amount strings/precision, and escapes separator,
quotes, and newlines correctly.  It must not refetch or export the un-applied draft.

Tests cover a positive report, access/error response, no implicit organization,
stale organization/date responses, and CSV matching the displayed report.  A local,
untracked synthetic render harness may be used for visual verification.  Reuse existing
buttons, inputs, cards, and styling; no redesign is part of this packet.

## Acceptance and delivery

Run the targeted Python report test and the component Vitest file, TypeScript checking,
and a synthetic filled render.  Do not commit before acceptance; do not push or deploy.
