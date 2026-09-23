# Accounting acceptance matrix

This matrix separates a feature that is present and locally evidenced in the
isolated source branch from an accepted operational result.  The latter needs
real source documents, organization policy, PostgreSQL recovery evidence and
the accountant's close.  It is therefore an operating checklist, not a claim
that 1C can already be retired.

Current source branch: `agent/crm-acc-prod009`; `alembic heads`
reports the single source head `0163`.

| Requirement | Source evidence | Still required for acceptance |
| --- | --- | --- |
| Separate books for each legal entity; account policy, rights and mandatory analytics | `accounting.organization`, policies, access grants and versioned accounts; [API checks](../../tests/accounting/test_api.py) and [accountant workspace](../../frontend/src/components/erp/accounting-view.tsx) | Accountant adopts the verified catalogue and policy for every legal entity; current statutory source must be confirmed. |
| Balanced, immutable posting packages; preview before posting; correction rather than edit | [posting service](../../modules/accounting/service.py), immutable receipts and [entry transaction checks](../../tests/accounting/test_entry_transaction_postgres.py) | Run the full current package on an owned PostgreSQL copy and have the accountant approve pilot postings. |
| Source documents, unposted queue, explicit manual confirmation and close blocking | [inbox controls](../../frontend/src/components/erp/accounting-controls.tsx), [close guard](../../modules/accounting/service.py), [API proof](../../tests/accounting/test_api.py) | Load real documents and resolve every period-related queue item. |
| OSV, account activity, ledger drill-down, P&L, cash flow and balance without synthetic capital | [reports](../../modules/accounting/reports.py), [account activity UI](../../frontend/src/components/erp/accounting-account-activity.tsx), [view tests](../../frontend/src/components/erp/accounting-view.test.tsx) | Reconcile reports with bank, stock, settlements and the accountant's matched OSV pair. |
| Purchases, purchase orders, procurement plan and supplier primary receipts | [procurement navigation](../../frontend/src/components/erp/procurement-nav.tsx), [purchase receipt posting](../../frontend/src/components/erp/procurement-posted-receipt.tsx), [sales/procurement trace](SALES-PROCUREMENT-RESERVATION-TRACE.md) | Use real supplier documents and match stock, VAT and landed-cost results. |
| Invoice reservation, shipment, TN/TTN scenario, paid-invoice cancellation only after refund, and client document trace | [trace contract](SALES-PROCUREMENT-RESERVATION-TRACE.md), [TN/TTN readiness](tn-ttn-readiness.md), targeted sales/procurement PostgreSQL scenario tests | Approve the applicable form, numbering, signatories and external delivery process; issue documents only after that approval. |
| Bank, settlements, advances, returns and FX | [bank pilot status](BANK-PILOT-STATUS.md), bank import/settlement source and tests | Map actual bank formats/accounts, obtain currency source evidence and complete real bank reconciliation. Full bank API and foreign-currency statement ingestion are not accepted. |
| VAT, ESCHF and foreign trade registers | [input/output VAT components](../../frontend/src/components/erp/accounting-input-vat-register.tsx), [foreign-trade module](../../modules/accounting/foreign_trade_register.py), [ESCHF source/version record](../eschf/sources.json) | Apply the ESCHF form and instruction effective from 13 May 2026, then confirm the matching technical format, provider, signature and portal result against real documents. The [tax authority announcement](https://nalog.gov.by/news/35429/) identifies Regulation No. 14 of 31 March 2026 as replacing the earlier form; the local unsigned candidate and VAT register do not certify external submission. |
| Production, late costs, repairs, customer property, fixed assets and depreciation | [production cost revision contract](production-output-cost-revisions.md), [repairs module](../../modules/accounting/repair_accounting.py), fixed-asset and production workspaces | Reconcile WIP, production, customer property and depreciation using real policy and source documents. |
| Payroll and statutory amounts | [payroll imports](../../modules/accounting/payroll_import.py), [statutory registry](../../modules/accounting/payroll_statutory.py), [HR draft and manual register](../../modules/hr/routes.py), [explicit employment binding](../../modules/accounting/payroll_employment.py), [versioned employer rules](../../modules/accounting/payroll_rule_set.py), [private source file registry](../../modules/accounting/payroll_evidence_files.py), [accounting workpaper contract](PAYROLL-WORKPAPER-CONTRACT.md), [production estimate](../../modules/production/routes.py) | For the pilot, import a verified external calculation with its receipt. The HR preview and employee handouts are read-only scenarios from manually supplied inputs; legacy HR rows still have no automatic legal-entity ownership or bank-payment proof. The accounting binding requires an explicit employer/contract and does not verify the contract's contents. A chief-configured rule set fixes the arithmetic method, rounding and complete configured list of rate roles/base modes. When it selects a stored policy file, the workpaper verifies its bytes; source contents and statutory applicability remain unverified. The workpaper also verifies stored contract/timesheet file identity and bytes when both IDs are selected, but salary and hours inside them remain human-reviewed claims. It calculates gross from those supplied amounts and every configured current percentage component; exemptions, caps, benefits and any unconfigured legal obligation remain outside it. It cannot post or certify a statutory salary. The production estimate uses fixed 22-day and premium assumptions and is explicitly nonstatutory. Full ERP payroll calculation and period-versioned compulsory forms remain unimplemented. A verified external payroll system may remain the source during staged 1C transition. |
| Opening balances, source ownership and 1C reconciliation without duplicate imports | [pilot input packet](PILOT-INPUT-PACKET.md), [strict manifest](PILOT-INPUT-MANIFEST.md), opening-import controls and tests | Receive signed real policy, balances, source hashes and one closed matched OSV pair. No default organization assignment is permitted. |
| Recovery and release | [release readiness](RELEASE-READINESS-2026-09-22.md) | Owned PostgreSQL upgrade/restore, target DB revision inspection, integration to the release baseline, target backup/restore and release receipt. |
| Replacement of 1C | All rows above are necessary local groundwork | Two successive accepted monthly closes, quarterly cycle, trial annual reporting, documented reconciliation of every variance, and an authorized production release. |

## Current local evidence

- `tests/accounting/test_migration_baseline.py` and
  `tests/accounting/test_reconciliation.py` passed together: **18 tests**.
- The accountant screen exposes organization and date range, plan of accounts,
  journal/OSV reports, period controls and document queue.  The UI tests cover
  organization isolation, review-before-posting, report drill-down and safe
  error handling.
- The close control explicitly checks document completeness, bank, settlements,
  stock, costing, depreciation, FX, tax, financial result and trial balance.
- For the later own-payroll stage, the tax authority's [2026 income-tax rate
  notice](https://nalog.gov.by/news/34207/) and [standard-deduction
  guidance](https://nalog.gov.by/individuals/income_taxation/tax_deductions/9332/)
  show why one percentage multiplication cannot be treated as a complete
  withholding calculation. Their applicability, versions and examples still
  require accountant review before an ERP rule is enabled.

These are local source checks.  They do not replace the real acceptance
conditions in the table and must not be used to mark the pilot, release or 1C
replacement complete.
