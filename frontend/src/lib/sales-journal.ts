/**
 * Журнал продаж — чистая доменная логика (без React), см. конвенцию src/lib/CLAUDE.md.
 * Экран: `/crm/sales` — лента закрытых won-сделок как журнал документов в 1С.
 * Контракт данных — `GET /api/sales/journal` (см. sales-journal.tsx).
 */

export type PaymentStatus = "paid" | "invoiced" | "none";
export type ShipmentStatus = "delivered" | "none";

export type JournalRow = {
  deal_id: number;
  number: string;
  title: string;
  counterparty: string;
  owner: string;
  funnel: string;
  amount: number;
  closed_on: string | null; // ISO yyyy-mm-dd
  revenue: number | null;
  gross_profit: number | null; // null = маржа не рассчитана (НЕ 0)
  margin_pct: number | null;
  margin_reason: string | null; // причина «маржа не рассчитана»
  payment: PaymentStatus;
  invoice_number: string | null;
  shipment: ShipmentStatus;
};

export type JournalFilters = {
  from: string; // ISO yyyy-mm-dd, "" = без ограничения
  to: string;
  funnel: string; // код воронки, "" = все
  owner: string; // "" = все менеджеры
  q: string; // поиск: номер / название / клиент
  unpaidOnly: boolean;
};

export const EMPTY_JOURNAL_FILTERS: JournalFilters = {
  from: "",
  to: "",
  funnel: "",
  owner: "",
  q: "",
  unpaidOnly: false,
};

/** Есть ли активные фильтры (для выбора текста пустого состояния). */
export function hasActiveFilters(filters: JournalFilters): boolean {
  return (
    filters.from !== "" ||
    filters.to !== "" ||
    filters.funnel !== "" ||
    filters.owner !== "" ||
    filters.q.trim() !== "" ||
    filters.unpaidOnly
  );
}

export function filterJournal(rows: JournalRow[], filters: JournalFilters): JournalRow[] {
  const q = filters.q.trim().toLowerCase();
  return rows.filter((r) => {
    const iso = r.closed_on;
    // период задан сравнением ISO-строк по closed_on; неизвестная дата под период не попадает
    if (filters.from && (!iso || iso < filters.from)) return false;
    if (filters.to && (!iso || iso > filters.to)) return false;
    if (filters.funnel && r.funnel !== filters.funnel) return false;
    if (filters.owner && r.owner !== filters.owner) return false;
    if (filters.unpaidOnly && r.payment === "paid") return false;
    if (q && !`${r.number} ${r.title} ${r.counterparty}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

export type JournalStats = {
  count: number;
  totalAmount: number;
  totalGross: number | null; // null = ни одна сделка среза не оценена
  pricedCount: number;
  unpaidCount: number;
};

export function journalStats(rows: JournalRow[]): JournalStats {
  const totalAmount = rows.reduce((s, r) => s + r.amount, 0);
  const priced = rows.filter((r) => r.gross_profit != null);
  const totalGross = priced.length
    ? priced.reduce((s, r) => s + (r.gross_profit ?? 0), 0)
    : null;
  const unpaidCount = rows.filter((r) => r.payment !== "paid").length;
  return { count: rows.length, totalAmount, totalGross, pricedCount: priced.length, unpaidCount };
}

export type MonthGroup = {
  key: string; // "2026-07" | "none"
  title: string; // "Июль 2026" | "Без даты"
  rows: JournalRow[];
  sum: number;
};

// Русские имена месяцев в именительном падеже — локально, НЕ toLocaleString
// (иначе результат зависит от ICU-окружения, где гоняются тесты).
const MONTH_NOM = [
  "январь", "февраль", "март", "апрель", "май", "июнь",
  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
];

function monthTitle(key: string): string {
  const [y, m] = key.split("-");
  const name = MONTH_NOM[Number(m) - 1] ?? "";
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${y}`;
}

/** Группировка по месяцу закрытия: месяцы DESC, строки без даты — отдельной группой в конце. */
export function monthGroups(rows: JournalRow[]): MonthGroup[] {
  const buckets = new Map<string, JournalRow[]>();
  for (const r of rows) {
    const key = r.closed_on ? r.closed_on.slice(0, 7) : "none";
    const arr = buckets.get(key);
    if (arr) arr.push(r);
    else buckets.set(key, [r]);
  }
  const dated = [...buckets.keys()].filter((k) => k !== "none").sort().reverse();
  const keys = buckets.has("none") ? [...dated, "none"] : dated;
  return keys.map((key) => {
    const groupRows = [...(buckets.get(key) ?? [])].sort((a, b) =>
      (b.closed_on ?? "").localeCompare(a.closed_on ?? ""),
    );
    return {
      key,
      title: key === "none" ? "Без даты" : monthTitle(key),
      rows: groupRows,
      sum: groupRows.reduce((s, r) => s + r.amount, 0),
    };
  });
}

/** "2026-07-11" → "11.07.2026"; null/некорректная дата → "—". */
export function formatDayMonth(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  if (!y || !m || !d) return "—";
  return `${d}.${m}.${y}`;
}

// Метки воронок — локальная карта с фолбэком на код (бэк присылает код, не заголовок).
const FUNNEL_LABELS: Record<string, string> = {
  new_clients: "Новые клиенты",
  repeat_clients: "Постоянные",
  tenders: "Тендеры",
};

export function funnelLabel(code: string): string {
  return FUNNEL_LABELS[code] ?? code;
}
