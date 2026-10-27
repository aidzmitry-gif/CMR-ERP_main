# Security hardening candidate, 2026-10-27

Reference reads now require `refs.view`. The grant follows the existing
`spravochniki` role matrix; ordinary sales/warehouse/onboarding roles do not
gain access to financial master data. Existing reference write restrictions
remain in place. Owner AI insight requires `system.write` before DB or LLM work.

Knowledge course/enrollment writes have separate permissions, granted to HR
and the existing super roles. Legal case writes require `legal.case.write`.
Office document, stage and carrier writes use the existing permissions;
finance and assistant keep those workflows. Contract and claim writes have
separate permissions. Super roles and the existing office manager retain access.

The frontend disables `X-Powered-By`, sets `frame-ancestors 'self'` and
`SAMEORIGIN`, and allows camera/microphone/geolocation only to the current origin.
No script policy is enforced without a separate browser compatibility review.
Next 15.5.28 and React 19.2.9 are pinned; PostCSS/Sharp overrides address vulnerable
transitive dependencies without a Next major upgrade.

Production and development Python locks include hashes and platform markers.
Compatible production dependency versions are preserved in
`requirements.constraints.txt`; vulnerable dependencies use fixed versions.
Regenerate with:

```sh
uv pip compile requirements.txt -c requirements.constraints.txt --python-version 3.12 --universal --generate-hashes -o requirements.lock.txt
uv pip compile requirements-dev.txt -c requirements.lock.txt --python-version 3.12 --universal --generate-hashes -o requirements-dev.lock.txt
```

CI installs the exact locks, audits Python through OSV and npm production
dependencies, and scans Git history with Gitleaks. `.gitleaksignore` contains
only 13 reviewed historical fingerprints: checksums, operation IDs and documented
placeholders. No rule or path is disabled. No live credentials were identified
in those findings; this is not proof that all secrets are absent.

The backend image uses UID/GID 10001. Before releasing, verify writable data
mounts for that identity and exercise startup/migrations on the accepted schema.
Never change production volume ownership without identifying its consumers.

Validation: 192 RBAC/functional cases, 2499 frontend cases, full Ruff,
frontend typecheck/lint/build and HTTP header readback passed locally.
OSV and npm production audits report no known vulnerabilities; historical and
staged Gitleaks scans pass with the reviewed fingerprints above. The 27 additional
OIDC/PDF cases yielded 23 passes and four PDF failures on Windows: direct import
confirms missing native `libgobject-2.0-0`. Linux CI and the image's native PDF
smoke must pass before accepting PDF compatibility. Mandatory CI remains a gate.

This candidate is not a production release. Integrate its selected changes into
the accepted application/frontend sources; the current deployed tree contains
additional changes absent from main. Preserve its schema, data, feature flags
and release baseline. Keycloak, DNS and server exposure changes have their own
release and acceptance steps.

No impact on the WMS training instruction: warehouse operations, screens and
commands are unchanged; the affected reference API is used by the reference UI.
Training administration permissions are restricted, with HR authoring preserved.
