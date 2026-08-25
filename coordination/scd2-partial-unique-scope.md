# Scope: scd2-partial-unique

## LOOP CONTRACT
- include:
  - migrations/versions/0084_scd2_partial_unique.py
  - tests/test_scd2_invariants.py
  - tests/test_scd2_partial_unique.py   (если решишь вынести race-тест в отдельный файл)
- exclude:
  - modules/*
  - config/
  - scripts/seed.py
  - core/domain/reference.py   (read-only reference — заземление на реальные модели, НЕ менять ORM)
  - core/services/scd2.py      (read-only reference — заземление на add_version/current_version, НЕ менять)
model: opus
- max_iterations: 8
- max_files_changed: 8
- stop_conditions:
  - pytest tests/test_scd2_invariants.py = 0 failed
  - import main = OK
  - ruff check = чисто
  - alembic heads = ровно один head (0084, линейно поверх 0083)

## Ограничения
- НЕ трогать чужие модули (modules/*)
- Миграция уже пред-выделена координатором: revision="0084", down_revision="0083".
  НЕ вызывать `python scripts/next_migration.py` — номер брать как есть.
- core/domain/reference.py и core/services/scd2.py — ТОЛЬКО читать для заземления
  (имена таблиц/колонок/классов); индекс описывается в самой миграции
  (`op.create_index(..., postgresql_where=...)`), декларативные ORM-модели не трогать.
- Это shared-kernel код ядра — коммит прямо в суперпроект (не submodule).
- НЕ пушить (пуш делает координатор)
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает)
