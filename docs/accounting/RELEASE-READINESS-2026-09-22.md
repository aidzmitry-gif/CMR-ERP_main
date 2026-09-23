# Accounting release readiness — source snapshot 2026-09-22

This is a release-control record for the isolated accounting source branch.
It makes no deployment request and does not certify an installed database,
statutory reporting, ESCHF delivery, or replacement of 1C.

The requirement-by-requirement source evidence and the remaining acceptance
conditions are maintained in [ACCEPTANCE-MATRIX.md](ACCEPTANCE-MATRIX.md).

## Local candidate update — 2026-09-23

- The isolated source branch is `agent/crm-acc-prod009`. The source migration graph
  now reports a single `0164` head. This is a newer local snapshot than the
  historical capture below; no target database was inspected.
- This source commit records `modules/hr` at
  `f8a6e0142f1920b07ec56818f42d156a602ff9c3`. It combines the isolated
  HR safety worktree with the separately committed CRM-PAY-NET-001 draft.
  Its configured Git
  remote is a local repository, while `.gitmodules` names the GitHub HR
  repository. No publication of this HR commit or the parent source commit was
  performed in this task. Before packaging a reproducible release, verify that
  every recorded submodule commit is fetchable from its declared release
  remote, then pin and build the exact parent/submodule pair.
- The HR change bounds manual amount/period input and selects the exact
  accrual for a payment marker. It also adds read-only, source-described
  scenario previews and employee handouts. It does not provide accepted
  statutory payroll calculation, legal-entity ownership for legacy HR rows or
  bank-payment evidence. Other changes from the parallel accountant
  reports/navigation task remain outside this snapshot until reviewed.
- Accounting revision `0161` records an explicit dated employee/contract to
  legal-entity binding before its one-component payroll preview. Legacy HR
  employees remain unmapped; this does not verify the contract, calculate a
  complete payroll run or certify statutory amounts. Its PostgreSQL migration
  has not been executed in this record because the local Docker engine is
  unavailable.
- Accounting revision `0162` adds an immutable organization payroll arithmetic
  rule set. A chief accountant must explicitly configure the gross method,
  rounding and every rate code's role/base mode before the workpaper can run.
  Its declared source hash is not a verification of the policy document. The
  PostgreSQL migration remains unexecuted in this record.
- Accounting revision `0163` adds organization-scoped, append-only receipts for
  private payroll source files. The preview can verify the selected contract
  and timesheet bytes, scope and declared hashes; a rule-set revision may also
  select a policy source file and recheck it before each preview. This does not verify their
  contents, rule applicability or statutory salary. `AIOS_PAYROLL_DATA_DIR`
  must be privately provisioned and backed up together with the database;
  target storage, restore and PostgreSQL migration remain unverified.
- Accounting revision `0164` adds append-only chief reviews of source-backed
  payroll arithmetic. Corrections append a linked revision and closed periods
  reject new reviews. Receipts do not post or certify statutory payroll;
  PostgreSQL trigger and migration acceptance remain unverified.
- The local pilot preflight now requires `belarus-pilot-input-v5`: a declared
  source owner for every section, either an external payroll register or a
  separate zero-accrual control file, and an ERP book ID matching both OSV files.
  The left OSV must declare an external export; the right must declare an ERP
  control export from a different named system. Earlier v2–v4 manifests cannot
  be treated as complete pilot input. The
  preflight checks file identity and declarations, not the external-ID-to-book
  mapping, authentic provenance, payroll figures, actual operational ownership
  or accountant acceptance.
- The source also pins `modules/production` at `be7d7e198bf09cc41c642d22125db401da5adc48`.
  This commit was created in the isolated production-module worktree; its
  configured remote is a local repository while `.gitmodules` declares
  `https://github.com/aidzmitry-gif/PRO-4.git`. Fetchability from that declared
  release remote is unverified. Its payroll and premium outputs are now
  identified as production planning estimates, not accounting payroll.

## Observed source state

- Application-source revision at capture (before this control-record commit):
  `1d963d8fbcfa3d8f8b646318ee0748b24b9c6b1f`
  (`agent/crm-acc-prod009`).
- `py -3 -m alembic heads` reports one **source** head: `0164`.
- The accounting module is enabled in
  [`config/modules.py`](../../config/modules.py), and the source UI contains
  the `Бухгалтерия` sidebar entry and `/erp/accounting` page.  This proves the
  feature is present in the source candidate only; it does not prove that the
  running site has this revision.
- This branch still has no evidence of merge to the production baseline, target
  database revision, release receipt, backup/recovery drill on the target, or
  accountant acceptance of a real close.

## Current migration graph

The prior historical checkpoint through `0132` remains documented in
[migration-integration-plan.md](migration-integration-plan.md).  The live
source graph has since been joined by `0133` (parents `0129` and `0132`) and is
linear through `0164`:

| Revisions | Subject | Evidence boundary |
| --- | --- | --- |
| `0134`–`0137` | Bank source completeness, provenance, duplicate identity and account mapping | Source graph only in this record; see the bank pilot documents for their scoped local PostgreSQL evidence. |
| `0138`–`0139` | Finished-goods transfer and immutable output-cost revision | Local synthetic acceptance is described in [production-output-cost-revisions.md](production-output-cost-revisions.md). |
| `0140`–`0150` | Entryless zero-value inventory, sales and WMS material allocations | The narrow supported cases and exclusions are documented in [zero-value-disposals.md](zero-value-disposals.md). |
| `0151`–`0155` | Late material costs and immutable full-pool / inventory-value evidence | Source graph only here; V1/V2 history remains additive and unchanged. |
| `0156` | Expense-article attribution of posted lines | The analytical-receipt contract is in [EXPENSE-ARTICLE-ATTRIBUTION-CONTRACT.md](EXPENSE-ARTICLE-ATTRIBUTION-CONTRACT.md). |
| `0157`–`0158` | Statutory requirement catalog and per-organization chart-catalog adoption | A source model only until current official rules and accountant adoption are verified. |
| `0159` | TN/TTN scenarios in versioned accounting policy | Requires organization policy and primary-document acceptance. |
| `0160` | Immutable OSV reconciliation issue queue and unmatched rows | Source graph only in this record; it must be exercised against a real reconciliation package before use for cutover. |
| `0161` | Explicit, immutable HR employee/contract to legal-entity binding for payroll previews | Local API and SQLite tests only; PostgreSQL migration and real employer documents remain unverified. |
| `0162` | Immutable organization payroll arithmetic rule set | Local API and SQLite tests only; official rule applicability and PostgreSQL migration remain unverified. |
| `0163` | Immutable payroll source-file receipts and private file store | Local API and SQLite tests only; target filesystem, backup/restore and PostgreSQL migration remain unverified. |
| `0164` | Linked immutable reviews of source-backed payroll arithmetic | Local API and SQLite tests only; PostgreSQL trigger and real accountant controls remain unverified. |

The command above validates migration topology only.  It neither connects to a
database nor substitutes for an upgrade, rollback, restore, or concurrent
PostgreSQL acceptance of the complete `0133`–`0164` range.  In particular,
`alembic upgrade head --sql` is not a release check for this repository: legacy
revision `0062` performs a data lookup that requires an online PostgreSQL
connection.  The schema candidate must therefore be exercised on an owned
PostgreSQL database, not accepted from generated offline SQL.

## Why the accountant page may be absent on the running site

The source candidate has the route, but a release of this range includes
frontend code, enabled-module configuration and schema migrations.  It cannot
be treated as an unchanged-backend package.  No release receipt ties the
currently running `belakb.by` build or its database to this source revision.
Consequently, source navigation is not evidence that a user can open
`/erp/accounting` on the server.

## Required gates before a release decision

1. Reconcile this isolated branch with the current integration/production
   baseline and inspect the target database's actual Alembic history.  Do not
   rewrite applied migration history.
2. Use a release path that explicitly supports frontend, configuration and
   schema changes; record the candidate SHA, check result and final receipt.
3. Verify a target-specific backup and restoration procedure before any schema
   change.  Local synthetic restores are insufficient.
4. Upgrade an owned copy of the target schema through the candidate range and
   run the required PostgreSQL concurrency, replay and period-close checks.
5. Supply the real policy, opening balances, primary documents and matching
   OSV package; then have the accountant accept a pilot close.  These are the
   gates for 1C replacement, not merely for code delivery.

Until these gates are evidenced, the source remains a locally verified
candidate and 1C remains the archive/reconciliation source for historical data.
