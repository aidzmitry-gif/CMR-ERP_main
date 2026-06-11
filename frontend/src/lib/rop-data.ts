/** Demo-данные дашборда РОП (Обзор + Ревью проигрышей).
 *
 * Витрина концепта — как `FUNNEL_EXTRAS` у других модулей: значения
 * демонстрационные (как в макетах-референсах), живые данные подключаются
 * отдельной фазой (стадия `lost`, `probability`, `manager_target`). Валюта — BYN.
 *
 * Чистые данные без зависимостей от React — держим здесь, страницы только рисуют.
 */

export type Tone = "green" | "amber" | "red" | "blue" | "violet" | "slate" | "teal";

// ===================== ОБЗОР РОП (cockpit) =====================

export interface RopKpi {
  label: string;
  value: string;
  sub: string;
  tone?: Tone;
}

/** Верхняя KPI-полоса обзора. */
export const overviewKpis: RopKpi[] = [
  { label: "План июнь", value: "280 000 BYN", sub: "цель месяца" },
  { label: "Прогноз (обязат. + закрыто)", value: "193 000 BYN", sub: "69% плана", tone: "teal" },
  { label: "Покрытие воронки", value: "3.2×", sub: "норма 3–5×" },
  { label: "Конверсия в продажу", value: "27%", sub: "лид → сделка" },
  { label: "Средний цикл сделки", value: "24 дн", sub: "заявка → закрытие" },
  { label: "Срыв сроков закрытия", value: "12%", sub: "прогноз съезжает", tone: "red" },
];

export interface AccuracyMonth {
  label: string;
  value: string;
  tone: Tone;
}

/** Точность прогноза по месяцам (план → факт). */
export const accuracy: AccuracyMonth[] = [
  { label: "Апр", value: "104%", tone: "green" },
  { label: "Май", value: "91%", tone: "amber" },
  { label: "Июнь", value: "69% (тек.)", tone: "slate" },
];
export const accuracyNote = "Из «обязательств» прошлого месяца закрылось 84%";

export interface MovementItem {
  label: string;
  value: string;
  tone: Tone;
}

/** Движение пайплайна за неделю. */
export const movement: MovementItem[] = [
  { label: "Новые", value: "+70 000", tone: "green" },
  { label: "Подтянуто", value: "+20 000", tone: "teal" },
  { label: "Срыв", value: "−17 000", tone: "amber" },
  { label: "Проиграно", value: "−10 000", tone: "red" },
];
export const movementNet = "Чистое движение: +63 000 BYN";

export interface ForecastPart {
  id: string;
  label: string;
  amount: number;
  count: number;
  tone: Tone;
  /** Входит ли в полосу прогноза (взвешенная проработка — только в легенду). */
  inBar: boolean;
}

/** Прогноз на месяц по категориям + контекст покрытия. */
export const forecast = {
  plan: 280000,
  parts: [
    { id: "won", label: "Закрыто", amount: 110000, count: 12, tone: "green", inBar: true },
    { id: "commit", label: "Обязательство", amount: 83000, count: 6, tone: "teal", inBar: true },
    { id: "best", label: "Лучший сценарий", amount: 63000, count: 5, tone: "amber", inBar: true },
    { id: "work", label: "В проработке (взвеш.)", amount: 42000, count: 18, tone: "slate", inBar: false },
  ] as ForecastPart[],
  forecastSum: 256000,
  toPlan: 24000,
  coverage: "3.2×",
  pipelineTotal: "900 000 BYN",
  warn:
    "Обязательство + закрыто = 193 000 BYN (69% плана). Тонкое «обязательство» при раздутой проработке — сигнал проверить квалификацию.",
};

export interface FunnelRow {
  stage: string;
  count: number;
  conv?: string;
  bottleneck?: boolean;
  tone: Tone;
}

/** Здоровье воронки — сколько сделок на каждом этапе. */
export const funnel: FunnelRow[] = [
  { stage: "Квалификация", count: 68, tone: "blue" },
  { stage: "Коммерческое предл.", count: 38, conv: "↓ 56%", tone: "blue" },
  { stage: "Согласование", count: 14, conv: "↓ 37%", bottleneck: true, tone: "red" },
  { stage: "Договор", count: 9, conv: "↓ 64%", tone: "teal" },
  { stage: "Закрыто: успешно", count: 6, conv: "↓ 67%", tone: "green" },
];
export const funnelNote = "Узкое место: КП → согласование (37%) — ниже нормы";

export interface AttentionDeal {
  name: string;
  amount: string;
  tone: Tone;
  note: string;
  action?: boolean;
}

/** Сделки, требующие внимания РОПа. */
export const attention: AttentionDeal[] = [
  { name: "ООО ХимПром", amount: "140 000 BYN", tone: "red", note: "Дебиторка: просрочка 18 дн → претензия" },
  { name: "ООО «Сатурн»", amount: "16 000 BYN", tone: "amber", note: "Скидка 14% (мин. 15 400 BYN) — ждёт согласования", action: true },
  { name: "ИП СтройКомплекс", amount: "42 000 BYN", tone: "red", note: "5 дней без действий" },
  { name: "ООО Тернопарк", amount: "18 000 BYN", tone: "violet", note: "Обязательство, но срок закрытия прошёл" },
  { name: "Гамма-Трейд", amount: "6 000 BYN", tone: "slate", note: "Слабая квалификация: не определён ЛПР" },
];

export interface TeamRow {
  name: string;
  inWork: string;
  commit: string;
  plan: number;
  planTone: Tone;
  calls: number;
}

/** Команда отдела продаж за месяц (BYN). */
export const team: TeamRow[] = [
  { name: "Анна А.", inWork: "290 000", commit: "72 000", plan: 92, planTone: "green", calls: 58 },
  { name: "Дмитрий Д.", inWork: "207 000", commit: "60 000", plan: 74, planTone: "amber", calls: 41 },
  { name: "Мария М.", inWork: "137 000", commit: "33 000", plan: 61, planTone: "amber", calls: 33 },
  { name: "Сергей С.", inWork: "100 000", commit: "28 000", plan: 48, planTone: "red", calls: 22 },
];
export const teamTotal = { inWork: "734 000", commit: "193 000", plan: 69, calls: 154 };

export interface FocusDeal {
  name: string;
  amount: string;
  prob: number;
  probTone: Tone;
  risk: string;
  riskTone: Tone;
  rec: string;
  date: string;
}

export const focusSummary =
  "6 фокусных · 410 000 BYN в работе · в графике 4, под риском 2 · прогноз к закрытию 280 000 BYN";

/** Фокусные сделки (правила-эвристики, Итерация 1). */
export const focus: FocusDeal[] = [
  { name: "ООО «Сатурн»", amount: "16 000 BYN", prob: 82, probTone: "green", risk: "В графике", riskTone: "green", rec: "Позвонить и закрыть скидку сегодня", date: "12.06" },
  { name: "ООО ХимПром", amount: "140 000 BYN", prob: 64, probTone: "amber", risk: "Дебиторка 18 дн", riskTone: "red", rec: "Эскалация: контроль оплаты до отгрузки", date: "20.06" },
  { name: "ООО АльфаМеталл", amount: "58 000 BYN", prob: 71, probTone: "amber", risk: "Молчит 2 дня", riskTone: "amber", rec: "Напомнить о КП и предложить аналог дешевле", date: "18.06" },
  { name: "Бранд-Маркет", amount: "9 000 BYN", prob: 48, probTone: "red", risk: "Нет след. шага", riskTone: "red", rec: "Назначить встречу с ЛПР, иначе уйдёт в проигрыш", date: "25.06" },
];
export const focusFootnote =
  "Вероятность — эвристика по правилам (дни без действий, дебиторка, скидка), не модель. Числа демонстрационные.";

// ===================== РЕВЬЮ ПРОИГРЫШЕЙ =====================

export interface LossQueueItem {
  id: string;
  name: string;
  amount: string;
  reason: string;
  wait: string;
  waitTone: Tone;
  selected?: boolean;
}

/** Очередь «условно проиграна» — ждут разбора РОПа. */
export const lossQueue: LossQueueItem[] = [
  { id: "alfa", name: "ООО АльфаМеталл", amount: "1,75 млн BYN", reason: "Цена выше конкурента", wait: "ждёт 6 ч · проверить сегодня", waitTone: "red", selected: true },
  { id: "energo", name: "ООО Энергия", amount: "3,2 млн BYN", reason: "Сроки поставки", wait: "ждут 1 день", waitTone: "slate" },
  { id: "stroy", name: "ИП СтройКомплекс", amount: "1,25 млн BYN", reason: "Нет товара в наличии", wait: "ждут 4 ч", waitTone: "slate" },
  { id: "gamma", name: "Гамма-Трейд", amount: "180 000 BYN", reason: "Нет ответа клиента", wait: "ждут 2 дня · просрочка проверки", waitTone: "red" },
];
export const lossQueueNorm = "Норматив: разобрать в течение 24 часов";

/** Разбор выбранной сделки (АльфаМеталл). */
export const lossReview = {
  name: "ООО АльфаМеталл",
  amount: "1,75 млн BYN",
  meta: "Проиграна на этапе «Согласование» · менеджер Дмитрий · была в работе 22 дня",
  reason: "Цена выше конкурента (−8%)",
  competitor: "Конкурент: МеталлТорг",
  better: [
    "Раньше выйти на ЛПР — подключили поздно",
    "Предложить аналог дешевле — не предложили",
    "Реакция на запрос — 2 дня, слишком медленно",
  ],
  winback: ["Аналог дешевле (−6%)", "Спец-цена через РОПа", "Резерв + ускор. поставка", "Встреча с ЛПР"],
  lessons: [
    { text: "SLA на выставление КП ≤ 4 часов", done: true },
    { text: "Плейбук: возражение по цене + аналоги", done: true },
    { text: "Обучение: переговоры о цене", done: false },
  ],
};

export interface LossReason {
  label: string;
  percent: number;
  tone: Tone;
}

/** Причины проигрышей за месяц. */
export const lossReasons: LossReason[] = [
  { label: "Цена выше конкурента", percent: 38, tone: "red" },
  { label: "Сроки поставки", percent: 22, tone: "amber" },
  { label: "Нет нужного товара", percent: 18, tone: "amber" },
  { label: "Условия оплаты", percent: 12, tone: "slate" },
  { label: "Нет решения / бюджета", percent: 10, tone: "slate" },
];
export const lossReasonsNote = "Главная причина — цена: усилить Price Engine и предлагать аналоги.";

export interface Improvement {
  text: string;
  owner: string;
  status: string;
  statusTone: Tone;
}

/** Трекер улучшений — что чиним по итогам разборов. */
export const improvements: Improvement[] = [
  { text: "SLA на выставление КП ≤ 4 ч", owner: "РОП", status: "в работе", statusTone: "amber" },
  { text: "Плейбук: возражение по цене + аналоги", owner: "Обуч.", status: "готово", statusTone: "green" },
  { text: "Держать остаток по топ-20 SKU", owner: "Закуп.", status: "запланир.", statusTone: "slate" },
  { text: "Раньше выявлять ЛПР (квалификация)", owner: "Квал", status: "в работе", statusTone: "amber" },
];
export const improvementsNote = "Замыкаем цикл: разбор → действие → проверка на следующих сделках.";
