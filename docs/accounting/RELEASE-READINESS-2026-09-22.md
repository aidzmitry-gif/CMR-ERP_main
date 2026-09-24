# Accounting release readiness — source snapshot 2026-09-22

Current isolated source head is `0174`. A local synthetic PostgreSQL 18.4
rehearsal checked both `0173 → 0172 → 0174` for the work-schedule file
constraints and `0174 → 0173 → 0174` for the reconciliation issue blocker.
The same run completed paired database/private-file recovery and verified
cleanup of its generated resources. Five PostgreSQL reconciliation/queue
tests passed, including a concurrent write. New reconciliation acceptance
checks the uploaded right-hand OSV against current ERP ledger bytes; legacy
receipts without that proof are not cutover-ready. This is local source and
schema evidence, not a target-database or deployment receipt.

One accepted OSV pair is now labelled `reconciliation_ready` only. The API's
top-level `cutover_ready` remains false for new and replayed receipts until
the independent external-source, two-month, quarter/year, recovery and release
gates are evidenced. The source HR gitlink `f8a6e014` exists in the local HR
repository but failed an exact fetch from its declared GitHub remote and was
absent from all advertised heads and tags in the 2026-09-24 read-only check.
The full gitlink audit below identifies five more such objects.

Current local synthetic PostgreSQL upgrade/restore and payroll-guard evidence
for source head `0172` is recorded in
[POSTGRES-ACCEPTANCE-2026-09-23.md](POSTGRES-ACCEPTANCE-2026-09-23.md).
The revision table below is the 2026-09-22 source snapshot; its earlier
"PostgreSQL unverified" statements do not describe the newer local test run.
Neither checkpoint verifies the target database or authorizes deployment.

This is a release-control record for the isolated accounting source branch.
It makes no deployment request and does not certify an installed database,
statutory reporting, ESCHF delivery, or replacement of 1C.

The requirement-by-requirement source evidence and the remaining acceptance
conditions are maintained in [ACCEPTANCE-MATRIX.md](ACCEPTANCE-MATRIX.md).

## Local candidate update — 2026-09-23

- The isolated source branch is `agent/crm-acc-prod009`. The source migration graph
  now reports a single `0165` head. This is a newer local snapshot than the
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
- Accounting revision `0165` prevents a new dated employment binding from
  changing a closed month or later closed history. Replays of an earlier accepted
  request remain readable. Local API checks pass; its PostgreSQL migration and
  direct-SQL trigger scenario still await an owned PostgreSQL instance.
- The local pilot preflight now requires `belarus-pilot-input-v6`: a declared
  source owner for every section, either an external payroll register or a
  separate zero-accrual control file, and an ERP book ID matching both OSV files.
  The left OSV must declare an external export; the right must declare an ERP
  control export from a different named system. The opening package's source
  digest must match an attached original-export file byte for byte. Earlier
  v2–v5 manifests cannot be treated as complete pilot input. The
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
- `py -3 -m alembic heads` reports one **source** head: `0165`.
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
linear through `0165`:

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
| `0165` | Closed-period guard for new dated payroll employment bindings | Local API and SQLite tests pass; direct PostgreSQL trigger scenario is registered but unexecuted. |

The command above validates migration topology only.  It neither connects to a
database nor substitutes for an upgrade, rollback, restore, or concurrent
PostgreSQL acceptance of the complete `0133`–`0165` range.  In particular,
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

## Integration comparison — 2026-09-24

The isolated source `agent/crm-acc-prod009` is at `9dd63c4b622888d941202e457103177ea35a13a4`; the older local integration checkout `agent/crm-acc-integration-001` is at `6780c1b44c64f0123886d19f44d2a72badb917dc`. Their merge base is `e83deecc08ab8666fbfbf0cd8ef279392d31cf1c`. Neither checkout was modified by this comparison.

- `git rev-list --left-right --count integration...source` reports 112 integration-only commit identities and 194 source-only identities. `git cherry source integration` marks all 112 integration commits as patch-equivalent to commits in source (zero unmatched integration patches); the reverse check marks 112 source commits as equivalent and 82 as additional patches. This is evidence against copying the older integration branch into source. Patch equivalence does not prove that the final trees, runtime behavior or release package match.
- `alembic heads` reports one head in each checkout: `0158` in integration and `0174` in source. A deployment must inspect the target database history and rehearse the complete candidate transition on its owned copy. Neither local head is evidence of the target's installed revision.
- Source records `modules/hr` at `f8a6e0142f1920b07ec56818f42d156a602ff9c3`. That object exists in the local HR repository under `agent/crm-acc-hr-safety-001`; its configured `origin` is another local repository, while the parent `.gitmodules` declares `https://github.com/aidzmitry-gif/HR-10.git`. The separate parallel HR checkout does not contain the object. The exact remote audit below now confirms that this and five other gitlinks are unavailable from their declared GitHub remotes. Do not substitute materialized local directories for a clean checkout.
- The source worktree has an unrelated untracked `reports/CRM-ACC-001/` directory and the integration checkout has an untracked coordination file; both were left untouched. No merge, push, target inspection, package build or deployment occurred.

The next release candidate should be assembled from the reviewed source commit and exact fetchable submodule commits, then tested against the actual target baseline by the migration-plus-frontend route in `ops/belakb-deploy/START-HERE.md`. The current v1 backend-only runner is not a path for this change. Real policies, opening balances, primary documents and accountant closes remain independent acceptance gates.

## Declared GitHub gitlink audit — 2026-09-24

Source `198d89982bd24b95b7fe6d5d5f241a87cfe990da` pins ten submodule commits. Each `.gitmodules` URL was checked in a new temporary bare repository with a direct, depth-one fetch of the exact SHA. Four commits loaded as Git commits. For every failed direct fetch, all advertised heads and tags were fetched without the depth limit; the pinned object was absent from that published history. A search of every published commit tree also found no byte-identical tree for any of the six missing objects. The probes were removed after validation.

| Module | Pinned SHA | Declared remote result |
| --- | --- | --- |
| finance | `59832b2f14a2ee02d8db266a67f8206616bdcd94` | Exact fetch failed; absent from heads/tags; no identical tree |
| hr | `f8a6e0142f1920b07ec56818f42d156a602ff9c3` | Exact fetch failed; absent from heads/tags; no identical tree |
| leads | `9a304f771ba74369ded199168e0e1da3ad6348d2` | Exact fetch failed; absent from heads/tags; no identical tree |
| logistics | `6923d2e021980ef2546f382364d38dc34a0fef29` | Exact fetch succeeded |
| marketing | `d4ed67fdc9b41e7abc370112e1a3fa8a3fe1e282` | Exact fetch succeeded |
| procurement | `c2483d60b4bc22526cd8e2694053fd9eddfdc273` | Exact fetch succeeded |
| production | `be7d7e198bf09cc41c642d22125db401da5adc48` | Exact fetch failed; absent from heads/tags; no identical tree |
| sales | `326b02034df21d137c2c9edf1bee3f9ae0682901` | Exact fetch failed; absent from heads/tags; no identical tree |
| service | `3d33800c44865cd7a7373b29192c5d59d3c4bec8` | Exact fetch succeeded |
| wms | `c84ec34592fc984f9421ae264d406d9a258c6df9` | Exact fetch failed; absent from heads/tags; no identical tree |

This is a concrete clean-checkout blocker for the exact source commit, not a reason to change the pinned code silently. Publishing the six exact submodule commits or deliberately integrating reviewed equivalent code into fetchable commits is required before packaging. Neither happened in this audit. The test says nothing about a production image, target schema, accountant reconciliation or permission to retire 1C.
