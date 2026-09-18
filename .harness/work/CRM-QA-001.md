# CRM-QA-001 — система контроля качества ERP и Harness

## Goal runner state

- Chain ID: CRM-QA-001
- Project root: `D:/6 Проекты/CRM ERP/Сlaude CRM - проект`
- Data owner: User and appointed ERP business-process owners
- Risk class: high
- External-side-effect boundary: local source/test/Harness files and CI configuration only; no production changes, deployment, migrations, external messages, secrets or push in this chain.
- Parent outcome: establish a fail-closed, risk-oriented ERP quality-control system that classifies tests by size and layer, protects critical user journeys and business invariants, blocks regressions in CI, stores fresh evidence in Harness, and reports actionable failures and delivery outcomes.
- User-visible scenario: a change that breaks a real assertion, lowers a declared coverage threshold, removes or leaves tests unclassified, violates the lint-warning baseline, or makes readiness/background processing fail produces a failed CI/Harness gate with the responsible suite, artifact and next action; a passing change produces a fresh acceptance report.
- Delivery boundary: local-verified; CI configuration prepared, not production-deployed.
- Blocker/resume condition: external notification delivery and production rollout require separately supplied environment access and approval; local test work continues independently.
- Status: running
- Plan revision: 4
- Approved passport revision: 4
- Approval provenance: user message `подтверждаю Plan revision 4` (2026-09-17)
- Primary task ID: `01a0adbb-4e58-7a12-8e08-62b2494189ca`
- Current task ID: `01a0adbb-4e58-7a12-8e08-62b2494189ca`
- Checkout/worktree policy: current checkout is dirty; one writer at a time in the primary checkout, read-only exploration may share it, and unrelated submodule/report changes remain outside this chain.
- Commit policy: primary-only checkpoint after acceptance; no automatic push.
- Integration branch/worktree: current `feat/identity-provisioner-invites` checkout
- Last accepted commit: `362c8d1`
- Current laziness-ladder rung: 2 — inspect and reuse existing pytest/Vitest, CI, Harness tools, `/ready` and incident-alert implementation first.
- Rejected lower rungs: rung 1 is insufficient because the requested system must produce executable gates and failure evidence; no new dependency or coverage-exclusion rung is authorized.
- Retained exceptions / ponytail triggers: existing full-suite API/integration failures, unavailable external providers, Postgres/Playwright prerequisites and unconfigured production webhook remain explicit exceptions; they cannot be hidden by unit coverage.
- Current verified subgoal: G06 done (local control plane)
- Next minimal slice and acceptance check: G05 — prove ERP Medium-layer money/stock/RBAC correctness with real Postgres, migrations, idempotency and concurrency evidence.
- Executable plan snapshot: `.harness/work/CRM-QA-001.passport.json`
- Last validated plan snapshot/hash: validator PASS; current passport SHA-256 `129ab45b9e9338ab75079d7ee3472fe51189ed309765659dc5078667e3a37923`; durable result: `.harness/work/CRM-QA-001.passport-validation.json`
- Measurement treatment IDs: baseline `CRM-QA-001-baseline-v1` | treatment `CRM-QA-001-treatment-v1`
- Metrics path/schema: `.harness/metrics/CRM-QA-001.jsonl` / schema 2
- Task report: observed tokens unavailable; G01 failed attempts 0; G01 evidence acceptance 1/1 (100%), with 6 recorded checks passed and 2 product gates red. The `escapedDefects=0` metric is run-local observation only, not a production escaped-defect claim.
- Model routing: `gpt-5.6-luna / max` for all test-writing, test-count, CI-gate and implementation slices; `gpt-6-astra / xhigh` for the independent final correctness/safety review; no silent model substitution.
- Global agent cap: 4
- Active agent count: 0
- Delegation depth cap: 1
- Compaction count: 0
- Context threshold: 45% when visible
- Standing chain authorization: approved
- Standing authorization scope: bounded continuation
- Archive policy: final-explicit-command

## Control contract

- Small/unit tests prove pure rules and isolated handlers with real inputs/outputs and no I/O.
- Medium/API/integration tests prove database, transaction, authorization, idempotency and external-boundary contracts.
- Contract tests protect event, import/export and connector payloads.
- Large/E2E/smoke tests prove only the critical user-visible money, access and recovery paths.
- Every critical user journey has a named owner, a business invariant, a Small test, a Medium test and (where user-visible) a Large smoke test.
- Every test has one primary size/layer; unclassified, duplicate, collection-error, skipped, xfailed and retried tests are visible in the report.
- Test count is a trend and deletion guard, not a substitute for coverage or behavior assertions.
- Coverage denominators and exclusions stay unchanged unless a separately recorded acceptance revision approves the change.
- A test that flakes is a tracked defect with an expiry/quarantine owner; retries cannot convert instability into a silent PASS.
- A single `quality-required` aggregator is the merge authority; individual jobs are evidence producers, not bypassable merge decisions.
- The gate is tied to the current commit SHA and is fresh for the current repository state.
- CI failure is actionable only when the report names the suite, module, artifact and next diagnostic action.

## Assessment and plan revision 2

The first draft was directionally correct but too optimistic as an operational control system. Fresh repository checks found:

- Revision-2 baseline recorded `py -3 -m ruff check .` failing with 18 errors in `tests/unit/modules/sales/test_sales_route_units_more.py`; the later G04 repair removed those unused/duplicate imports and dead locals, and the current broad check is recorded in the G04 evidence.
- The backend workflow labels one step `unit + api + integration` and then runs an undifferentiated `pytest -q`; it does not produce separate required results for each layer or expose unmarked tests.
- `pyproject.toml` declares only `unit`, `api` and `integration`; contract/smoke ownership is not machine-readable yet.
- `frontend/package-lock.json` exists, but CI uses `npm install`; dependency resolution is not deterministic enough for a release gate.
- Frontend lint is fail-closed at the recorded local baseline of **45 warnings**; any increase makes the CI step fail. A future decrease can lower the cap after evidence refresh.
- There is no committed test-count inventory or deletion guard; the earlier 3,174 figure is a run result, not a durable baseline by layer/domain.
- The E2E job uses a separate SQLite/dev backend and must remain explicitly distinct from Postgres integration evidence.
- The checkout contains project Harness evidence files, but no project-owned canonical `acceptance_gate.py`/`harness_metrics.py` entrypoint was found; a durable control must not depend on an arbitrary report snapshot path.
- Incident delivery is intentionally no-op when the webhook URL is empty. Development may keep this mode, but a production release gate must report missing alert configuration as a blocker.

Revision 2 changed the acceptance model to fail closed: first prove that the gates themselves are truthful, then add counts and layer controls, then accept the full regression state. Test count remains a deletion/regression signal, never a quality substitute.

## Method basis and ERP adaptation — revision 3

The plan now follows established practices, adapted to this ERP rather than copying a generic test pyramid:

- Use **test size as an enforceable contract**: Small/Unit has no database, network or filesystem I/O; Medium/API or integration may use a local database/service boundary; Large/E2E uses real service composition and a browser. This follows Google’s size definitions and makes a test’s speed and isolation auditable.
- Use a **risk-weighted pyramid**, not a fixed 70/20/10 quota. Google presents 70/20/10 as a starting heuristic, not a law. For this ERP, money, permissions, inventory/concurrency, accounting, migrations and connector idempotency define where Medium/Large evidence is mandatory.
- Define critical user journeys (CUJs) before writing E2E: invitation/login and authorization; lead → deal → quote → contract → invoice/payment; procurement → landed cost → stock; reservation/concurrency; Belarus chart of accounts and finance reports; inbound/outbound webhook failure and recovery. Each CUJ gets Small rules, Medium API/integration checks and a very small Large smoke path where a user-visible proof is needed.
- Treat **flake as a defect**, not as a reason to increase retries. CI retries are recorded; an unstable test gets an owner, reason, quarantine expiry and replacement plan. Unbounded `skip`/`xfail` is not acceptance evidence.
- Make GitHub’s **single required aggregator check** the merge authority. Every layer reports artifacts, then `quality-required` fails if any required job failed, was cancelled, had collection errors or was silently skipped. Include `merge_group` so merge queues cannot bypass validation.
- Use native machine-readable reports: pytest markers plus JUnit XML, Vitest JSON/JUnit and coverage summaries. Counts are derived from collection/report files, never from terminal text or manually edited totals.
- Track delivery outcomes in addition to test metrics: change lead time, deployment frequency, change fail rate, failed-deployment recovery time and rework rate. These are DORA signals; they are not substituted by test count or coverage.
- Keep runtime telemetry vendor-neutral: structured logs/metrics/traces with correlation, severity, environment, commit and deduplication fields. The current webhook sink remains the smallest useful alert path; OpenTelemetry compatibility is a future transport choice, not a new dependency by default.

Reference basis: [Google test sizes](https://testing.googleblog.com/2010/12/test-sizes.html), [Google test pyramid](https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html), [pytest markers and strict markers](https://docs.pytest.org/en/stable/how-to/mark.html), [pytest JUnit XML](https://docs.pytest.org/en/stable/how-to/output.html), [Vitest reporters](https://vitest.dev/guide/reporters), [Vitest coverage](https://vitest.dev/guide/coverage), [GitHub status checks](https://docs.github.com/en/pull-requests/reference/status-checks), [DORA metrics](https://dora.dev/guides/dora-metrics/), [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/).

## Plan revision 4 — ERP control model

Revision 4 adds the controls that make the plan useful for an ERP, where a green UI test is not proof that money, stock or accounting data is safe.

### Business invariants before coverage

The risk map must name the invariant, owner, severity, source module, test layers and release consequence:

- Finance: Decimal/rounding rules, VAT and grand totals, payment idempotency, balanced postings and no duplicate financial events.
- Inventory: no negative stock, reservation locking/concurrency, FIFO/FEFO choice, landed-cost allocation conservation and rollback on partial failure.
- Workflow/RBAC: allowed state transitions, department ownership, fail-closed access, audit identity and immutable event provenance.
- Accounting: Belarus chart hierarchy, parent references, effective dates, account uniqueness and report-to-ledger consistency.
- Integrations: HMAC/token validation, deduplication, retry/backoff, outbox/inbox semantics, timeout handling and safe replay.
- Data lifecycle: migration upgrade from clean and representative fixtures, backward-compatible reads, constraints/indexes and rollback evidence.

Coverage is a supporting signal. A module is not accepted only because its line percentage is high if one of these invariants has no test at the correct layer.

### Operating gates

1. **Gate 0 — collection and hygiene:** strict markers, no collection errors, no unclassified tests, no unowned skip/xfail, Ruff/typecheck and deterministic dependency install.
2. **Gate 1 — Small:** fast unit tests on every PR; no DB/network/filesystem I/O.
3. **Gate 2 — Medium:** API, Postgres, migration, contract, idempotency and concurrency tests for affected risk domains.
4. **Gate 3 — Large:** a small number of CUJ smoke/E2E tests for money, access, stock and recovery paths.
5. **Gate 4 — scheduled deep checks:** full regression, mutation tests for finance/RBAC/stock, dependency/security checks, resilience and performance probes.
6. **Merge authority:** one `quality-required` aggregator checks all required jobs, current commit SHA, artifacts, cancellations, skipped jobs and known blocker policy. No individual green job can bypass a red sibling.

Fast PR checks and deep scheduled checks are different feedback loops, not different truth standards. A scheduled failure creates a tracked defect with owner and due date; it is not silently made green with `continue-on-error`.

### Flake, skip and retry policy

- Small and Medium tests have zero automatic retries.
- Large/E2E may retry once only to collect diagnostics; a retry is reported as flaky evidence, not hidden.
- Every skip/xfail has a reason, issue/reference, owner and expiry date. Expired exceptions fail the gate.
- Quarantine is temporary, visible in the Harness defect register and capped by a defined expiry; no permanent quarantine folder.

### Release decision

`unit green` is not `CRM ready for sale`. Release acceptance requires: required CI checks pass; no unresolved P0/P1 business-invariant defects; Postgres/migration evidence is fresh; CUJ smoke passes; alerting configuration is present; rollback/restore evidence is available for schema/data changes; and all remaining exceptions have an owner and explicit business acceptance.

### Operational scorecard

Harness records test duration, queue time, pass/fail, retry/flaky rate, skipped/xfail count, coverage/count deltas, escaped defects and time to restore. After real deployments it records DORA metrics; unavailable production data remains `unknown`, not zero.

## Control artifacts to add or reuse

- `.harness/policy/quality-risk-map.json` — ERP modules, critical invariants and required test layers/CUJs.
- `.harness/policy/cuj-matrix.json` — critical user journeys, prepared inputs, expected outcomes and evidence owners.
- `.harness/policy/flake-policy.json` — diagnostic-only retry and bounded quarantine policy.
- `scripts/quality/quality_control.py` — deterministic registry/JUnit gate; it returns non-zero on integrity or strict-policy violations.
- `scripts/quality/flake_control.py` — flake policy validator and negative-case self-test.
- `scripts/quality/source_snapshot.py` — fail-closed parent/submodule source-alignment preflight.
- `.harness/tools/build_g03_inventory.py` — native collection and fingerprinted inventory builder.
- `.harness/work/CRM-QA-001.g03.inventory.json` and `.harness/work/CRM-QA-001.g03.regression-baseline.json` — generated count/deletion evidence.
- `.harness/metrics/CRM-QA-001.jsonl` — schema-2 incremental telemetry only at meaningful checkpoints.
- `docs/TESTING_AND_ALERTING.md` — local test and alerting guidance; remote branch protection remains a separate action.

Generated coverage, raw reports and telemetry stay out of the source baseline unless explicitly classified as durable evidence. CI must use `npm ci` when the lock-file is present and must not silently downgrade a failed layer to a warning.

## G01 gate-truth baseline evidence — 2026-09-17

Fresh evidence was collected against commit `362c8d1c6f13364e74766ffec73f58b55c5fb698` on branch `feat/identity-provisioner-invites`. The checkout was already dirty: four submodule worktrees and prior Harness/report artifacts were preserved and not treated as this chain's product changes. The source snapshot is explicit in `.harness/work/CRM-QA-001.source-snapshot.json`: the worktrees do not currently match the parent gitlinks (`finance`, `leads`, `marketing`, `sales`). The figures in this G01 section are the historical baseline; the current refresh is recorded under G03/G04 below.

### Backend collection and unit gate

- `pytest --collect-only -q -m unit`: **874** tests.
- `pytest --collect-only -q -m api`: **1,364** tests.
- `pytest --collect-only -q -m integration`: **12** tests.
- `pytest --collect-only -q -m "not unit and not api and not integration"`: **0** tests; collection total **2,077**.
- Marker counts are overlapping sets, not a partition: `unit`-marked share is `874 / 2,077 = 42.08%`, not a claim that 42.08% of all behavior is unit-tested.
- `py -3 -m pytest -q -m unit --cov --cov-branch ...`: **874 passed**, 6 warnings, JUnit `work/CRM-QA-001.backend-unit.xml`.
- Unit line gate used by the current CI formula: **13,965 / 14,949 = 93.42%**. Coverage.py's combined line+branch display is **90.27%**; branch coverage is **75.16%**. These are intentionally reported separately.
- `ruff check .`: **PASS** after removing unused/duplicate imports and dead local assignments from `tests/unit/modules/sales/test_sales_route_units_more.py`.

### Full backend regression

- `py -3 -m pytest -q --junitxml=...`: **2,050 passed, 15 failed, 12 skipped, 24 warnings** in **584.60 s**; JUnit `work/CRM-QA-001.backend-full.xml` is fresh on the current worktree. Coverage figures remain from the separate unit coverage run and are not relabeled as full-regression coverage.
- Failing nodeids: `tests/test_finance.py::test_margin_by_deal_hides_gross_when_cogs_unattributed`, `tests/test_finance.py::test_claim_resolved_is_idempotent_on_redelivery`, `tests/test_leads.py::test_lead_convert_creates_deal`, `tests/test_leads.py::test_lead_converted_event_carries_items`, `tests/test_leads.py::test_rbac_sales_manager_full_funnel`, `tests/test_leads.py::test_lead_converted_creates_price_quote_for_invoice`, `tests/test_links.py::test_payment_paid_fallback_prefers_unpaid_invoice`, `tests/test_procurement_ship_deadline.py::test_plan_auto_derives_target_from_deadline`, `tests/test_sales_contract.py::test_render_contract_escapes_untrusted_ctx_values`, `tests/test_sales_deals_v2.py::test_invoice_document_amount_includes_vat`, `tests/test_telephony.py::test_resolve_owner_by_active_deal`, `tests/test_telephony.py::test_resolve_owner_closed_deal_no_deal_id`, `tests/test_telephony.py::test_resolve_owner_unknown_number`, `tests/test_telephony.py::test_incoming_logs_resolves_and_pushes`, `tests/test_telephony.py::test_list_calls_filter_by_deal_id`.
- Independent source-snapshot triage classifies **14/15** failures as expected-parent-gitlink versus checked-out-submodule drift, not confirmed defects in the parent `HEAD`; the remaining deadline test uses a fixed `2026-12-31` date and is stale on the current date. The exact parent/worktree revisions and next action are recorded in `.harness/work/CRM-QA-001.source-snapshot.json`; no submodule alignment was performed.

### Frontend and infrastructure assumptions

- `npm run test:coverage`: **188 test files passed, 2,326 tests passed**; lines **9,721 / 10,681 = 91.01%**, statements 89.35%, branches 81.65%, functions 85.82%; `frontend/coverage/coverage-summary.json` is fresh evidence.
- `npm run typecheck`: PASS. `npm run lint -- --max-warnings 45`: PASS with **0 errors / 45 warnings**; the workflow now fails closed on any warning increase.
- The first sandboxed Vitest start hit Windows `spawn EPERM`; the identical command completed successfully under the approved elevated execution. This is an environment limitation to monitor, not a product test result.
- `frontend/package-lock.json` exists while CI still uses `npm install`; deterministic install remains open for G04.
- Playwright E2E is a distinct SQLite/dev-backend path (`sqlite+aiosqlite:///./e2e.db`, localhost:4000, AI enabled), not Postgres evidence. Postgres integration, browser E2E, production webhook delivery and DORA data were not claimed by this baseline.

### G01 decision

G01 acceptance passes because the gate truth, counts, fresh artifacts, red checks and infrastructure assumptions were reproducibly recorded. At that historical baseline, Ruff and the full backend regression were red; the current Ruff and regression results are recorded in the refresh below. Unit line coverage is above the current 91% formula, while branch coverage and business-invariant coverage require later waves.

## G02 risk/invariant and CUJ matrix evidence — 2026-09-17

G02 produced and contract-validated:

- `.harness/policy/quality-risk-map.json`: **6** risk domains and **20** invariants covering finance, inventory, workflow/RBAC/audit, Belarus accounting/reference data, integrations and data lifecycle. Each domain has a role-level owner, P0/P1/P2 severity, source paths, current evidence, required Small/Medium/Large layers and release consequence.
- `.harness/policy/cuj-matrix.json`: **6** critical user journeys with prepared inputs, action, observable outcome, invariant IDs, layer-specific evidence and current blockers: identity/authorization; lead→deal→quote→contract→invoice/payment; procurement→landed cost→stock; reservation/concurrency; Belarus chart/reporting; webhook failure/recovery.
- Contract check: `G02 CONTRACT PASS 6 20 6`; all CUJ owner roles exist, all CUJ invariant references resolve, each CUJ has all three test-size evidence keys, and both artifacts are pinned to the current commit.
- Real gaps retained rather than normalized away: `StockService.reserve` has no available-quantity guard or row lock; `on_claim_resolved` has no observed replay guard; lead conversion is event-mediated and currently fails to return/close the deal link in the full suite; the static Belarus chart has structural tests but no local debit/credit ledger proof; telephony and RBAC failures remain from G01.
- Graphify was used only for navigation: forced code-only AST found **1,237** code files and wrote **11,807** nodes / **29,338** edges. It warned about 27 source files with zero nodes and a missing `tree_sitter_sql` dependency; no graph output is treated as acceptance evidence, and the risk/CUJ entries were checked against source paths and tests.

G02 acceptance passes as a design/control artifact. It does not close the named P0/P1 defects, assign personal owners, prove Postgres concurrency/migrations, or claim sale readiness. G03 is the next minimal slice.

## G03 machine-readable test inventory evidence — refreshed 2026-09-18

G03 was collected with the reusable report-only collector .harness/tools/build_g03_inventory.py and the bounded command py -3 .harness/tools/build_g03_inventory.py. It runs native pytest --collect-only, Vitest list --json and Playwright --list; it does not execute test bodies or change product/test source.

- Native backend collection: **2,100** total; marker memberships are unit **897**, api **1,191**, integration **12**. Explicit markers now take precedence over path defaults, so the registry has **2,100** backend IDs with **zero layer overlap**.
- Backend unit-marker share is **897 / 2,100 = 42.71%**. This is a layer-membership ratio, not behavioral coverage; project-wide primary-unit share is **3,226 / 4,436 = 72.72%**.
- Native frontend discovery: **2,329** Vitest IDs and **7** CRM Playwright IDs in **5** files. Playwright uses frontend/playwright.config.ts; the separate modules/production prototype config remains a documented dependency blocker.
- Registry total: **4,436** unique IDs. Primary layer counts are unit **3,226**, api **1,191**, integration **12**, e2e **7**, overlap **0**; reviewed size counts are Small **1,621**, Medium **2,808**, Large **7**, and unknown **0**. Frontend size evidence now covers every discovered Vitest case: pure-render/isolated rules are Small, API/auth/I-O boundaries are Medium, and browser journeys are Large.
- Risk/CUJ classification is path- and case-level evidence based. The current policy classifies all **4,436** records with **0** unclassified domains and **0** unclassified CUJs; the collector does not spread a `file::case` rule over every test in the file without specificity evidence.
- Existing current-worktree JUnit evidence is linked: backend full **2,074 passed / 14 failed / 12 skipped** across **2,100** cases; unit **897 passed**; fresh API **1,177 passed / 14 failed** across **1,191** executed cases; frontend Vitest **2,329 passed** with **0 failed / 0 skipped** and **91.02% line coverage**. The fixed-date procurement deadline test was made date-relative and now passes, and the scorecard-control plus nested-alert-redaction tests pass. Retry/xfail state is not invented: where the native/JUnit reports do not expose it, the registry records unknown; Playwright remains list-only in this slice.
- Durable artifacts: `.harness/policy/CRM-QA-001.regression-baseline.json`, `.harness/work/CRM-QA-001.g03.inventory.json`, `.harness/work/CRM-QA-001.g03.evidence.json`, `.harness/work/CRM-QA-001.g03.regression-baseline.json`, native stdout/stderr reports, `.harness/tools/build_g03_inventory.py` and `tests/unit/test_quality_control.py`. The accepted policy baseline detects added, removed, changed and classification-changed IDs using source/case fingerprints and is never replaced by a normal collector run.
- Refreshed contract result: **G03 CONTRACT PASS** — **4,436** inventory records matched the accepted policy baseline, zero duplicate IDs, current HEAD 362c8d1c6f13364e74766ec73f58b55c5fb698, all source fingerprints present; collector ruff and py_compile pass. Baseline drift is fail-closed and requires the explicit `--accept-baseline` action.
- Environment limitation recorded, not hidden: the local G03 Vitest list subprocess still returns spawn EPERM in sandbox, while a native external run executed **2,329/2,329** tests with **0 failed / 0 skipped** and **91.02% line coverage**; the JUnit and coverage artifacts are linked in G04 evidence. No Playwright body execution is claimed from this slice.
- API collection boundary: the executed lane used `pytest -q tests -m api`; an unscoped invocation can collect `scripts/hooks-tests/test_guard.py` and abort with an internal `SystemExit(0)`, so the CI workflow now names the `tests` root explicitly.

Current superseding G03 refresh (2026-09-18T05:39:45Z) is **4,436** records: backend **2,100**, primary unit **3,226**, api **1,191**, integration **12**, e2e **7**, with domain/CUJ unclassified counts **0/0**; integrity and strict validation are PASS, and accepted baseline drift is none. G03 acceptance passes for the registry/control artifact. It does **not** make the product green or sale-ready: full regression, Postgres/migration proof, runtime webhook delivery, ownership and external browser/webhook prerequisites remain open for G05–G08.

## G04 CI gates and fail-closed aggregator evidence — refreshed 2026-09-18

G04 added a reusable registry gate at scripts/quality/quality_control.py and updated .github/workflows/ci.yml. The workflow now listens to push, pull_request and merge_group, uses contents: read, runs explicit unit/api/integration marker lanes, installs frontend dependencies with npm ci in all three relevant jobs, builds the native G03 registry, and exposes one quality-required aggregator with always() plus explicit failure propagation. The integration lane now validates its JUnit report with `--require-executed`, so an all-skipped pytest result cannot be accepted as green.

- Gate integrity check: **exit 0** on **4,436** records, zero duplicate IDs, native source availability, source fingerprints and artifact hashes; accepted baseline comparison has no added, removed or changed IDs. G04 now stores SHA-256 fingerprints for the exact G03/JUnit/coverage/CI inputs it summarizes.
- Gate self-test: **exit 0** for accepted integrity, missing inventory, missing evidence, duplicate ID, unknown-classification and skipped-JUnit negative cases. Temporary fixtures are exact files under .harness/work and are removed after the run.
- Strict classification check: **exit 0** after native Vitest discovery outside the sandbox; there are zero layer overlaps, unknown sizes, unclassified domains or unclassified CUJs across **4,436** records. The separate external Vitest body run is green at 2,329/2,329 with 91.02% line coverage.
- Workflow syntax/static check: YAML parse **exit 0**; actionlint is unavailable locally. Frontend lint is **0 errors / 45 warnings** and the CI cap is now exactly **45**, so warning growth fails closed. Backend and frontend strict coverage gates now require **strictly greater than 91%**. The local integration fixture produced **12 skipped / 0 passed** with pytest exit 0, and `validate-junit --require-executed` correctly returned **exit 1**. The fresh explicit API lane produced **1,177 passed / 14 failed / 899 deselected** across **1,191** cases and its JUnit gate returned **exit 1**. The current full backend job produced **2,074 passed / 14 failed / 12 skipped** across **2,100** cases and its JUnit gate returned **exit 1**. The remote GitHub Actions run was not executed from this checkout. package-lock.json was not regenerated, product code/migrations/submodules/secrets/deploy/push were not touched.
- Known upstream red gates remain visible: the fresh full backend has 2,074 passed, 14 failures and 12 skips; all 14 are source-snapshot drift candidates after the stale fixed-date procurement test was repaired, and real Postgres is still unavailable. The new quality-required job will therefore remain red until the source snapshot, evidence and external prerequisites are resolved.
- The diagnostic-only flake policy is validated locally and wired into CI: retries cannot turn a failed required check green, and quarantines require an owner, issue, reason and a maximum 14-day expiry. GitHub Actions itself was not run from this checkout. Evidence artifacts: `.harness/work/CRM-QA-001.g04.evidence.json`, registry reports, source snapshot and `.harness/work/CRM-QA-001.g05.integration-junit-gate.json`. No production or sale-readiness claim follows from this local control-plane acceptance.

G04 acceptance passes for the local CI/control implementation; remote CI execution, branch protection and product green status remain open. G05 is the next bounded slice.

## G06 Runtime readiness, incident alerts and flake controls — 2026-09-17

- Fresh targeted JUnit: **19 passed / 0 failed / 0 skipped** across readiness, incident-alert, runtime-access, system-boundary and flake-policy tests.
- `validate-junit --require-executed` exits **0**; the flake policy validator and self-test also exit **0**.
- The local control plane proves structured incident payloads, cooldown/de-duplication, secret redaction, readiness failure containment and diagnostic-only retry/quarantine rules.
- This is **local control acceptance**, not production alert acceptance: live webhook delivery, production configuration/credentials and remote CI required-check behavior remain unknown and are explicit release blockers.
- Evidence: `.harness/work/CRM-QA-001.g06.orientation.json`, `.harness/work/CRM-QA-001.g06.runtime-unit.xml`, `.harness/work/CRM-QA-001.g06.runtime-unit-gate.json`.

G06 local acceptance passes. It does not bypass G05: real PostgreSQL/migration/idempotency/concurrency evidence is still required before release or sale-readiness.

## G05 Postgres prerequisite probe — 2026-09-17

G05 orientation and the bounded environment probe are recorded in .harness/work/CRM-QA-001.g05.orientation.json. The integration layer now contains **12** real-Postgres tests across test_postgres.py and test_scd2_partial_unique.py; Alembic reports head **0110**. Five new cases cover the migration head, fail-closed RBAC, outbox `SKIP LOCKED`, reservation concurrency and bank-operation uniqueness.

- Native collection: **12 tests collected**, exit 0.
- Execution without a database: **12 skipped**, exit 0. The fixture explicitly skips when AIOS_DATABASE_URL is absent and Docker is unavailable; this is an environment probe, not a pass. The new JUnit gate rejects the report with exit 1 because all 12 cases were skipped and no executed case passed.
- Local facts: AIOS_DATABASE_URL is absent, port 5432 is not listening, Docker executable exists but docker info exits 1 because the daemon is unavailable. A local Docker service/Desktop startup attempt was authorized and recorded, but the service remained stopped and the API returned unavailable/permission denied. No Postgres behavior, migration upgrade, concurrency or idempotency proof was claimed.
- Independent read-only G05 probe reproduced the same facts: 12 tests, no listeners on 5432/5433/15432, `docker info` exit 1, and no SQLite substitution. This corroborates the blocker but does not count as integration evidence.
- Scope remained safe: no migration, product, schema, production, deployment or push change; no new unrun test was added merely to increase the count.
- G05 is **not accepted** and remains ready for the next external-state change. The measurable next action is to start the local Docker Postgres daemon or run the CI PostgreSQL service, then execute all 12 integration tests and classify any product failures. The latest probe and fail-closed gate are `.harness/work/CRM-QA-001.ci-integration-local-2.xml` and `.harness/work/CRM-QA-001.g05.integration-junit-gate-2.json`.

## G07 pre-acceptance regression report — 2026-09-17

Current superseding G07 run (2026-09-18) is **2,074 passed / 14 failed / 12 skipped** across **2,100** cases. The 14 failures remain release blockers and source-snapshot candidates; the scorecard remains pre-acceptance-blocked.

The fresh full-suite result is captured in `.harness/work/CRM-QA-001.release-defects.json`: 2,070 passed, 14 failed, 12 skipped, 0 errors across 2,096 cases. The report marks all 14 as release blockers and keeps the source-snapshot causes as candidates rather than facts. The current project-owned operational scorecard is `.harness/work/CRM-QA-001.scorecard.json`; it fingerprints the evidence to parent HEAD `362c8d1c6f13364e74766ffec73f58b55c5fb698`, records DORA and production alert data as `unknown`, and does not claim G08 acceptance. G07 remains **planned**, because release acceptance still requires source-aligned reproduction plus G05 PostgreSQL/migration/concurrency evidence.

The scorecard control is reusable at `scripts/quality/scorecard_control.py`. Its current validation exits **0** and its three focused unit tests pass; it fails closed on changed input hashes, a stale HEAD, coverage not greater than 91%, or an `accepted` status that still contains failed/skipped/error cases, missing Postgres proof, unknown production alert delivery or source-snapshot drift. This validates the scorecard's honesty and integrity; it is not itself release acceptance.

## Subgoals

| ID | Observable result | Depends on | Wave | Subsystem | Risk | Execution | Model | Status | Acceptance/evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G00 | Plan revision 4 approval and executable passport state validated before evidence collection | none | 1 | control-plane | low | primary | gpt-5.6-luna / max | done | Approval provenance, bounded continuation and validator-readable state are recorded; no product acceptance is implied |
| G01 | Gate-truth baseline: current lint/test failures, markers, counts, coverage and infrastructure assumptions | G00 | 2 | baseline | high | primary | gpt-5.6-luna / max | done | Fresh collection, unit/full backend, frontend coverage/typecheck/lint, Ruff, commit and infrastructure evidence are recorded; red product gates remain explicit |
| G02 | ERP risk/invariant catalog and CUJ matrix | G01 | 3 | domain-quality | high | primary | gpt-5.6-luna / max | done | 6 domains, 20 invariants and 6 CUJ records are JSON-valid, source-pinned and connected to Small/Medium/Large evidence |
| G03 | Machine-readable inventory by backend/frontend, Small/Medium/Large size, layer, domain, CUJ and unclassified state | G01, G02 | 4 | test-registry | medium | subagent/primary fallback | gpt-5.6-luna / max | done | 4,436 unique IDs, native backend/Vitest/Playwright counts, JUnit status evidence, case-level policy matching, explicit unknown retry/xfail fields, immutable policy baseline and fail-closed contract checks |
| G04 | Separate CI gates, deterministic installs and one required aggregator | G01, G03 | 5 | CI | high | subagent/primary fallback | gpt-5.6-luna / max | done | npm ci, explicit marker/size jobs, quality-required, merge_group, fail-closed collection and artifacts are deterministic; remote CI remains unrun |
| G05 | ERP Medium-layer correctness: Postgres, migrations, contracts, idempotency and concurrency | G02, G03 | 5 | integration-quality | high | subagent | gpt-5.6-luna / max | ready | Real Postgres and migration evidence cover money/stock/RBAC invariants; SQLite E2E is not used as a substitute; local Docker/Postgres is unavailable |
| G06 | High-signal readiness, runtime-alert and flake controls | G04 | 6 | runtime-observability | high | subagent | gpt-5.6-luna / max | done | 19 executed local tests cover `/ready`, structured incidents and diagnostic-only flake policy; live webhook/production alert configuration remains a release blocker |
| G07 | Full regression and release report with defect/exception decisions | G04, G05, G06 | 7 | acceptance | high | primary | gpt-5.6-luna / max | planned | Full results, CUJ matrix, migration/rollback evidence, P0/P1 blockers, branch-protection checklist and next actions are recorded honestly |
| G08 | Project-owned Harness evidence, metrics and operational scorecard | G01, G04, G07 | 8 | Harness | medium | primary | gpt-5.6-luna / max | planned | Acceptance, fingerprint, test counts, defects, schema-2 metrics and DORA fields are fresh and tied to one commit |
| G09 | Independent correctness and simplify review | G07, G08 | 9 | review | high | verifier | gpt-6-astra / xhigh | planned | Independent reproduction passes; unnecessary files/gates are removed; parent acceptance is fresh; no production claim is inferred |

## Planned waves

1. Control bootstrap: G00.
2. Baseline: G01 after G00.
3. Domain contract: G02 after G01.
4. Inventory: G03 after G02.
5. Parallel CI and Postgres correctness: G04, G05 after G03.
6. Runtime control: G06 after G04.
7. Release acceptance: G07 after G04/G05/G06.
8. Harness scorecard: G08 after G01/G04/G07.
9. Independent review: G09 after G07/G08.

## External acceptance still required

- GitHub branch protection must require the single `quality-required` check and keep its source workflow stable; if a merge queue is enabled, the workflow must also run on `merge_group`. Repository settings are not changed by this local chain.
- Production must provide `AIOS_INCIDENT_WEBHOOK_URL` and its secret through the deployment secret store; local tests cannot prove delivery to an unconfigured receiver.
- Postgres integration and Playwright E2E prerequisites must be available for their respective gates; SQLite E2E is not a substitute for Postgres evidence.
- DORA metrics require real deployment and incident history; until then they remain `unknown`, not zero.
- Mutation, dependency/security, resilience and performance checks are scheduled evidence first; they become merge blockers only after a stable baseline and measured runtime are established.

## Approval boundary

The user approval of Plan revision 4 authorizes only this local chain, its listed subgoals, bounded test changes, CI/Harness artifacts and local verification. Test-writing is assigned to `gpt-5.6-luna / max`; the independent final verifier is a separate role. It does not authorize production deployment, schema migration, secrets, external notification setup, submodule changes or a new push.
