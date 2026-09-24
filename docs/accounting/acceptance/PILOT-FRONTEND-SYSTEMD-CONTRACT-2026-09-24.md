# CRM-ACC-001: frontend systemd contract for the mixed pilot

Status: **prepared, not activated**. This is a candidate and rollback contract
for the existing `cmr-frontend.service`, not a production deployment. The
mixed release remains `NO-GO` under `PILOT-MIXED-RELEASE-2026-09-24.md`.

## Read-only server observation, 24 September 2026

`cmr-frontend.service` is active under `/usr/bin/node` v22.22.3. Its resolved
`ExecStart` is
`/opt/cmr-erp-releases/crm-ready-r4-ui-20260916/frontend/node_modules/.bin/next start -p 3100`,
with the same release's `frontend` as `WorkingDirectory`. The old `.next/BUILD_ID`
is `F_-CH9cdxitoaicSnuYyR`. The unit is `Type=simple`, `Restart=always`,
`User=root`; systemd reports many older drop-ins that change launch paths.
The last active launch override is
`zzzzzzzzzzzzzzzzzz-crm-ready-r4-ui.conf`. Existing OIDC and backend URL
drop-ins must remain in effect; no environment values were copied into this
document.

Caddy's active `Caddyfile` contains upstreams for frontend `localhost:3100`
and API `127.0.0.1:8000`. The `aios_default` Docker network has the main app,
PostgreSQL, Keycloak and Redis. PostgreSQL also listens on host loopback
`127.0.0.1:5432`. The host has additional running restore/test containers and
an inactive Mottor intake service. This inventory does **not** establish that
all possible DB writers, webhooks, direct connections or external integrations
are stopped. A production write freeze needs its own fresh proof.

## Immutable candidate and launch contract

The candidate is the already verified standalone archive
`.harness/artifacts/CRM-ACC-001/frontend-standalone-1fd4e081.tar.gz`:
19,653,244 bytes, SHA-256
`29bb7e29d7679da59c03dbb39e6295337789d5f12dac6c67c4919422eb6aea02`,
`BUILD_ID=NugLquCeWhonBTHKU0uZf`. It contains `server.js`, `.next/BUILD_ID`
and `.next/static`, with no `.env*`. A fresh network-isolated Linux container
started it with Node 22.22.3 and returned Ready, an anonymous accounting
redirect to login and static JS HTTP 200. It has **not** run under the server's
systemd unit or passed authenticated OIDC/accountant checks.

Before any future activation, extract only this checked archive into a **new**
immutable release directory such as
`/opt/cmr-erp-releases/crm-acc-001-1fd4e081/frontend`; verify its extracted
`BUILD_ID`, server.js and checksum provenance. Keep the current release and
all current drop-ins intact. The candidate drop-in would be a new file named
`zzzzzzzzzzzzzzzzzzz-crm-acc-001-frontend.conf` (one more leading `z` than
the observed final launch override):

```ini
[Service]
WorkingDirectory=/opt/cmr-erp-releases/crm-acc-001-1fd4e081/frontend
ExecStart=
ExecStart=/usr/bin/node /opt/cmr-erp-releases/crm-acc-001-1fd4e081/frontend/server.js
Environment=PORT=3100
```

This changes the launch command and directory while retaining the existing
service's OIDC/backend configuration. It is a **template**, not a file to
install before the mixed-release preflight. The service manager must resolve
exactly this `ExecStart` and `WorkingDirectory` after `daemon-reload`; if a
newer drop-in, service edit or unexpected environment wins, stop before
restart. Check the new unit with `systemd-analyze verify` and compare its
resolved properties without printing environment or secrets.

## Activation and rollback invariants

1. First complete the mixed-release gates: exact image/source and server
   fingerprint; all DB writers and ingress; write-frozen, restored DB **and
   files** backup; explicit `0116 → 0176` rehearsal; tested backend/data
   rollback. Do not run v1 backend-only `apply` for this change.
2. Preserve the pre-switch `FragmentPath`, ordered `DropInPaths`, resolved
   launch path, `BUILD_ID` and checksum of the old release. The new drop-in
   must be the only frontend service configuration addition. Do not edit or
   remove older drop-ins to make the candidate win.
3. Only after backend/schema checks, start the candidate in the controlled
   window. Check the resolved systemd properties, service state, exact
   `BUILD_ID`, Caddy route, login redirect and an authorized accountant
   scenario; record the result in the mixed-release receipt before reopening
   writes. A local standalone smoke test is insufficient.
4. To undo the **frontend launch override**, remove only the newly installed
   candidate drop-in, reload systemd and restart the original service. Verify
   that the resolved launch path and old `BUILD_ID` match the preserved
   baseline. This is permissible only when the old frontend remains
   compatible with the actual backend/schema. Frontend rollback does not
   reverse database migration or writes; use the mixed-release data recovery
   decision for those cases.

No server file, service, database, Caddy route or container was changed while
preparing this contract. The template's order and artifact identity were
checked locally; systemd parsing and switch/rollback still require an
isolated end-to-end rehearsal before production activation.
