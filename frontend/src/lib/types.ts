export type Priority = "Высокий" | "Средний" | "Низкий";

/**
 * Защитный маппер для {@link Priority}: backend может прислать «high»/«medium»/«low»,
 * null или мусор — приводим к ru-ключам, дефолт «Средний» (минимально шумит в UI).
 * Живёт рядом с типом, чтобы при добавлении нового значения правка была в одном файле.
 */
export function toPriority(raw: unknown): Priority {
  if (raw === "Высокий" || raw === "Средний" || raw === "Низкий") return raw;
  if (raw === "high") return "Высокий";
  if (raw === "low") return "Низкий";
  return "Средний";
}

export type ChannelKey = "phone" | "whatsapp" | "viber" | "telegram" | "email";

export interface Deal {
  id: string;
  number: string;
  company: string;
  description: string;
  amount: number;
  priority: Priority;
  owner: string;
  date?: string;
  nextStep?: string;
  nextStepAt?: string; // ISO дата+время следующего шага (слайс 4) — для группировки «По датам действий»
  closedDate?: string;
  starred?: boolean;
  // развёрнутый блок «что нужно сделать» (как у карточки в стадии КП на макете)
  todo?: string;
  actionTime?: string;
  actionDate?: string;
  itemsLabel?: string;
  itemsCount?: number;
  // Сделки 2.0 (SALES-43/44): вероятность, прогноз, история стадий, причина отказа.
  probability?: number; // 0..100; если не задана — дефолт по стадии (SALES-44)
  expectedCloseDate?: string; // ожидаемая дата закрытия (SALES-44)
  stageChangedAt?: string; // ISO-дата входа в текущую стадию — для «дней в стадии» (SALES-43)
  lostReasonCode?: string; // код причины отказа из справочника (SALES-40)
  lostComment?: string; // комментарий менеджера при отказе (SALES-40)
  // Бейдж «🚚 под приход» (П6 UI ТЗ) — живой, из аудита sales.supply.arrived.
  supplyArrivedAt?: string;
  supplyArrivedSku?: string;
}

/** Причина отказа (SALES-40): код + человекочитаемый заголовок для выпадашки. */
export interface LossReason {
  code: string;
  title: string;
}

export interface Stage {
  id: string;
  title: string;
  color: string;
  count: number;
  sum: number;
  deals: Deal[];
}

export type KpiIcon = "phone-key" | "phone" | "ruble" | "snow" | "doc";
export type KpiTone = "blue" | "indigo" | "green" | "cyan" | "slate";

export interface Kpi {
  id: string;
  label: string;
  value: number;
  target: number;
  percent: number;
  money?: boolean;
  icon: KpiIcon;
  tone: KpiTone;
}

export type ChatKind = "person" | "logistics" | "purchasing" | "warehouse";

export interface Chat {
  id: string;
  name: string;
  time: string;
  message: string;
  unread?: number;
  kind: ChatKind;
}

export interface FunnelTotal {
  id: string;
  label: string;
  value: string;
  delta: string;
}

export interface DealMessage {
  from: string;
  channel: ChannelKey;
  time: string;
  text: string;
}

export interface DealItemView {
  title: string;
  lastPrice?: number;
  minPrice?: number;
}

export interface DealDetail {
  number: string;
  company: string;
  description: string;
  amount: number;
  priority: Priority;
  nextStep: string;
  contact: string;
  datetime: string;
  itemsTitle: string;
  items: DealItemView[];
  messages: DealMessage[];
  focus: boolean;
  starred: boolean;
  dealDate: string;

  // ── MDM / 1С расширение ────────────────────────────────────────────────────
  // Все поля опциональны: backend заполняет по мере готовности интеграций,
  // UI уже умеет различать «нет данных» vs «есть данные». Контекст —
  // memory: mdm-1c-data-provenance-ui, spravochniki-mdm-decision,
  //         invoice-1c-reserve-shipment, onec-odata-setup.

  /** Контрагент в MDM-витрине (источник истины — 1С, alias по УНП). */
  counterparty?: {
    id: number;
    unp?: string;
    sourceSystem?: "erp" | "1c" | "bitrix";
    externalRef?: string;
    isGolden?: boolean;
    mergedIntoId?: number;
  };

  /** Активная стадия + сколько в ней висим (для маркера «протух»). */
  stage?: {
    idx: number;
    id: string;
    title: string;
    daysInStage?: number;
    isStale?: boolean;
  };

  /** Вероятность закрытия 0..100 (SALES-44). Явный override; нет — UI берёт дефолт по стадии. */
  probability?: number;
  /** Ожидаемая дата закрытия (SALES-44). */
  expectedCloseDate?: string;
  /** Причина отказа (SALES-40) — код из справочника LOSS_REASONS + комментарий менеджера. */
  lostReasonCode?: string;
  lostComment?: string;

  /** Крайняя дата отгрузки клиенту — уходит сигналом в закупки (sales.deal.ship_deadline.set). */
  shipDeadline?: string;
  /** Штраф за опоздание: ставка %/день просрочки, потолок % от суммы, свободное примечание. */
  penaltyRatePct?: number;
  penaltyCapPct?: number;
  penaltyTerms?: string;

  /** Себестоимость / прибыль / маржа для metrics-полосы (считается на клиенте по позициям). */
  pricing?: {
    cost?: number;
    costSource?: "landed_zak" | "avg_1c" | "manual";
    profit?: number;
    margin?: number;
  };

  /** Оплата: invoiced — счёт ERP; paid — факт из 1С (банк/касса). */
  pay?: {
    invoiced: number;
    paid: number;
    vat?: number;
    dueDate?: string;
    lastPaymentAt?: string;
    source1cDocId?: string;
  };

  /** Отгрузка: рейс/ETA из logistics, резерв/статус склада из 1С, сквозной груз из ZAK. */
  ship?: {
    tripId?: string;
    eta?: string;
    route?: string;
    reserve1cDocId?: string;
    warehouseStatus?: "none" | "reserved" | "picked" | "shipped";
    cargoTripDealIds?: number[];
  };

  /** Доставка: метод/адрес/дата — CRM; склад — WMS-справочник 1С. */
  delivery?: {
    method?: "pickup" | "address" | "our_truck";
    address?: string;
    date?: string;
    warehouseId?: number;
    warehouse1cRef?: string;
  };

  /** Постоянный клиент: счётчики — CRM; LTV/средний чек — 1С. */
  regular?: {
    isRegular: boolean;
    orderCount?: number;
    lastOrderAt?: string;
    nextExpectedAt?: string;
    avgCheck?: number;
    ltv?: number;
    intervalDays?: number;
    trendPct?: number;
  };

  /** Другие сделки этого counterparty (по counterparty.id). */
  linkedDealIds?: number[];

  /** Документы: source отделяет ERP-сторону от 1С (накладные/реализации). */
  docs?: Array<{
    id: number;
    kind: "contract" | "invoice" | "waybill" | "act" | "other";
    source: "erp" | "1c";
    onecRef?: string;
    title: string;
    status: string;
  }>;

  /** Температура и тип воронки — для группировок. */
  temperature?: "hot" | "warm" | "cold";
  funnel?: "new" | "regular" | "tender" | "project";
}

export type LeadStatus = "new" | "qualified" | "routed" | "converted" | "rejected";

/** Фиксированный список причин отказа лида — зеркалит бэкендовый REJECT_REASONS
 *  (modules/leads/leads.py). POST /leads/{id}/reject вернёт 422 на значение вне списка. */
export const REJECT_REASONS = ["не наш профиль", "нет бюджета", "дубль", "конкурент"] as const;

export interface Manager {
  name: string;
  regions: string[];
  products: string[];
  load: number;
}

export interface Lead {
  id: number;
  source: string; // site|telegram|whatsapp|email|phone|tender
  name: string;
  company: string;
  phone?: string;
  email?: string;
  region: string;
  product: string;
  message: string;
  status: LeadStatus;
  score: number;
  qualification: string; // "" | "target" | "non-target"
  reason: string;
  assignedTo: string;
  funnel: string; // "" | new | regular | tender | project
  dealId?: number;
  aiRationale?: string; // обоснование AI-квалификатора (если AI включён)
  rejectReason: string; // "" | одна из REJECT_REASONS — причина отказа (терминальный статус)
  nextStepAt: string | null; // ISO datetime следующего шага продавцу, или null
  nextStepNote: string; // заметка к следующему шагу
  createdAt?: string; // ISO datetime приёма лида — для чипа ожидания реакции
  firstActionAt?: string | null; // ISO datetime первого действия лидоруба (qualify/route/reject), или null пока не тронут
  itemsCount?: number; // Цикл 3: число позиций подобранного КП на лиде
  itemsTotal?: number; // Цикл 3: сумма КП (qty*price), BYN
  utmSource?: string; // Цикл 4: UTM-источник рекламы, приведшей лид
  utmCampaign?: string; // Цикл 4: UTM-кампания — чип на карточке лида
}

/** Дневной план/факт лидоруба (Цикл 5) — GET/PUT /leads/plan.
 *  `*Target` — дневная норма, `*Fact` — факт за сегодня; `reactionTargetMin` — потолок
 *  скорости первой реакции (держать НЕ выше), `reactionFactMin` — факт (null если сегодня
 *  ещё не реагировали). */
export interface LeadPlan {
  leadsTarget: number;
  qualifiedTarget: number;
  convertedTarget: number;
  reactionTargetMin: number;
  leadsFact: number;
  qualifiedFact: number;
  convertedFact: number;
  reactionFactMin: number | null;
}

/** Отчёт качества источника/кампании (Цикл 4) — GET /leads/stats/sources. */
export interface LeadSourceStat {
  source: string;
  utmCampaign: string;
  total: number;
  target: number;
  converted: number;
  rejected: number;
  avgScore: number;
  targetPct: number;
  conversionPct: number;
  pipeline: number; // Цикл 7: Σ КП сконвертированных лидов источника (BYN)
}

/** Скорборд передач лидоруба продавцам (Цикл 7) — GET /leads/stats/handoffs.
 *  Вклад специалиста в план продавца: передано (routed/converted), доведено до сделки,
 *  сумма КП (pipeline, BYN), конверсия. */
export interface LeadHandoffStat {
  manager: string;
  assigned: number;
  converted: number;
  pipeline: number;
  conversionPct: number;
}

export interface LeadAttachment {
  id: number;
  leadId: number;
  filename: string;
  contentType: string;
  sizeBytes: number;
  source: string; // manual|email|tender
  createdAt: string;
}

// --- Универсальная воронка ERP-модулей (закупки, производство, склад, HR и др.) ---

export interface FunnelCard {
  id: number;
  code: string;
  title: string;
  subtitle: string;
  flag: string;
  amount: number | null;
  priority: string;
  status_tag: string;
  owner: string;
  date: string;
  progress: number | null;
  next_step: string;
  insight: string;
  score?: string;
  state?: string;
  action?: string;
  details?: { k: string; v: string }[];
  tags: string[];
}

export interface FunnelStage {
  id: string;
  title: string;
  color: string;
  count: number;
  sum: number;
  cards: FunnelCard[];
}

export type FunnelTone = "blue" | "indigo" | "green" | "cyan" | "slate" | "amber" | "violet" | "red";

/** Верхняя плитка «План/Факт» воронки (как в референсах). */
export interface FunnelKpi {
  label: string;
  value: string;
  target?: string; // «40» → отрисуется как «/ 40»
  note: string; // подпись снизу, напр. «80% от плана»
  percent: number; // заполнение прогресс-бара (0–100)
  tone: FunnelTone;
}

/** Элемент правой панели (AI-лента / чаты / дедлайны). */
export interface FunnelPanelItem {
  title: string;
  text: string;
  badge?: number;
  tone?: "ai" | "alert" | "info" | "ok";
}

export interface FunnelPanel {
  title: string;
  items: FunnelPanelItem[];
  tabs?: string[]; // под-вкладки панели (напр. «Лента · Поставщики · Задачи»)
  /** Панель — переписка (чат): сворачивается в узкую рейку-аватарки, раскрывается по hover
   * (общее правило чат-рейки). Оперативные ленты (AI-агенты, «Цех · сегодня», дедлайны) —
   * НЕ чат: остаются полностью видимыми, ничего не прячем за hover. */
  chat?: boolean;
}

/** Метрика нижних итогов с трендом-дельтой. */
export interface FunnelSummaryMetric {
  label: string;
  value: string;
  delta?: string; // «+12%» / «−0.3%»
}
