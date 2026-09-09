# Sales mail staging and relay

This is a standalone Python standard-library worker for the dedicated
`order@microchips.by` mailbox. It has two durable stages:

1. `poll` reads new messages from IMAP `INBOX` in readonly mode and stores raw
   bytes in a private SQLite queue.
2. `relay` sends pending raw bytes to the loopback sales API and marks a row
   delivered only after the API returns the exact deterministic receipt and raw
   hash.

The worker never deletes, flags, moves, or otherwise mutates mailbox messages.
It uses `BODY.PEEK[]`, starts at `UIDNEXT - 1` on first initialization, and
halts durably if `UIDVALIDITY` changes. The queue identity is
`mailbox + UIDVALIDITY + UID`. A queue initialized for another mailbox cannot
be reused.

The API contract is:

```text
POST http://127.0.0.1:8000/integrations/sales-mail/v1
X-Sales-Mail-Token: <secret>
Content-Type: application/json
```

The JSON body is `{mailbox, uidvalidity, uid, raw_sha256, raw_base64}`. The
receipt ID is the lowercase full SHA-256 of the UTF-8 bytes of
`mailbox + NUL byte (U+0000) + canonical_positive_uidvalidity + NUL byte (U+0000) + canonical_positive_uid`.
The response must contain the same `receipt_id` and exact `raw_sha256`.

Run commands from the application checkout:

```powershell
python -m ops.sales_mail.cli init --config C:\path\sales-mail.json --queue C:\path\queue.sqlite
python -m ops.sales_mail.cli run --config C:\path\sales-mail.json --queue C:\path\queue.sqlite
python -m ops.sales_mail.cli status --queue C:\path\queue.sqlite
```

Use a private config file with a real mailbox password and token supplied by
the deployment system. `config.example.json` contains placeholders only. On
POSIX deployment, set mode `0600` for the config and queue. Windows ACLs must
be restricted by the platform administrator; POSIX mode bits do not protect a
Windows deployment. The example systemd unit and timer are documentation only
and are not installed by this checkout.
