"use client";

import { useEffect, useState } from "react";
import { useCurrency } from "@/components/kanban/currency-context";
import { STAGE_PROBABILITY } from "@/lib/sales-stages";

/**
 * Метрики сделки: Сумма / Себестоимость (landed) / Прибыль / Маржа / Вероятность /
 * Взвеш.прогноз / Закрытие. Источник себеса — серверный GET /sales/deals/{id}/margin
 * (landed cost через фасад ядра, [[landed_cost]]). Маржа клиентом БОЛЬШЕ НЕ считается
 * (раньше — джойн позиций сделки с остатками 1С на клиенте, [[pricing-calculation-todo]];
 * расчёт переехал на сервер за landed-фасад):
 *
 * - Все priced → revenue/cogs_landed/gross/margin_pct из ответа (BYN, через useCurrency).
 * - Частично priced (priced_count < total_count) → бейдж «оценка по N из M позиций».
 * - landed-фасад None или ничего не оценено → honest «себестоимость закупок не рассчитана»
 *   с подсказкой про procurement (методику установки цены НЕ изобретаем).
 *
 * Деньги — в валюте выбранного ЮЛ (CurrencyProvider в crm/layout) через useCurrency.fmt.
 * Вероятность (SALES-44)/прогноз — явный override сделки → дефолт по стадии
 * (STAGE_PROBABILITY, канон sales-stages.ts). Взвеш. прогноз = Сумма × вероятность.
 */
type MarginLineStatus = "priced" | "no_price" | "no_cost";

type MarginLine = {
  sku_code: string;
  title: string;
  qty: number;
  unit_price: number | null;
  revenue: number | null;
  unit_landed_cost: number | null;
  cogs: number | null;
  margin_pct: number | null;
  status: MarginLineStatus;
  cost_shipment_id: number | null;
  cost_fixed_at: string | null;
  cost_fx_rate: number | null;
};

type DealMargin = {
  deal_id: number;
  revenue: number;
  cogs_landed: number | null;
  gross_profit: number | null;
  margin_pct: number | null;
  priced_count: number;
  total_count: number;
  reason: string | null;
  lines: MarginLine[];
};

type Status = "loading" | "error" | "ready";

export function DealMetrics({
  dealId,
  amount,
  closeDate,
  stageId,
  probability,
}: {
  dealId: string;
  amount: number;
  closeDate: string;
  stageId?: string;
  probability?: number;
}) {
  const { fmt } = useCurrency(); // деньги в валюте выбранного ЮЛ (CurrencyProvider в crm/layout)
  const [status, setStatus] = useState<Status>("loading");
  const [margin, setMargin] = useState<DealMargin | null>(null);

  useEffect(() => {
    let alive = true;
    setStatus("loading");
    void (async () => {
      try {
        const res = await fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/margin`, {
          cache: "no-store",
        });
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as DealMargin;
        if (!alive) return;
        setMargin(data);
        setStatus("ready");
      } catch {
        if (alive) setStatus("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, [dealId]);

  // Вероятность: явный override сделки, иначе дефолт по стадии (канон sales-stages.ts).
  const prob = probability ?? (stageId ? STAGE_PROBABILITY[stageId] : undefined);

  const dash = status === "loading" ? "…" : "—";
  const hasCogs = status === "ready" && margin?.cogs_landed != null;
  const hasGross = status === "ready" && margin?.gross_profit != null;
  const cells: { label: string; value: string; tone?: "money" }[] = [
    { label: "Сумма", value: fmt(amount) },
    { label: "Себестоимость", value: hasCogs ? fmt(margin!.cogs_landed!) : dash },
    { label: "Прибыль", value: hasGross ? fmt(margin!.gross_profit!) : dash, tone: "money" },
    { label: "Маржа", value: margin?.margin_pct != null ? `${margin.margin_pct}%` : dash },
    { label: "Вероятность", value: prob != null ? `${prob}%` : "—" },
    { label: "Взвеш. прогноз", value: prob != null ? fmt((amount * prob) / 100) : "—" },
    { label: "Закрытие", value: closeDate || "—" },
  ];

  // Бейдж «оценка по N из M позиций» при частичной оценке.
  const partial =
    status === "ready" &&
    margin != null &&
    margin.total_count > 0 &&
    margin.priced_count > 0 &&
    margin.priced_count < margin.total_count;

  // Провенанс себеса (партия/курс) — из любой priced-позиции (берём первую).
  const provenance =
    status === "ready" && margin != null
      ? margin.lines.find((l) => l.status === "priced" && l.cost_shipment_id != null) ?? null
      : null;

  return (
    <>
      <div className="mt-2.5 flex flex-wrap divide-x divide-line overflow-hidden rounded-[10px] border border-line">
        {cells.map((c) => (
          <div
            key={c.label}
            className="flex min-w-[150px] flex-1 flex-wrap items-baseline gap-1.5 px-3.5 py-[7px]"
          >
            <div className="text-[11px] uppercase tracking-wide text-muted">{c.label}</div>
            <div
              className={`text-[15px] font-extrabold tabular-nums ${
                c.tone === "money" ? "text-money" : "text-ink"
              }`}
            >
              {c.value}
            </div>
          </div>
        ))}
      </div>

      {/* Бейджи состояний маржи (под таблицей, как было) */}
      {status === "error" && (
        <div className="mt-1 text-[11px] text-red-600">
          Не удалось рассчитать маржу — повторите позже.
        </div>
      )}

      {partial && (
        <div className="mt-1 inline-flex items-center gap-1.5 text-[11px] text-faint">
          <span className="rounded-md bg-sunken px-1.5 py-0.5 font-semibold text-muted">
            оценка по {margin!.priced_count} из {margin!.total_count} позиций
          </span>
          <span>остальные — без landed cost или без цены клиенту.</span>
        </div>
      )}

      {provenance && (
        <div className="mt-1 inline-flex items-center gap-1.5 text-[11px] text-faint">
          <span className="rounded-md bg-sunken px-1.5 py-0.5 font-semibold text-muted">
            себес · из procurement
          </span>
          <span>
            партия #{provenance.cost_shipment_id}
            {provenance.cost_fx_rate != null && ` · курс ${provenance.cost_fx_rate}`}
          </span>
        </div>
      )}

      {status === "ready" && margin?.reason && (
        <div className="mt-1 text-[11px] text-faint">
          {margin.reason}. Расчёт себестоимости — модуль «Закупки» (landed cost: фрахт/пошлина/брокер).
        </div>
      )}
    </>
  );
}
