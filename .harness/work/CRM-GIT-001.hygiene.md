# CRM-GIT-001 repository hygiene evidence

- Initial protected inventory: 1396 root and nested-submodule status entries, 1391 files.
- Inventory SHA-256: `019166a8a2e1bb4519093a68f0b152c2ee7de67cef508fded412a54e29f3f032`.
- Preservation check after local excludes: 1387 non-Goal files checked, 0 missing, 0 hash mismatches.
- Local exclusion mechanism: an idempotent managed block in `.git/info/exclude`; original copied to `.harness/work/CRM-GIT-001.git-info-exclude.before`.
- Installed exact entries: 380. Directory entries collapse root review artifacts, `.codex` runtime, and five Obsidian junctions without touching their targets.
- Visible Git status reduced from 1396 inventory records to 297 root status entries; no working file was moved or deleted.

## Disposition

- Root screenshots, exported HTML/documents and `_sales-mockups-share`/`_docs_out`: retained locally and excluded by exact path.
- Local runtime (`.codex`, coverage snapshot, migration state, developer Compose overrides): retained locally and excluded by exact path.
- Obsidian junctions (`connectors`, `coordination`, `core`, `docs`, `modules`): excluded because they duplicate canonical project trees. Real vault settings, notes, project links and attachments remain visible for later review.
- Coordination source documents: retained and still visible; none was silently ignored or staged.
- Submodule caches: deferred to G03 because ignore rules belong inside each submodule.

## Rollback

Restore `.git/info/exclude` from `.harness/work/CRM-GIT-001.git-info-exclude.before`. The exclusion step itself has no data-file rollback because it did not change data files.
