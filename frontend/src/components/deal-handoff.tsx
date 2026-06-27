"use client";

import { useEffect, useState } from "react";
import { type DealHandoff, fetchDealHandoff } from "@/lib/api";
import { useCurrency } from "@/components/kanban/currency-context";

/**
 * Блок «Передано в исполнение» (П10 ТЗ) на карточке won-сделки. Источник — последний
 * `sales.deal.handoff` в outbox (`GET /deals/{id}/handoff`). honest-empty: handoff ещё
 * не эмитнут (сделка не won, либо relay не доставил) — блок не показываем.
 */
export function DealHandoffBlock({ dealId }: { dealId: string }) {
  const { fmt } = useCurrency();
  const [data, setData] = useState<DealHandoff | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    void fetchDealHandoff(dealId).then((d) => {
      if (!alive) return;
      setData(d);
      setLoaded(true);
    });
    return () => {
      alive = false;
    };
  }, [dealId]);

  if (!loaded || !data) return null;

  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 px-[18px] py-[14px]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-[13.5px] font-bold text-emerald-700">Передано в исполнение</div>
        {data.handed_off_at && (
          <div className="text-[11px] text-emerald-700/80">
            {new Date(data.handed_off_at).toLocaleString("ru-RU")}
          </div>
        )}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-[12.5px] sm:grid-cols-4">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-emerald-700/80">Сумма</div>
          <div className="font-semibold text-ink">{fmt(data.amount)}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-emerald-700/80">Валовая прибыль</div>
          <div className="font-semibold text-money">
            {data.gross_profit != null ? fmt(data.gross_profit) : "—"}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-emerald-700/80">Ответственный</div>
          <div className="font-semibold text-ink">{data.owner || "—"}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-emerald-700/80">Позиций</div>
          <div className="font-semibold text-ink">{data.items.length}</div>
        </div>
      </div>
      {data.items.length > 0 ? (
        <ul className="mt-3 space-y-1 text-[12.5px]">
          {data.items.map((it) => (
            <li key={it.sku_code} className="flex items-center justify-between gap-2 border-t border-emerald-200/60 pt-1">
              <span className="text-ink">
                <span className="font-mono text-[11px] text-faint">{it.sku_code}</span>{" "}
                {it.title}
              </span>
              <span className="tabular-nums text-muted">× {it.qty}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-[11px] text-emerald-700/80">
          Позиций нет — handoff передаёт только сводку сделки.
        </div>
      )}
      <p className="mt-2 text-[11px] text-emerald-700/70">
        Событие `sales.deal.handoff` ушло в шину для downstream-модулей (логистика/финансы/офис).
      </p>
    </div>
  );
}
