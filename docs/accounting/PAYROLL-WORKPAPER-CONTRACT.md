# Payroll workpaper: arithmetic and acceptance boundary

`POST /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-workpaper-preview`
calculates a read-only, organization-scoped gross salary and the explicitly
listed percentage components. It does not create a payroll run or ledger entry.

The accountant salary section links to the existing `/erp/hr/payroll` draft
workbook and printable employee slips. That HR preview is not scoped to an
accounting organization and does not become an accounting source or posting
until its inputs are independently checked and imported with evidence.
Only an accountant or chief accountant with membership in that organization can
call it. The response is private and uncached.

The caller must select an immutable, currently active employee/contract binding
for the entire dated work segment, a verified accounting policy applicable for
the whole month, and the latest immutable payroll rule set configured by the
chief accountant. The rule set records its source document hash, gross method,
rounding and every rate code's role and base mode. The workpaper requires every
configured rate exactly once at its current organization-specific version and
checks that its ID and digest match the version captured when the chief recorded
the rule set. If a rate changes for a later month, the new workpaper is blocked
until the chief records a new rule-set revision for that month; earlier months
retain their applicable rate version. The caller cannot reclassify a deduction
as an employer contribution. It also
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
file identity and integrity. For a structurally valid stored XLSX timesheet,
the caller must also select an exact employee row. The server sums only numeric
day cells of that row over `work_from`–`work_to` and requires equality with
`worked_hours`. The selected row and count of uninterpreted text-coded days
are kept in the calculation basis. The accountant must still confirm that the
row belongs to the employee and interpret all codes; the salary amount and
monthly norm remain documented inputs rather than parsed contract facts.
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

For a stored timesheet, `GET /accounting/organizations/{org_id}/payroll-evidence-files/{file_id}/timesheet-preflight`
rechecks the private bytes and returns a redacted structural report. A selected
XLSX with an unreadable or inconsistent month, day headers, formula, cached
hours, day count or personnel identifier blocks a **new arithmetic review**;
upload and read-only preview remain available for investigation. A PDF or
other supported source is marked `manual_source` and remains a human-review
case. A passing XLSX structure exposes redacted row numbers for explicit
selection; it does not identify which row belongs to the employee, interpret
time codes, validate the contract or authorize statutory payroll.

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

The current rule-set API exposes `rate_versions` (the immutable configured
requirement IDs and digests) together with the rate roles and base modes. The
accountant workspace's **Расчётный лист** tab uses those IDs, an explicitly
selected employer binding and stored contract/timesheet/adjustment-file receipts
to call the read-only workpaper preview. Salary, norm hours, worked hours and
the locations of the facts in the documents are entered explicitly. The tab
shows the full arithmetic trace and source-byte flags. An accountant or chief
can upload a contract, monthly timesheet or rate-base adjustment for the
selected binding. The upload receipt is scoped to that organization, binding,
kind and month, and a lost POST response is recovered by its idempotency key
before any retry. The private file store must be configured and backed up with
the database. A missing source or configuration blocks the preview rather than
supplying a default.

The **Правила расчёта** tab now lets the chief configure that immutable
organization/month rule set in the accountant workspace. It requires an
explicitly selected verified accounting policy, stored organization-scoped
`payroll_policy` file, supported gross method and rounding, each effective
percentage rate's role/base mode and classification evidence. The UI submits
the displayed requirement IDs and digests as `expected_rate_versions`; the
server rejects a changed version instead of silently binding a newer rate.
The POST is idempotent by request key. If its response is lost, the UI reads
`GET /payroll-rule-sets/by-request/{request_key}` in the same organization and
keeps the frozen command for replay until the outcome is known. Accountants
can read the current configuration; only a chief can create a revision. This
is a configuration of arithmetic, not proof that all statutory rates or source
facts are correct.

For a byte-backed preview, the chief alone may enter an explanation and record
an immutable arithmetic-only review. The UI reads the monthly summary to find
the latest review of that exact binding and date segment; a changed calculation
supersedes that receipt instead of overwriting it. A lost review response is
resolved by request key, and an uncertain request is retried with the same
body. This does not post a payroll run or ledger entry, verify that the facts
inside source files are true, or certify legal rates. The chief must still
configure the rule set with a stored policy file in **Правила расчёта**;
the workpaper tab links to it when no current rule set exists.

The accountant workspace's **Контроль зарплаты** tab reads this monthly
summary and the private `payroll-source-reconciliation` result for the selected
legal entity and month. It shows missing intervals, the latest reviewed totals,
differences from posted external imports and links to their ledger entries.
Changing the organization or month discards the previous view; a response with
a different scope is rejected. This is a read-only control, not an interface
for creating a workpaper, confirming a payroll result or submitting a form.

For a month with at least one **known** active employer/contract binding,
closing controls require reviewed gross-payroll import receipts covering each
known active binding or an organization-scoped `payroll_zero_activity` file
when there are no payroll postings. The
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

Migration `0168` uses those stable IDs to close that gap for **known** active
bindings. When gross-payroll receipts exist, every imported gross line must
carry a binding ID, and every known active binding needs at least one such
line or a chief-uploaded `payroll_zero_individual` source file for that binding
and month. The individual file is byte-checked before application-level close;
a later mapped accrual supersedes it as the closing basis without deleting it.
The closing-controls response lists missing binding IDs, unmapped line count,
and the individual files currently used. PostgreSQL also refuses a direct
period close when this coverage is incomplete. A whole-month zero file remains
the route for a month without payroll postings; individual zero files do not
replace it. Source documents are stored, not interpreted by the software:
truth of the zero-accrual statement, completeness of the real workforce and
statutory payroll remain subject to accountant review.

`GET /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-source-reconciliation`
compares the latest reviewed workpaper arithmetic with posted external gross,
deduction and contribution imports by `employment_binding_id`. It lists the
entry IDs, differences for each binding, missing gross and statutory mappings,
conflicting individual statutory-zero documents and unmapped source lines.
An individual statutory-zero document is counted only after its stored bytes
are checked against its receipt. Before using an import, it checks the receipt identity and hash,
its stored posting and the actual ledger lines. `matched_arithmetic_only`
requires a current known-roster review, complete known workpaper date coverage,
both import types, no missing statutory source per gross binding, no conflicting
zero document, no unmapped lines or receipt gaps, and zero differences.
The response remains private, read-only and explicitly uncertified. A matched
arithmetic result does not establish document authenticity, complete real
employee population, legal rate applicability, payroll payment or readiness
of an external statutory form.
When reviewed workpapers and gross-import receipts coexist, month-closing
controls show an incomplete or differing reconciliation to accountants and
chief accountants as a review item. Readers of the general closing controls
do not receive the private reconciliation status or difference count.
This is a visible accountant decision, not automatic acceptance of the
provisional workpaper or a substitute for a documented pilot variance.

Migration `0171` adds a separate closing source for deductions and employer
contributions. A month with a reviewed gross-payroll import cannot close until
it has a reviewed statutory-import receipt or a chief-uploaded, month-scoped
`payroll_statutory_zero` document stating that no such amounts apply. The zero
document is byte-checked again at application close; a conflicting statutory
posting blocks close. PostgreSQL checks the source presence and conflict even
for a direct period update. The software does not decide whether zero amounts
are legally justified or whether imported lines cover every applicable tax
and contribution. The chief accountant must verify those facts against the
current rules and the source register before accepting the pilot month.

Migration `0172` closes the partial-import case. When external statutory lines
exist, each line must carry a stable employment binding, and each binding with
gross accrual needs a statutory line or a chief-uploaded
`payroll_stat_zero_person` file for that binding and month. A zero file for a
binding that also has an imported amount is contradictory. Closing controls
show missing binding IDs and unmapped lines; application close rechecks the
individual files, while PostgreSQL rejects a direct close with incomplete
binding coverage. This proves source assignment to known ERP contracts, not
the completeness of the real workforce or each legally applicable component.
