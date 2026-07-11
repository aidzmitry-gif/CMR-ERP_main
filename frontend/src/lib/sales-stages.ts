/**
 * Канон стадий воронки продаж — единый фронтовый источник (SALES-43).
 * Зеркало backend `modules/sales/stages.py` (Сделки 2.0, цена ДО встречи):
 * id / title / color и порядок = колонки канбана. Держать синхронным с бэком.
 *
 * NB: legacy-набор (new/qual/prop/appr/won) ещё живёт в board.ts (STAGE_PROBABILITY)
 * и mock-data.ts (STAGES) и залочен board.test.ts — их миграция на этот канон —
 * отдельный шаг (демо-фикстуры + тест). Здесь — источник для карточки сделки.
 */
export interface SalesStage {
  id: string;
  title: string;
  color: string;
}

/** Все 11 стадий (9 прогрессия + 2 терминала-отказа); порядок = бэк stages.py. */
export const SALES_STAGES: SalesStage[] = [
  { id: "new", title: "Новая заявка", color: "#3B82F6" },
  { id: "qual", title: "Квалифицирован", color: "#8B5CF6" },
  { id: "price_req", title: "Цена запрошена", color: "#F59E0B" },
  { id: "has_price", title: "Есть цена", color: "#EAB308" },
  { id: "meeting", title: "Встреча назначена", color: "#14B8A6" },
  { id: "invoice", title: "Счёт отправлен", color: "#0EA5E9" },
  { id: "protected", title: "Счёт защищён", color: "#6366F1" },
  { id: "contract", title: "Договор/предоплата", color: "#10B981" },
  { id: "won", title: "Успех", color: "#22C55E" },
  { id: "cond_lost", title: "Условный отказ", color: "#F97316" },
  { id: "lost", title: "Отказ", color: "#EF4444" },
];

/** Терминальные стадии (сделка закрыта; cond_lost — реанимируемый, НЕ терминал). */
export const TERMINAL_STAGES: ReadonlySet<string> = new Set(["won", "lost"]);

/** Линейная прогрессия для степпера: new → … → won (без терминалов-отказа). */
export const PROGRESSION_STAGES: SalesStage[] = SALES_STAGES.filter(
  (s) => s.id !== "cond_lost" && s.id !== "lost",
);

/** id → стадия (валидация / UI-заголовок). */
export const STAGE_BY_ID: Record<string, SalesStage> = Object.fromEntries(
  SALES_STAGES.map((s) => [s.id, s]),
);

/** Индекс стадии в линейной прогрессии (−1 для терминалов-отказа / неизвестной). */
export function progressionIndex(stageId: string): number {
  return PROGRESSION_STAGES.findIndex((s) => s.id === stageId);
}

/**
 * Дефолтная вероятность закрытия (%) по стадии (SALES-44) — зеркало backend
 * PROBABILITY_BY_STAGE. Переопределяется явным `deal.probability` на сделке.
 */
export const STAGE_PROBABILITY: Record<string, number> = {
  new: 10,
  qual: 25,
  price_req: 35,
  has_price: 45,
  meeting: 55,
  invoice: 70,
  protected: 85,
  contract: 95,
  won: 100,
  cond_lost: 5,
  lost: 0,
};

/** Терминальная стадия «отказ» (SALES-40) — fallback-колонка доски без бэка. */
export const LOST_STAGE: SalesStage = STAGE_BY_ID.lost;

/**
 * Пресет «следующего шага» (слайс 4, «след. шаг в 2 клика»): деловой текст + сдвиг срока
 * в днях от `now` (см. {@link presetDateISO}). Первый пресет стадии — дефолт для авто-
 * назначения при смене стадии (drag&drop без ручного выбора менеджера).
 */
export interface NextStepPreset {
  label: string;
  offsetDays: number;
}

/**
 * Пресеты по стадиям канона (SALES_STAGES) — 3 на стадию, деловой русский, по смыслу
 * стадии. won/lost — НАМЕРЕННО без пресетов (сделка закрыта, следующий шаг не нужен).
 * cond_lost — реанимационные (сделка не терминальна, см. sales-stages.ts верх файла).
 */
export const NEXT_STEP_TEMPLATES: Record<string, NextStepPreset[]> = {
  new: [
    { label: "Позвонить, уточнить потребность", offsetDays: 0 },
    { label: "Отправить приветственное письмо", offsetDays: 0 },
    { label: "Квалифицировать заявку", offsetDays: 1 },
  ],
  qual: [
    { label: "Отправить КП", offsetDays: 1 },
    { label: "Уточнить бюджет и сроки", offsetDays: 0 },
    { label: "Согласовать спецификацию", offsetDays: 1 },
  ],
  price_req: [
    { label: "Уточнить у клиента объём и сроки", offsetDays: 0 },
    { label: "Согласовать цену с закупками", offsetDays: 1 },
    { label: "Напомнить клиенту про запрос", offsetDays: 2 },
  ],
  has_price: [
    { label: "Отправить цену клиенту", offsetDays: 0 },
    { label: "Позвонить по цене", offsetDays: 1 },
    { label: "Согласовать скидку", offsetDays: 2 },
  ],
  meeting: [
    { label: "Подтвердить встречу", offsetDays: 0 },
    { label: "Подготовить презентацию/образцы", offsetDays: 1 },
    { label: "Провести встречу", offsetDays: 1 },
  ],
  invoice: [
    { label: "Проверить оплату", offsetDays: 3 },
    { label: "Позвонить по счёту", offsetDays: 2 },
    { label: "Напомнить об оплате", offsetDays: 1 },
  ],
  protected: [
    { label: "Проверить резерв на складе", offsetDays: 1 },
    { label: "Уточнить срок оплаты", offsetDays: 2 },
    { label: "Подтвердить отгрузочные реквизиты", offsetDays: 2 },
  ],
  contract: [
    { label: "Дожать подписание", offsetDays: 2 },
    { label: "Отправить договор на подпись", offsetDays: 0 },
    { label: "Проверить предоплату", offsetDays: 3 },
  ],
  cond_lost: [
    { label: "Повторный заход: новая цена", offsetDays: 14 },
    { label: "Узнать, что решил клиент", offsetDays: 7 },
    { label: "Предложить рассрочку/бонус", offsetDays: 5 },
  ],
};

/** Дефолт для стадий вне канона (напр. коды секций «Все вместе» rp_*, tn_* без явных
 * пресетов, или будущие стадии редактора воронок) — нейтральные, работают для любой стадии. */
export const DEFAULT_NEXT_STEP_TEMPLATES: NextStepPreset[] = [
  { label: "Позвонить клиенту", offsetDays: 0 },
  { label: "Написать клиенту", offsetDays: 1 },
  { label: "Уточнить статус сделки", offsetDays: 2 },
];

/** Пресеты стадии; неизвестная/не заданная стадия — {@link DEFAULT_NEXT_STEP_TEMPLATES}. */
export function nextStepTemplatesFor(stageId: string | undefined): NextStepPreset[] {
  return (stageId && NEXT_STEP_TEMPLATES[stageId]) || DEFAULT_NEXT_STEP_TEMPLATES;
}

/** Первый (дефолтный) пресет стадии — для авто-назначения при смене стадии без пресетов UI. */
export function nextStepPreset(stageId: string | undefined): NextStepPreset {
  return nextStepTemplatesFor(stageId)[0];
}

/**
 * ISO-строка локальной даты пресета срока: `now` + `offsetDays` дней, время фиксировано
 * 09:00:00 (начало рабочего дня). БЕЗ суффикса `Z` — `Date.parse`/{@link dateBucketId}
 * (board.ts) трактуют такую строку как локальное время (симметрично остальным датам канона).
 * Детерминирована через явный параметр `now` — тестируема без реального времени.
 */
export function presetDateISO(offsetDays: number, now: number): string {
  const d = new Date(now);
  d.setDate(d.getDate() + offsetDays);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}T09:00:00`;
}

/**
 * Шаблон сообщения КЛИЕНТУ (слайс 8, «касания клиента с доски») — готовый текст для секции
 * «Написать клиенту» в drawer'е сделки (канал WhatsApp/Telegram/Email/Viber). В отличие от
 * {@link NextStepPreset} (внутренняя задача менеджера) — это то, что реально уходит клиенту;
 * менеджер может отредактировать перед отправкой. label — заголовок кнопки-шаблона.
 */
export interface MessageTemplate {
  label: string;
  text: string;
}

/**
 * Шаблоны сообщений по стадиям канона (SALES_STAGES) — 2-3 на стадию, деловой русский, по
 * смыслу стадии. won/lost — НАМЕРЕННО без шаблонов (сделка закрыта, писать клиенту нечего).
 * cond_lost — реанимационные (сделка не терминальна, см. верх файла).
 */
export const MESSAGE_TEMPLATES: Record<string, MessageTemplate[]> = {
  new: [
    {
      label: "Представиться, уточнить потребность",
      text: "Добрый день! Спасибо за обращение. Подскажите, пожалуйста, какой товар и в каком объёме вас интересует — подберём вариант и рассчитаем цену.",
    },
    {
      label: "Уточнить удобное время звонка",
      text: "Добрый день! Получили вашу заявку. Когда вам удобно созвониться, чтобы уточнить детали?",
    },
  ],
  qual: [
    {
      label: "Уточнить бюджет и сроки",
      text: "Добрый день! Чтобы подготовить точное предложение, подскажите, пожалуйста, желаемые сроки поставки и ориентировочный бюджет.",
    },
    {
      label: "Запросить спецификацию",
      text: "Добрый день! Пришлите, пожалуйста, спецификацию или перечень позиций — подготовим коммерческое предложение.",
    },
  ],
  price_req: [
    {
      label: "Сообщить, что цена уточняется",
      text: "Добрый день! Ваш запрос передан в закупки, уточняем цену — вернёмся с ответом в ближайшее время.",
    },
    {
      label: "Уточнить объём для точной цены",
      text: "Добрый день! Чтобы дать точную цену, подскажите, пожалуйста, точный объём и требуемые сроки поставки.",
    },
  ],
  has_price: [
    {
      label: "Напомнить о КП",
      text: "Добрый день! Направляли вам предложение — подскажите, успели посмотреть? Готов ответить на вопросы.",
    },
    {
      label: "Уточнить решение по КП",
      text: "Добрый день! Уточните, пожалуйста, как продвигается рассмотрение нашего предложения — есть вопросы или комментарии?",
    },
    {
      label: "Предложить созвон по КП",
      text: "Добрый день! Готов кратко созвониться и разобрать предложение — когда вам удобно?",
    },
  ],
  meeting: [
    {
      label: "Подтвердить встречу",
      text: "Добрый день! Подтверждаю нашу встречу — уточните, пожалуйста, время и место по-прежнему вам удобны?",
    },
    {
      label: "Напомнить о встрече",
      text: "Добрый день! Напоминаю о встрече — если появятся уточняющие вопросы до неё, я на связи.",
    },
  ],
  invoice: [
    {
      label: "Напоминание об оплате",
      text: "Добрый день! Напоминаю: счёт №… действителен до …. Подтвердите, пожалуйста, оплату.",
    },
    {
      label: "Уточнить статус оплаты",
      text: "Добрый день! Подскажите, пожалуйста, счёт передан в оплату? Если нужны дополнительные документы — пришлю.",
    },
  ],
  protected: [
    {
      label: "Подтвердить резерв и реквизиты",
      text: "Добрый день! Резерв по вашему счёту оформлен. Подтвердите, пожалуйста, реквизиты и удобную дату отгрузки.",
    },
    {
      label: "Уточнить срок оплаты под резерв",
      text: "Добрый день! Резерв товара действует ограниченный срок — подскажите, пожалуйста, когда ожидать оплату?",
    },
  ],
  contract: [
    {
      label: "Статус договора",
      text: "Добрый день! Подскажите, пожалуйста, на какой стадии рассмотрение договора с вашей стороны — нужны ли правки?",
    },
    {
      label: "Напомнить про подписание",
      text: "Добрый день! Напоминаю про договор — готовы выслать оригиналы или подписать по ЭДО, как вам удобнее?",
    },
  ],
  cond_lost: [
    {
      label: "Возвращаемся с улучшенным предложением",
      text: "Добрый день! Пересмотрели условия по вашему запросу — готовы предложить более выгодную цену и сроки. Обсудим?",
    },
    {
      label: "Узнать причину паузы",
      text: "Добрый день! Подскажите, пожалуйста, что стало решающим фактором паузы — возможно, подберём альтернативу.",
    },
  ],
};

/** Дефолт для стадий вне канона (напр. коды секций «Все вместе» rp_*, tn_* без явных
 * шаблонов, или будущие стадии редактора воронок) — нейтральные, работают для любой стадии. */
export const DEFAULT_MESSAGE_TEMPLATES: MessageTemplate[] = [
  {
    label: "Уточнить статус",
    text: "Добрый день! Подскажите, пожалуйста, как продвигается решение по нашему предложению?",
  },
  {
    label: "Напомнить о себе",
    text: "Добрый день! На связи по вашему запросу — если появятся вопросы, пишите.",
  },
];

/** Шаблоны сообщений стадии; неизвестная/не заданная стадия — {@link DEFAULT_MESSAGE_TEMPLATES}. */
export function messageTemplatesFor(stageId: string | undefined): MessageTemplate[] {
  return (stageId && MESSAGE_TEMPLATES[stageId]) || DEFAULT_MESSAGE_TEMPLATES;
}
