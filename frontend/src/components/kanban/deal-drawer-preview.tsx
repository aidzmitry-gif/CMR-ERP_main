"use client";

import { ArrowRight, Calendar, Flag, User, X } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { ChannelRow } from "@/components/channels";
import { PriorityBadge } from "@/components/priority-badge";
import { Button } from "@/components/ui/button";
import { formatByn } from "@/lib/format";
import type { Deal } from "@/lib/types";

/**
 * Drawer-preview сделки на доске (sales-card-expanded.html прототип).
 * Выезжает справа по single-click на карточку. Double-click открывает полную
 * страницу /crm/deals/[id]. Backdrop кликабельный для закрытия, Esc — тоже.
 */
export function DealDrawerPreview({ deal, onClose }: { deal: Deal | null; onClose: () => void }) {
  // Esc-закрытие
  useEffect(() => {
    if (!deal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [deal, onClose]);

  // Backdrop виден всегда, чтобы анимация выезда работала; pointer-events выкл, когда закрыто.
  const open = deal != null;

  return (
    <>
      {/* Backdrop — приглушает доску, закрывает по клику. z-40 ниже модалок (z-50). */}
      <div
        aria-hidden
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-ink/30 transition-opacity duration-150 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      {/* Drawer — фиксирован справа, 460px (max-w-[94vw] для узких экранов). */}
      <aside
        role="dialog"
        aria-label={deal ? `Превью сделки ${deal.number}` : "Превью сделки"}
        aria-hidden={!open}
        className={`fixed inset-y-0 right-0 z-50 flex w-[460px] max-w-[94vw] flex-col border-l border-line bg-surface shadow-pop transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {deal && (
          <>
            <header className="flex items-start gap-3 border-b border-line px-[18px] py-3">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] text-muted">№ {deal.number}</div>
                <h2 className="mt-px truncate text-[17px] font-extrabold text-ink">
                  {deal.company || "Контрагент не указан"}
                </h2>
                <div className="mt-0.5 truncate text-[12.5px] text-muted">
                  {deal.description || "—"}
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Закрыть превью"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken hover:text-ink"
              >
                <X size={16} />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-[18px] py-[14px]">
              <div className="flex flex-wrap items-center gap-2">
                <PriorityBadge priority={deal.priority} withIcon />
                <span className="rounded-md bg-sunken px-2 py-0.5 text-[11px] font-semibold text-muted">
                  контрагент · из MDM / 1С
                </span>
              </div>

              {/* Сумма крупно */}
              <div className="mt-3 text-[22px] font-extrabold tabular-nums text-ink">
                {formatByn(deal.amount)}
              </div>
              {deal.probability != null && deal.probability > 0 && (
                <div className="mt-1 text-[12px] text-muted">
                  <span className="font-semibold text-accent-ink">{deal.probability}%</span>{" "}
                  · взвешенно ≈ {formatByn(Math.round(deal.amount * (deal.probability / 100)))}
                </div>
              )}

              {/* KV-список с быстрой инфой (как в прототипе) */}
              <dl className="mt-4 divide-y divide-line border-y border-line">
                <Row label="Ответственный" icon={<User size={13} className="text-muted" />}>
                  {deal.owner || "—"}
                </Row>
                <Row label="Следующий шаг" icon={<Flag size={13} className="text-accent-ink" />}>
                  {deal.nextStep || "—"}
                </Row>
                {(deal.date || deal.closedDate || deal.expectedCloseDate) && (
                  <Row
                    label={deal.closedDate ? "Закрыта" : "Ожид. закрытие"}
                    icon={<Calendar size={13} className="text-muted" />}
                  >
                    {deal.closedDate ?? deal.expectedCloseDate ?? deal.date ?? "—"}
                  </Row>
                )}
              </dl>

              {/* Каналы связи */}
              <div className="mt-4 rounded-xl border border-line p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Связь с клиентом
                </div>
                <ChannelRow />
              </div>

              {/* Подсказка про UX взаимодействия */}
              <div className="mt-4 rounded-lg bg-sunken px-3 py-2 text-[11px] text-faint">
                💡 <b className="text-muted">Двойной клик</b> по карточке на доске — открывает
                полную страницу сделки.
              </div>
            </div>

            <footer className="border-t border-line px-[18px] py-3">
              <Link href={`/crm/deals/${deal.id}`} className="block">
                <Button variant="primary" block icon={<ArrowRight size={15} />}>
                  Открыть полную карточку
                </Button>
              </Link>
            </footer>
          </>
        )}
      </aside>
    </>
  );
}

function Row({
  label,
  icon,
  children,
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-2 text-[13px]">
      <span className="inline-flex shrink-0 items-center gap-1.5 text-muted">
        {icon}
        {label}
      </span>
      <span className="min-w-0 text-right font-medium text-ink">{children}</span>
    </div>
  );
}
