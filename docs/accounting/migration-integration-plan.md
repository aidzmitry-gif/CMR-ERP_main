# Accounting migration integration

Status (2026-09-13): registered and locally verified through **0130** in the accounting agent branch. Not merged or deployed. Real accounting and statutory cutover acceptance remain open.

## Registered chain

`0116 → 0120 (SEND) → 0117 → 0118 → 0119 (counterparties) → 0121 (ESCHF) → 0130 (accounting)`

0130 was reserved under the existing shared migration lock after checking other Git worktrees: 0122–0129 are already used elsewhere. Their numbers are skipped here; their features are not claimed to be integrated. The single Alembic head is 0130. The isolated branch reparents 0117 to 0120 and 0121 to 0119; no deployed history was changed. Any future deployment must first inspect the target database revision history and reconcile the other branches.

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

1. Check full GitHub CI on the final integrated branch and finish unresolved application acceptance, including dedicated PostgreSQL ESCHF concurrency tests.
2. Inspect the actual target revision history and reconcile other reserved application migrations before deployment approval; do not rewrite already-applied history.
3. Obtain and reconcile real organization policies, account balances and primary documents; complete the required monthly, quarterly and annual acceptance cycles.
4. Verify the actual backup and recovery procedure in the intended deployment environment. A synthetic local restore does not prove production recovery.
5. Validate current statutory references, native bindings, signature and portal results before claiming ESCHF delivery or replacement of 1C.
