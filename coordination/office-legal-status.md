# Status: office-legal

## Task
Реестр юридических договоров: backend + frontend.

## Acceptance Gate
- [x] `pytest tests/test_office_legal.py` = 0 failed (11/11 green)
- [x] `import main` = OK (тест test_import_main_ok)
- [x] `tsc --noEmit` = OK (0 errors)
- [x] `ruff check` = OK (после --fix isort)
- [x] Коммиты в репо (не пушено)

## Итерации
### Итерация 1 — Complete

**Think:** Модель LegalContract нужна в modules/office (не submodule). Схема, роуты, миграция 0079, frontend, тесты.

**Test:** 11/11 green первым запуском.

**Validate:** ruff — 1 isort fix → clean. tsc → clean.

**Wire:** Все файлы в коммитах:
- `bdb7fa4` — modules/office/{models,routes,schemas}.py
- `1484eec` — migration 0079, tests, frontend (подхвачено hr-okk воркером)

**Review:** Все DoD-критерии зелёные.

## Файлы
| Файл | Изменение |
|------|-----------|
| modules/office/models.py | +LegalContract ORM |
| modules/office/routes.py | +4 эндпоинта /contracts |
| modules/office/schemas.py | +LegalContractCreate/Out/Patch |
| migrations/versions/0079_office_legal_contract.py | новая |
| frontend/src/components/erp/office-legal-view.tsx | новый |
| frontend/src/app/erp/office/contracts/page.tsx | новый |
| tests/test_office_legal.py | 11 тестов |

## PITFALLS-DISCOVERED
- **СИМПТОМ: modules/office не является submodule** — причина: CLAUDE.md перечисляет 9 submodules (sales/procurement/production/wms/logistics/finance/marketing/service/hr), office НЕ входит в список → **ЛЕЧЕНИЕ: перед коммитом проверять .gitmodules, если модуль там отсутствует — просто обычный git add в суперпроекте**.

---

STATE: COMPLETE
