# Scope: CRUD-хвост справочников — классификаторы модулей (Sonnet-флот)

> **Модель воркеров: Sonnet.** Один воркер = один модуль. Задача тиражирует **готовый
> эталон ядра** (Opus, Ф1) на классификаторы своего модуля. Архитектурных решений не
> требуется — следуй правилам ниже дословно. Если правило не покрывает случай — НЕ
> придумывай, оставь TODO и пинг оркестратора.

## Что уже готово (эталон — НЕ трогать, только переиспользовать)

- Контракт `core.register_reference(Reference(...))` + dataclass'ы `Reference`,
  `ReferenceColumn` — `core/runtime/contract.py`.
- Фабрики CRUD-роутеров — `core/runtime/reference_routes.py`:
  - `build_simple_ref_router(model, *, fields, editable, required=(), key_field="code")`
    → list (с `?archived=true`), create, patch `/{code}`, archive `DELETE /{code}` (soft через `is_active`).
  - `build_versioned_ref_router(model, *, key_field, value_fields, list_fields)`
    → list (`?key=`), `/current?key=`, `/as-of?key=&on=YYYY-MM-DD`, `POST /versions` (SCD2).
- SCD2-хелперы (для версионных) — `core/services/scd2.py`.
- Каталог-витрина: `GET /system/references` (по отделам) и `/system/references/ai-catalog`.
- Доменный док: **`core/reference/CLAUDE.md`** — прочитай первым.
- Системные справочники ядра (public) уже под `/system/refs/*` — образец проводки внизу `reference_routes.py`.

## Жёсткие правила координации (нарушение = конфликт на main)

1. **Полоса.** Перед стартом впиши строку в `coordination/ACTIVE-SESSIONS.md` →
   «Полосы»: зона `<module> reference-crud`, пути `modules/<module>/**`. Не лезь в чужой модуль.
2. **core/ заморожен для тебя.** Файлы `core/**` держит Opus-сессия «Справочники». НЕ редактируй
   их — только импортируй (`from core.runtime.reference_routes import ...`, `from core.runtime.contract import ...`).
3. **Submodule.** `modules/<module>/` — git-submodule: коммить в репозиторий модуля + bump
   указателя в суперпроекте В СВОЕЙ сессии. Чужой модуль не bump-ай.
4. **Миграции.** Нужна колонка (`is_active`, `start_date/end_date`)? Возьми номер из
   `ACTIVE-SESSIONS.md` → «Счётчик миграций» (следующий свободный) и **сразу инкрементируй там**,
   ДО написания файла. Реально проверь `grep 'revision = ' migrations/versions/` — счётчик отстаёт.
5. **Коммить мелко.** ruff чисто (`ruff check .`), тесты модуля зелёные, до коммита.
6. **Локально, без push** (если оператор не просил обратное).

## Алгоритм для ОДНОГО модуля

1. **Прочитай** `core/reference/CLAUDE.md` + хвост `core/runtime/reference_routes.py` (проводка ядра).
2. **Найди классификаторы своего модуля** — маленькие справочные таблицы (стадии, причины, типы,
   статусы, категории…). См. список-ориентир в аппендиксе ниже; сверь с РЕАЛЬНЫМИ моделями
   `modules/<module>/models.py`. Регистрируй только то, что реально есть как таблица; чего нет —
   в TODO (не создавай новые сущности без запроса).
3. **Для каждого классификатора** реши тип по правилу:
   - **простой** (стабильный `code`+`title`, нужен архив) → `build_simple_ref_router`.
     Требуется колонка `is_active: Mapped[bool]` (есть — ок; нет — добавь миграцией, см. правило 4).
     Если natural key не `code` — передай `key_field=`.
   - **версионный/датированный** (цены, нормы с историей, версии BOM) → `build_versioned_ref_router`
     (нужны `start_date: Mapped[date]`, `end_date: Mapped[date|None]`, поля-значения).
   - **иерархия** (план счетов, ЦФО, оргструктура, ячейки): пока трактуй `parent_id` как обычное
     редактируемое поле в простом CRUD (полноценный tree-редактор — отдельная фаза фронта). Пометь `🌳` в реестре.
   - **enum в коде, не таблица** (напр. хардкод-стадии) → только `register_reference` (метаданные),
     CRUD не делай; в `Reference.description` отметь «значения фиксированы кодом».
4. **Зарегистрируй** каждый в `register(core)` модуля:
   ```python
   core.declare_permissions([
       Permission("<module>.refs.view", "Просмотр справочников <module>"),
       Permission("<module>.refs.edit", "Правка справочников <module>"),
   ])
   core.register_reference(Reference(
       key="<module>.<name>", title="<RU>", department="<RU-отдел>",
       owner_schema="<module>", endpoint="/<module>/refs/<name>",
       columns=(ReferenceColumn("code","Код","string",editable=False,
                                semantic="стабильный код для мягких ссылок"),
                ReferenceColumn("title","Наименование","string"),
                ReferenceColumn("is_active","Активен","bool",
                                semantic="архивные не выбираются в новых документах")),
       permissions=("<module>.refs.view","<module>.refs.edit"),
       archivable=True, versioned=<bool>, ai_exposed=<bool>,
       description="...",
   ))
   ```
   `department` — человекочитаемое имя отдела (Продажи/Закупки/Производство/Склад/Финансы/HR/
   Логистика/Сервис/Маркетинг). `ai_exposed=True` для часто-запрашиваемых (типы/статусы/причины), `False`
   для служебных. `versioned=True` ровно для датированных.
5. **Подключи CRUD-роутер** под префиксом модуля: собери `APIRouter` со всеми классификаторами
   модуля (по образцу `build_reference_router()` в ядре) и отдай через `core.include_router(r, prefix="/<module>")`
   так, чтобы пути были `/<module>/refs/<name>` (совпадают с `endpoint` в Reference).
6. **Тесты** (api, SQLite): на каждый простой — list/create/patch/archive(+`archived=true`)/404;
   на версионный — add-version → `/current` → `/as-of` на границе интервала → 409 на перекрытие.
   Опирайся на `tests/test_reference_crud.py` как на образец.

## Definition of Done (на модуль)

- Классификаторы видны в `GET /system/references` под правильным `department`; `ai_exposed`-те — в
  `/system/references/ai-catalog`.
- CRUD работает по `/<module>/refs/<name>`; архив прячет запись из дефолтного списка.
- Версионные: `/as-of` отдаёт ровно одну версию на дату (граница `[start, end)` — `start` включительно).
- `ruff check .` чисто; тесты модуля зелёные; миграция (если была) — корректный номер, чейн линейный.
- Полоса и счётчик миграций в `ACTIVE-SESSIONS.md` обновлены.

## Анти-цели (НЕ делать)

- НЕ редактировать `core/**` (лента Opus). НЕ дублировать данные справочников в реестр — данные у владельца.
- НЕ строить MDM/merge (это сервис ядра, отдельная фаза). НЕ строить фронт (отдельная фаза).
- НЕ создавать новые бизнес-сущности — только регистрировать/обслуживать существующие классификаторы.
- НЕ брать чужой номер миграции вслепую — только через счётчик + `grep`.

## Аппендикс: классификаторы-ориентиры по модулям (сверять с реальными моделями)

| Модуль | Отдел | Классификаторы-кандидаты (§3.3 концепции) |
|---|---|---|
| sales | Продажи | стадии воронки*, причины отказа/loss-reasons, источники лидов, типы сделок, прайс-листы 🕘 |
| procurement | Закупки | типы поставщиков, условия оплаты (Net 30/60), сроки поставки, сертификации, инкотермс |
| production | Производство | BOM/спецификации 🕘, маршруты/операции, нормы (🕘?), центры обработки |
| wms | Склад | зоны 🌳, ячейки 🌳, типы операций, статусы партий |
| finance | Финансы | план счетов 🌳, статьи затрат/доходов 🌳, ЦФО 🌳, проекты/направления, типы документов |
| hr | HR | должности, оргструктура 🌳, типы начислений, причины увольнения |
| logistics | Логистика | перевозчики, тарифы (🕘?), типы ТС, маршруты доставки |
| service | Сервис | типы обращений, SLA, категории неисправностей |
| marketing | Маркетинг | каналы, кампании, сегменты, UTM-источники |

\* стадии воронки часто фиксированы кодом (STAGES) — тогда метаданные-only, CRUD не делать.
🕘 = версионный (SCD2), 🌳 = иерархия (parent_id как поле). Знаки — ориентир, проверяй по факту.

---
_Эталон: core/runtime/reference_routes.py · core/services/scd2.py · core/reference/CLAUDE.md ·
tests/test_reference_crud.py. Концепция: coordination/db-and-reference-data-concept.md (§3.3, §6)._
