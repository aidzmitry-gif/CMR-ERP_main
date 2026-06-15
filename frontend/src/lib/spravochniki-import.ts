// Pure utility for the 1С sync screen — no React/Next deps.

export interface SyncSummary {
  counterparties: number;
  new_counterparties: number;
  counterparty_aliases: number;
  stock: number;
}

export interface SyncSummaryItem {
  label: string;
  value: number;
}

/** Maps raw /integrations/1c/sync response to display-ready items. */
export function formatSyncSummary(s: SyncSummary): SyncSummaryItem[] {
  return [
    { label: "Контрагентов обработано", value: s.counterparties },
    { label: "Создано новых", value: s.new_counterparties },
    { label: "Алиасов добавлено", value: s.counterparty_aliases },
    { label: "Позиций склада", value: s.stock },
  ];
}
