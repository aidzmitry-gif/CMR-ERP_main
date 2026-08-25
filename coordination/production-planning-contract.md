# Контракт: Производство · Планирование + Аналитика

> Backend-контракт под два последних экрана производства. Спроектирован на Opus,
> реализовывать может Sonnet-сессия по этому документу. Прототипы:
> `modules/production/prototypes/production/proizvodstvo_planirovanie.html` и `…_analitika.html`.
> Паттерн модуля — как уже сделанные Нормы/Выработка/ОТК/BOM (см. `modules/production/CLAUDE.md`).

## Архитектурное решение (главная развилка)

**План — ОДНА тонкая таблица в длинном формате** (одна строка = одна ячейка `год×изделие×месяц`),
**НЕ** широкая таблица на 12 колонок и **НЕ** таблица «на участок». **Факт нигде не хранится —
он выводится из фактически завершённых нарядов.** Норма (н.ч/шт) тоже не дублируется в плане —
единственный источник `ProductionNorm`, н.ч считаются на чтении.

Почему так:
- План — это только намерение «сколько штук изделия X в месяце M года Y». Это 1 число на ячейку.
  Длинный формат → upsert одной ячейки тривиален, добавление/удаление позиции = вставка/удаление 12 строк,
  миграция не нужна при смене числа месяцев/изделий.
- Факт как хранимая величина = рассинхрон с нарядами. Берём из `production_order` (см. ниже) — всегда правда.
- Аналитика — **чистый read-model** (агрегация orders+qc+payroll+plan), своих таблиц НЕ заводит.

Итог: **1 новая таблица** (`production_plan`) + **1 новая колонка** (`production_order.completed_at`).

---

## 1. Изменения схемы (миграция `0034`)

> ⚠️ Реализовано как `0036` (не 0034): sales-сессия параллельно заняла 0034/0035.
> `down_revision="0035"`. Файл — `migrations/versions/0036_production_plan.py` (суперпроект).

### 1.1 Новая таблица `production.production_plan`

ORM (в `modules/production/models.py`, submodule PRO-4):

```python
class ProductionPlan(Base):
    """План производства: сколько штук изделия в конкретном месяце года (экран «Планирование»).

    Длинный формат — одна строка = одна ячейка матрицы (год × изделие × месяц).
    Норма н.ч/шт НЕ хранится здесь — берётся из ``ProductionNorm`` по ``product`` на чтении.
    Факт НЕ хранится — выводится из завершённых нарядов (``ProductionOrder.completed_at``).
    Уникальность: (year, product, month).
    """

    __tablename__ = "production_plan"
    __table_args__ = (
        UniqueConstraint("year", "product", "month", name="uq_production_plan_cell"),
        {"schema": "production"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    product: Mapped[str] = mapped_column(String(255))   # совпадает с ProductionOrder.product / ProductionNorm.title
    month: Mapped[int] = mapped_column(Integer)          # 1..12
    plan_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

Миграция (Postgres — источник истины схемы):
```python
op.create_table(
    "production_plan",
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("year", sa.Integer, nullable=False, index=True),
    sa.Column("product", sa.String(255), nullable=False),
    sa.Column("month", sa.Integer, nullable=False),
    sa.Column("plan_qty", sa.Integer, nullable=False, server_default="0"),
    sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    sa.UniqueConstraint("year", "product", "month", name="uq_production_plan_cell"),
    schema="production",
)
```
(SQLite-тесты получают таблицу автоматически через `Base.metadata.create_all` — миграция не нужна для pytest.)

### 1.2 Колонка `production.production_order.completed_at`

Зачем: честный факт по месяцам и «выработка по дням» требуют **даты завершения** наряда.
Сейчас её нет (`created_at` — это создание, `due_date` — строка-план). Добавляем:

```python
# в ProductionOrder:
completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```
Миграция: `op.add_column("production_order", sa.Column("completed_at", sa.DateTime, nullable=True), schema="production")`.

**Где заполнять:** в `routes.py`, в ветке `PATCH /orders/{id}` при переходе в `done`
(там уже ставится `progress=100`, `made_qty=qty`, emit `production.completed`) — добавить
`order.completed_at = datetime.utcnow()` (или `func.now()` через флаг — но проще `datetime.utcnow()`,
т.к. строка коммитит сама). Старые `done`-наряды без `completed_at` → факт по ним падает на месяц
`created_at` как фолбэк (см. §3 правило факта).

---

## 2. Pydantic-схемы (`modules/production/schemas.py`)

```python
class PlanCellUpdate(BaseModel):           # PUT одной ячейки
    year: int
    product: str
    month: int = Field(ge=1, le=12)
    plan_qty: int = Field(ge=0)

class PlanPositionUpsert(BaseModel):        # создать/заменить позицию на год целиком
    year: int
    product: str
    monthly: list[int]                      # ровно 12 значений (янв..дек), qty

class PlanMonthCell(BaseModel):
    month: int
    plan_qty: int
    plan_nh: float
    fact_qty: int
    fact_nh: float

class PlanRowOut(BaseModel):
    product: str
    norm_nh: float                          # н.ч/шт из утверждённой нормы (0 если нет)
    months: list[PlanMonthCell]             # 12
    year_qty: int
    year_nh: float

class PlanTotalsOut(BaseModel):
    month_nh: list[float]                   # план н.ч по месяцам (12)
    fact_nh: list[float]                    # факт н.ч по месяцам (12)
    load_pct: list[float]                   # month_nh / capacity_nh * 100 (12)
    year_nh: float
    plan_ytd: float                         # план н.ч с начала года по текущий месяц включ.
    fact_ytd: float                         # факт н.ч YTD
    peak_month: int                         # индекс 0..11 макс. загрузки
    low_month: int

class PlanBoardOut(BaseModel):
    year: int
    capacity_nh: float                      # мощность н.ч/мес (см. §3)
    rows: list[PlanRowOut]
    totals: PlanTotalsOut
```

Аналитика — read-model, тоже схемы Out (см. §4).

---

## 3. Правила вычислений (зафиксировать в тестах)

- **norm_nh(product)** = `nh` утверждённой (`status="approved"`) `ProductionNorm` с `title == product`
  (точное совпадение, как подстановка нормы в наряд). Нет такой — `0.0`.
- **plan_nh(cell)** = `plan_qty × norm_nh`.
- **fact_qty(year, product, month)** = `Σ made_qty` нарядов, где `product` совпадает, `stage == "done"`,
  и месяц завершения == month. **Месяц завершения** = `completed_at`, а если он `NULL` (старые наряды) —
  `created_at`. Год тоже из этой даты == year.
- **fact_nh(cell)** = `fact_qty × norm_nh`.
- **capacity_nh** (мощность цеха, н.ч/мес) = `max(1, число строк ProductionWorker) × 176`.
  176 = рабочих часов в месяце на сборщика (4 сборщика × 176 = 704 — как в прототипе).
  Вынести `176` в константу модуля `ASSEMBLER_HOURS_PER_MONTH` рядом с `WORK_RATE`/`PREMIUM_RATE`/`NORM_DAYS`.
- **load_pct[m]** = `month_nh[m] / capacity_nh × 100`.
- **plan_ytd / fact_ytd**: «текущий месяц» = месяц по серверной дате (`datetime.utcnow().month`).
  plan_ytd = сумма `month_nh` за месяцы < текущего + `month_nh[текущий]` целиком (MVP — без дробления),
  fact_ytd = сумма `fact_nh` за месяцы ≤ текущего. (Прототип дробит текущий месяц коэффициентом —
  в MVP не дробим, просто берём целый; допустимое упрощение, отметить в тесте.)
- **peak_month / low_month** = `argmax/argmin(load_pct)`.

---

## 4. HTTP-эндпоинты (`modules/production/routes.py`, префикс `/production`)

> Роуты модуля **коммитят сами** (`session.commit()`) — это локальная конвенция модуля production,
> не общий паттерн. CRUD без `core/db/repository`.

### План
- `GET /production/plan?year=2026` → `PlanBoardOut`. Год по умолчанию = `utcnow().year`.
  Собирает все позиции плана за год, докручивает norm_nh/факт/итоги/мощность. Это единственный
  тяжёлый запрос — отдаёт всё, что нужно матрице, графику мощности и KPI.
- `PUT /production/plan/cell` (body `PlanCellUpdate`) → upsert одной ячейки (год+изделие+месяц).
  Возвращает обновлённый `PlanBoardOut` за этот год (фронт перерисовывает матрицу целиком). 200.
  `plan_qty=0` — допустимо (ячейка обнуляется, но строка может остаться).
- `POST /production/plan/position` (body `PlanPositionUpsert`) → создать/заменить позицию на год:
  upsert 12 ячеек из `monthly`. 201. Возвращает `PlanBoardOut`.
- `DELETE /production/plan/position?year=2026&product=<...>` → удалить все 12 ячеек позиции. 204.

> Альтернатива по вкусу реализатора: вместо «возвращать весь board из мутаций» — отдавать
> `{ok: true}` и звать `GET /plan` с фронта. Но единый возврат board экономит roundtrip — предпочесть его.

### Аналитика (read-model, без новых таблиц)
- `GET /production/analytics?year=2026` → объект ниже. Всё агрегируется из orders + qc + payroll + plan.

```python
class AnalyticsOut(BaseModel):
    # KPI
    vyrabotka_fact_nh: float        # Σ fact_nh за год (или период) — выработка факт
    vyrabotka_plan_nh: float        # Σ plan_nh YTD — план периода
    efficiency_pct: float           # выработка н.ч ÷ (отработанные часы табеля) ×100; часы = Σ days_worked×8
    fpy_pct: float                  # accept ÷ (accept+rework+scrap) ×100  (с первого предъявления)
    pass_rate_pct: float            # (accept+rework) ÷ всего ×100  (как в /qc/stats)
    scrap_pct: float                # scrap ÷ всего ×100
    premium_fot_byn: float          # Σ (nh_output × PREMIUM_RATE) по табелю — премия от выработки
    # Серии для графиков
    plan_fact_by_month: list[dict]  # [{month, plan_nh, fact_nh}] ×12  (= totals из /plan)
    scrap_reasons: list[dict]       # [{reason, count}] — group by ProductionQc.reason where decision=scrap
    team_contribution: list[dict]   # [{name, nh_output, share_pct}] из payroll/workers
    top_products: list[dict]        # [{product, fact_nh}] — топ по факту за период, desc
```
- Источники: `pass_rate/scrap/fpy` ← как `GET /qc/stats` (accept/rework/scrap счётчики);
  `efficiency/premium/team` ← `ProductionWorker` (`nh_output`, `days_worked`) + константы;
  `plan_fact_by_month/top_products/vyrabotka` ← план (§4) + факт (§3).
- «Выработка по дням» (график) — опционально в MVP: требует группировки нарядов по `completed_at::date`.
  Если делаешь — добавь `daily_output: list[{date, nh}]` за текущий месяц. Иначе пропусти, отметив в коде.

### События
- Новых публикаций/подписок **не нужно**. (Опционально, вне MVP: `production.plan.updated` для аудита —
  не делать без отдельной просьбы.)

---

## 5. Тесты (суперпроект, `tests/`)

`tests/test_production_plan.py` (api-маркер по пути):
1. PUT cell создаёт ячейку; повторный PUT того же (year,product,month) — обновляет, не дублирует (уникальность).
2. POST position пишет 12 ячеек; year_qty == Σ monthly.
3. norm_nh подхватывается из approved-нормы по точному product; без нормы → 0, plan_nh → 0.
4. **Факт**: создать наряд product=X qty=N → PATCH в done → fact_qty месяца завершения == N (по completed_at).
   Наряд не-done или другого product не попадает в факт.
5. capacity_nh = worker_count×176; load_pct[m] = month_nh[m]/capacity×100.
6. plan_ytd/fact_ytd/peak_month/low_month считаются согласно §3.
7. DELETE position убирает все 12 ячеек (board.rows без неё).

`tests/test_production_analytics.py`:
1. pass_rate/scrap_pct/fpy из решений ОТК (accept/rework/scrap) — числовая проверка.
2. premium_fot = Σ nh_output×PREMIUM_RATE; efficiency = выработка÷(days_worked×8)×100.
3. scrap_reasons группирует по reason; top_products desc по факту; plan_fact_by_month длиной 12.

> Фикстура `tests/conftest.py` строит таблицы из ORM (create_all) — `ProductionPlan` появится сама.
> Для теста факта по месяцам ставь `completed_at` явно (или патчи через done-ветку и проверяй текущий месяц).

---

## 6. Фронт (суперпроект `frontend/`, воркер-безопасно)

Паттерн — как Нормы/BOM: `lib/*.ts` (+ `.test.ts` vitest) + Server-page (SSR на `BACKEND_URL`) +
`"use client"` компонент (мутации через `/api/...`). Проверка: `npx tsc --noEmit` + `npm --prefix frontend run test:run` (НЕ `next lint`).

- `frontend/src/lib/production-plan.ts` — типы `PlanBoard/PlanRow/PlanCell/PlanTotals`, хелперы
  `loadTone(pct)` (>100 red / ≥70 amber / else green — как `loadCls` в прототипе), `fmtNh` (1 знак, запятая),
  API-обёртки `fetchPlanServer/fetchPlan/putPlanCell/upsertPosition/deletePosition`. + `.test.ts` (loadTone границы, fmtNh, агрегаты).
- `frontend/src/app/erp/production/planning/page.tsx` — Server-page, `crumbs={["ERP","Производство","Планирование · план/факт"]}`.
- `frontend/src/components/erp/plan-matrix.tsx` — KPI-строка, редактируемая матрица (месяц×изделие, клик по ячейке qty → PUT cell on blur), строка Σ с загрузкой %, график мощности (CSS-бары план/факт), добавление/удаление позиции.
- Аналогично `lib/production-analytics.ts` + `app/erp/production/analytics/page.tsx` + `components/erp/production-analytics-view.tsx`
  (⚠️ имя `analytics-view.tsx` уже занято модулем erp/analytics — назвать **`production-analytics-view.tsx`**).
- **Сайдбар** (`frontend/src/components/sidebar.tsx`, ХОТСПОТ — захватить в ACTIVE-SESSIONS перед правкой):
  в подменю production добавить 2 пункта — `{label:"Планирование · план/факт", href:"/erp/production/planning"}`
  и `{label:"Аналитика производства", href:"/erp/production/analytics"}`. Сейчас там есть «Наряды/Маршруты/Оборудование» заглушки — вставить выше них.

---

## Порядок реализации (для Sonnet-сессии)
1. **Захвати миграцию `0034`** в `coordination/ACTIVE-SESSIONS.md` (инкрементируй счётчик → 0035) и сайдбар-хотспот.
2. Backend submodule: модель `ProductionPlan` + колонка `completed_at` + `ASSEMBLER_HOURS_PER_MONTH`, схемы, роуты, заполнение `completed_at` в done-ветке. Коммит в PRO-4.
3. Суперпроект: миграция `0034`, тесты `test_production_plan.py` + `test_production_analytics.py`, bump указателя submodule. `pytest -k "production_plan or production_analytics"` = зелёно.
4. Фронт: lib+page+компонент ×2, сайдбар +2 пункта. `tsc --noEmit`=0, vitest зелёно. Освободи хотспот.
5. Обнови память `production-erp-port.md` (Планирование+Аналитика сделаны → производство закрыто целиком).

Коммиты **локальные** (вкл. submodule) — не пушить без явной просьбы.
