# Воркер: legal-knowledge — Претензии (office.legal_claim) + учёт курсов (knowledge.course_enrollment)

## Цель (Goal-Driven)
Две независимые фичи по одному и тому же паттерну «плоский реестр + CRUD» (как `office.legal_contract`):
1. Реестр юридических претензий (`office.legal_claim`) в модуле `office` — CRUD-эндпоинты `/office/claims` + фронт-таблица.
2. Учёт прохождения курсов (`knowledge.course_enrollment`) в модуле `knowledge` — таблица назначений курса сотруднику с трекингом статуса/даты завершения, CRUD `/knowledge/enrollments` + фронт-таблица.

Критерий готовности: `pytest tests/test_office_claims.py tests/test_knowledge_enrollments.py` = 0 failed,
`python -c "import main"` = OK, `ruff check` чисто, `tsc --noEmit` = OK.

## Контекст
РАБОЧАЯ ДИРЕКТОРИЯ: твой worktree (spawn_workers уже поставил cwd). НЕ упоминай путь главного репо и
НЕ делай cd в …\Сlaude CRM - проект — иначе закоммитишь в общую ветку в обход изоляции.

Оба модуля — **in-tree** папки суперпроекта (НЕ submodule, `.gitmodules` их не содержит): `modules/office/`
и `modules/knowledge/`. Коммитить прямо в суперпроект, gitlink обновлять НЕ нужно.

- Модуль `office`: `modules/office/models.py` (уже есть `OfficeDoc`, `LegalContract`),
  `modules/office/routes.py` (роуты `/office/contracts` — это и есть эталон-паттерн),
  `modules/office/schemas.py` (`LegalContractCreate/Out/Patch`), `modules/office/module.py`
  (`OfficeModule`, `api_prefix = "/office"`). Тест-эталон: `tests/test_office_legal.py`.
  Событие `office.claim.requested` уже эмитится из `modules/office/events.py` (эскалация просрочки
  > 15 дней → Юрист) — это ПОВОД для претензии, но не сама сущность реестра. Новую модель `LegalClaim`
  с событием НЕ связывать (просто независимый реестр, как `LegalContract`).
- Модуль `knowledge`: `modules/knowledge/models.py` (`Course`, схема `knowledge`),
  `modules/knowledge/routes.py` (`/knowledge/courses`, `/knowledge/board`),
  `modules/knowledge/schemas.py` (`CourseCreate/Out`, `StageUpdate`), `modules/knowledge/module.py`
  (`KnowledgeModule`, `api_prefix = "/knowledge"`). ВАЖНО: `Course` — это уже полноценная модель курса
  (не заглушка), но НЕТ трекинга «кто из сотрудников какой курс на каком этапе прошёл» — это и есть
  задача: новая таблица `course_enrollment` (назначение курса сотруднику + статус + % + дата завершения).
  НЕ трогай `Course`/`/knowledge/courses`/`/knowledge/board` — они рабочие, только добавляешь рядом.
- Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`.
- Модули НЕ обращаются к внутренностям друг друга и не делают FK на чужую схему (§ Архитектура в
  корневом CLAUDE.md) — сотрудника храни как строку (`employee_name`), как `OfficeDoc.owner`/`LegalContract.counterparty_name`,
  БЕЗ `ForeignKey("hr.employee.id")`.

## Миграции (номера УЖЕ выделены координатором — НЕ вызывай scripts/next_migration.py)
- `migrations/versions/0085_office_legal_claim.py` — `revision = "0085"`, `down_revision = "0084"`
- `migrations/versions/0086_knowledge_course_enrollment.py` — `revision = "0086"`, `down_revision = "0085"`

⚠️ Текущий head в дереве миграций на момент выдачи задания — `0083`. Если к моменту твоего старта
уже существует `migrations/versions/0084_*.py` — используй его revision id как свой `down_revision`
для `0085` вместо `"0084"` (проверь `ls migrations/versions/` и открой файл, чтобы прочитать реальный
`revision = "..."`). Твои собственные revision id остаются `"0085"` и `"0086"` — меняется только то,
на что ссылается `down_revision` у 0085.

## Шаг 1 — Модель LegalClaim в modules/office/models.py (после класса LegalContract)
Следуй буквально паттерну `LegalContract` (тот же файл, строки с `class LegalContract`):
```python
class LegalClaim(Base):
    """Претензия контрагенту (по просрочке оплаты, браку, недопоставке и т.п.)."""

    __tablename__ = "legal_claim"
    __table_args__ = {"schema": "office"}

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(64), default="", server_default="")
    counterparty_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    claim_type: Mapped[str] = mapped_column(String(64), default="overdue_payment", server_default="overdue_payment")
    # overdue_payment | defect | shortage | other
    status: Mapped[str] = mapped_column(String(32), default="open", server_default="open")
    # open | sent | responded | resolved | rejected
    amount_byn: Mapped[str] = mapped_column(String(20), default="0.00", server_default="0.00")
    filed_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    office_doc_ref: Mapped[str] = mapped_column(String(64), default="", server_default="")  # ссылка на office_doc.number, если претензия из просрочки
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```
(Импорты `Mapped`, `mapped_column`, `String`, `DateTime`, `func`, `Base` уже есть в файле — новых не добавлять.)

## Шаг 2 — Миграция 0085 (migrations/versions/0085_office_legal_claim.py)
Скопируй структуру `migrations/versions/0079_office_legal_contract.py` (`op.create_table(..., schema="office")`),
с колонками из Шага 1 (все `nullable=False, server_default=...`, кроме `filed_at`/`resolved_at` — `nullable=True`).
`revision = "0085"`, `down_revision = "0084"` (или реальный head — см. предупреждение выше).

## Шаг 3 — Схемы в modules/office/schemas.py (после LegalContractPatch)
Паттерн `LegalContractCreate/Out/Patch`:
```python
class LegalClaimCreate(BaseModel):
    counterparty_name: str
    claim_type: str = "overdue_payment"
    status: str = "open"
    amount_byn: str = "0.00"
    filed_at: str | None = None
    description: str = ""
    office_doc_ref: str = ""
    number: str = ""


class LegalClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    counterparty_name: str
    claim_type: str
    status: str
    amount_byn: str
    filed_at: str | None = None
    resolved_at: str | None = None
    description: str
    office_doc_ref: str = ""


class LegalClaimPatch(BaseModel):
    status: str | None = None
    resolved_at: str | None = None
    description: str | None = None
    amount_byn: str | None = None
```

## Шаг 4 — Роуты в modules/office/routes.py (в самом конце файла, после блока «Реестр юридических договоров»)
Паттерн 1-в-1 с `/office/contracts` (list с фильтрами, create с автономером, get by id, patch):
```
GET  /office/claims?status=&claim_type=   — список с фильтрами
POST /office/claims                        — создать; автономер ПРЕТ-{год}-{NNNN}, если number пуст
GET  /office/claims/{id}                   — одна претензия (404 если нет)
PATCH /office/claims/{id}                  — статус/resolved_at/description/amount_byn
```
Импортировать `LegalClaim`, `LegalClaimCreate`, `LegalClaimOut`, `LegalClaimPatch` в шапке файла (расширить
существующие `from modules.office.models import ...` и `from modules.office.schemas import ...`).

## Шаг 5 — Фронт: frontend/src/components/erp/office-claims-view.tsx
Скопируй структуру `frontend/src/components/erp/office-legal-view.tsx` (`OfficeLegalView`) 1-в-1: фильтры
(статус/тип претензии) + кнопка «+ Претензия» + форма создания + таблица (Номер | Контрагент | Тип |
Статус | Подана | Сумма BYN). Компонент `OfficeClaimsView`, эндпоинты `/api/office/claims`.

## Шаг 6 — Страница frontend/src/app/erp/office/claims/page.tsx
Паттерн `frontend/src/app/erp/office/contracts/page.tsx`:
```tsx
import { AppShell } from "@/components/app-shell";
import { OfficeClaimsView } from "@/components/erp/office-claims-view";

export default function OfficeClaimsPage() {
  return (
    <AppShell crumbs={["ERP", "Офис-менеджер", "Претензии"]}>
      <OfficeClaimsView />
    </AppShell>
  );
}
```

## Шаг 7 — Тесты tests/test_office_claims.py
Паттерн `tests/test_office_legal.py` 1-в-1 (list empty, create autonumber, create custom number, get by id,
get not found, patch status, patch description, patch not found, filter by status, filter by type,
`import main` OK).

---

## Шаг 8 — Модель CourseEnrollment в modules/knowledge/models.py (после класса Course)
```python
class CourseEnrollment(Base):
    """Назначение курса сотруднику + трекинг прохождения (учёт курсов)."""

    __tablename__ = "course_enrollment"
    __table_args__ = {"schema": "knowledge"}

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(Integer)  # id knowledge.course, без FK на др. схему — как в office
    employee_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    status: Mapped[str] = mapped_column(String(32), default="assigned", server_default="assigned")
    # assigned | in_progress | completed | overdue
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # %
    assigned_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```
(`Integer` уже импортирован в файле для `Course.duration`/`progress` — новых импортов не требуется.)

## Шаг 9 — Миграция 0086 (migrations/versions/0086_knowledge_course_enrollment.py)
Та же структура `op.create_table(..., schema="knowledge")` с колонками Шага 8.
`revision = "0086"`, `down_revision = "0085"`.

## Шаг 10 — Схемы в modules/knowledge/schemas.py (после StageUpdate)
```python
class CourseEnrollmentCreate(BaseModel):
    course_id: int
    employee_name: str
    status: str = "assigned"
    progress: int = 0
    assigned_at: str | None = None


class CourseEnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    employee_name: str
    status: str
    progress: int
    assigned_at: str | None = None
    completed_at: str | None = None


class CourseEnrollmentPatch(BaseModel):
    status: str | None = None
    progress: int | None = None
    completed_at: str | None = None
```

## Шаг 11 — Роуты в modules/knowledge/routes.py (в конце файла)
```
GET  /knowledge/enrollments?employee_name=&status=   — список с фильтрами
POST /knowledge/enrollments                           — создать назначение курса сотруднику
GET  /knowledge/enrollments/{id}                       — одна запись (404 если нет)
PATCH /knowledge/enrollments/{id}                      — статус/progress/completed_at
  Бизнес-правило: если payload.status == "completed" и completed_at не передан — проставить
  сегодняшнюю дату автоматически (date.today().isoformat()), progress выставить в 100.
```
Импортировать `CourseEnrollment`, `CourseEnrollmentCreate/Out/Patch` в шапке файла.

## Шаг 12 — Фронт: frontend/src/components/erp/knowledge-enrollments-view.tsx
Тот же паттерн таблица+форма, что `OfficeLegalView`/`OfficeClaimsView`: фильтры (сотрудник/статус) +
кнопка «+ Назначить курс» + форма (course_id, employee_name, assigned_at) + таблица
(Сотрудник | Курс ID | Статус | Прогресс % | Назначен | Завершён).

## Шаг 13 — Страница frontend/src/app/erp/knowledge/enrollments/page.tsx
```tsx
import { AppShell } from "@/components/app-shell";
import { KnowledgeEnrollmentsView } from "@/components/erp/knowledge-enrollments-view";

export default function KnowledgeEnrollmentsPage() {
  return (
    <AppShell crumbs={["ERP", "База знаний", "Учёт курсов"]}>
      <KnowledgeEnrollmentsView />
    </AppShell>
  );
}
```

## Шаг 14 — Тесты tests/test_knowledge_enrollments.py
Тот же набор кейсов, что в Шаге 7 (list empty, create, get by id/404, patch status/progress/completed_at
автопроставление, patch not found, filter by employee_name, filter by status, `import main` OK).

## Запуск
```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"; $env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
Remove-Item .\dev.db -ErrorAction SilentlyContinue
python -m pytest tests/test_office_claims.py tests/test_knowledge_enrollments.py -x -q
python -c "import main"
ruff check modules/office/ modules/knowledge/ tests/test_office_claims.py tests/test_knowledge_enrollments.py --line-length 100

cd frontend
npx tsc --noEmit
```

## DoD
- `pytest tests/test_office_claims.py tests/test_knowledge_enrollments.py` — 0 failed
- `import main` — OK
- `ruff check` — чисто
- `tsc --noEmit` (frontend) — OK
- Коммит прямо в суперпроект (оба модуля in-tree, НЕ submodule — gitlink обновлять не нужно)
- `STATE: COMPLETE` в `coordination/legal-knowledge-status.md`
- НЕ пушить
