# Accounting acceptance matrix

This matrix separates a feature that is present and locally evidenced in the
isolated source branch from an accepted operational result.  The latter needs
real source documents, organization policy, PostgreSQL recovery evidence and
the accountant's close.  It is therefore an operating checklist, not a claim
that 1C can already be retired.

Status on 2026-09-26: the Goal graph has **35 of 41** implementation nodes
marked done. The six open nodes are G03D (document lifecycle), G06C (own
payroll calculation), G07 (opening balances), G06E (statutory payroll forms),
G08 (accepted pilot month) and G09 (cutover proof). The **13 requirement rows
below are 13 separate operational acceptance groups**; none is recorded as
accepted for production use or retirement of 1C. A passed local test is
evidence for a group, not its acceptance. G09 additionally requires two
consecutive accepted month closes, a quarterly cycle and a trial annual run.
The bounded test-and-fix workflow is recorded in
[Luna test/fix rules](LUNA-TEST-FIX-RULES.md); its test counts are not operational
acceptance counts.

Current source branch: `agent/crm-acc-prod009`; `alembic heads` on 2026-09-26
reports the single development source head `0189`. The fixed first-release candidate
remains at `0186`; this later manual-document change is not part of that release.
Two focused tests on a disposable local
PostgreSQL 16 database passed for the supplier-contract revocation migration
and procurement receipt history; the temporary container was removed. The earlier local synthetic PostgreSQL
[checkpoint](POSTGRES-ACCEPTANCE-2026-09-23.md) covers an empty-base upgrade
through its recorded revision, restore and targeted payroll guards, not the
current target database or all later source migrations.

| Requirement | Source evidence | Still required for acceptance |
| --- | --- | --- |
| Separate books for each legal entity; account policy, rights and mandatory analytics | `accounting.organization`, policies, access grants and versioned accounts; [API checks](../../tests/accounting/test_api.py) and [accountant workspace](../../frontend/src/components/erp/accounting-view.tsx) | Accountant adopts the verified catalogue and policy for every legal entity; current statutory source must be confirmed. |
| Balanced, immutable posting packages; preview before posting; correction rather than edit | [posting service](../../modules/accounting/service.py), immutable receipts and [entry transaction checks](../../tests/accounting/test_entry_transaction_postgres.py) | Run the full current package on an owned PostgreSQL copy and have the accountant approve pilot postings. |
| Source documents, unposted queue, explicit manual confirmation and close blocking | [inbox controls](../../frontend/src/components/erp/accounting-controls.tsx), [versioned manual documents](../../modules/accounting/manual_documents.py), [close guard](../../modules/accounting/service.py), [API proof](../../tests/accounting/test_manual_documents.py) | Load real documents and resolve every period-related queue item. The development-only manual document workflow needs integration and accountant acceptance before release. |
| OSV, account activity, ledger drill-down, P&L, cash flow and balance without synthetic capital | [reports](../../modules/accounting/reports.py), [account activity UI](../../frontend/src/components/erp/accounting-account-activity.tsx), [view tests](../../frontend/src/components/erp/accounting-view.test.tsx) | Reconcile reports with bank, stock, settlements and the accountant's matched OSV pair. |
| Purchases, purchase orders, procurement plan and supplier primary receipts | [procurement navigation](../../frontend/src/components/erp/procurement-nav.tsx), [all-date source-document register](../../frontend/src/components/erp/procurement-receipt-drafts.tsx), [read-only unlinked posting queue](../../frontend/src/components/erp/procurement-unlinked-purchases.tsx), [purchase receipt posting](../../frontend/src/components/erp/procurement-posted-receipt.tsx), [sales/procurement trace](SALES-PROCUREMENT-RESERVATION-TRACE.md) | Use real supplier documents and match stock, VAT and landed-cost results. The source register contains procurement-owned primary receipts of the selected legal entity. The separate queue exposes `inventory_purchase` postings with no same-entity saved primary receipt link; these entries are not supplier invoices, and their origin still requires explicit reconciliation. |
| Invoice reservation, shipment, TN/TTN scenario, paid-invoice cancellation only after refund, and client document trace | [trace contract](SALES-PROCUREMENT-RESERVATION-TRACE.md), [TN/TTN readiness](tn-ttn-readiness.md), targeted sales/procurement PostgreSQL scenario tests | Approve the applicable form, numbering, signatories and external delivery process; issue documents only after that approval. |
| Bank, settlements, advances, returns and FX | [bank pilot status](BANK-PILOT-STATUS.md), bank import/settlement source and tests | Map actual bank formats/accounts, obtain currency source evidence and complete real bank reconciliation. Full bank API and foreign-currency statement ingestion are not accepted. |
| VAT, ESCHF and foreign trade registers | [input/output VAT components](../../frontend/src/components/erp/accounting-input-vat-register.tsx), [foreign-trade module](../../modules/accounting/foreign_trade_register.py), [ESCHF source/version record](../eschf/sources.json) | Apply the ESCHF form and instruction effective from 13 May 2026, then confirm the matching technical format, provider, signature and portal result against real documents. The [tax authority announcement](https://nalog.gov.by/news/35429/) identifies Regulation No. 14 of 31 March 2026 as replacing the earlier form; the local unsigned candidate and VAT register do not certify external submission. |
| Production, late costs, repairs, customer property, fixed assets and depreciation | [production cost revision contract](production-output-cost-revisions.md), [repairs module](../../modules/accounting/repair_accounting.py), fixed-asset and production workspaces | Reconcile WIP, production, customer property and depreciation using real policy and source documents. |
| Payroll and statutory amounts | [payroll imports](../../modules/accounting/payroll_import.py), [statutory registry](../../modules/accounting/payroll_statutory.py), [HR draft and manual register](../../modules/hr/routes.py), [explicit employment binding](../../modules/accounting/payroll_employment.py), [versioned employer rules](../../modules/accounting/payroll_rule_set.py), [private source file registry](../../modules/accounting/payroll_evidence_files.py), [accounting workpaper contract](PAYROLL-WORKPAPER-CONTRACT.md), [accountant workpaper](../../frontend/src/components/erp/accounting-payroll-workpaper.tsx), [accountant payroll control](../../frontend/src/components/erp/accounting-payroll-control.tsx), [production estimate](../../modules/production/routes.py) | For the pilot, import a verified external calculation with its receipt. The HR preview and employee handouts are read-only scenarios from manually supplied inputs; legacy HR rows still have no automatic legal-entity ownership or bank-payment proof. The accounting binding requires an explicit employer/contract and does not verify the contract's contents. A chief-configured rule set fixes the arithmetic method, rounding and complete configured list of rate roles/base modes. New rules explicitly map each percentage rate to a payroll obligation; old unmapped rules and conflicts with the organization's reviewed applicability are visible blockers, but no tariff or legal completeness is inferred. The accountant workpaper previews arithmetic from selected stored contract, timesheet and monthly work-schedule files and explicitly entered salary/hours. It can upload those private files for an explicit employer binding; a chief alone can record an append-only arithmetic review with correction linkage. It verifies stored file bytes and, for an explicitly selected XLSX row, matches entered hours to numeric day cells in the declared work interval. A new chief arithmetic review requires a byte-verified monthly work schedule with a cited norm location. Employee-to-row identity, text day codes, contract salary, schedule approval and statutory applicability still require human verification. A selected numeric cell in a month-labelled XLSX work schedule can now be checked against the entered norm; non-XLSX norm values remain manually reviewed. Exemptions, caps, benefits and unconfigured obligations remain outside it. It cannot post or certify a statutory salary. The accountant control tab shows provisional monthly coverage and differences against posted imports with ledger links; it cannot create or accept a payroll result. The production estimate uses fixed 22-day and premium assumptions and is explicitly nonstatutory. Full ERP payroll calculation and period-versioned compulsory forms remain unimplemented. A verified external payroll system may remain the source during staged 1C transition. |
| Opening balances, source ownership and 1C reconciliation without duplicate imports | [pilot input packet](PILOT-INPUT-PACKET.md), [strict v6 manifest](PILOT-INPUT-MANIFEST.md), [optional live book check](../../scripts/accounting_pilot_live_preflight.py), opening-import controls and tests. The reconciliation screen downloads a current ERP OSV; preview and new acceptance reject a right-hand CSV that differs from its exact current bytes. | Receive signed real policy, balances, source hashes, external payroll register or documented zero accruals, ownership decision for each section and one closed matched OSV pair. The declared 1C file's origin and completeness still need external proof; the optional live check can compare a declared book and current ERP OSV, but no target DB or real source was checked. No default organization assignment is permitted. |
| Recovery and release | [release readiness](RELEASE-READINESS-2026-09-22.md), [local PostgreSQL checkpoint](POSTGRES-ACCEPTANCE-2026-09-23.md) | Target DB revision inspection, integration to the release baseline, target-specific backup/restore including private payroll files, and release receipt. The local empty-base upgrade and restore do not satisfy the target gate. |
| Replacement of 1C | All rows above are necessary local groundwork | Two successive accepted monthly closes, quarterly cycle, trial annual reporting, documented reconciliation of every variance, and an authorized production release. |

## Current local evidence

- The read-only legacy finance reconciliation now pairs duplicate payment
  references by exact BYN amount and reports mismatched amounts and malformed
  1C source rows separately. Its screen shows both categories without converting
  returned money strings through JavaScript floats. The finance suite passed
  75/75 and the focused finance screen passed 25/25 locally. The current 1C
  payment adapter is still unavailable, so this does not accept the bank or
  opening-balance groups above.
- Development slices `0187` and `0188` add numbered, versioned manual accounting documents
  and an immutable cancellation receipt for erroneous unposted drafts.
  The [draft workflow](MANUAL-DOCUMENT-DRAFTS.md) records author and server time
  per save, exposes a register and changes in the accountant UI, blocks close
  while a draft remains unposted, and posts only an exact saved revision.
  A cancelled draft retains its history and leaves the close queue. Focused
  local API tests 13/13, UI tests 31/31 and two disposable PostgreSQL
  revision/atomic-post/cancellation tests passed. This is not part of the fixed `0186` release.
- A later local source change binds the `counterparty` analytical value of a
  new manual document to an active MDM ID, UNP and revision. Preview, save and
  posting reject free text or a stale directory snapshot; exact replay of a
  previously posted entry remains readable after a rename. This was checked
  with targeted API, sales regression, UI and disposable PostgreSQL tests. The
  contract, warehouse and other manual analytical fields still require their
  own reference binding before this meets the full document standard.
- The next local source change binds manual `sku` analytics to the shared active
  SKU ID, code, title and unit. Free text and stale snapshots fail before new
  preview, save or post; a completed entry keeps its historical description.
  Focused API 6/6, UI 33/33, TypeScript, Ruff and disposable PostgreSQL 1/1
  checks passed. At that point, contract, warehouse and remaining manual analytics
  were still open.
- A further local source change binds manual `warehouse` analytics to an active
  organization-owned WMS directory ID, code and title. Preview, save, post and
  the legacy direct manual route reject free text, cross-company IDs and stale
  descriptions; exact replay keeps posted history. Focused API 7/7, UI 35/35,
  TypeScript, ESLint, Ruff and disposable PostgreSQL 1/1 passed. Contracts and
  other manual analytics remain open.
- Development migration `0189` and the inventory-issue API bind every new
  accountant stock issue to the selected organization warehouse ID/name/title
  and active SKU ID/code/title/unit. The UI submits directory snapshots rather
  than free text; both monetary receipts and zero-value V6/V4 commands retain
  them. Existing V2/V4 history keeps its old digest. On a disposable PostgreSQL
  16 database, 9/9 focused API scenarios passed for monetary, specific-zero and
  allocated-zero issues, including concurrent confirm, foreign/stale directory
  rejection and exact replay; a separate replay check passed after both source
  directory titles were changed. Focused backend tests passed 105/105 and the
  issue UI passed 13/13 with TypeScript, ESLint, Ruff and the single Alembic head
  check. This remains local development evidence: G03D still includes the rest
  of the document lifecycle and no operational acceptance group is closed.
- The next local G03D slice replaces free-text manual `contract` analytics with
  an exact contract-directory snapshot. Accountants search the selected
  counterparty's active supplier contracts and issued sales contracts; the
  saved line carries source, immutable ID, number, title and version. Preview,
  save, post and the legacy direct manual route reject an incomplete, foreign
  or stale contract, while an already posted entry replays after revocation.
  Related backend regression passed 58/58, the focused API suite 8/8, the UI
  and client validator 37/37, and disposable PostgreSQL 1/1; TypeScript,
  ESLint and Ruff passed. Settlement-document and remaining manual analytics,
  release integration and real accountant acceptance remain open.
- The third local G03D slice replaces free-text manual `settlement_document`
  analytics with the exact current procurement receipt revision or immutable
  issued sales invoice selected for the same organization and counterparty.
  Supplier receipts are also checked against the chosen supplier contract;
  sales invoices are checked against their prepared invoice/contract package.
  A later receipt revision blocks an unposted manual document until the
  accountant selects it again, while an already posted entry preserves and
  replays its original snapshot. Focused API/UI checks and a disposable
  PostgreSQL 16 replay check passed. Remaining manual analytics, release
  integration and real accountant acceptance keep G03D open.
- The fourth local G03D slice binds manual `employee` analytics to the exact
  active payroll-employment register revision for the selected organization
  and operation date. The saved snapshot contains the employee, employment
  binding, contract, revision, digest and required department. Free text and
  foreign, future, ended, stale or forged bindings fail before preview, save
  or post; an already posted entry retains exact historical replay. An
  independent review also added a pre-SQL PostgreSQL INTEGER bound after an
  oversized binding ID reproduced an overflow. Focused backend 19/19,
  frontend 41/41, disposable PostgreSQL 16 1/1, TypeScript, ESLint, Ruff and
  diff checks passed. Other manual analytics, release integration and real
  accountant acceptance keep G03D open.
- CRM deal Save and Close now requires a response with the exact deal ID,
  submitted editor fields and a valid new edit token. The PATCH response is
  generated from the saved deal; two concurrent edits on disposable
  PostgreSQL yielded one success, one conflict and one audit entry. Focused
  backend, frontend, type and lint checks passed. A real browser/user scenario
  and integration into a reproducible release remain open.
- The complete local Sales DB suite now passes 47/47 after its two legacy
  assertions stopped expecting invented 1C references. A locally issued
  document is labelled as issued in ERP; an external 1C reference appears only
  when one was actually returned. The changed document UI passed 49/49 focused
  tests plus TypeScript and lint. This does not prove accounting posting,
  customer notification or deployment.

- On 2026-09-26, a fresh disposable PostgreSQL 16 database passed **2**
  supplier-contract/receipt-history checks at migration `0186` and **4**
  payroll applicability, organization-review, closed-period and partial-binding
  guard checks. Both test containers were removed. These targeted checks do not
  certify statutory payroll calculations or the target production database.
- The focused reconciliation, migration-baseline and pilot-preflight suites
  passed together: **34 tests**. Five PostgreSQL reconciliation/queue tests
  also passed with the registered migration tail through `0174`.
- The current G07 reconciliation check binds a new accepted right-hand CSV to
  the live ERP ledger export for the same book and period. An identical pair of
  uploaded CSVs alone cannot become a cutover receipt. Existing receipts
  without this verification remain readable but are not marked cutover-ready.
- Offline and read-only live pilot preflight repeat the manifest and all artifact
  hashes immediately before returning success. An in-flight change of a bank,
  payroll or other attached source rejects the packet; later importer and
  accountant acceptance still require the same bytes and provenance.
- A matching closed pair now reports `reconciliation_ready`, which permits one
  accountant reconciliation receipt. It does not report `cutover_ready`: the
  external 1C origin and the required close, recovery and release sequence are
  independent acceptance evidence. Historical receipts remain immutable and
  their top-level cutover result is false on replay.
- The accountant screen exposes organization and date range, plan of accounts,
  journal/OSV reports, period controls and document queue.  The UI tests cover
  organization isolation, review-before-posting, report drill-down and safe
  error handling.
- The close control explicitly checks document completeness, bank, settlements,
  stock, costing, depreciation, FX, tax, financial result and trial balance.
- Known active employment now requires a chief-attested monthly source roster
  whose declared employee and binding IDs match the ERP book. The file is
  byte-checked at close, but its contents and complete real-world population
  still require accountant verification.
- The chief may separately attest the contract salary, timesheet hours and
  schedule norm in an immutable workpaper revision with cited document locations.
  Monthly control counts only the latest attested segments and identifies missing
  attestations; this human check does not certify rates, payroll posting or forms.
- The monthly own-payroll candidate combines only attested workpaper segments,
  binds the current review/roster/rule selection to a digest and lists missing
  coverage and rule-completeness gates. It is read-only and excludes un-attested
  amounts; no salary accrual, payment or compulsory form is created.
- The chief may separately record an organization/month review of tax, FSZN and
  work-injury rule applicability against a private file and exact source locator.
  Corrections append a new receipt; the candidate identifies the current review
  and remaining unresolved codes. These findings do not prove the current law,
  select a tariff or remove the statutory-completeness blocker.
- External payroll import lines may carry a stable employer-binding ID; the
  preview rejects cross-entity, unknown, future and name-mismatched mappings.
  Legacy free-text lines remain accepted and are marked as incompletely mapped.
- For the later own-payroll stage, the tax authority's [2026 income-tax rate
  notice](https://nalog.gov.by/news/34207/) and [standard-deduction
  guidance](https://nalog.gov.by/individuals/income_taxation/tax_deductions/9332/)
  show why one percentage multiplication cannot be treated as a complete
  withholding calculation. Their applicability, versions and examples still
  require accountant review before an ERP rule is enabled.

These are local source checks.  They do not replace the real acceptance
conditions in the table and must not be used to mark the pilot, release or 1C
replacement complete.
