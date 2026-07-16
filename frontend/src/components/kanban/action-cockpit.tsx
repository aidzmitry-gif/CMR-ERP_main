"use client";

import clsx from "clsx";
import { X } from "lucide-react";
import { useEffect } from "react";
import type {
  CloseabilityItem,
  CloseabilityResult,
  FocusQueueItem,
  FocusQueueResult,
  FocusSeverity,
  InvoiceRiskItem,
  InvoiceRiskResult,
  InvoiceRiskSeverity,
} from "@/lib/board";
import { plural } from "@/lib/format";
import type { Deal } from "@/lib/types";

export type CockpitTab = "now" | "invoices" | "close";

const SEVERITY_CLASS: Record<FocusSeverity | InvoiceRiskSeverity, string> = {
  crit: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  warn: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  info: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
};

/** Честное пустое состояние очереди — общее для всех трёх вкладок кокпита. */
function QueueEmpty({ title, note }: { title: string; note: string }) {
  return (
    <div className="mt-10 text-center">
      <div className="text-sm font-semibold text-ink">{title}</div>
      <div className="mt-1 text-xs text-faint">{note}</div>
    </div>
  );
}

/** Одна строка очереди — общий каркас карточки для всех трёх вкладок (было продублировано
 *  трижды в FocusPanel/InvoiceRiskPanel/CloseabilityPanel, теперь один компонент). */
function QueueRow({
  title,
  amount,
  fmt,
  subtitle,
  tagClass,
  tagLabel,
  onSelect,
}: {
  title: string;
  amount: number;
  fmt: (value: number) => string;
  subtitle: string;
  tagClass: string;
  tagLabel: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="rounded-xl border border-line bg-surface p-3 text-left shadow-card transition-shadow hover:shadow-pop"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate text-[13.5px] font-semibold text-ink">{title}</span>
        <span className="shrink-0 text-[13.5px] font-bold tabular-nums text-ink">{fmt(amount)}</span>
      </div>
      <div className="mt-0.5 truncate text-[11.5px] text-muted">{subtitle}</div>
      <span
        className={`mt-1.5 inline-flex items-center rounded-[5px] px-1.5 py-0.5 text-[10.5px] font-bold ${tagClass}`}
      >
        {tagLabel}
      </span>
    </button>
  );
}

/** Хвост «+ ещё N» под списком (total считает ДО обрезки cap, см. board.ts). */
function HiddenTail({ total, shown }: { total: number; shown: number }) {
  const hidden = total - shown;
  if (hidden <= 0) return null;
  return <div className="py-2 text-center text-xs text-faint">+ ещё {hidden}</div>;
}

/** Вкладка «⚡ Сейчас» — упорядоченная очередь «что делать сейчас» (focusQueue, board.ts).
 *  Вынесена как отдельный презентационный компонент (без оверлея/шапки/Esc) — раньше это
 *  был весь FocusPanel, теперь только список, который использует ActionCockpit. */
export function FocusList({
  result,
  stageTitle,
  fmt,
  onSelectDeal,
}: {
  result: FocusQueueResult;
  stageTitle: (stageId: string) => string;
  fmt: (value: number) => string;
  onSelectDeal: (deal: Deal) => void;
}) {
  const { items, total } = result;
  if (items.length === 0) {
    return (
      <QueueEmpty title="Всё разобрано ✨" note="Нет сделок, которые требуют действия прямо сейчас." />
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {items.map((item: FocusQueueItem) => (
        <QueueRow
          key={item.deal.id}
          title={item.deal.company || "Контрагент не указан"}
          amount={item.deal.amount}
          fmt={fmt}
          subtitle={`№ ${item.deal.number} · ${stageTitle(item.stageId)}`}
          tagClass={SEVERITY_CLASS[item.severity]}
          tagLabel={item.reason}
          onSelect={() => onSelectDeal(item.deal)}
        />
      ))}
      <HiddenTail total={total} shown={items.length} />
    </div>
  );
}

/** Вкладка «🧾 Счета» — очередь «Счета под риском» (invoicesAtRisk, board.ts): проведён,
 *  но не оплачен, а срок/резерв уходит. Раньше — весь InvoiceRiskPanel, теперь только список. */
export function InvoiceRiskList({
  result,
  fmt,
  onSelectDeal,
}: {
  result: InvoiceRiskResult;
  fmt: (value: number) => string;
  onSelectDeal: (deal: Deal) => void;
}) {
  const { items, total } = result;
  if (items.length === 0) {
    return (
      <QueueEmpty
        title="Всё под контролем ✨"
        note="Нет выставленных счетов, которые просрочены, скоро истекут или потеряли резерв."
      />
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {items.map((item: InvoiceRiskItem) => (
        <QueueRow
          key={item.deal.id}
          title={item.deal.company || "Контрагент не указан"}
          amount={item.amount}
          fmt={fmt}
          subtitle={`Счёт № ${item.docNumber} · сделка № ${item.deal.number}`}
          tagClass={SEVERITY_CLASS[item.severity]}
          tagLabel={item.reason}
          onSelect={() => onSelectDeal(item.deal)}
        />
      ))}
      <HiddenTail total={total} shown={items.length} />
    </div>
  );
}

/** Вкладка «🏁 Дожать» — очередь «Дожать до плана» (closeabilityQueue, board.ts): открытые
 *  сделки, ранжированные по реалистичности закрыть сейчас. Раньше — весь CloseabilityPanel,
 *  теперь только список; контекст гэпа (planGap) рисует сам ActionCockpit над списком. */
export function CloseabilityList({
  result,
  stageTitle,
  fmt,
  onSelectDeal,
}: {
  result: CloseabilityResult;
  stageTitle: (stageId: string) => string;
  fmt: (value: number) => string;
  onSelectDeal: (deal: Deal) => void;
}) {
  const { items, total } = result;
  if (items.length === 0) {
    return <QueueEmpty title="Открытых сделок нет ✨" note="Дожимать пока нечего." />;
  }
  return (
    <div className="flex flex-col gap-2">
      {items.map((item: CloseabilityItem) => (
        <QueueRow
          key={item.deal.id}
          title={item.deal.company || "Контрагент не указан"}
          amount={item.deal.amount}
          fmt={fmt}
          subtitle={`№ ${item.deal.number} · ${stageTitle(item.stageId)} · взвешенно ${fmt(item.weighted)}`}
          tagClass="bg-accent-soft text-accent-ink"
          tagLabel={`${item.probability}% · ${item.dateLabel}`}
          onSelect={() => onSelectDeal(item.deal)}
        />
      ))}
      <HiddenTail total={total} shown={items.length} />
    </div>
  );
}

const TABS: { key: CockpitTab; icon: string; label: string }[] = [
  { key: "now", icon: "⚡", label: "Сейчас" },
  { key: "invoices", icon: "🧾", label: "Счета" },
  { key: "close", icon: "🏁", label: "Дожать" },
];

/**
 * Кокпит «Что делать» (цикл 13, решение оператора): раньше три отдельные кнопки-очереди
 * в тулбаре доски («Фокус дня» / «Счета под риском» / «Дожать до плана») открывали три
 * независимых оверлея (FocusPanel/InvoiceRiskPanel/CloseabilityPanel, теперь удалены) —
 * объединены в один оверлей с 3 вкладками. Визуальный каркас (backdrop+aside/шапка/Esc/
 * размер) — тот же, что был у каждой из трёх панелей, просто один на всех.
 *
 * Все 3 вкладки показываются ВСЕГДА (стабильная структура, не прыгают местами); пустая
 * вкладка — приглушённый бейдж «0» + честное пустое состояние в теле (см. *List выше).
 */
export function ActionCockpit({
  open,
  onClose,
  tab,
  onTabChange,
  focusResult,
  invoiceRiskResult,
  invoiceScanUncovered = 0,
  closeabilityResult,
  planGap,
  stageTitle,
  fmt,
  onSelectDeal,
}: {
  open: boolean;
  onClose: () => void;
  tab: CockpitTab;
  onTabChange: (tab: CockpitTab) => void;
  focusResult: FocusQueueResult;
  invoiceRiskResult: InvoiceRiskResult;
  /** Цикл 12 + находка opus: сколько счетов поздних стадий не влезло в кап батча — честный
   *  хвост «+N не проверено», чтобы очередь не выглядела полной, когда за капом есть счета. */
  invoiceScanUncovered?: number;
  closeabilityResult: CloseabilityResult;
  /** Гэп до плана периода (та же величина, что в шапке скорборда) — контекст вкладки «Дожать»;
   *  `null`, если плана/среднего чека в данных нет (honest-empty). */
  planGap: { gap: number; deals: number; avg: number } | null;
  stageTitle: (stageId: string) => string;
  fmt: (value: number) => string;
  onSelectDeal: (deal: Deal) => void;
}) {
  // Esc-закрытие — тот же паттерн, что был у каждой из трёх панелей.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const tabInfo: Record<CockpitTab, { total: number; crit: boolean }> = {
    now: {
      total: focusResult.total,
      // По ПОЛНОЙ очереди (focusQueue считает до обрезки cap) — симметрично `total` рядом.
      // Из `items` признак слеп: сделки правой стадии вытесняют просроченные из топ-N.
      crit: focusResult.crit,
    },
    invoices: {
      total: invoiceRiskResult.total,
      crit: invoiceRiskResult.items.some((i) => i.severity === "crit"),
    },
    // «Дожать» не несёт своего severity (см. CloseabilityItem) — акцент даёт planGap,
    // тот же признак, что красит бейдж кнопки-триггера в тулбаре (единая логика).
    close: { total: closeabilityResult.total, crit: Boolean(planGap) },
  };

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-ink/30 transition-opacity duration-150 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        role="dialog"
        aria-label="Что делать"
        aria-hidden={!open}
        className={`fixed inset-y-0 right-0 z-50 flex w-[380px] max-w-[92vw] flex-col border-l border-line bg-surface shadow-pop transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Контент — только пока кокпит реально открыт (паттерн трёх прежних панелей):
            иначе закрытый кокпит держал бы в DOM карточки очередей — дублирует текст с
            доской, ломает a11y-дерево. */}
        {open && (
          <>
            <header className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-3">
              <h2 className="text-[15px] font-extrabold text-ink">▶ Что делать</h2>
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть панель"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
              >
                <X size={16} />
              </button>
            </header>

            <div className="flex gap-1 border-b border-line px-[10px] py-2">
              {TABS.map((t) => {
                const info = tabInfo[t.key];
                const active = tab === t.key;
                return (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => onTabChange(t.key)}
                    className={clsx(
                      "flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[12.5px] font-semibold",
                      active ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-sunken",
                    )}
                  >
                    <span aria-hidden>{t.icon}</span>
                    {t.label}
                    <span
                      className={clsx(
                        "rounded-full px-1.5 py-0.5 text-[10.5px] font-bold",
                        info.total === 0
                          ? "bg-sunken text-faint"
                          : info.crit
                            ? "bg-red-600 text-white"
                            : "bg-accent-soft text-accent-ink",
                      )}
                    >
                      {info.total}
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="flex-1 overflow-y-auto px-[14px] py-3">
              {tab === "now" && (
                <FocusList
                  result={focusResult}
                  stageTitle={stageTitle}
                  fmt={fmt}
                  onSelectDeal={onSelectDeal}
                />
              )}
              {tab === "invoices" && (
                <>
                  <InvoiceRiskList result={invoiceRiskResult} fmt={fmt} onSelectDeal={onSelectDeal} />
                  {invoiceScanUncovered > 0 && (
                    <div className="mt-2 rounded-lg bg-sunken px-3 py-2 text-center text-[11px] text-muted">
                      ⚠ Ещё {invoiceScanUncovered} {plural(invoiceScanUncovered, ["сделка", "сделки", "сделок"])} поздних
                      стадий не просканировано на риск счёта
                    </div>
                  )}
                </>
              )}
              {tab === "close" && (
                <>
                  {/* Шапка-контекст гэпа — как раньше в заголовке CloseabilityPanel. */}
                  <div className="mb-2 text-[12px] text-muted">
                    {planGap
                      ? `До плана: ${fmt(planGap.gap)} · ≈${planGap.deals} ${plural(planGap.deals, ["сделка", "сделки", "сделок"])} со ср. чеком ${fmt(planGap.avg)}`
                      : closeabilityResult.total > 0
                        ? `${closeabilityResult.total} ${plural(closeabilityResult.total, ["открытая сделка", "открытые сделки", "открытых сделок"])} в очереди`
                        : "Очередь пуста"}
                  </div>
                  <CloseabilityList
                    result={closeabilityResult}
                    stageTitle={stageTitle}
                    fmt={fmt}
                    onSelectDeal={onSelectDeal}
                  />
                </>
              )}
            </div>
          </>
        )}
      </aside>
    </>
  );
}
