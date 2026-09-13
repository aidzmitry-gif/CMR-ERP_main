# Accounting migration integration

Status (2026-09-13): registered and locally verified through **0132** in the accounting agent branch. Not merged or deployed. Real accounting and statutory cutover acceptance remain open.

## Registered chain

`0116 → 0120 (SEND) → 0117 → 0118 → 0119 (counterparties) → 0121 (ESCHF) → 0130 (accounting) → 0131 (reservation remainder) → 0132 (expense approval guard)`

0130 was reserved under the existing shared migration lock after checking other Git worktrees: 0122–0129 are already used elsewhere. Their numbers are skipped here; their features are not claimed to be integrated. The single Alembic head is 0132. The isolated branch reparents 0117 to 0120 and 0121 to 0119; no deployed history was changed. Any future deployment must first inspect the target database revision history and reconcile the other branches.

## Application integration

- SEND root `62cfcdc6` / sales `a5562b4`: incoming mail, assignment, attachments and replies. Accounting routes and proxy download/cache headers were preserved. No live mail worker was enabled.
- Counterparty root `58e6808e` / sales `6de335c4`: stable legal-entity/branch IDs, contact scope, import and immutable party snapshots. Generic party changes and accounting bindings cannot disagree with the confirmed invoice buyer.
- ESCHF package `05d53eef`: durable local preparation and offline adapter. ERP invoices freeze the required party projection; source loading requires organization membership, a valid issuance receipt and unchanged party facts. No signer, source provider, transport or background worker was enabled.

0130 contains the frozen SQL from the reviewed accounting proposal. It does not import mutable runtime models or read a working SQL file during upgrade. The historical proposal remains in `docs/accounting`; the executable migration is `migrations/versions/0130_accounting_ledger.py`. Automatic destructive downgrade is refused.

## Observed PostgreSQL acceptance

[Machine-readable result and migration hashes](acceptance/registered-0130.json).

On the dedicated loopback PostgreSQL instance, a new owned UUID database was upgraded through the registered chain to 0121. A synthetic existing logistics import shipment was inserted. An ordinary `alembic upgrade head` then recorded **0130** and preserved that shipment. All **51 accounting tables** were present.

A synthetic balanced accounting entry was posted, backed up and restored to a separate owned database. Verification matched **234 table contents, 366 triggers and 172 sequences**. The restored ledger contained two lines and rejected mutation of the entry. Owned test databases were removed with ownership-marker checks; no shared database was reset.

Local detailed evidence: `reports/CRM-ACC-001/acc_install_b2ad69b97ab647869278910ad697ba41/` contains the registered upgrade log and result. This replaces the earlier graph-only/Operations-only installation evidence; it is not a production restore drill.

## Remaining release gates

1. Check full GitHub CI on the final integrated branch and finish unresolved application acceptance, including the newly enabled PostgreSQL ESCHF concurrency tests in CI.
2. Inspect the actual target revision history and reconcile other reserved application migrations before deployment approval; do not rewrite already-applied history.
3. Obtain and reconcile real organization policies, account balances and primary documents; complete the required monthly, quarterly and annual acceptance cycles.
4. Verify the actual backup and recovery procedure in the intended deployment environment. A synthetic local restore does not prove production recovery.
5. Validate current statutory references, native bindings, signature and portal results before claiming ESCHF delivery or replacement of 1C.

## ESCHF PostgreSQL checkpoint

[Local PostgreSQL acceptance](acceptance/eschf-postgres.json): 79 repository/API checks and 89 source/freshness checks passed in two bounded batches. Source fixture setup was updated to include the real CRM stage/loss guards introduced by integration. No guard was disabled. Both dedicated ephemeral PostgreSQL containers were removed.

GitHub CI now provisions a separate ESCHF service matching the strict fixture address/database/user guard. These tests previously skipped without `ESCHF_TEST_DATABASE_URL`; the new CI run must confirm the integrated result. Synthetic adapters do not establish native signature validity, portal submission or statutory acceptance.

## Partial shipment remainder

0131 adds immutable WMS remainder-release receipts to the existing reservation ledger. It reuses reviewed WMS package b73c41b from the isolated reservation task; the duplicate pilot ledger and its 0122 migration are excluded. Neither 0130 nor already published migrations were rewritten.

The API releases only unshipped reserved quantities after a physical act. For physical stock 10, reservation 6 and shipment 2, releasing 4 leaves physical stock 8, reserved 0 and free 8. The invoice, financial status and shipment act remain unchanged. An explicit reason and current preview digest are required; replay uses the original UUID and body. Invoice cancellation remains separate.

Registered upgrade to 0131 passed on an owned temporary PostgreSQL database, preserving a pre-existing logistics shipment and all 51 accounting tables. This checkpoint has no new restore acceptance: the earlier 0130 restore proof remains scoped to 0130. The existing invoice shipment screen now offers a remainder preview, reason and explicit confirmation. A saved same-key request recovers an unknown response; a verified stale basis requires recalculation. Actual Next/FastAPI browser acceptance passed (invoice quantity 2, ship 1, release 1); this remains synthetic local acceptance, not deployment or real user acceptance.

## Expense approval guard correction

0132 replaces only the ambiguous JSON expression in `guard_expense_receipt`: extract `result` first, then remove `approval_digest`. Without parentheses, PostgreSQL could not select an operator and valid budget approval failed. Published 0130 and 0131 remain unchanged. Six expense PostgreSQL checks passed, including approval/replay, immutable budgets and receipt requirements. Registered upgrade to 0132 preserved a pre-existing logistics record; see [acceptance](acceptance/registered-0132.json). This does not extend the earlier restore drill beyond 0130.
