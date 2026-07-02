/**
 * Формат даты аудита DD.MM.YYYY из значения, которое отдаёт backend (`str(datetime)`).
 *
 * Backend сериализует через `str()`, поэтому строка — `"2026-06-15 23:30:00.123456"`
 * (разделитель пробел, не `T`) или с офсетом `…+00:00`. `new Date()` на такой форме
 * ведёт себя по-разному в разных движках (naive → как локальное время → сдвиг дня в
 * `getUTC*`; строгие движки → Invalid Date → `NaN.NaN.NaN`). Берём календарную дату
 * прямо из ведущих `YYYY-MM-DD` — они одинаковы при любом разделителе и таймзоне.
 */
export function formatAuditDate(ts: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ts);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : ts;
}

// ── M2: происхождение по полям (provenance) ──────────────────────────────────

/** Описание источника поля для бейджа: подпись, иконка, тональность (CSS-класс). */
export interface SourceMeta {
  label: string;
  icon: string;
  /** ключ темы для бейджа — пара классов в компоненте (egr/erp/manual/onec/bitrix). */
  tone: "egr" | "erp" | "manual" | "onec" | "bitrix";
}

/** Источники по убыванию доверия — порядок = приоритет survivorship (egr > erp > manual > 1c > bitrix). */
const SOURCE_META: Record<string, SourceMeta> = {
  egr: { label: "ЕГР", icon: "🏛", tone: "egr" },
  erp: { label: "ERP", icon: "✦", tone: "erp" },
  manual: { label: "Вручную", icon: "✍", tone: "manual" },
  "1c": { label: "1С", icon: "📥", tone: "onec" },
  bitrix: { label: "Битрикс", icon: "🔵", tone: "bitrix" },
};

/** Метаданные источника по его коду; неизвестный код → нейтральный (manual-тон). */
export function sourceMeta(source: string): SourceMeta {
  return SOURCE_META[source] ?? { label: source, icon: "•", tone: "manual" };
}

/** Сколько полей пришло из каждого источника (для сводки «доверие к данным»).
 * Возвращает в порядке убывания доверия, только непустые. */
export function provenanceCounts(
  provenance: Record<string, { source: string }>,
): { source: string; meta: SourceMeta; count: number }[] {
  const counts = new Map<string, number>();
  for (const { source } of Object.values(provenance)) {
    counts.set(source, (counts.get(source) ?? 0) + 1);
  }
  return Object.keys(SOURCE_META)
    .filter((s) => counts.has(s))
    .concat([...counts.keys()].filter((s) => !(s in SOURCE_META)))
    .map((source) => ({ source, meta: sourceMeta(source), count: counts.get(source) ?? 0 }));
}

// ── M5: 360°-история касаний ─────────────────────────────────────────────────

/** Подпись и иконка типа касания (звонок/сделка/сообщение). */
export function touchKindMeta(kind: string): { label: string; icon: string } {
  switch (kind) {
    case "call":
      return { label: "Звонок", icon: "📞" };
    case "deal":
      return { label: "Сделка", icon: "🤝" };
    case "message":
      return { label: "Сообщение", icon: "💬" };
    default:
      return { label: kind, icon: "•" };
  }
}

/** Дата+время касания DD.MM.YYYY HH:MM из ISO (как `formatAuditDate`, но с временем). */
export function formatTouchTs(ts: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(ts);
  if (m) return `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}`;
  return formatAuditDate(ts);
}

// ── M3: журнал исходящего синка ERP → 1С ─────────────────────────────────────

/** Подпись и тон статуса линка выгрузки (для бейджа в журнале синка). */
export function syncStateMeta(state: string): { label: string; tone: "ok" | "wait" | "err" } {
  switch (state) {
    case "synced":
      return { label: "выгружено", tone: "ok" };
    case "pending":
      return { label: "в очереди", tone: "wait" };
    case "error":
      return { label: "ошибка", tone: "err" };
    default:
      return { label: state, tone: "wait" };
  }
}

/** Человеческая подпись типа сущности в журнале синка / правилах слияния. */
export function syncEntityLabel(entityType: string): string {
  switch (entityType) {
    case "counterparty":
      return "Контрагент";
    case "sku":
      return "Номенклатура";
    default:
      return entityType;
  }
}

// ── M2: правила слияния (survivorship) ───────────────────────────────────────

/** Подпись и пояснение стратегии слияния для экрана правил. */
export function strategyMeta(strategy: string): { label: string; hint: string } {
  switch (strategy) {
    case "source_priority":
      return {
        label: "Приоритет источника",
        hint: "Берётся значение из самого доверенного доступного источника (по порядку).",
      };
    case "manual_only":
      return {
        label: "Только вручную",
        hint: "Меняет только человек в ERP; никакой синк не перезаписывает.",
      };
    case "most_recent":
      return {
        label: "Самое свежее",
        hint: "Выигрывает значение с самой поздней датой, независимо от источника.",
      };
    case "non_empty_wins":
      return {
        label: "Непустое замещает",
        hint: "Непустое заполняет пустое; при конфликте двух непустых эталон сохраняется.",
      };
    default:
      return { label: strategy, hint: "" };
  }
}

/** Защищает ли стратегия поле от затирания синком из 1С (закреплено за источником выше 1С). */
export function ruleProtectsFromSync(rule: {
  strategy: string;
  source_priority: string[];
}): boolean {
  if (rule.strategy === "manual_only") return true;
  if (rule.strategy === "source_priority") {
    // защищено, если 1С НЕ первый приоритет (выше него есть egr/erp/manual)
    return rule.source_priority.length > 0 && rule.source_priority[0] !== "1c";
  }
  // most_recent / non_empty_wins — синк может обновить (не закреплено за источником)
  return false;
}
