# Воркер: hr-okk — ОКК баллы сотрудников

## Цель (Goal-Driven)
Добавить систему ОКК-оценки (Отдел контроля качества) сотрудников: backend-эндпоинты + UI страница.
Критерий готовности: `pytest tests/test_hr_okk.py` = 0 failed, `import main` = OK, `tsc --noEmit` = OK.

## Контекст
- CWD: `D:\6 Проекты\CRM ERP\Сlaude CRM - проект`
- Submodule: `modules/hr/` (HR-10.git) — коммить туда ОТДЕЛЬНО, потом bump gitlink в суперпроекте
- Модуль HR: `modules/hr/models.py` (Employee, Candidate, PayrollEntry), `modules/hr/routes.py`
- Миграция: взять номер через `python scripts/next_migration.py hr-okk "hr okk_score"` — это выдаст N
- Auth: `AIOS_AUTH_MODE=dev`, `AIOS_ENVIRONMENT=dev` — обязательно для `import main`

## ОКК-оценка (что это)
ОКК = Отдел Контроля Качества. Раз в месяц каждый сотрудник получает баллы по категориям:
дисциплина, качество работы, клиентский сервис, командная работа.

## Шаг 1 — Модель OkkScore в modules/hr/models.py
```python
class OkkScore(Base):
    __tablename__ = "okk_score"
    __table_args__ = {"schema": "hr"}
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("hr.employee.id"))
    period: Mapped[str] = mapped_column(String(7))   # "YYYY-MM"
    discipline: Mapped[int] = mapped_column(Integer, default=0)   # 0-25
    quality: Mapped[int] = mapped_column(Integer, default=0)      # 0-25
    service: Mapped[int] = mapped_column(Integer, default=0)      # 0-25
    teamwork: Mapped[int] = mapped_column(Integer, default=0)     # 0-25
    total: Mapped[int] = mapped_column(Integer, default=0)        # сумма 0-100
    comment: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

## Шаг 2 — Миграция
`python scripts/next_migration.py hr-okk "hr okk_score table"` → получить номер N
Создать `migrations/versions/N_hr_okk_score.py` с `create_table("okk_score", schema="hr")`

## Шаг 3 — Схемы Pydantic в modules/hr/schemas.py
- `OkkScoreCreate`: employee_id, period, discipline, quality, service, teamwork, comment
- `OkkScoreOut`: все поля + id + total (вычисляемый при создании)

## Шаг 4 — Эндпоинты в modules/hr/routes.py
```
GET  /hr/okk-scores?employee_id=&period=   — список оценок с фильтрами
POST /hr/okk-scores                        — создать оценку (total = sum всех баллов)
GET  /hr/okk-scores/{id}                   — одна запись
```
`total` считать в роуте: `discipline + quality + service + teamwork`

## Шаг 5 — Frontend: frontend/src/components/erp/hr-okk-view.tsx
- Таблица оценок: Сотрудник | Период | Дисциплина | Качество | Сервис | Командная | Итого
- Итого подсвечивать: ≥90 зелёный, 70-89 жёлтый, <70 красный
- Фильтр по периоду
- Форма «Добавить оценку»: выбор сотрудника (из GET /hr/employees), период (YYYY-MM), 4 слайдера/инпута 0-25

## Шаг 6 — Страница frontend/src/app/erp/hr/okk/page.tsx

## Шаг 7 — Тесты tests/test_hr_okk.py
- GET /hr/okk-scores → 200 список
- POST → 201, total = sum
- GET с filter employee_id → только его оценки
- total правильно вычисляется
- import main зелёный

## Запуск
```powershell
.\.venv\Scripts\Activate.ps1
$env:AIOS_AUTH_MODE="dev"; $env:AIOS_ENVIRONMENT="dev"; $env:PYTHONPATH="."
$env:AIOS_DATABASE_URL="sqlite+aiosqlite:///./dev.db"
Remove-Item .\dev.db -ErrorAction SilentlyContinue
python -m pytest tests/test_hr_okk.py -x -q
python -c "import main"
ruff check modules/hr/ tests/test_hr_okk.py --line-length 100
```

## DoD
- pytest зелёный + import main + ruff + tsc --noEmit
- Коммит в modules/hr/ (submodule) → bump gitlink в суперпроекте
- `STATE: COMPLETE` в coordination/hr-okk-status.md
- НЕ пушить
