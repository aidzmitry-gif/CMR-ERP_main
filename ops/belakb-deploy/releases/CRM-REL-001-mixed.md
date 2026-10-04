# CRM-REL-001 mixed release preparation

Status: **ISOLATED REHEARSAL VERIFIED**, `release_ready=false`. This route exports committed
backend sources and proves an isolated migration/restore. It has no production
apply command and does not modify or bootstrap `/opt/belakb-deploy-v1`.

Backend application checkpoint: `a2e9f615237d3af33e7f4292f36ed529f6164b70`.
Current frontend application checkpoint: `a6644cc29bae24109daf98ebaed316a1e4b782df`.
The final package checkpoint must be an exact commit containing these ops files;
its selected backend Git objects and ten module gitlinks must equal the accepted
backend checkpoint. Working files and untracked files are never exported.

## Immutable backend source and image

`prepare_mixed.py --isolated-opt-in CRM-REL-001-isolated-only source --repo <repo>
--package-checkpoint <final-40-hex-commit> --output <new-absolute-directory-outside-repo>`
exports `context/source`, `context/Dockerfile` and a hash-bound `manifest.json`.
The source roots are config, connectors, core, integrations, modules, migrations,
docker and scripts, plus main.py, requirements.txt, alembic.ini, pyproject.toml,
the committed Dockerfile and the two accepted integration proof programs.
Sales runtime imports additionally require exactly the committed files
`ops/sales_mail/{__init__.py,config.py,queue.py,relay.py}`. The rest of ops is excluded.
Each pinned module exports committed code/template/schema assets, including SQL guards. Root docs,
frontend, private datasets, .env files, keys and generated caches are excluded;
Environment blobs are excluded before any content read; other selected secret/data
paths or symlinks cause refusal. Review the manifest for
runtime assets outside these declared roots before accepting source closure.

Root builds the generated context with `docker build --network=none --pull=false`.
It uses dependency runtime
`sha256:469fbba3826e14647fb9b03280843ff591fc6f875244bb17e08f51043ef21319`;
the whole inherited `/app` is removed before COPY. No apt/pip installation occurs.
The cached runtime already passed pip/native PDF probes, but is not a release image.

`prepare_mixed.py --isolated-opt-in CRM-REL-001-isolated-only verify-image
--manifest <manifest.json> --manifest-sha256 <sha256> --image <new-full-image-id>
--receipt <new-absolute-receipt.json> --probe-state-root <receipt-parent-directory>`
requires an existing private 0700 owner directory on server. It repeats pip check, exact file hashes/no stale files,
entrypoint/provenance, requirements compatibility, imports, Alembic head and
native Cyrillic PDF extraction. These probes have no source bind or network access.
The required head is `crm_rel_001_output_source_01`.

Every probe fsyncs an atomic private JSON record containing name, owner, immutable
image, network and cidfile **before Docker create**, and uses `--cidfile` to retain
the exact ID. Records/CID files stay directly in `--probe-state-root`, which must
equal the absolute receipt's parent; rehearsal uses its own private output directory.
There is no default temporary directory or resource sweeper. After an interrupted
process, recover one known record with
`prepare_mixed.py --isolated-opt-in CRM-REL-001-isolated-only recover-probe
--state <absolute-probe-record.json> --state-sha256 <current-record-sha256>`.
Recovery validates record identity/root/CID and reuses strict image/owner/network/
mount guards before deletion by full ID. Ambiguous state or cleanup errors refuse
success and retain the pending record. Docker absence is accepted only at exit1
with an anchored known error (including lowercase `error: no such object`);
permission errors, mixed messages, timeouts and other failures are rejected.

## Fresh copy and independent restore

Root supplies a current hash-bound baseline JSON with `schema: ["0116"]`, exact
`app_id`, `app_image`, `pg_id`, and `runtime_sha256` using the existing v1 runtime
projection. Current IDs/config hashes must be remeasured before execution.

The hash-bound data contract is `{ "format": 1, "chain": "CRM-REL-001",
"transformations": [], "link_checks": [{"name": "<accepted-key-invariant>",
"sql": "SELECT <exact-invariant>"}] }`. Fill actual key/link checks from the
measured original schema. Default comparison includes every original table,
column, row multiplicity and exact PostgreSQL numeric/integer sums. No table is
excluded except Alembic's version table. Any intended historical data change must
name a proper subset of non-key columns and an exact `oracle_sql` SELECT returning
all original columns on the reference copy. Primary/FK columns and undeclared
columns remain unchanged; blanket accounting/CRM table waivers are refused.

`rehearse_mixed_copy.py --isolated-opt-in CRM-REL-001-isolated-only
--manifest <path> --manifest-sha256 <sha256> --baseline <path>
--baseline-sha256 <sha256> --data-contract <path> --data-contract-sha256 <sha256>
--image <new-full-image-id> --output /opt/cmr-erp-rehearsals/CRM-REL-001/<new-run>`
requires root on the measured host. It checks production identity/head, reads a
fresh `pg_dump -Fc`, records UTC/hash/bytes and keeps dump/list/fingerprints on
server in a new 0700 directory with 0600 files. This is a consistent live-read
copy, not a write-frozen production rollback backup.

The first PostgreSQL owns a fresh anonymous volume, `network=none`, no published
ports and only the readonly private dump bind. Both reference and upgrade DBs are
actually restored at 0116. The candidate image upgrades the isolated DB through
its shared loopback network namespace, then original-column hashes/counts/sums,
exact declared transformations and links are checked. Alembic is executed twice.
A separately created PostgreSQL is restored from the original dump **after** the
upgrade; its original head/hashes/counts/sums/links must match the first reference.
Production image/IDs/runtime projection/head are checked again.

Partial resource IDs/names are recorded before creation. Cleanup verifies exact
ID/name/owner/image/network/mounts and rejects any production mount; it attempts
all owned resources even if one guard fails. Cleanup uncertainty makes the final
receipt fail. Only receipt metadata/hashes leave the server; dump/data fingerprints
stay private. Interruption runs the same cleanup and cannot report success.

## Remaining release gates owned by coordinator

Actual new image build/verification, fresh-copy contract, upgrade and second
restore receipts remain required. Source preparation/local tests are not these
server proofs. No production service/container/config/database is changed here.

Frontend is a separate committed production OIDC build and standalone package;
the accepted dev build is insufficient. Bind source/lockfile/artifact hashes,
BUILD_ID and public OIDC fields (`oidc`, issuer
`https://auth.belakb.by/realms/aios`, client `aios-backend`, origin
`https://belakb.by`). Root owns this packaging and its actual proof. Retain the
measured return point `/opt/cmr-erp-releases/crm-ready-r4-ui-20260916/frontend`,
BUILD_ID `F_-CH9cdxitoaicSnuYyR`, until separately authorized switching.
G08 still owns production writer freeze/rollback backup/switch/user OIDC scenario.
This card cannot become RELEASE_READY without actual backend/copy/restore/frontend
proofs and a reviewed recovery route.

## Verified isolated results — 2026-10-03

Application checkpoint remains `a2e9f615237d3af33e7f4292f36ed529f6164b70`.
The built source/tools package is checkpoint
`d9b405b32d33c6e2e8cd78aa6de62ec38a8cb816`; later evidence-card edits do not
change that package identity or the application Git objects.

- Backend image: `sha256:055b3c085487b50eb09a2d0158b02ce7d76bde3db3c4bf88868487f87c106ce8`.
  Source manifest: `640fbe198c0ba88791f810d3fee67fe6a9e57e60aa0791f9699788b2443ade46`.
  Exact image source, installed requirements, pip check and native Cyrillic PDF
  passed. Its actual Docker entrypoint/PID1/health200 passed against an owned
  empty PostgreSQL with writers/automigrate disabled; no source bind or egress.
  That empty fixture is not a backup or a production/OIDC startup acceptance.
- Historical frontend, superseded by the renewal below: source checkpoint
  `a2e9f615237d3af33e7f4292f36ed529f6164b70`,
  BUILD_ID `nmkv-Zps_gDgnIgq5V-R3`, archive
  `cfc70256b8f1423cb5203f1b1f58f5ca579f2274c4d98388e7ec030a919af1e5`.
  On Linux, isolated startup, login200, OIDC-start307/PKCE and locked Linux Sharp
  PNG passed. Actual OIDC login and client hydration remain unproved.
- Fresh copy: `/opt/cmr-erp-rehearsals/CRM-REL-001/G06-fresh-copy-d9b4-01`.
  Backup `database.dump`: 2,294,689 bytes,
  SHA256 `af335aa9b4794132e9ab4b488bfd827294844a8435182f8e70829ed78ce0abb1`.
  It is a consistent read-only live snapshot, not the final write-frozen rollback
  backup for a production switch. All backup and business rows remain on server.
- Upgrade from measured `0116` to `crm_rel_001_output_source_01`, repeated upgrade,
  and a second independent restore of the original backup after upgrade passed.
  All original columns/row multiplicities/exact numeric sums for 113 tables and
  60,334 rows survived; 28 explicit relationship checks matched. No transformations.
  Protected fingerprint artifact SHA256:
  `f2694d97f0d3d7142442be3ec049cc1a4c9d1ab0910d795145485688d4885ec1`.
- Guarded removal of owned containers/anonymous PG volumes completed. Exact
  container absence and unchanged live image/IDs/config were audited afterwards.
  Live schema remains `0116`; production changes are zero.

The canonical evidence is under `.harness/work/CRM-REL-001-evidence` in the project
workspace: `G06-backend-pg-startup-result.json`, `G06-backend-r2-copy-result.json`,
`G06-post-copy-audit.json`, `G06-frontend-linux-r2-result.json` and
`G06-source-reuse-boundary.json`. G04/G13 synthetic financial/UI scenarios remain
applicable: only these ops files changed after their accepted application commit;
the 747 common exported files match after LF/CRLF normalization. Test-only files
and private module documentation are deliberately absent from the runtime image.

Historical July/August close is blocked by missing confirmed analytical opening
balances, source/OSV snapshot identity and unexplained turnover differences
58.91 BYN (July) / 1,521.86 BYN (August), plus accountant allocation/payroll rules.
No balancing entries, live period close or forced migration were performed.
G10/G11 must resolve these prerequisites before G07 RELEASE_READY; production
freeze/final backup/OIDC browser acceptance/switch/final receipt belong to the
existing release coordinator. The v1 mixed-release refusal remains unchanged.

## Exact frontend renewal and current server baseline — 2026-10-04

G15 checkpoint `a6644cc29bae24109daf98ebaed316a1e4b782df` changes only the
login error guard and its regression test. An OIDC error now remains readable
after reload; the explicit retry and normal automatic sign-in still work.
Focused tests (22), typecheck, lint, production build and actual browser
error/reload/retry passed. This is not proof of authenticated candidate access.

G16 binds that committed frontend to BUILD_ID `8T71p1XFiqZ472xNljdbL`:
893 selected source files match the commit after LF/CRLF normalization
(891 raw-byte matches; two files differ only in line endings), and the locked
dependency closure is unchanged. Immutable archive:
32,901,860 bytes, SHA256
`429f5318795cc20180618057ca81779b5edc0ce5e66f3f9201652e4554d8293b`.
All 2,671 runtime files match the manifest. Source manifest SHA256:
`ad5c7849951a69ad20e7b79a4a069e4667dc5fd25590457db7911709e005b885`.

On the measured server, the existing guarded probe ran in a new private network
namespace with zero egress routes. Linux Sharp PNG, login200, exact login chunk,
OIDC-start307, S256 and HttpOnly state cookies passed; the redirect was not
followed. The owned Node process stopped and a separate readback verified its
absence, private file permissions and every extracted file hash. Durable receipt:
`/opt/cmr-erp-rehearsals/CRM-REL-001/G16-frontend-a664-01/receipt.json`, SHA256
`b74f11cc491d293f2c2cb622f701c9f6d6493f32af66bcc645eccf00350c7413`.

The SSH access, expected host/Node and existing tailscaled service were confirmed.
Before/after observations at 04:01:47 / 04:04:07 UTC agree on production
container IDs, images, schema `0116`, runtime/environment/Compose hashes and
installed v1 runner hashes. No production or access configuration changed in
this run. Current runtime projection SHA256:
`860a14eb63d10d7ecc57fbfb8a164e2ca3d4af65df6b20e6f24d9c063ee81430`.
Current baseline evidence: `G16-frontend-renewal/after-baseline.json`; the
comparison excludes only the observation timestamp.

Measured Git reuse confirms unchanged backend, migrations, ten module gitlinks,
business pages and auth kernel. The accepted backend image and historical G06
copy/restore proof above remain applicable within that unchanged source boundary;
no new database dump or migration run is claimed for October4. The old frontend
runtime proof is replaced by G16. Evidence under `G16-frontend-renewal` includes
`linux-result.json`, `server-readback.json`, `baseline-comparison.json` and
`source-reuse-boundary.json`.

Full isolated OIDC login is still **NOT_PROVEN**: this sealed frontend has a
production callback; an existing isolated callback/IdP allowlist/backend must be
proved before attempting authenticated candidate access. G10/G11 discrepancies
remain deferred by the user. `release_ready=false`; no coordinator handoff,
production switch, live 1C/ERP close, or push has occurred.
