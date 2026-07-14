"use client";

import { Package, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  addDealItem,
  type DealItemFull,
  deleteDealItem,
  fetchDealItems,
  fetchSkus,
  type SkuOption,
  updateDealItem,
} from "@/lib/api";
import { useCurrency } from "@/components/kanban/currency-context";
import { COST_SRC_LABEL, fetchDealMargin, type MarginLine, marginBySku } from "@/lib/margin";

export function DealItems({ dealId }: { dealId: string }) {
  const { fmt } = useCurrency(); // цены/себес в валюте выбранного ЮЛ (CurrencyProvider в crm/layout)
  const [items, setItems] = useState<DealItemFull[]>([]);
  const [skus, setSkus] = useState<SkuOption[]>([]);
  // Себес/маржа позиций — из ТОГО ЖЕ фасада, что и карточка метрик (GET /sales/deals/{id}/margin),
  // чтобы цифры и метка источника («из 1С»/«демо»/«из закупок») на одном экране не расходились.
  const [margin, setMargin] = useState<Map<string, MarginLine>>(new Map());
  const [skuId, setSkuId] = useState<number | null>(null);
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setItems(await fetchDealItems(dealId));
    setMargin(marginBySku(await fetchDealMargin(dealId)));
  }

  useEffect(() => {
    void fetchDealItems(dealId).then(setItems);
    void fetchDealMargin(dealId).then((m) => setMargin(marginBySku(m)));
    void fetchSkus().then((s) => {
      setSkus(s);
      if (s.length) setSkuId(s[0].id);
    });
  }, [dealId]);

  async function onAdd() {
    if (!skuId) return;
    setBusy(true);
    await addDealItem(dealId, skuId, qty);
    setQty(1);
    await refresh();
    setBusy(false);
  }

  async function onQty(itemId: number, value: number) {
    if (value <= 0) return;
    // Себес/маржа — на единицу, от количества не зависят → маржу не перезапрашиваем.
    setItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, qty: value } : i)));
    await updateDealItem(itemId, value);
  }

  async function onDelete(itemId: number) {
    setBusy(true);
    await deleteDealItem(itemId);
    await refresh();
    setBusy(false);
  }

  return (
    <div className="mt-4 rounded-xl border border-line p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <Package size={18} className="text-accent-ink" />
        Номенклатура <span className="font-medium text-accent-ink">({items.length} поз.)</span>
      </div>

      <ul className="mt-3 space-y-2">
        {items.length === 0 && <li className="text-sm text-muted">Позиций пока нет</li>}
        {items.map((item) => {
          const ml = margin.get(item.code);
          const hasCost = ml != null && ml.unit_landed_cost != null;
          return (
          <li key={item.id} className="flex items-center gap-2 rounded-lg bg-sunken px-3 py-2">
            <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-line-strong" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-muted">{item.title}</div>
              {item.last_price != null && (
                <span className="text-xs text-faint">
                  {fmt(item.last_price)}
                  {item.min_price != null && item.min_price < item.last_price
                    ? ` · мин ${fmt(item.min_price)}`
                    : ""}
                </span>
              )}
              {hasCost ? (
                <div className="flex flex-wrap items-baseline gap-x-1.5 text-[11px] font-semibold text-money">
                  <span>
                    себес {fmt(ml!.unit_landed_cost!)}
                    {ml!.margin_pct != null ? ` · маржа ${Math.round(ml!.margin_pct)}%` : ""}
                  </span>
                  {ml!.cost_source != null && (
                    <span className="font-normal text-faint">· {COST_SRC_LABEL[ml!.cost_source]}</span>
                  )}
                </div>
              ) : ml != null && ml.status === "no_cost" ? (
                <div className="text-[11px] text-faint">себестоимость не рассчитана</div>
              ) : null}
            </div>
            <input
              type="number"
              min={1}
              value={item.qty}
              onChange={(e) => onQty(item.id, Number(e.target.value))}
              className="w-16 shrink-0 rounded-lg border border-line bg-surface px-2 py-1 text-sm text-ink outline-none focus:border-accent"
            />
            <span className="shrink-0 text-xs text-muted">{item.unit}</span>
            <button
              onClick={() => onDelete(item.id)}
              disabled={busy}
              title="Удалить позицию"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-red-50 hover:text-red-600 disabled:opacity-60"
            >
              <Trash2 size={15} />
            </button>
          </li>
          );
        })}
      </ul>

      <div className="mt-3 flex items-center gap-2">
        <select
          value={skuId ?? ""}
          onChange={(e) => setSkuId(Number(e.target.value))}
          aria-label="Номенклатура (справочник из 1С через MDM)"
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
        >
          {skus.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} · {s.title}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={1}
          value={qty}
          onChange={(e) => setQty(Number(e.target.value))}
          className="w-16 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <button
          onClick={onAdd}
          disabled={busy || !skuId}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
        >
          <Plus size={16} /> Добавить
        </button>
      </div>
      {/* Провенанс: SKU = MDM-витрина из 1С; себес/маржа — из фасада цены/себеса (та же цифра,
          что в метриках сделки), не из отдельного расчёта по остаткам. */}
      <div className="mt-1.5 text-[10px] text-faint">
        номенклатура · справочник из 1С (через MDM); себес/маржа — из фасада цены/себеса (как в
        метриках сделки); цены last/мин — из истории сделок CRM / Price Engine
      </div>
    </div>
  );
}
