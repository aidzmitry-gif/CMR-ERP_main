# CRM-GIT-001 atomic bundle map

No bundle may use broad staging. Mixed files are staged by an exact cached patch and verified with `git diff --cached --name-only` plus `git diff --cached --check`.

| ID | Purpose | Exact source scope | Acceptance / commit dependency |
| --- | --- | --- | --- |
| B01 | Repository governance | `AGENTS.md` | diff review; documentation-only commit |
| B02 | Migration allocator safety | `scripts/next_migration.py`, `tests/unit/test_next_migration.py` | unit tests; `--peek` leaves no reservation |
| B03 | Integration RBAC | RBAC hunks of `modules/integrations/routes.py`, `tests/test_integrations_auth.py` | focused pytest; no bank hunk |
| B04 | OIDC proxy headers | `frontend/src/app/api/[...path]/route.ts`, `frontend/src/lib/access.ts`, `frontend/src/lib/api-proxy-headers.ts`, focused frontend test | forwarded Authorization wins; token fallback; dev role preserved |
| B05 | 1C reference import skip | `core/services/reference_import.py`, `tests/test_reference_import.py` | rows without UNP skipped and counted; idempotence tests pass |
| B06 | Finance claim contract | finance pointer temporarily at `a7de3ef`, claim hunks of `tests/test_finance.py` | claim focused tests, then parent gitlink commit |
| B07 | Bank intake | Alfa hunks of `config/settings.py`; bank hunks of `core/services/__init__.py`; `core/services/bank.py`; `modules/integrations/alfa.py`; `modules/integrations/module.py`; finance pointer `ccc3c2c`; `migrations/versions/0106_finance_bank_transaction.py`; `tests/test_finance_bank.py` | bank tests, migration test, exact parent gitlink |
| B08 | Google Sheets gateway | GSheets hunks of `config/settings.py` and `core/services/__init__.py`; `core/services/gsheets.py`; `pyproject.toml`; `requirements.txt` | dependency/import and fail-soft tests; no bank hunk |
| B09 | Office deal/payment link | `modules/office/CLAUDE.md`, `events.py`, `models.py`; `migrations/versions/0105_office_doc_deal_id.py`; office tests | targeted office tests and migration chain |
| B10 | Sales touch history | sales pointer `aaf899c`; `tests/test_sales_touch_history.py`; `tests/test_touch_history.py` | touch-history tests and exact gitlink |
| B11 | Leads reverse planning | leads pointer `a04feb0`; `tests/unit/test_leads_planning.py` | planning tests and exact gitlink |
| B12 | Marketing module contract | marketing pointer `c40f0cf` | documentation-only gitlink commit |
| B13 | Frontend behavior coverage | four modified frontend test files | focused Vitest suite; no production-code hunk |
| B14 | Frontend lint cleanup | `logistics-scorecard.tsx`, `catalog-picker-modal.tsx` | lint and typecheck |
| B15 | Historical migration 0087 | `migrations/versions/0087_leads_init.py` | hold until schema-history proof; never mix with 0105/0106 |
| B16 | Fleet/knowledge documents | retained visible coordination, Obsidian real-vault files, root docs/prototypes | secret/PII scan and explicit commit-or-local-retain classification |
| B17 | Goal evidence | `.harness/**` except local exclude backups if they reveal local configuration | validator, hashes, and final report |

## Required order

1. B01-B05 can be committed independently after their focused checks.
2. B06 is committed before B07 so the finance gitlink history remains atomic.
3. B09 migration `0105` precedes B07 migration `0106` in the Alembic chain, even if feature commits are otherwise independent.
4. B10-B12 contain submodule pointers only after the corresponding inner commits are verified.
5. B13-B14 follow their own frontend checks.
6. B15 remains held unless G05 produces direct proof.
7. B16 and B17 are last so generated/fleet material cannot contaminate feature commits.
