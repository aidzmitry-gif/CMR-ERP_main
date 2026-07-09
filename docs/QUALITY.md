# Quality checks

This project has three practical local check levels. Use the smallest one that
matches the risk of the change.

For the surrounding inspect/change/verify/commit rhythm, see
[ENGINEERING_LOOP.md](ENGINEERING_LOOP.md).

## Fast backend smoke

```powershell
.\.venv\Scripts\python.exe -m ruff check core config connectors tests --no-cache
.\.venv\Scripts\python.exe -m pytest tests\test_skeleton.py tests\test_lifespan.py tests\test_core_extras.py tests\test_connectors_core.py -q
```

Use this after infrastructure, connector, or core test-fixture changes.

## Frontend unit suite

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run test:run -- --pool=forks
```

This runs TypeScript, ESLint, and the Vitest suite. In restricted sandboxes
Vitest can fail with
`spawn EPERM` while Vite loads the config; run it in a normal shell or CI when
that happens.

## Broader backend check

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run this before merge/release work. Integration tests may need Docker or a
Postgres-capable environment depending on the selected markers.

## Known local caveats

- Windows/sandbox environments may leave `.git/index.lock` after failed Git
  writes. Remove it only after checking that no Git operation is active.
- Submodules can also keep stale locks under `.git/modules/modules/*/index.lock`.
  Before removing them, check for active `git.exe` processes and confirm the
  lock files are old and zero bytes.
- In restricted Windows shells, `git submodule status` can fail before it reads
  the repository because Git Bash cannot create its signal pipe. Retry in a
  normal shell or CI before treating it as a repository failure.
- File-operation tests use atomic writes and SQLite. In restricted sandboxes,
  `os.replace` or SQLite file databases can fail with permission or disk I/O
  errors even when the same tests pass in a normal shell.
- Runtime outputs such as `*.log`, `*.err`, `.tmp_pytest/`,
  `.tmp_ruff_cache/`, and `pytest-cache-files-*/` are intentionally ignored.
