# Payroll workpaper: arithmetic and acceptance boundary

`POST /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-workpaper-preview`
calculates a read-only, organization-scoped gross salary and the explicitly
listed percentage components. It does not create a payroll run or ledger entry.
Only an accountant or chief accountant with membership in that organization can
call it. The response is private and uncached.

The caller must select an immutable, currently active employee/contract binding
for the entire dated work segment, a verified accounting policy applicable for
the whole month, an identified contract amount and timesheet with document
references and SHA-256 strings, exact monthly norm and worked hours, the
`monthly_salary_by_hours` arithmetic method with its own policy evidence, and
`half_up_cent` rounding evidence. For each listed rate, the caller selects the
current organization-specific percentage requirement, its deduction or
employer-contribution role, the classification basis and any documented
adjustment to gross. Missing or inconsistent inputs fail closed; no role salary,
rate, time norm or tax deduction is supplied by the application.

The workpaper reports `gross_byn`, amounts for **listed** components,
`after_listed_deductions_byn`, `cost_including_listed_contributions_byn` and a
digest of the full calculation basis. These totals are not a statutory net
salary or complete employer cost: unlisted components, eligibility, caps,
exemptions, benefits and period aggregation are not calculated. Document
digests, method applicability and rate classification are recorded as claims,
not verified by the API. `posting_available=false` and
`statutory_payroll_certified=false` are fixed. A subsequent accepted payroll
workflow must verify source documents and accountant-approved rules, persist
immutable results and corrections, reconcile payment and post only after
separate confirmation.

The existing single-rate arithmetic preview remains available for review of
one supplied base. It has no automatic link to this workpaper and cannot be
used as evidence that a complete payroll run was calculated.
