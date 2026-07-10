# Engineering loop

Use this loop for small, safe improvements in the CRM/ERP project.

## 1. Inspect

- Read the current status before editing: `git status --short`.
- Identify whether the target file is already modified by someone else.
- Prefer stable project surfaces: docs, quality config, tests, or narrowly scoped module files.
- Do not clean, reset, or rewrite unrelated WIP.

## 2. Change

- Keep one intent per change.
- Prefer additive hardening over broad rewrites.
- Update nearby docs when a command, caveat, or workflow changes.
- Avoid touching generated screenshots, local databases, logs, and mockup artifacts unless the task is about those assets.

## 3. Verify

Pick the smallest check that proves the change:

```powershell
.\.venv\Scripts\python.exe -m ruff check core config connectors tests --no-cache
.\.venv\Scripts\python.exe -m pytest tests\test_skeleton.py tests\test_lifespan.py tests\test_core_extras.py tests\test_connectors_core.py -q
npm --prefix frontend run test:run -- --pool=forks
```

In restricted sandboxes, filesystem-heavy tests can fail for environment reasons.
Retry in a normal shell before treating `PermissionError`, SQLite disk I/O, or
`spawn EPERM` as product regressions.

## 4. Commit

- Stage only files that belong to the current intent.
- Use short messages in the form `area: action`.
- If `.git/index.lock` exists, remove it only after checking that no Git operation is active.
- Leave unrelated working-tree changes untouched.

## Suggested four-cycle packet

1. Stabilize local checks.
2. Reduce generated/runtime artifacts.
3. Improve documentation discovery.
4. Record caveats and follow-up risks.
