# Scope: security-p1-2-rbac  (ПЕРЕ-СКОУПЛЕНО координатором → CORE-LEVEL, без submodule-правок)

## LOOP CONTRACT
- include:
  - tests/test_security_rbac_sweep.py         (новый — ГЛАВНЫЙ дедлайн-артефакт)
  - core/runtime/access.py                    (правишь ТОЛЬКО если свип нашёл дыру на уровне ядра)
  - config/access.py                          (правишь ТОЛЬКО PACKAGE_TO_SLUG/OPEN — НЕ значения ACCESS_MATRIX)
- exclude:
  - modules/**                                (per-endpoint require_permission внутри модулей — это Wave F P1-3, НЕ трогать)
  - config/settings.py                        (auth_mode default — НЕ трогать)
  - config/modules.py
  - core/services/auth.py                     (require_permission/get_current_user/fail-closed — только читать, НЕ менять)
  - core/db/base.py · core/runtime/core.py
  - migrations/versions/**                    (миграций нет)
  - frontend/**
  - scripts/seed.py
model: opus
- max_iterations: 10
- max_files_changed: 4
- stop_conditions:
  - pytest -m api tests/test_security_rbac_sweep.py = 0 failed
  - pytest -m api (полный слой) = 0 failed  (ничего не сломал)
  - import main = OK
  - ruff check = чисто

## Ограничения (security-critical — читать перед каждой правкой)
- ЦЕЛЬ полосы: ДОКАЗАТЬ инвариант «write-эндпоинт чужого модуля → 403» автоматическим свипом
  по ВСЕМ зарегистрированным роутам и ЗАКРЫТЬ дыры на уровне ЯДРА (не по-модульно).
- Существующий гейт — `core/runtime/access.py::AccessControlMiddleware`: он УЖЕ режет 403 по
  префиксу модуля для ЛЮБОГО метода (в т.ч. write) до роута. Твоя работа — не дублировать его
  в модулях, а: (1) написать свип-тест, (2) если свип показал write-роут, который гейт НЕ ловит
  (пакет без UI-слага в PACKAGE_TO_SLUG; роут под OPEN_PREFIXES, который на деле state-changing;
  роутер без префикса) — закрыть это в ядре (`config/access.py` mapping или `access.py` логика).
- НЕ ослаблять защиту нигде. Fail-closed фундаментален: без роли → 403, НИКОГДА не 200.
  Тест падает на легитимном роуте → дай запросу заголовок роли-владельца (X-User-Roles), НЕ снимай гейт.
- НЕ менять значения `ACCESS_MATRIX` (роль→модули) — матрица согласована владельцем. Можно только
  дополнить `PACKAGE_TO_SLUG`/`OPEN_PREFIXES`, если свип обнажил незамапленный пакет/префикс.
- НЕ флипать прод в secure/oidc; НЕ трогать `config/settings.py`.
- Это код ЯДРА/суперпроекта — коммит ПРЯМО в суперпроект (НЕ submodule). Миграций нет.
- НЕ пушить (пуш — координатор).
- auth: `AIOS_AUTH_MODE=dev AIOS_ENVIRONMENT=dev` (иначе import main падает).
