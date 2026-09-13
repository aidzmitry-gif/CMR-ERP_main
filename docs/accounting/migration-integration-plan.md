# Accounting migration integration proposal

Status: SEND application and revision 0120 integrated in the accounting agent branch; counterparty application and revisions 0117–0119 are also integrated; ESCHF application and revision 0121 are integrated; accounting registration remains pending. Not deployed or production-ready.

The separate worktrees currently branch from different parents. Proposed combined order:

`0116 -> 0120 (mail) -> 0117 -> 0118 -> 0119 (counterparties) -> 0121 (ESCHF) -> accounting`

Keep 0120 based on 0116 as in SEND PR 55. In a combined integration branch, change 0117 parent from 0116 to 0120 and 0121 parent from 0118 to 0119. The accounting revision remains unallocated; do not deploy the graph-only placeholder.

## Frozen inputs inspected on 2026-09-13

| Revision | Source checkout commit | Migration file SHA-256 | Proposed parent |
| --- | --- | --- | --- |
| 0120 | `62cfcdc6fbf6a59a268482e778b5994c6baa0dc5` | `02335dfeacc24bc1194f325c4b0d856a70c7256ca40449186dbafaa796def1ae` | 0116 |
| 0117 | `58e6808e7c6088f87cceb22080e7ae30a830eb98` | `f1200becbbc77c1942b83377d60dd85f3be372f44557e650f90cc978c3f0c40b` | 0120 |
| 0118 | `58e6808e7c6088f87cceb22080e7ae30a830eb98` | `aaf2232fbc6ea27f2c31e3ae335055ff4e9711fdb82fff0fd941ffb46d5fb8d9` | 0117 |
| 0119 | `58e6808e7c6088f87cceb22080e7ae30a830eb98` | `769833d5e35eb60ac5c21b224e2839f5ca8caf976584ccbaaf8cefb7e591a4a7` | 0118 |
| 0121 | `05d53eef9c66306a7bf2b1879b08d2aa0d22f6a9` | `c05b79f3c475a2b36cf51792d4234a8e9c0a8c1027f7ab1fc8091f2010573d5a` | 0119 |

## Observed compatibility

- Registered baseline 0116 upgraded successfully in a newly created, owned local PostgreSQL database.
- The five frozen upstream upgrades above were applied in the proposed order, then the accounting SQL proposal. All succeeded; 51 accounting tables exist; an existing synthetic logistics import shipment was unchanged.
- The owned database was dropped after the check. No shared or production database was migrated.
- A separate temporary Alembic version tree containing the same baseline and proposed parent changes has exactly one head and 122 revisions including a graph-only accounting node.

The runtime probe invokes each upgrade through Alembic Operations directly. Its alembic_version remains 0116; it does **not** prove that a registered combined chain has been upgraded. The graph check proves topology separately, not runtime migration execution.

Local evidence: `reports/CRM-ACC-001/acc_install_d37b6fe404bc475cae7221e86a85b429/result.json`, `upstream-migration-compatibility-inputs.json`, and `proposed-version-graph-result.json` in the accounting integration worktree.

## Remaining release work

1. SEND application changes are integrated from root `62cfcdc6` / sales `a5562b4`, preserving accounting routes and proxy cache headers. Counterparty identities are integrated at the checkpoint below; ESCHF application changes are integrated at the checkpoint below; SQL compatibility alone does not prove API/model compatibility.
2. Reconcile shared revision reservations against the final upstream branches; recheck source hashes if any migration changes.
3. Register the accounting revision after the final shared chain and apply the **registered** chain on an isolated PostgreSQL database; verify one head and the resulting alembic_version.
4. Review correction/downgrade behavior and test a backup/restore of the final registered schema before production authorization.

No already-applied migration may be reparented on an existing deployment without first inspecting its actual revision history. This document proposes integration of currently separate branches, not rewriting deployed history.

## SEND integration checkpoint (2026-09-13)

The agent branch now registers the unchanged SEND migration 0120 after 0116; `alembic heads` reports only 0120. Mail intake, scoped routing, attachments, reply snapshots, queue tooling and the `/crm/mail` interface are integrated. No live mailbox worker or outgoing transport was enabled.

Acceptance: 132 selected backend tests passed, one skipped and two subtests passed; 18 frontend tests passed; TypeScript, targeted ESLint and Ruff passed. The actual Next page was inspected with an incoming synthetic request and blocked external requests. These checks do not prove a registered PostgreSQL upgrade or live mailbox delivery. The PostgreSQL routing suite is included for CI.

Next: integrate the remaining ESCHF application package, preserve the agreed chain, then register and verify the accounting revision.

## Counterparty integration checkpoint (2026-09-13)

Integrated root `58e6808e` / sales `6de335c4`: stable legal-entity and branch IDs, explicit branch import, contact scope, immutable document party snapshots and reference UI. In this isolated branch only, 0117 follows registered SEND 0120; 0118 and 0119 retain their upstream parents. One Alembic head is 0119. No deployed migration history was changed.

The integration keeps the accounting deal lock and lost-stage coordinator. Additional cross-module checks reject a generic party change or binding preview that disagrees with an existing confirmed buyer. Invoice preview rejects mismatched buyer/branch IDs and captures the legal name and branch facts in the original; later reference edits do not rewrite the original. Legacy deals with no CRM ID still require the existing explicit accounting binding.

52 frontend checks, typecheck and targeted lint passed. Backend branch/reference and invoice acceptance were exercised locally; a focused integration scenario confirms the buyer conflict and frozen invoice branch snapshot. The actual branch form was inspected using synthetic data, preserving the `0001` portal code. PostgreSQL registered-chain execution and concurrency acceptance remain to verify. No production migration or external filing occurred.

Remaining application prerequisite: ESCHF. The frozen accounting SQL proposal still needs registration after the combined chain and verification of a fresh registered PostgreSQL upgrade and recovery.

## ESCHF integration checkpoint (2026-09-13)

Integrated the ESCHF-only package from `05d53eef` without importing its older counterparty files. Revision 0121 follows 0119 in this isolated branch; `alembic heads` reports only 0121. The module declares local API roles but installs no transport, source provider, signer or background worker. The deployable requirements include the pinned lxml range used by offline XML validation.

ERP invoice issuance now captures the same explicit `party` projection consumed by ESCHF. The source reader additionally requires organization membership and validates the immutable ERP issuance receipt. The actual issue-to-source-reader API scenario passed, including rejection without organization access and rejection after party revision changes. Legacy issued originals are not rewritten.

Offline preparation/adapter and packaging checks were run. Exact-hash native artifacts retain their upstream LF bytes and the official XSD retains its original bytes. A generated synthetic unsigned candidate passed pinned XSD validation (`unsigned_xml_sha256=98f8d3a7be5014415f42a9a457b89560f9ff4605b5cb4b8bf7e8dbb96ae14375`). This is no proof of signing, portal acceptance or live delivery.

Next: execute the registered 0116→0120→0117→0118→0119→0121 chain in an isolated PostgreSQL database, allocate and register accounting after it, and verify final recovery. ESCHF PostgreSQL suites still require their explicitly guarded dedicated database.
