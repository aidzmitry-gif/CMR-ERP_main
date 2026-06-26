"use client";

import { useEffect, useState } from "react";
import {
  type DealItemFull,
  fetchDealItems,
  fetchStock,
  type StockRow,
} from "@/lib/api";
import { formatByn } from "@/lib/format";
import { STAGE_PROBABILITY } from "@/lib/sales-stages";

/**
 * Метрики сделки: Сумма/Себестоимость/Прибыль/Маржа/Вероятность/Взвеш.прогноз/Закрытие.
 *
 * Себес/прибыль/маржа считаются на клиенте по правилу «в наличии → себес из 1С»
 * ([[pricing-calculation-todo]]): позиции сделки (fetchDealItems) джойнятся с остатками
 * 1С по коду (fetchStock.cost). Под-заказ (себес из 1С нет) в расчёт не идёт — он
 * появится с предварительным расчётом. Цена позиции — из 1С (правило «в наличии →
 * цена из 1С», как и себестоимость). Пока грузится — «…», нет себес — «—».
 *
 * Вероятность (SALES-44): явный `probability` сделки, иначе дефолт по стадии
 * (STAGE_PROBABILITY, канон sales-stages.ts). Взвеш. прогноз = Сумма × вероятность —
 * ожидаемый вклад сделки в пайплайн.
 */
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
  const [items, setItems] = useState<DealItemFull[] | null>(null);
  const [stock, setStock] = useState<Record<string, StockRow>>({});

  useEffect(() => {
    void fetchDealItems(dealId).then(setItems);
    void fetchStock().then((rows) => {
      const byCode: Record<string, StockRow> = {};
      for (const r of rows) if (!byCode[r.sku_code]) byCode[r.sku_code] = r;
      setStock(byCode);
    });
  }, [dealId]);

  let costedRevenue = 0;
  let cost = 0;
  let anyCost = false;
  let hasUnderOrder = false;
  for (const it of items ?? []) {
    const st = stock[it.code];
    if (st?.cost != null) {
      anyCost = true;
      costedRevenue += (st.price ?? 0) * it.qty; // цена из 1С (правило «в наличии → цена из 1С»)
      cost += st.cost * it.qty;
    } else {
      hasUnderOrder = true;
    }
  }
  const profit = costedRevenue - cost;
  const marginPct = costedRevenue > 0 ? Math.round((profit / costedRevenue) * 100) : null;
  const dash = items == null ? "…" : "—"; // грузим vs нет данных

  // Вероятность: явный override сделки, иначе дефолт по стадии (канон).
  const prob = probability ?? (stageId ? STAGE_PROBABILITY[stageId] : undefined);
  const cells: { label: string; value: string; tone?: "money" }[] = [
    { label: "Сумма", value: formatByn(amount) },
    { label: "Себестоимость", value: anyCost ? formatByn(cost) : dash },
    { label: "Прибыль", value: anyCost ? formatByn(profit) : dash, tone: "money" },
    { label: "Маржа", value: marginPct != null ? `${marginPct}%` : dash },
    { label: "Вероятность", value: prob != null ? `${prob}%` : "—" },
    { label: "Взвеш. прогноз", value: prob != null ? formatByn((amount * prob) / 100) : "—" },
    { label: "Закрытие", value: closeDate || "—" },
  ];

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
      {anyCost && hasUnderOrder && (
        <div className="mt-1 text-[11px] text-faint">
          Маржа — по позициям «в наличии» (себес из 1С); под-заказ ждёт предрасчёта.
        </div>
      )}
    </>
  );
}
