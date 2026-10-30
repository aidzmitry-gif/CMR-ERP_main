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

/** A completed HTTP response does not by itself confirm the import counters. */
export function parseSyncSummary(value: unknown): SyncSummary | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const counts = ["counterparties", "new_counterparties", "counterparty_aliases", "stock"] as const;
  for (const key of counts) {
    if (!Object.hasOwn(value, key)) return null;
    const count: unknown = (value as Record<string, unknown>)[key];
    if (typeof count !== "number" || !Number.isSafeInteger(count) || count < 0) return null;
  }
  const summary = value as SyncSummary;
  return {
    counterparties: summary.counterparties,
    new_counterparties: summary.new_counterparties,
    counterparty_aliases: summary.counterparty_aliases,
    stock: summary.stock,
  };
}

/** Maps raw /integrations/1c/sync response to display-ready items. */
export function formatSyncSummary(s: SyncSummary): SyncSummaryItem[] {
  return [
    { label: "Контрагентов обработано", value: s.counterparties },
    { label: "Создано новых", value: s.new_counterparties },
    { label: "Алиасов добавлено", value: s.counterparty_aliases },
    { label: "Обновлено складских позиций", value: s.stock },
  ];
}

/** Only fixed public refusal descriptions are shown; source payloads can contain private data. */
export function formatSyncRefusal(status: number, payload: unknown): string {
  const messages: Record<string, { status: number; text: string }> = {
    invalid_onec_classification: { status: 502, text: "1С вернула противоречивую классификацию контрагента. Проверьте признак подразделения и ссылку на головную организацию." },
    invalid_onec_identity: { status: 502, text: "Не подтверждена ссылка контрагента 1С. Требуется проверка источника." },
    branch_mapping_required: { status: 422, text: "Для подразделения не подтверждена связь с головной организацией." },
    legal_address_required: { status: 422, text: "Не подтверждён юридический адрес контрагента. Требуется проверка данных и маппинга 1С." },
    unp_required: { status: 422, text: "Не подтверждён УНП контрагента из 9 цифр." },
    invalid_legal_name: { status: 422, text: "Юридическое наименование не прошло проверку. Данные не обрезаются автоматически." },
    invalid_legal_address: { status: 422, text: "Юридический адрес не прошёл проверку. Данные не обрезаются автоматически." },
    ambiguous_unp: { status: 409, text: "Несколько контрагентов имеют один УНП. Требуется явное сопоставление." },
    source_identity_conflict: { status: 409, text: "Связь записи 1С с контрагентом неоднозначна. Требуется проверка сопоставления." },
    source_kind_conflict: { status: 409, text: "Запись источника уже связана с подразделением. Требуется проверка типа контрагента." },
  };
  const detail = payload && typeof payload === "object" && "detail" in payload ? payload.detail : undefined;
  const code = detail && typeof detail === "object" && "code" in detail ? detail.code : undefined;
  if (typeof code === "string" && Object.hasOwn(messages, code) && messages[code].status === status) {
    return `${messages[code].text} (HTTP ${status}; ${code})`;
  }
  return `Результат синхронизации не подтверждён (HTTP ${status}). Причина не подтверждена.`;
}
