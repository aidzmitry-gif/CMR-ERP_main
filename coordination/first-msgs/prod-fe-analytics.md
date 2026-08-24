# prod-fe-analytics — задание

## Контекст

Ты — воркер фронтенда CRM/ERP. Строишь экран «Аналитика производства».
Бэкенд **уже готов** (эндпоинт GET /production/analytics?year= существует). Submodule не трогаешь.

Главный контракт-документ: `coordination/production-planning-contract.md` (§4 «Аналитика» + §6 «Фронт»).
Образец паттерна: `frontend/src/lib/production-bom.ts` + `frontend/src/app/erp/production/bom/page.tsx`.

## Goal-Driven: напиши lib+test → сделай tsc зелёным → сделай vitest зелёным → сделай компонент → закоммить

## Файлы в твоей ответственности

```
frontend/src/lib/production-analytics.ts          — типы + хелперы + API-обёртки
frontend/src/lib/production-analytics.test.ts     — vitest (чистые функции)
frontend/src/app/erp/production/analytics/page.tsx — Server-page (SSR)
frontend/src/components/erp/production-analytics-view.tsx  — "use client" компонент
```

⚠️ ВАЖНО: файл называется `production-analytics-view.tsx` (НЕ `analytics-view.tsx` — это имя уже занято другим модулем erp/analytics).

НЕ трогаешь: `sidebar.tsx`, submodule, migrations, тесты backend.

## API эндпоинт (уже существует на backend)

```
GET /production/analytics?year=2026 → AnalyticsOut
```

Структура ответа (AnalyticsOut):
```
vyrabotka_fact_nh: float       — Σ fact_nh за год
vyrabotka_plan_nh: float       — Σ plan_nh YTD
efficiency_pct: float          — выработка н.ч ÷ (days_worked × 8) × 100
fpy_pct: float                 — accept ÷ (accept+rework+scrap) × 100 (с первого предъявления)
pass_rate_pct: float           — (accept+rework) ÷ всего × 100
scrap_pct: float               — scrap ÷ всего × 100
premium_fot_byn: float         — Σ (nh_output × PREMIUM_RATE) — премия от выработки
plan_fact_by_month: [{month, plan_nh, fact_nh}] × 12
scrap_reasons: [{reason, count}] — группировка причин брака
team_contribution: [{name, nh_output, share_pct}] — вклад сборщиков
top_products: [{product, fact_nh}] — топ изделий по факту desc
```

Клиент ходит через `/api/production/analytics` (прокси). SSR — через `process.env.BACKEND_URL`.

## Типы (production-analytics.ts)

```typescript
export interface MonthPlanFact {
  month: number;
  plan_nh: number;
  fact_nh: number;
}

export interface ScrapReason {
  reason: string;
  count: number;
}

export interface TeamMember {
  name: string;
  nh_output: number;
  share_pct: number;
}

export interface TopProduct {
  product: string;
  fact_nh: number;
}

export interface AnalyticsData {
  vyrabotka_fact_nh: number;
  vyrabotka_plan_nh: number;
  efficiency_pct: number;
  fpy_pct: number;
  pass_rate_pct: number;
  scrap_pct: number;
  premium_fot_byn: number;
  plan_fact_by_month: MonthPlanFact[];
  scrap_reasons: ScrapReason[];
  team_contribution: TeamMember[];
  top_products: TopProduct[];
}
```

## Хелперы (production-analytics.ts)

```typescript
/** Форматировать BYN: 2 знака, пробел между тысячами */
export function fmtByn(val: number): string {
  return val.toLocaleString("ru-BY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Форматировать н.ч: 1 знак, запятая */
export function fmtNh(nh: number): string {
  return nh.toFixed(1).replace(".", ",");
}

/** Форматировать процент: 1 знак, знак % */
export function fmtPct(pct: number): string {
  return pct.toFixed(1).replace(".", ",") + "%";
}

/** Цвет KPI-карточки для процентных показателей:
 *  fpy/pass_rate/efficiency — высокий хороший → green ≥80, amber ≥60, else red
 *  scrap_pct — низкий хороший → green ≤5, amber ≤15, else red
 */
export function kpiTone(type: "high" | "low", pct: number): string {
  if (type === "high") {
    if (pct >= 80) return "text-green-600";
    if (pct >= 60) return "text-amber-600";
    return "text-red-600";
  } else {
    if (pct <= 5) return "text-green-600";
    if (pct <= 15) return "text-amber-600";
    return "text-red-600";
  }
}
```

## API-обёртки (production-analytics.ts)

```typescript
const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function fetchAnalyticsServer(year?: number, roles?: string): Promise<AnalyticsData | null> { ... }
export async function fetchAnalytics(year?: number): Promise<AnalyticsData | null> { ... }
```

## page.tsx (Server Component)

```tsx
import { AppShell } from "@/components/app-shell";
import { ProductionAnalyticsView } from "@/components/erp/production-analytics-view";
import { fetchAnalyticsServer } from "@/lib/production-analytics";
import { currentRole } from "@/lib/role-server";

export default async function ProductionAnalyticsPage() {
  const role = await currentRole();
  const data = await fetchAnalyticsServer(new Date().getFullYear(), role);
  return (
    <AppShell crumbs={["ERP", "Производство", "Аналитика производства"]}>
      <ProductionAnalyticsView initial={data} />
    </AppShell>
  );
}
```

## production-analytics-view.tsx ("use client" компонент)

Что должен отображать:
1. **KPI-карточки** (6 штук в сетке):
   - Выработка факт / план (н.ч) + дельта
   - Эффективность % (kpiTone high)
   - FPY % — с первого предъявления (kpiTone high)
   - Брак % (kpiTone low)
   - Пропускаемость % — pass_rate_pct (kpiTone high)
   - Премия ФОТ (BYN, fmtByn)

2. **График «План/Факт по месяцам»** (CSS-бары):
   - 12 месяцев, каждый = 2 бара (план и факт), подписи янв..дек
   - Высота пропорциональна максимальному значению
   - Легенда: «план» (синий) / «факт» (зелёный)

3. **Таблица «Причины брака»**: reason | count | доля %; сортировка по count desc

4. **Вклад сборщиков**: таблица или горизонтальные бары: name | nh_output н.ч | share_pct %

5. **Топ изделий**: таблица product | fact_nh н.ч, топ-5 максимум

6. **Выбор года**: кнопки ‹ › → fetchAnalytics(year) → обновить data

Стиль — Tailwind, как в других production-экранах. `initial: AnalyticsData | null` — при null показать «Данные недоступны».

## production-analytics.test.ts

Тестируй ТОЛЬКО чистые функции:
- `fmtByn(1234.567)` → корректный формат с 2 знаками
- `fmtNh(1.0)` → "1,0"; `fmtNh(0)` → "0,0"
- `fmtPct(95.5)` → "95,5%"
- `kpiTone("high", 80)` → "text-green-600"
- `kpiTone("high", 60)` → "text-amber-600"
- `kpiTone("high", 59)` → "text-red-600"
- `kpiTone("low", 5)` → "text-green-600"
- `kpiTone("low", 16)` → "text-red-600"

## Верификация

```powershell
npx tsc --noEmit                           # 0 ошибок TypeScript
npm --prefix frontend run test:run         # vitest зелёный
```

НЕ запускать `next lint` (eslint не установлен, зависает).

## Коммит

Один коммит в свою ветку (prod-fe-analytics). Формат six-layer:
```
feat(frontend): prod-fe-analytics — аналитика производства

What: production-analytics.ts (типы+хелперы+API), production-analytics-view.tsx (KPI+графики+таблицы), page.tsx
Why: экран аналитики производства §4+§6 контракта
How: Server-page SSR + "use client" компонент, SSR+клиент fetch через /api прокси
Refs: coordination/production-planning-contract.md §4, §6
Tests: production-analytics.test.ts (vitest 0), tsc --noEmit 0
Notes: sidebar не тронут (оркестратор добавит после интеграции)
```

Завершить баннером `STATE: COMPLETE` в `coordination/prod-fe-analytics-status.md`.
