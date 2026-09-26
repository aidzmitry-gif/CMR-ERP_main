# Бухгалтерская справка: черновик и проведение

Development source heads `0187` and `0188` add a saved document before an immutable manual
ledger posting. It is separate from the fixed first-release candidate at `0186`.

The accountant selects the legal entity and opens **Документы → Ручная операция**.
After entering the source reference, three dates, explanation, accounts, amounts
and required analytics, **Проверить проводки** calculates the package. **Сохранить**
assigns a stable `БС-{id}` number; **Сохранить и закрыть** also returns to the
workspace only after the server confirms the exact saved version. The register
opens each document by number. Every save adds an immutable revision with the
actor, server time, complete posting snapshot and digest. The card displays
changed fields and each line's old/new account, side, BYN amount, original currency,
quantity, rate, cash activity and analytics alongside preserved earlier
versions. An edited or failed save
keeps the form open. Concurrent edits use `expected_version` and return 409 to
the stale editor; a command UUID allows safe retry of the same save.

**Подтвердить и провести** accepts only the reviewed digest of the latest saved
revision. The server writes the entry and binds it to the document in one
transaction. A retry with the same command returns the same receipt; another
document cannot claim the same already posted source/version. Posted documents
cannot be edited; later correction uses a new linked accounting operation.
Unposted manual documents dated in or before a closing month block its close.
The client checks the returned document/version/digest/entry receipt before it
reports success. Navigation warns about unsaved form changes.

Where an account requires counterparty analytics, the form searches the shared
MDM directory and saves the selected ID, name, UNP and record revision in the
posting snapshot. New manual previews/saves/postings reject free-text or stale
counterparty facts, including the legacy direct-entry route. A previously
posted entry can still be replayed exactly after the directory changes; its
saved ledger dimensions and document revisions are not rewritten. Other
analytical fields are not yet all bound to reference IDs.

Where an account requires `sku`, the form searches the shared active SKU
directory and saves ID, code, title and unit. New manual previews, saves and
postings reject a free-text code or stale SKU snapshot, including the legacy
direct-entry route. A posted entry retains its historical SKU description after
the directory changes and can be replayed exactly.

Where an account requires `warehouse`, the form searches active warehouses of
the selected organization and saves the warehouse ID, code and title. New
manual previews, saves and postings reject free text, a warehouse from another
organization or a stale warehouse snapshot. The exact posted entry keeps its
historical warehouse description after a directory change.

An erroneous **unposted** draft can be annulled with a required reason.
Cancellation creates a separate immutable receipt with author and server time;
the numbered document and all prior revisions remain readable. The cancelled
draft no longer blocks month close and cannot be edited or posted. A posted
document cannot be annulled here and requires a linked correction instead.

This workflow proves software behavior, not an approved Belarusian accounting
policy or correctness of real source documents. It needs an accountant's pilot
review, target database migration rehearsal and the shared release gate before
production use.
