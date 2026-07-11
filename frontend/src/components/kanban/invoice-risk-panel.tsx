"use client";

import { X } from "lucide-react";
import { useEffect } from "react";
import type { InvoiceRiskItem, InvoiceRiskResult, InvoiceRiskSeverity } from "@/lib/board";
import { plural } from "@/lib/format";
import type { Deal } from "@/lib/types";

const SEVERITY_CLASS: Record<InvoiceRiskSeverity, string> = {
  crit: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  warn: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
};

/**
 * Панель «Счета под риском» (цикл 12): счёт проведён (posted) в 1С, но НЕ оплачен, а срок
 * действия/резерв уходит — это почти закрытая выручка, которая утекает. Очередь считает
 * `invoicesAtRisk` (board.ts) поверх батча `invoiceDocs` (deals-workspace.tsx).
 *
 * Не {@link FocusPanel}: та строит очередь ПО СДЕЛКАМ (`focusQueue`, одна сделка — одна
 * причина внимания), здесь причина всегда «счёт», и карточке нужны свои поля (номер счёта,
 * статус резерва) — под `FocusQueueItem` это легло бы с искажением смысла полей. Визуальный
 * язык — тот же образец (оверлей/aside/шапка/карточка), намеренно не изобретён заново.
 */
export function InvoiceRiskPanel({
  open,
  onClose,
  result,
  fmt,
  onSelectDeal,
}: {
  open: boolean;
  onClose: () => void;
  result: InvoiceRiskResult;
  fmt: (value: number) => string;
  onSelectDeal: (deal: Deal) => void;
}) {
  // Esc-закрытие — тот же паттерн, что FocusPanel/DealDrawerPreview.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const { items, total } = result;
  const hidden = total - items.length;

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
        aria-label="Счета под риском"
        aria-hidden={!open}
        className={`fixed inset-y-0 right-0 z-50 flex w-[380px] max-w-[92vw] flex-col border-l border-line bg-surface shadow-pop transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Контент — только пока панель реально открыта (как FocusPanel): иначе закрытая
            панель держит в DOM карточки счетов — дублирует текст с доской, ломает a11y-дерево. */}
        {open && (
          <>
            <header className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-3">
              <div className="min-w-0">
                <h2 className="text-[15px] font-extrabold text-ink">🧾 Счета под риском</h2>
                <div className="mt-0.5 text-[12px] text-muted">
                  {total > 0
                    ? `${total} ${plural(total, ["счёт", "счёта", "счетов"])} требуют внимания`
                    : "Счетов под риском нет"}
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть панель"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
              >
                <X size={16} />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-[14px] py-3">
              {items.length === 0 ? (
                <div className="mt-10 text-center">
                  <div className="text-sm font-semibold text-ink">Всё под контролем ✨</div>
                  <div className="mt-1 text-xs text-faint">
                    Нет выставленных счетов, которые просрочены, скоро истекут или потеряли резерв.
                  </div>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {items.map((item) => (
                    <RiskItemRow
                      key={item.deal.id}
                      item={item}
                      fmt={fmt}
                      onSelect={() => onSelectDeal(item.deal)}
                    />
                  ))}
                  {hidden > 0 && (
                    <div className="py-2 text-center text-xs text-faint">+ ещё {hidden}</div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </aside>
    </>
  );
}

function RiskItemRow({
  item,
  fmt,
  onSelect,
}: {
  item: InvoiceRiskItem;
  fmt: (value: number) => string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="rounded-xl border border-line bg-surface p-3 text-left shadow-card transition-shadow hover:shadow-pop"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate text-[13.5px] font-semibold text-ink">
          {item.deal.company || "Контрагент не указан"}
        </span>
        <span className="shrink-0 text-[13.5px] font-bold tabular-nums text-ink">{fmt(item.amount)}</span>
      </div>
      <div className="mt-0.5 truncate text-[11.5px] text-muted">
        Счёт № {item.docNumber} · сделка № {item.deal.number}
      </div>
      <span
        className={`mt-1.5 inline-flex items-center rounded-[5px] px-1.5 py-0.5 text-[10.5px] font-bold ${SEVERITY_CLASS[item.severity]}`}
      >
        {item.reason}
      </span>
    </button>
  );
}
