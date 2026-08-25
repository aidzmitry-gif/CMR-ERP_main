# prod-fe-planning — задание

## Контекст

Ты — воркер фронтенда CRM/ERP. Строишь экран «Планирование · план/факт» производства.
Бэкенд **уже готов** (миграция 0036, эндпоинты работают). Submodule не трогаешь — всё в суперпроекте.

Главный контракт-документ: `coordination/production-planning-contract.md` (§6 — фронт).
Образец паттерна: `frontend/src/lib/production-bom.ts` + `frontend/src/app/erp/production/bom/page.tsx` + `frontend/src/components/erp/bom-panel.tsx`.

## Goal-Driven: напиши lib+test → сделай tsc зелёным → сделай vitest зелёным → сделай компонент → закоммить

## Файлы в твоей ответственности

```
frontend/src/lib/production-plan.ts          — типы + хелперы + API-обёртки
frontend/src/lib/production-plan.test.ts     — vitest (чистые функции)
frontend/src/app/erp/production/planning/page.tsx  — Server-page (SSR)
frontend/src/components/erp/plan-matrix.tsx  — "use client" компонент матрицы
```

НЕ трогаешь: `sidebar.tsx`, submodule, migrations, тесты backend.

## API эндпоинты (уже существуют на backend)

```
GET  /production/plan?year=2026        → PlanBoardOut (вся матрица за год)
PUT  /production/plan/cell             body: {year, product, month, plan_qty} → PlanBoardOut
POST /production/plan/position         body: {year, product, monthly: int[12]} → PlanBoardOut
DELETE /production/plan/position?year=2026&product=...  → 204
```

Клиент ходит через `/api/production/...` (прокси). SSR ходит через `process.env.BACKEND_URL ?? "http://localhost:8000"`.

## Типы (production-plan.ts)

```typescript
export interface PlanCell {
  month: number;      // 1..12
  plan_qty: number;
  plan_nh: number;    // plan_qty × norm_nh, считается бэком
  fact_qty: number;
  fact_nh: number;    // fact_qty × norm_nh, считается бэком
}

export interface PlanRow {
  product: string;
  norm_nh: number;        // н.ч/шт из утверждённой нормы (0 если нет)
  months: PlanCell[];     // всегда 12 элементов
  year_qty: number;
  year_nh: number;
}

export interface PlanTotals {
  month_nh: number[];   // план н.ч по месяцам (12)
  fact_nh: number[];    // факт н.ч по месяцам (12)
  load_pct: number[];   // plan_nh / capacity_nh * 100 (12)
  year_nh: number;
  plan_ytd: number;
  fact_ytd: number;
  peak_month: number;   // 0-based индекс
  low_month: number;
}

export interface PlanBoard {
  year: number;
  capacity_nh: number;    // мощность цеха н.ч/мес (workers × 176)
  rows: PlanRow[];
  totals: PlanTotals;
}

export interface PlanCellUpdate {
  year: number;
  product: string;
  month: number;
  plan_qty: number;
}

export interface PlanPositionUpsert {
  year: number;
  product: string;
  monthly: number[];   // ровно 12
}
```

## Хелперы (production-plan.ts)

```typescript
/** Цвет загрузки по порогам: >100 → red, ≥70 → amber, else → green */
export function loadTone(pct: number): string {
  if (pct > 100) return "bg-red-50 text-red-600";
  if (pct >= 70) return "bg-amber-50 text-amber-600";
  return "bg-green-50 text-green-600";
}

/** Форматировать н.ч: 1 знак после запятой, разделитель — запятая (руский стиль) */
export function fmtNh(nh: number): string {
  return nh.toFixed(1).replace(".", ",");
}
```

## API-обёртки (production-plan.ts)

```typescript
const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

// SSR (Server Component) — прямо на бэкенд
export async function fetchPlanServer(year?: number, roles?: string): Promise<PlanBoard | null> { ... }

// Клиент — через /api прокси
export async function fetchPlan(year?: number): Promise<PlanBoard | null> { ... }
export async function putPlanCell(update: PlanCellUpdate): Promise<PlanBoard | null> { ... }
export async function upsertPosition(data: PlanPositionUpsert): Promise<PlanBoard | null> { ... }
export async function deletePosition(year: number, product: string): Promise<boolean> { ... }
```

## page.tsx (Server Component)

```tsx
import { AppShell } from "@/components/app-shell";
import { PlanMatrix } from "@/components/erp/plan-matrix";
import { fetchPlanServer } from "@/lib/production-plan";
import { currentRole } from "@/lib/role-server";

export default async function ProductionPlanningPage() {
  const role = await currentRole();
  const board = await fetchPlanServer(new Date().getFullYear(), role);
  return (
    <AppShell crumbs={["ERP", "Производство", "Планирование · план/факт"]}>
      <PlanMatrix initial={board} />
    </AppShell>
  );
}
```

## plan-matrix.tsx ("use client" компонент)

Что должен делать:
1. **KPI-строка** вверху: «Мощность: X н.ч/мес», «План YTD: X н.ч», «Факт YTD: X н.ч», «Пик: месяц».
2. **Выбор года**: кнопки ‹ › или select; при смене — fetchPlan(year).
3. **Матрица** (таблица):
   - Заголовок: «Изделие» | Янв..Дек | «Итого»
   - Строки изделий:
     - Ячейка qty редактируется: клик → input (число) → blur → putPlanCell → board обновляется
     - Цвет ячейки от loadTone(load_pct[month-1])
     - В заголовке строки — кнопка удалить позицию (мусорка)
   - Строка «Σ н.ч» (итого план н.ч по столбцам)
   - Строка «Загрузка %» (load_pct с цветными бейджами)
4. **График мощности** под матрицей: для каждого месяца — два CSS-бара (план и факт), пропорциональные capacity_nh. Подписи: план н.ч / факт н.ч.
5. **Добавить позицию**: кнопка → форма (product: text, monthly[12]: числа) → POST → board обновляется.

Стиль — следуй тому, что уже есть в bom-panel.tsx / norms-table.tsx (Tailwind, таблицы без внешних UI-libs кроме lucide-react).

## production-plan.test.ts

Тестируй ТОЛЬКО чистые функции (без fetch, без React):
- `loadTone`: граничные значения 70, 100, 101
- `fmtNh`: 1.0 → "1,0"; 176.5 → "176,5"; 0 → "0,0"
- Если добавишь aggregate-хелперы (например, `sumYearNh(rows)`) — тестируй их тоже

## Верификация

```powershell
npx tsc --noEmit                           # 0 ошибок TypeScript
npm --prefix frontend run test:run         # vitest зелёный
```

НЕ запускать `next lint` (eslint не установлен, зависает).

## Коммит

Один коммит в свою ветку (prod-fe-planning). Формат six-layer:
```
feat(frontend): prod-fe-planning — матрица план/факт производства

What: production-plan.ts (типы+хелперы+API), plan-matrix.tsx (матрица+KPI+график), page.tsx
Why: экран планирования производства §6 контракта
How: Server-page SSR + "use client" компонент, мутации через /api прокси
Refs: coordination/production-planning-contract.md §6
Tests: production-plan.test.ts (vitest 0), tsc --noEmit 0
Notes: sidebar не тронут (оркестратор добавит после интеграции)
```

Завершить баннером `STATE: COMPLETE` в `coordination/prod-fe-planning-status.md`.
