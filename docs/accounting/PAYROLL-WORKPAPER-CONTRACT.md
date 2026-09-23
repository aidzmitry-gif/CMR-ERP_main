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
exemptions and benefits are not calculated; this single-segment preview does
not aggregate a period. Document
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

`POST /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-workpaper-reviews`
records a chief accountant's immutable **arithmetic-only** review. It requires
the exact preview basis digest, stored and byte-verified contract, timesheet,
policy and any adjusted-rate source files. A repeat of the same request key
returns its original receipt. An amended calculation creates a new revision
linked to the latest receipt; the old one remains readable through
`GET /accounting/organizations/{org_id}/payroll-workpaper-reviews/{request_key}`.
Overlapping work segments for the same binding and month are rejected.
New reviews are blocked when this or a later period is closed. The receipt
records the bytes verified at review time but does not claim that files remain
unchanged later, that their figures are true, or that statutory payroll is
complete. It does not post to the ledger.

A new dated employer/contract binding is also blocked once its month or any
later accounting period is closed; a repeat of an already accepted request
still returns its original receipt. Revision `0165` enforces this at the
PostgreSQL insert boundary as well as in the API. Corrections to closed history
require the controlled reopening process before a new dated binding is added.

`GET /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-arithmetic-summary`
reads all immutable reviewed segments of one legal entity and month. It checks
receipt hashes, scope, component arithmetic and correction chains, then sums
only the latest revision of each non-overlapping work segment. The response
lists selected receipt IDs and basis/snapshot hashes; `selection_digest` changes
when a selected revision changes. `coverage_digest` changes when the known
employment timeline changes; `summary_digest` binds both digests and totals.
Accountant/chief membership is required.
`known_binding_coverage` compares selected segments with the current effective
history of **explicitly bound** contracts, reporting unreviewed date intervals
and segments outside that history. A complete result covers only contracts
already recorded in this organization's binding registry; unbound employees,
authenticity of contracts, hours, payments and applicable legal rules remain
unknown. Therefore `organization_payroll_population_verified`,
`coverage_verified`, `source_facts_verified`, `posting_available` and
`statutory_payroll_certified` remain false. No ledger entry, payroll run or
external form is created.

For a month with at least one **known** active employer/contract binding,
closing controls now require a matching reviewed gross-payroll import receipt
or an organization-scoped `payroll_zero_activity` file for that month. The
latter is uploaded only by the chief accountant through the existing private
payroll file endpoint, with explicit evidence, and its bytes are rechecked
before application-level close. A later payroll posting supersedes the zero
file for closing purposes; the file remains immutable and the conflict is
shown for review. A posting without its matching month receipt still blocks
closing. Migration `0166` also refuses direct PostgreSQL period close when a
known active binding has neither source. Zero files cannot be newly attached
to closed months. These checks cover only contracts registered in this book;
they neither verify the document's statements nor establish the complete
employee population or statutory payroll. The pilot manifest remains the
separate source-of-truth declaration for the real pilot month.

The chief can additionally upload a monthly `payroll_population` source file
and record `POST /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-population-reviews`.
The review stores the claimed source employee count and sorted employee and
employer-binding IDs. It accepts only the exact IDs currently known for that
book/month, links the byte-checked source file and preserves corrections as
append-only revisions. The latest review becomes stale when another known
binding is added or corrected. For a month with known active bindings, close
requires a current review and rechecks the source file bytes; PostgreSQL
revision `0167` also blocks a direct close without the matching review. The
GET payroll-population endpoint exposes the latest review and whether its IDs
still match. This makes responsibility for roster completeness explicit; it
does **not** parse the roster's contents, prove that every real employee was
entered into ERP, validate payroll amounts, or certify a statutory form.

External gross-accrual and deductions/contributions import lines can now carry
an `employment_binding_id`. When supplied, the preview checks that the binding
belongs to the selected legal entity, existed by the payroll month, and retains
the same employee name in its immutable employer snapshot. The stable ID is
preserved in the source-bound receipt. Existing imports without this optional
field keep their original command shape and replay identity. An omitted ID is
explicitly reported as an incomplete stable mapping in the preview; this
change alone does not prove that every employee in the reviewed roster received
an accrual or a documented zero amount.
