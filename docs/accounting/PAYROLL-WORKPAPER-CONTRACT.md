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
digests and the rule-set source document are recorded as claims unless the
caller selects both `contract_file_id` and `timesheet_file_id`. With those IDs,
the workpaper verifies the private file bytes against server-calculated hashes,
the legal entity, employee binding, document references and timesheet month.
An optional `adjustment_file_id` similarly checks a documented adjusted rate
base. Missing, changed or cross-entity files block the preview. This proves
file identity and integrity, not the salary or hours stated inside the file.
The chief can also select `source_file_id` when recording the rule-set revision.
The configuration compares the stored file reference and SHA-256 with the
declared policy source; every subsequent workpaper preview rechecks its bytes.
Without this ID, the rule-set source remains a claim. Byte identity never
verifies what a policy document says or whether its rules are legally applicable.
`posting_available=false` and
`statutory_payroll_certified=false` are fixed. A subsequent accepted payroll
workflow must verify source documents and accountant-approved rules, persist
immutable results and corrections, reconcile payment and post only after
separate confirmation.

`POST /accounting/organizations/{org_id}/payroll-evidence-files` stores an
immutable metadata receipt and up to 10 MiB of private PDF, image or Office
bytes. List and download require accountant/chief access to the same legal
entity; download rechecks the hash. The server requires an existing private
absolute `AIOS_PAYROLL_DATA_DIR` and does not accept client filesystem paths.
The file store must be included in backup/restore with the database; no target
storage or recovery has been verified. The receipt is append-only, while the
document's contents and authenticity still require human review.

The existing single-rate arithmetic preview remains available for review of
one supplied base. It has no automatic link to this workpaper and cannot be
used as evidence that a complete payroll run was calculated.
