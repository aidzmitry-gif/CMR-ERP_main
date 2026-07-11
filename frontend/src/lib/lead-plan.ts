// Расчёт темпа дневного плана лидоруба (Цикл 5). Чистая логика — тестируется отдельно
// от React (frontend/CLAUDE.md: доменная логика в src/lib). Панель план/факта показывает
// не только «факт из N», но и «успеваешь ли к этому часу» — иначе норму видно только в конце дня.

// Рабочий день лидоруба: 9:00–18:00 локального времени (окно, по которому размазан план).
export const WORKDAY_START_HOUR = 9;
export const WORKDAY_END_HOUR = 18;

/** Доля рабочего дня, прошедшая к `now` (0..1): до 9:00 — 0, после 18:00 — 1. */
export function workdayElapsedFraction(now: Date): number {
  const h = now.getHours() + now.getMinutes() / 60;
  if (h <= WORKDAY_START_HOUR) return 0;
  if (h >= WORKDAY_END_HOUR) return 1;
  return (h - WORKDAY_START_HOUR) / (WORKDAY_END_HOUR - WORKDAY_START_HOUR);
}

/** Минуты РАБОЧИМИ часами (9:00-18:00 локального времени, ежедневно) между двумя моментами.
 *
 * Цикл 14 — честный SLA: ночь не считается. Иначе к 9:05 утра все ночные лиды одинаково
 * «горят 9ч+» — сигнал неразличим (alarm fatigue), а реально горящий дневной лид тонет
 * в утреннем пожаре. Идём по дням, суммируя пересечение интервала с рабочим окном.
 * ponytail: выходные считаются рабочими — отдел работает и по субботам; появится график
 * смен — вынести окно в настройку. */
export function workingMinutesBetween(from: Date, to: Date): number {
  if (to.getTime() <= from.getTime()) return 0;
  let total = 0;
  const cur = new Date(from);
  while (cur.getTime() < to.getTime()) {
    const dayStart = new Date(cur);
    dayStart.setHours(WORKDAY_START_HOUR, 0, 0, 0);
    const dayEnd = new Date(cur);
    dayEnd.setHours(WORKDAY_END_HOUR, 0, 0, 0);
    const segStart = Math.max(cur.getTime(), dayStart.getTime());
    const segEnd = Math.min(to.getTime(), dayEnd.getTime());
    if (segEnd > segStart) total += (segEnd - segStart) / 60000;
    cur.setHours(24, 0, 0, 0); // на следующий день 00:00
  }
  return Math.round(total);
}

export interface PacePoint {
  fact: number;
  target: number;
  expectedByNow: number; // сколько нужно набрать к этому часу
  remaining: number; // осталось до нормы
  pct: number; // прогресс 0..100 (факт/цель)
  onTrack: boolean; // факт не отстаёт от ожидаемого к этому часу
}

/** «Набрать не ниже» — обработано/целевых/сделки: прогресс + отставание от темпа. */
export function planPace(fact: number, target: number, elapsed: number): PacePoint {
  const expectedByNow = Math.round(target * elapsed);
  const remaining = Math.max(0, target - fact);
  const pct = target > 0 ? Math.min(100, Math.round((fact / target) * 100)) : 100;
  return { fact, target, expectedByNow, remaining, pct, onTrack: fact >= expectedByNow };
}
