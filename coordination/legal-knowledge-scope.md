# Scope: legal-knowledge

## LOOP CONTRACT
- include:
  - modules/office/models.py
  - modules/office/routes.py
  - modules/office/schemas.py
  - modules/knowledge/models.py
  - modules/knowledge/routes.py
  - modules/knowledge/schemas.py
  - migrations/versions/0085_office_legal_claim.py
  - migrations/versions/0086_knowledge_course_enrollment.py
  - frontend/src/components/erp/office-claims-view.tsx
  - frontend/src/app/erp/office/claims/page.tsx
  - frontend/src/components/erp/knowledge-enrollments-view.tsx
  - frontend/src/app/erp/knowledge/enrollments/page.tsx
  - tests/test_office_claims.py
  - tests/test_knowledge_enrollments.py
  - coordination/legal-knowledge-status.md
- exclude: все прочие modules/*, core/, config/, scripts/seed.py, modules/office/module.py,
  modules/knowledge/module.py, modules/office/events.py, modules/office/stages.py,
  modules/knowledge/stages.py, любые другие frontend-страницы/компоненты кроме перечисленных выше
model: sonnet
- max_iterations: 8
- max_files_changed: 16
- stop_conditions:
  - pytest tests/test_office_claims.py tests/test_knowledge_enrollments.py = 0 failed
  - import main = OK
  - ruff check modules/office/ modules/knowledge/ tests/test_office_claims.py tests/test_knowledge_enrollments.py = чисто
  - tsc --noEmit (frontend) = OK

## Ограничения
- НЕ трогать чужие модули (sales, procurement, production, wms, logistics, finance, marketing,
  service, hr, integrations) и общее ядро (core/, config/)
- НЕ трогать существующие эндпоинты/модели office.LegalContract, office.OfficeDoc,
  knowledge.Course, knowledge.STAGES — только добавлять новое рядом
- Миграции 0085 и 0086 — ПРЕ-ВЫДЕЛЕНЫ координатором. НЕ вызывать `python scripts/next_migration.py`.
  revision="0085" (down_revision="0084" либо реальный текущий head, если 0084 уже существует к моменту
  старта — проверить `ls migrations/versions/`), revision="0086" (down_revision="0085")
- Оба модуля (`office`, `knowledge`) — in-tree папки суперпроекта, НЕ submodule (нет записи в
  `.gitmodules`) — коммитить прямо в суперпроект, bump gitlink НЕ требуется
- НЕ пушить (пуш делает координатор)
- auth: AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev (иначе import main падает)
- Деньги в API — строкой (amount_byn: str), не float — как в LegalContract
