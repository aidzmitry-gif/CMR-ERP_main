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
row belongs to the employee and interpret all codes. The server rejects an XLSX
row whose name in column C or personnel code in column B does not match the
binding's stored employee name and chief-supplied personnel identifier. The
preview stores only match booleans, not raw names or codes from the XLSX. An
old binding without a personnel identifier remains readable but cannot support
a new XLSX workpaper until a new dated employer-binding revision is recorded.
Matching a chief-supplied identifier is not proof that the underlying HR
document is authentic or that the person legally holds the contract.
The salary amount and
monthly norm remain documented inputs rather than parsed contract facts.
For a monthly norm, the accountant can attach a private `work_schedule` file
scoped to the same legal entity, employment binding and month, with the exact
location of the norm in that document. The workpaper rechecks its bytes and
records the file reference, SHA-256 and ID in the immutable calculation basis.
For a non-XLSX schedule, it does not parse the document or certify the entered norm.
For a stored XLSX work schedule, the accountant selects the exact cell on its
single month-labelled sheet. The preview rereads the stored bytes, requires a
literal numeric value (not a formula or cached formula result), and compares
it with the entered monthly norm. A missing cell, wrong month or differing
number blocks a new arithmetic review. The selected cell and comparison result
are retained in the basis. PDF and other supported schedules still require
manual confirmation of the norm; a matching XLSX cell does not establish the
schedule's approval, legal applicability or employee identity.
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
`work_schedule` is a monthly employee-bound source, subject to the same private
storage, receipt and backup rules as the timesheet.
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
work schedule, policy and any adjusted-rate source files. The preliminary
preview may omit a schedule for investigation, but it cannot receive a new
chief-review receipt until the schedule is attached. A repeat of the same request key
returns its original receipt. An amended calculation creates a new revision
linked to the latest receipt; the old one remains readable through
`GET /accounting/organizations/{org_id}/payroll-workpaper-reviews/{request_key}`.
Overlapping work segments for the same binding and month are rejected.
New reviews are blocked when this or a later period is closed. The receipt
records the bytes verified at review time but does not claim that files remain
unchanged later, that their figures are true, or that statutory payroll is
complete. It does not post to the ledger.

The chief may separately attest that the salary amount, worked hours and
monthly norm were checked against the contract, timesheet and work schedule.
This is an explicit `source_fact_attestation` plus a document-location
`source_fact_evidence` in the same immutable receipt; neither field is inferred
from file hashes or arithmetic. Historical arithmetic-only receipts remain
unattested. A later attestation of the same calculation is a new linked
revision, and a corrected calculation does not inherit the earlier attestation.
The monthly summary counts attested selected segments and lists those still
missing this human check. `source_facts_verified` remains false because the
application has not independently verified document truth or applicability.

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

`GET /accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-own-candidate`
returns a read-only, content-addressed monthly candidate built only from the
latest chief-attested workpaper segments. It repeats current source-file byte
checks, checks the known binding intervals, the chief's current population
roster and its file, and the configured rule-source and rate versions. A stable
`candidate_digest` identifies the exact source selection and blockers; a roster
or review change produces a different digest. The totals omit un-attested
segments and cannot be treated as a full payroll amount when coverage is
incomplete. The configured list of percentage rules still does not prove all
applicable employee-specific deductions, caps, benefits and exemptions. The
candidate always reports this normative blocker and cannot post, pay or create
compulsory forms. No candidate receipt is persisted by this read-only API.

The chief may upload a private `payroll_organization_rule` file for one
organization and month, then POST a sourced organization-rule review at
`/accounting/organizations/{org_id}/periods/{YYYY-MM}/payroll-organization-reviews`.
Each of the existing tax, FSZN and work-injury rule-gap codes has an explicit
`applicable`, `not_applicable` or `unresolved` decision, a written finding and
a locator inside the selected file. The command has a request key and may
supersede only the current revision. `GET .../current` rechecks current file
bytes; `GET /accounting/organizations/{org_id}/payroll-organization-reviews/by-request/{key}`
recovers a lost write response. The candidate includes the current review
digest and the still-unresolved codes, so a correction changes its digest.
All statutory rule gaps remain visible even when a chief records a decision:
the software has not verified the legal text, employer tariff or policy.
Closed periods reject new files and reviews; no rate is inferred, and posting,
payment and forms stay disabled.

Each newly configured percentage rate may now carry an explicit obligation
code for income-tax withholding, FSZN or work-injury insurance. The accountant
UI requires this selection for a new rule-set revision. Historical rules without
it remain replayable but the monthly candidate reports
`payroll_rate_obligation_unmapped`. The candidate compares the mapped code
with the current chief's organization/month rule review: absent or unresolved
decisions report `payroll_rate_obligation_unreviewed`; `not_applicable` with a
configured rate reports `payroll_rate_conflicts_with_organization_review`.
This is source-trace and conflict detection, not verification of a rate, base,
cap, exemption or the completeness of mandatory payroll obligations. The
statutory blocker, posting/payment prohibition and external-import path remain.

The organization/month chief review may additionally record the preceding
month's national average wage for an applicable FSZN fact: exact BYN amount,
month, publication date and official Belstat URL. Its existing private
`payroll_organization_rule` file is the source receipt, rechecked by bytes on
current reads; the accountant identifies the amount within the document.
The accountant form can submit only the FSZN fact from that wage source; it
does not require inventing decisions about income tax or work-injury insurance
from an unrelated Belstat document.
Historical reviews without this optional fact retain their request digests.
A wrong wage month is rejected. The monthly candidate then compares five times
that explicit wage with the sum of **listed, chief-attested** FSZN component
bases across all selected workpaper segments for the same ERP employee. A
different FSZN base within one segment blocks the comparison. Exceeding the
ceiling raises a specific recalculation blocker while the earlier percentage
amounts remain unchanged. The comparison is not a statutory contribution
base: unrecorded payments, excluded categories, professional pension insurance,
minimum contributions and special rules still require separate evidence.
Posting, payment and mandatory forms remain unavailable.

The chief may also cite the payroll month's minimum wage for an Article 9
comparison, using a separate byte-checked organization/month evidence file,
its digest, official MNS or Mintrud URL, publication date and exact location.
The employee applicability review records whether the chief found the general
minimum applicable or one of Article 9's listed exceptions, with a private
employee/month source. When applicable, the chief also records the sourced
full-month norm of hours separately from the employee's individual schedule.
Without it, the candidate gives no number. Existing review digests remain unchanged when these
optional facts are absent. From already attested segments of one ERP employee,
the candidate sums worked time, checks one binding, consistent segment norms
and the separately attested full-month norm, then checks one
set of listed FSZN rates, and compares the existing listed components with a
time-adjusted minimum from the explicit wage. Ambiguous inputs produce a
blocker instead of a number. The comparison is provisional: unlisted payments,
true tariff/category, source authenticity and employer-specific policy remain
unverified; it never changes contribution totals or permits posting/payment.

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
Before returning a current monthly arithmetic summary or reconciliation, it
rechecks the stored bytes and receipt claims for each latest segment's policy,
contract, timesheet, work schedule and rate-base adjustment files. Missing or
changed source bytes reject the current view; historical review receipts remain
readable. `current_file_bytes_verified` describes that byte check only, not
document authenticity, the truth of salary/hours or statutory applicability.
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
