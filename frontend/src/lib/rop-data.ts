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
  { id: "promsnab", name: "ООО ПромСнаб", amount: "58 000 BYN", reason: "Цена выше конкурента", wait: "ждёт 6 ч · проверить сегодня", waitTone: "red", selected: true },
  { id: "energoblok", name: "ООО Энергоблок", amount: "84 000 BYN", reason: "Сроки поставки", wait: "ждут 1 день", waitTone: "slate" },
  { id: "tehkomplekt", name: "ИП ТехКомплект", amount: "41 000 BYN", reason: "Нет товара в наличии", wait: "ждут 4 ч", waitTone: "slate" },
  { id: "orbita", name: "Орбита-Трейд", amount: "12 000 BYN", reason: "Нет ответа клиента", wait: "ждут 2 дня · просрочка проверки", waitTone: "red" },
];
export const lossQueueNorm = "Норматив: разобрать в течение 24 часов";

/** Разбор выбранной сделки (ПромСнаб). */
export const lossReview = {
  name: "ООО ПромСнаб",
  amount: "58 000 BYN",
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

// ===================== ПЛАНИРОВАНИЕ (ёмкость) =====================

export interface PlanCard {
  label: string;
  value: string;
  note?: string;
  gap: string;
  percent: number;
  tone: Tone;
  accent?: boolean;
}

/** Три плоскости плана + эшелон под контракты. */
export const planCards: PlanCard[] = [
  { label: "Контракты · июнь (подписать)", value: "193 000 / 300 000 BYN", percent: 64, gap: "разрыв 107 000 · прогноз закрытия / план контрактов", tone: "amber" },
  { label: "Прибыль по отгрузке · июнь", value: "54 000 / 60 000 BYN", note: "текущие к отгрузке 42к + быстрые 12к", percent: 90, gap: "разрыв 6 000 · маржа по отгрузкам месяца", tone: "green" },
  { label: "Поступление денег · июнь", value: "215 000 / 250 000 BYN", percent: 86, gap: "разрыв 35 000 · платёжный календарь (≠ отгрузке)", tone: "green" },
  { label: "Под контракты · эшелон", value: "480 000 BYN", note: "отгрузка Q3–Q4 · контракты подписаны", percent: 100, gap: "в прибыль июнь не входят, в контракты — да", tone: "violet", accent: true },
];
export const planCardsNote =
  "План по контрактам 300к (подписать) шире плана выручки 280к в Обзоре — контракты включают отгрузки будущих периодов (эшелон).";

export interface CapacityRow {
  name: string;
  plan: string;
  forecast: string;
  gap: string;
  gapTone: Tone;
  pipeline: string;
  pipelineTone?: Tone;
  win: string;
  winTone?: Tone;
  verdict: string;
  verdictTone: Tone;
  verdictNote: string;
  stage: string;
  coaching: string;
}

/** Хватает ли воронки каждому менеджеру под план. */
export const capacity: CapacityRow[] = [
  { name: "Анна А.", plan: "90 000", forecast: "72 000", gap: "18 000", gapTone: "green", pipeline: "80 000", win: "28%", verdict: "Хватает воронки", verdictTone: "green", verdictNote: "новые не нужны — дожимать текущие", stage: "Конверсия в норме по этапам", coaching: "фокус: удержание скорости" },
  { name: "Дмитрий Д.", plan: "75 000", forecast: "60 000", gap: "15 000", gapTone: "amber", pipeline: "70 000", win: "26%", verdict: "Почти хватает", verdictTone: "amber", verdictNote: "дожать + 1 новая для буфера", stage: "Этап: КП → Переговоры (слабый)", coaching: "ценностное КП + аналоги" },
  { name: "Мария М.", plan: "70 000", forecast: "33 000", gap: "37 000", gapTone: "red", pipeline: "45 000", win: "22%", verdict: "Нужно +4 новых (~140к)", verdictTone: "blue", verdictNote: "воронки мало, чтобы закрыть разрыв", stage: "Этап: Квалификация (теряет рано)", coaching: "BANT, скрипт discovery" },
  { name: "Сергей С.", plan: "65 000", forecast: "28 000", gap: "37 000", gapTone: "red", pipeline: "100 000", pipelineTone: "red", win: "12%", winTone: "red", verdict: "Не брать новые", verdictTone: "red", verdictNote: "воронки много, конверсия низкая — чинить", stage: "Этап: Переговоры → Договор", coaching: "возражения + разбор звонков" },
];

/** Итоговая строка таблицы ёмкости — сумма столбцов (сходится с картой «Контракты»). */
export const capacityTotal = { plan: "300 000", forecast: "193 000", gap: "107 000", pipeline: "295 000" };
export const capacityNote =
  "«Воронка взвеш.» — квалифицированный пайплайн под план; полный пайплайн «в работе» (290к и т.д.) — в Обзоре. Прогноз = обязательство закрытия по менеджеру.";

export interface PlanAction {
  who: string;
  text: string;
  tone: Tone;
}

/** План действий отдела на месяц. */
export const planActions: PlanAction[] = [
  { who: "Анна", text: "дожать 2 сделки в «Договор» (32 000) к 20.06", tone: "green" },
  { who: "Дмитрий", text: "+1 новая + ускорить отгрузку «Тернопарк» в июнь", tone: "amber" },
  { who: "Мария", text: "+4 сделки в воронку (закрепить разбор причин проигрышей) + коучинг квалификации", tone: "blue" },
  { who: "Сергей", text: "стоп на новые; ревизия воронки 100 000 + разбор 5 звонков", tone: "red" },
  { who: "Отдел", text: "добрать прибыль +6 000: ускорить отгрузки готовых сделок", tone: "teal" },
  { who: "Деньги", text: "закрыть дебиторку «ХимПром» (18 дн) для поступления", tone: "red" },
];
export const planRule =
  "Правило: разрыв ÷ Win% = нужная воронка. Меньше — берём новые; больше при низком Win — чиним конверсию.";
export const planNorm = "Норма покрытия 3–4× к плану, но с поправкой на конверсию по этапам.";

export interface Lever {
  title: string;
  text: string;
}

/** Рычаги конверсии по этапам воронки. */
export const conversionLevers: Lever[] = [
  { title: "Квалификация", text: "BANT/чек-лист, скрипт выявления потребности, отсев нецелевых" },
  { title: "КП / презентация", text: "ценностное КП, расчёт выгоды, кейсы, аналоги, демо" },
  { title: "Переговоры / цена", text: "плейбук возражений по цене, срочность, выход на ЛПР" },
  { title: "Скорость / дожатие", text: "SLA на следующий шаг, разбор звонков, ролевые игры" },
];
export const leversNote = "Коучинг — по записям звонков, привязанным к слабому этапу. A/B-тест скриптов там, где просадка против нормы.";

// ===================== ТЕМП (пульс · прибыль · скорость) =====================

export interface PaceMeter {
  label: string;
  state: string;
  stateTone: Tone;
  percent: number;
  toDate: string;
  forecast: string;
  note?: string;
  noteTone?: Tone;
}

export const paceHeader = "Сегодня · день 6 из 21 · неделя 2";
export const paceBadge = "Прибыль в графике, выручка отстаёт";

/** Дневной пульс: контракты / прибыль / деньги. */
export const paceMeters: PaceMeter[] = [
  { label: "Контракты", state: "Отставание", stateTone: "amber", percent: 21, toDate: "к дате 62к · план 86к (−24к)", forecast: "прогноз 244к (−56к)" },
  { label: "Прибыль (отгрузка)", state: "В графике", stateTone: "green", percent: 30, toDate: "к дате 18к · план 17к (+1к)", forecast: "маржа 11% · план 14% (−3пп)", note: "рычаг прибыли", noteTone: "amber" },
  { label: "Деньги", state: "Отставание", stateTone: "amber", percent: 21, toDate: "к дате 52к · план 71к (−19к)", forecast: "прогноз 215к (−35к)" },
];

export interface VelocityCell {
  label: string;
  value: string;
  badge?: string;
  badgeTone?: Tone;
  accent?: boolean;
}

/** Sales velocity — пять рычагов прибыли. */
export const velocity = {
  formula: "Открытых 48 × Конверсия 24% × Чек 35 000 × Маржа 11% ÷ Цикл 24 дн",
  result: "≈ 1 850 BYN прибыли / день",
  cells: [
    { label: "Открытых сделок", value: "48" },
    { label: "Конверсия (win)", value: "24%", badge: "рычаг", badgeTone: "blue" },
    { label: "Средний чек", value: "35 000" },
    { label: "Маржа", value: "11%", badge: "главный рычаг", badgeTone: "red", accent: true },
    { label: "Цикл сделки", value: "24 дн", badge: "длинный", badgeTone: "amber" },
  ] as VelocityCell[],
  highlight:
    "+3пп маржи (перестать скидывать) и +5пп конверсии → +45% прибыли на новых сделках.",
  note:
    "Самый дешёвый рычаг — маржа: ценностные продажи дают +2–4пп маржи и до −12% скидок, влияя сразу на все рычаги.",
};

export interface AiRec {
  n: number;
  text: string;
  badge: string;
}

export const aiHeader = "ИИ-рекомендации к темпу · приоритет действий для прибыли";
export const aiForecast =
  "Прогноз прибыли 39к → при марже 13% и закрытии 2 фокусных → 58к. ИИ расставит действия по влиянию на прибыль:";

/** Рекомендации ассистента РОП (Итерация 1). */
export const aiRecs: AiRec[] = [
  { n: 1, text: "Поднять пол по марже: 3 сделки Сергея со скидкой >10% → пересогласовать", badge: "+маржа ~2пп" },
  { n: 2, text: "Апсейл и бандлы к 5 текущим клиентам → назначить Марии", badge: "+средний чек" },
  { n: 3, text: "Контроль оплаты «ХимПром» (дебиторка 18 дн) до отгрузки", badge: "+деньги" },
];

export interface MarginBar {
  label: string;
  value: string;
  valueTone: Tone;
  percent: number;
  tone: Tone;
}

/** Маржа и утечки. */
export const marginAvg: MarginBar = { label: "Средняя маржа", value: "11% · план 14% (−3пп)", valueTone: "amber", percent: 78, tone: "amber" };
export const marginMix: MarginBar = { label: "Маржинальный микс (высокомаржинальные SKU)", value: "35% · цель 50%", valueTone: "amber", percent: 35, tone: "amber" };
export const discountLeak = {
  value: "−18 000 BYN/мес (−6пп маржи)",
  note: "70% сделок закрываются со скидкой — высоко; режем через аппрув и «пол» по марже",
};

export interface ManagerMargin {
  name: string;
  margin: string;
  percent: number;
  tone: Tone;
}

/** Маржа по менеджерам. */
export const managerMargins: ManagerMargin[] = [
  { name: "Анна А.", margin: "14%", percent: 80, tone: "green" },
  { name: "Дмитрий Д.", margin: "12%", percent: 68, tone: "amber" },
  { name: "Мария М.", margin: "11%", percent: 62, tone: "amber" },
  { name: "Сергей С.", margin: "8%", percent: 45, tone: "red" },
];
export const managerMarginsNote = "Сергей «покупает» сделки скидкой — главный источник утечки.";
export const leakageNote =
  "В опте 10%+ прибыли утекает в бесконтрольных скидках и случайном миксе заказов — лечится правилами «что такое хорошая сделка», замером и разбором отклонений.";

/** Рычаги прибыли — отдел. */
export const profitLeversDept: string[] = [
  "Ценностные продажи вместо скидок (выгода/ROI)",
  "Жёсткий аппрув скидок РОПом + «пол» по марже",
  "Апсейл / кросс-сейл / бандлы — выше средний чек",
  "Маржинальный микс — двигать высокомаржинальные SKU и аналоги",
  "Квалификация (MEDDIC) — меньше слитого цикла",
];

export interface ManagerLever {
  name: string;
  badge: string;
  badgeTone: Tone;
  text: string;
}

/** Рычаги прибыли — по менеджерам. */
export const profitLeversManagers: ManagerLever[] = [
  { name: "Сергей С.", badge: "маржа 8–12%", badgeTone: "red", text: "удержание цены, разбор где скинул зря, тренинг по марже" },
  { name: "Мария М.", badge: "выше чек", badgeTone: "amber", text: "апсейл и кросс-сейл к текущим клиентам, бандлы" },
  { name: "Дмитрий Д.", badge: "меньше торга", badgeTone: "amber", text: "ценностное КП с расчётом выгоды — меньше скидывает на КП→Переговоры" },
  { name: "Анна А.", badge: "крупные/проектные", badgeTone: "green", text: "высокомаржинальные сделки + наставник по удержанию цены" },
];
export const velocityFooter = "Sales velocity: +10% к трём рычагам и −10% к циклу → +47% скорости.";
export const paceAiFootnote = "AI-рекомендации, прогноз прибыли и флаг утечки — ИИ, Итерация 1.";

// ===================== ДЕНЬГИ · ДЕБИТОРКА (DSO / старение) =====================
// Деньги — отдельная плоскость от прибыли: отгрузили с прибылью ≠ получили оплату.
// Завязано на нити других экранов: ХимПром 140к/18дн (Обзор), поступления 215к/250к и
// к дате 52к/71к (Темп) — числа сходятся.

/** KPI-полоса дебиторки (переиспользуем форму RopKpi). */
export const cashKpis: RopKpi[] = [
  { label: "Дебиторка всего", value: "312 000 BYN", sub: "к получению" },
  { label: "Просрочено", value: "191 000 BYN", sub: "61% дебиторки", tone: "red" },
  { label: "DSO (средний срок)", value: "34 дн", sub: "цель ≤ 30", tone: "amber" },
  { label: "Поступило к дате", value: "52 000 BYN", sub: "план 71к · −19к", tone: "amber" },
  { label: "Прогноз месяца", value: "215 000 BYN", sub: "план 250к · −35к", tone: "amber" },
  { label: "Просрочка 60+ дн", value: "9 000 BYN", sub: "в юр. отдел", tone: "red" },
];

export interface AgingBucket {
  bucket: string;
  amount: number;
  tone: Tone;
}

/** Корзины старения по дням просрочки (сумма = 312к). */
export const aging: AgingBucket[] = [
  { bucket: "Не просрочено", amount: 121000, tone: "green" },
  { bucket: "Просрочка 1–30 дн", amount: 140000, tone: "amber" },
  { bucket: "Просрочка 31–60 дн", amount: 42000, tone: "red" },
  { bucket: "Просрочка 60+ дн", amount: 9000, tone: "red" },
];
export const agingNote = "61% дебиторки просрочено — высоко. Главный риск — ХимПром 140к (1–30 дн).";

export interface Debtor {
  name: string;
  amount: string;
  status: string;
  statusTone: Tone;
  owner: string;
  action?: string;
}

/** Топ дебиторов (привязаны к клиентам Обзора). */
export const debtors: Debtor[] = [
  { name: "ООО ХимПром", amount: "140 000 BYN", status: "просрочка 18 дн", statusTone: "red", owner: "Дмитрий", action: "Эскалация" },
  { name: "ИП СтройКомплекс", amount: "42 000 BYN", status: "просрочка 41 дн", statusTone: "red", owner: "Мария", action: "Претензия" },
  { name: "ООО Тернопарк", amount: "18 000 BYN", status: "срок сегодня", statusTone: "amber", owner: "Анна", action: "Напомнить" },
  { name: "ООО «Сатурн»", amount: "16 000 BYN", status: "в срок (−3 дн)", statusTone: "green", owner: "Анна" },
  { name: "Бранд-Маркет", amount: "9 000 BYN", status: "просрочка 62 дн → юр.", statusTone: "red", owner: "Сергей", action: "В юр. отдел" },
];

export interface CalendarWeek {
  week: string;
  amount: string;
  state: string;
  tone: Tone;
  percent: number;
}

/** Платёжный календарь — недельные поступления (сумма = прогноз 215к). */
export const calendar: CalendarWeek[] = [
  { week: "Неделя 1 · 3–9 июн", amount: "52 000 / 71 000", state: "собрано · −19к", tone: "amber", percent: 73 },
  { week: "Неделя 2 · 10–16 июн", amount: "60 000", state: "ожидается", tone: "slate", percent: 100 },
  { week: "Неделя 3 · 17–23 июн", amount: "55 000", state: "ожидается", tone: "slate", percent: 92 },
  { week: "Неделя 4 · 24–30 июн", amount: "48 000", state: "ожидается", tone: "slate", percent: 80 },
];
export const calendarNote =
  "Прогноз месяца 215 000 / 250 000 BYN (−35к). Добрать — ускорить оплату ХимПром и СтройКомплекс.";

export interface ManagerDso {
  name: string;
  debt: string;
  overdue: string;
  dso: string;
  tone: Tone;
  note: string;
}

/** DSO по менеджерам (сумма долга = 312к, просрочка = 191к). */
export const managerDso: ManagerDso[] = [
  { name: "Анна А.", debt: "60 000", overdue: "0", dso: "24 дн", tone: "green", note: "собирает в срок" },
  { name: "Дмитрий Д.", debt: "165 000", overdue: "140 000", dso: "44 дн", tone: "red", note: "ХимПром 140к завис — контроль до отгрузки" },
  { name: "Мария М.", debt: "50 000", overdue: "42 000", dso: "38 дн", tone: "red", note: "СтройКомплекс — претензия" },
  { name: "Сергей С.", debt: "37 000", overdue: "9 000", dso: "33 дн", tone: "amber", note: "Бранд-Маркет → юр. отдел" },
];
export const managerDsoTotal = { debt: "312 000", overdue: "191 000", dso: "34 дн" };

/** Дисциплина платежей — правила РОПа. */
export const cashDiscipline: string[] = [
  "Предоплата ≥ 30% по новым клиентам",
  "Стоп-отгрузка при просрочке > 30 дн",
  "Кредитный лимит на клиента — по истории платежей",
  "Эскалация в юр. отдел при просрочке > 60 дн",
  "Контроль оплаты до отгрузки для крупных (ХимПром 140к)",
];
export const cashDisciplineNote =
  "Деньги — отдельная плоскость от прибыли: можно отгрузить с прибылью и не получить оплату. DSO ≤ 30 дн держит оборотку.";
