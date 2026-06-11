/** Demo-данные экрана РОП «Активность · ведущие индикаторы».
 *
 * Ведущие индикаторы (звонки, встречи, КП, реакция на лид) — управляемы
 * сегодня и предсказывают выручку завтра, в отличие от отстающих результатов
 * (Деньги, Этапы). Числа демонстрационные и сведены с другими экранами РОП:
 *   • звонки 58/41/33/22 = 154 — как `team`/`teamTotal` в rop-data.ts;
 *   • закрыто 6 сделок — как нижний этап `funnel` (Обзор);
 *   • индекс активности 92/74/61/48 = `team.plan` (% выполнения плана);
 *   • застрявшие сделки — те же клиенты, что в `attention`/`focus`.
 *
 * Чистые данные без зависимостей от React — страница только рисует.
 */

import type { RopKpi, Tone } from "@/lib/rop-data";

// ===================== KPI-полоса (ведущие индикаторы) =====================

/** Верхняя полоса — активность отдела за неделю (форма RopKpi). */
export const activityKpis: RopKpi[] = [
  { label: "Звонки · неделя", value: "154", sub: "план 175 · 88%", tone: "amber" },
  { label: "Встречи и демо", value: "28", sub: "план 32 · −4", tone: "amber" },
  { label: "Новые квалификации", value: "22", sub: "лиды в воронку · план 25", tone: "slate" },
  { label: "Выставлено КП", value: "17", sub: "коммерческих · план 20", tone: "amber" },
  { label: "Реакция на лид", value: "3.4 ч", sub: "цель ≤ 2 ч", tone: "red" },
  { label: "Без следующего шага", value: "11", sub: "сделок · гигиена воронки", tone: "red" },
];

// ===================== Активность vs норма (неделя) =====================

export interface ActivityNorm {
  label: string;
  fact: number;
  norm: number;
  percent: number;
  tone: Tone;
}

/** Объёмы активности против недельной нормы. */
export const activityNorms: ActivityNorm[] = [
  { label: "Звонки", fact: 154, norm: 175, percent: 88, tone: "amber" },
  { label: "Встречи и демо", fact: 28, norm: 32, percent: 88, tone: "amber" },
  { label: "Новые квалификации", fact: 22, norm: 25, percent: 88, tone: "slate" },
  { label: "Выставлено КП", fact: 17, norm: 20, percent: 85, tone: "amber" },
  { label: "Касаний на активную сделку", fact: 4.1, norm: 6, percent: 68, tone: "red" },
];
export const activityNormsNote =
  "Активность — ведущий индикатор: предсказывает выручку следующего месяца. Объёмы держатся на 85–88% нормы, слабее всего — касания на сделку и реакция на лид (теряем тёплые лиды).";

// ===================== Цепочка: активность → результат =====================

export interface ActivityFunnelStep {
  label: string;
  count: number;
  /** Конверсия из предыдущего шага. */
  conv?: string;
  bottleneck?: boolean;
  tone: Tone;
}

/** Воронка активности: звонки → встречи → КП → закрытые сделки. */
export const activityFunnel: ActivityFunnelStep[] = [
  { label: "Звонки", count: 154, tone: "blue" },
  { label: "Встречи / демо", count: 28, conv: "↓ 18% звонок → встреча", bottleneck: true, tone: "red" },
  { label: "Выставлено КП", count: 17, conv: "↓ 61% встреча → КП", tone: "teal" },
  { label: "Закрыто: успешно", count: 6, conv: "↓ 35% КП → сделка", tone: "green" },
];
export const activityFunnelNote =
  "Слабое звено — звонок → встреча (18%): много активности «вхолостую», тёплых лидов мало. Ведущие индикаторы держат план следующего месяца, а не текущего.";

// ===================== Активность по менеджерам =====================

export interface ManagerActivity {
  name: string;
  calls: number;
  meetings: number;
  kp: number;
  /** Сделки без назначенного следующего шага. */
  noNext: number;
  /** Индекс активности 0–100 (≈ % выполнения плана). */
  index: number;
  indexTone: Tone;
}

/** Активность по менеджерам за неделю (звонки сведены с `team` в rop-data). */
export const managerActivity: ManagerActivity[] = [
  { name: "Анна А.", calls: 58, meetings: 11, kp: 6, noNext: 1, index: 92, indexTone: "green" },
  { name: "Дмитрий Д.", calls: 41, meetings: 8, kp: 5, noNext: 3, index: 74, indexTone: "amber" },
  { name: "Мария М.", calls: 33, meetings: 6, kp: 4, noNext: 3, index: 61, indexTone: "amber" },
  { name: "Сергей С.", calls: 22, meetings: 3, kp: 2, noNext: 4, index: 48, indexTone: "red" },
];
export const managerActivityTotal = { calls: 154, meetings: 28, kp: 17, noNext: 11 };
export const managerActivityNote =
  "Индекс активности почти повторяет % выполнения плана (Обзор): Сергей — мало звонков и встреч, 4 сделки без следующего шага. Активность управляема сегодня, в отличие от результата.";

// ===================== Сделки без следующего шага =====================

export interface StaleDeal {
  name: string;
  owner: string;
  amount: string;
  idle: string;
  idleTone: Tone;
  action?: string;
}

/** Гигиена воронки — застрявшие сделки (те же клиенты, что в `attention`/`focus`). */
export const staleDeals: StaleDeal[] = [
  { name: "ИП СтройКомплекс", owner: "Мария", amount: "42 000 BYN", idle: "5 дней без действий", idleTone: "red", action: "Назначить шаг" },
  { name: "ООО АльфаМеталл", owner: "Дмитрий", amount: "58 000 BYN", idle: "молчит 2 дня", idleTone: "amber", action: "Напомнить" },
  { name: "Бранд-Маркет", owner: "Сергей", amount: "9 000 BYN", idle: "нет следующего шага", idleTone: "red", action: "Встреча с ЛПР" },
  { name: "Гамма-Трейд", owner: "Сергей", amount: "6 000 BYN", idle: "не определён ЛПР", idleTone: "slate", action: "Квалификация" },
];
export const staleDealsNote =
  "11 сделок без следующего шага — главный лаг-фактор. Норматив: у каждой активной сделки назначен следующий шаг с датой.";

// ===================== Нормативы активности =====================

/** Правила РОПа по ведущим индикаторам. */
export const activityRules: string[] = [
  "Звонки ≥ 35 в неделю на менеджера",
  "Реакция на новый лид ≤ 2 часов",
  "У каждой активной сделки — следующий шаг с датой",
  "≥ 6 касаний на сделку до решения",
  "Еженедельный разбор активности 1-на-1 с РОПом",
];
export const activityRulesNote =
  "Ведущие индикаторы (звонки, встречи, реакция, касания) управляемы сегодня и предсказывают выручку/прибыль завтра — в отличие от отстающих (Деньги, Этапы).";
