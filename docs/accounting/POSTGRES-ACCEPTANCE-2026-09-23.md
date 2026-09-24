# Local PostgreSQL acceptance checkpoint — 2026-09-23

## New local G07 check — 2026-09-24

Source head `0174` on an isolated PostgreSQL 18.4 container: five focused
reconciliation/queue tests passed, including two concurrent writers for one
immutable issue. The test fixture replayed the explicit migration tail through
`0174`; this revision admits the `erp_snapshot_mismatch` blocker without
weakening the existing difference-count and immutable-history guards. A
separate disposable recovery rehearsal upgraded a fresh database to `0174`,
checked `0173 → 0172 → 0174` for the work-schedule constraint, checked
`0174 → 0173 → 0174` for the reconciliation guard, and restored a synthetic
database receipt with its private file. Database-only restore and modified
file bytes were rejected. Generated databases, container and scratch files
were removed. None of this inspects the target database or proves that the
left-hand OSV was exported from 1C.

This checkpoint used a dedicated, disposable `postgres:18.4-alpine` container
bound only to a loopback port. It did not connect to a running ERP, production
database or user data. Source branch: `agent/crm-acc-prod009`; source Alembic
head: `0172`.

## Executed checks

- `python -m pytest tests/accounting/test_postgres.py -k payroll -q`:
  **2 passed** on fresh per-test PostgreSQL databases. The close-guard fixture
  now opens a period before attempting closure with the required evidence and
  closed-generation value. The partial-coverage fixture creates a real
  source-bound payroll import through `prepare_payroll_accrual` and
  `confirm_payroll_accrual`, then confirms that the database blocks closing for
  an uncovered known binding. The stored individual-zero source moves the
  scenario to the separate population-review guard. The initial obsolete
  fixtures failed earlier guards; no database guard was relaxed.
- `python -m pytest tests/accounting/test_payroll_import_postgres.py
  tests/accounting/test_payroll_statutory_postgres.py -q`: **4 passed**.
  These cover the gross and statutory-import PostgreSQL paths independently.
- `python -m pytest tests/accounting/test_payroll_evidence_files.py -q`:
  **3 passed**. One private test file is backed up, altered (download refused),
  restored from the backed-up bytes, then downloaded against the original
  receipt. This checks file-byte recovery with retained metadata, not a full
  database-and-file-store disaster recovery procedure.
- `python -m alembic upgrade head` with `AIOS_ENVIRONMENT=dev` and an isolated
  empty `accounting_migration` database: **PASS**, linear upgrade through
  `0172`. A custom-format `pg_dump` of that database was restored with
  `pg_restore --exit-on-error` into a separate empty `accounting_restore`
  database: **PASS**. Both report Alembic `0172`, **69** accounting-schema
  tables and **252** non-internal accounting-schema triggers. The restored
  database also contains `payroll_workpaper_review`, `payroll_evidence_file`
  and `guard_payroll_statutory_binding_close()`.
- Test dump: **1,740,221 bytes**, SHA-256
  `e8f31835023abcd1f467f1cf8c83078ba21f2c83db39feaa733dcfb7bca20d52`.
  The dump and both databases existed only inside the disposable container.

The PostgreSQL fixture replays the frozen accounting proposal and explicitly
registered migration tail into a new per-test database. The separate Alembic
run covers the complete source migration chain on an empty database. Together
they prove these local paths, but they do not prove an upgrade from the
server's actual schema and data, a target backup/restore, private-file-store
recovery alongside the database, legal payroll correctness, or accountant
acceptance. G06C, G07 and the real pilot remain open.

## Paired database and private-file recovery — 2026-09-24

The local `scripts/accounting_recovery_rehearsal.py` now creates one synthetic
`payroll_policy` file through the real accounting evidence service in its own
generated organization and PostgreSQL database. It copies the private file tree
and dumps that database, then restores the database into a second generated
database and the file tree into a separate temporary directory. No existing
ERP database, document or file-store path is used.

Fresh execution with an already-local `postgres:18.4-alpine` image identified
by SHA-256 image ID passed at source head `0172`: one reconciliation receipt and
one payroll-file receipt survived. Against the restored receipt, database-only
recovery rejected the missing file, paired recovery verified the original
bytes and SHA-256, tampering was rejected, and copying the backed-up file back
restored access. Ruff, Python compile, CLI help and diff check passed. An
independent `docker ps -a` check found no generated recovery container; the
temporary scratch directory was absent after cleanup.

This proves one synthetic, quiescent paired restore on disposable local
resources. A live backup still needs an application-consistent snapshot of the
entire database and private file store, actual target data, access and restore
procedures, and a separate accountant acceptance; this run does not establish
production recovery or payroll correctness.

## Work-schedule file migration — 2026-09-24

`python scripts/accounting_recovery_rehearsal.py --image 9a8afca54e78
--check-work-schedule-migration` passed on a newly generated local PostgreSQL
18.4 container and databases. The runner upgraded to source head `0173`,
verified that both `payroll_evidence_kind` and `payroll_evidence_subject`
contain `work_schedule`, downgraded to `0172` and verified its absence, then
reapplied `0173` and verified its presence again. Its paired database/private
file recovery checks also passed at `0173`; the runner reported removal of
both generated databases, the generated container and its scratch file tree.
The local API test separately stores a synthetic schedule receipt scoped to
one employer binding and month, rejects a missing binding, wrong month, wrong
file kind and changed bytes. The local run does not cover the target schema,
real schedules or accountant approval of the stated norm.

## Employer rule-review migration and paired recovery — 2026-09-24

Source head `0176` was exercised on a disposable PostgreSQL `18.4-alpine`
container. `python -m pytest tests/accounting/test_postgres.py::test_payroll_organization_review_postgres_guards -q`
passed (1/1): a valid organization/month review inserted, while an incorrect
source, missing decision and attempted mutation were rejected by database
guards. `python scripts/accounting_recovery_rehearsal.py --image
postgres:18.4-alpine` passed after full Alembic upgrade to `0176`: one
synthetic organization-rule review and its private file were restored together
with the database. Database-only restore and changed restored bytes were
rejected; paired intact bytes were accepted. The runner removed generated
databases, container and scratch files. This is local synthetic evidence, not
a target-database upgrade, recovery of real records, legal-rule verification,
or accountant acceptance.
