# Payroll workpaper: arithmetic and acceptance boundary

`POST /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-workpaper-preview`
calculates a read-only, organization-scoped gross salary and the explicitly
listed percentage components. It does not create a payroll run or ledger entry.
Only an accountant or chief accountant with membership in that organization can
call it. The response is private and uncached.

The caller must select an immutable, currently active employee/contract binding
for the entire dated work segment, a verified accounting policy applicable for
the whole month, and the latest immutable payroll rule set configured by the
chief accountant. The rule set records its source document hash, gross method,
rounding and every rate code's role and base mode. The workpaper requires every
configured rate exactly once at its current organization-specific version; the
caller cannot reclassify a deduction as an employer contribution. It also
requires an identified contract amount and timesheet with document references
and SHA-256 strings, exact monthly norm and worked hours, and documented
adjustment to gross where the configured base mode needs it. Missing or
inconsistent inputs fail closed; no role salary, rate, time norm or tax
deduction is supplied by the application.

The workpaper reports `gross_byn`, amounts for **listed** components,
`after_listed_deductions_byn`, `cost_including_listed_contributions_byn` and a
digest of the full calculation basis. These totals are not a statutory net
salary or complete employer cost: unlisted components, eligibility, caps,
exemptions, benefits and period aggregation are not calculated. Document
digests and the rule-set source document are recorded as claims; their
authenticity and statutory applicability are not verified by the API.
`posting_available=false` and
`statutory_payroll_certified=false` are fixed. A subsequent accepted payroll
workflow must verify source documents and accountant-approved rules, persist
immutable results and corrections, reconcile payment and post only after
separate confirmation.

The existing single-rate arithmetic preview remains available for review of
one supplied base. It has no automatic link to this workpaper and cannot be
used as evidence that a complete payroll run was calculated.
