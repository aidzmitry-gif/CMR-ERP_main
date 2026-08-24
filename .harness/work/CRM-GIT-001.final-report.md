# CRM-GIT-001 revision 1 — final local integration report

## Boundary

- Branch: `chore/cc-2119-revision`.
- Baseline: `683ec5e`; current integration range contains 35 root commits before this evidence commit.
- Performed: local inspection, exact-path/hunk staging, edits, tests, Docker-isolated acceptance, and local commits.
- Not performed: push, merge, deploy, production writes, real email, deletion, or movement of retained files.

## Accepted functional bundles

- Repository policy, migration allocator, integration RBAC, and 1C import guard.
- Historical migration `0087` plus a single Alembic head through `0107`.
- OIDC/PKCE proxy and session flow; Keycloak employee invitation by email, employee, department, and role.
- microchips.by website and inbound-email lead intake with token, source, UTM, deduplication, and persistence checks.
- Office payment linkage, finance claim semantics, safe bank intake, and Google Sheets gateway.
- Sales touch history, reverse lead planning, and exact parent gitlinks.
- Frontend interaction coverage and no-behavior lint cleanup.
- Marketing module contract, project plans, fleet records, Obsidian knowledge, and marketing UI prototype.
- OIDC smoke-script indentation repaired after the full Ruff gate exposed the defect.

## Integration matrix

- Backend affected-file matrix: 16 test files, 178 tests passed in 97.21 seconds.
- A redundant full-repository pytest was started, exceeded the project's 10-minute test budget, and was stopped after PID/command verification once the affected-file matrix was green; no service process was stopped.
- Frontend Vitest: 80 files, 934 tests passed.
- Frontend production build: passed; 119 static/dynamic routes generated.
- Frontend lint/typecheck: passed with 43 pre-existing non-blocking React warnings and zero errors.
- Python Ruff and py_compile: passed after the OIDC smoke repair.
- Alembic: exactly one head, `0107`.
- Docker Compose: `docker compose config -q` passed.
- Submodules: sales `aaf899c`, finance `ccc3c2c`, leads `a04feb0`, marketing `c40f0cf`, procurement `282339c`; every parent gitlink matches and all five inner worktrees are clean.
- Additional focused evidence: 97 lead-intake tests; 43 finance/integration tests; 30 identity tests; 23 sales/leads tests; 15 handoff-planning tests; 10 pricing-reference tests; isolated PostgreSQL, Keycloak 26, Mailpit, and one-time invitation-link acceptance passed.

## Preservation and classification

- Initial protected inventory: 1396 root/submodule status entries and 1391 files.
- Final classification ledger: 274 protected entries, all classified.
- Repository bundles: 189 non-Goal files tracked through atomic commits; Goal evidence is a separate final bundle.
- Local retention: 68 raw, private, runtime, backup, browser-snapshot, probe, and user-settings files remain byte-identical by size and SHA-256.
- Local hygiene: 448 exact reversible entries in `.git/info/exclude`; no project `.gitignore` change.
- Sensitive-data scan: 249 text files checked without printing values. Raw Riftek/customer contacts, phone-bearing browser snapshots, real ROP planning data, operational extracts, and local backups were retained locally and not committed.
- No working file was deleted or moved.

## Known non-blocking debt

- The successful frontend build reports 43 existing React hook/static-component warnings; they were outside the approved dirty-state decomposition and were not bulk-refactored.
- Historical Markdown records contain pre-existing trailing spaces used by some files for hard line breaks; they were preserved byte-for-byte.
- `coordination/STATUS.md` and `coordination/readiness.json` are explicitly a dated 2026-07-25 snapshot; the live scanner now observes migration head `0107`.

## Handoff

The branch is prepared locally for a later, separately authorized review/push/deploy step. Production secrets, SMTP configuration, DNS, Keycloak production realm changes, and microchips.by webhook activation remain outside this revision.
