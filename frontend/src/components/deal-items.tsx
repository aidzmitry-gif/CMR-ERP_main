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

export function DealItems({ dealId }: { dealId: string }) {
  const [items, setItems] = useState<DealItemFull[]>([]);
  const [skus, setSkus] = useState<SkuOption[]>([]);
  const [skuId, setSkuId] = useState<number | null>(null);
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setItems(await fetchDealItems(dealId));
  }

  useEffect(() => {
    void refresh();
    void fetchSkus().then((s) => {
      setSkus(s);
      if (s.length) setSkuId(s[0].id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    <div className="mt-4 rounded-xl border border-slate-200 p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <Package size={18} className="text-brand-600" />
        Номенклатура <span className="font-medium text-brand-600">({items.length} поз.)</span>
      </div>

      <ul className="mt-3 space-y-2">
        {items.length === 0 && <li className="text-sm text-muted">Позиций пока нет</li>}
        {items.map((item) => (
          <li key={item.id} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2">
            <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-slate-700">{item.title}</div>
              {item.last_price != null && (
                <span className="text-xs text-slate-400">
                  {item.last_price.toLocaleString("ru-RU")} ₽
                  {item.min_price != null && item.min_price < item.last_price
                    ? ` · мин ${item.min_price.toLocaleString("ru-RU")}`
                    : ""}
                </span>
              )}
            </div>
            <input
              type="number"
              min={1}
              value={item.qty}
              onChange={(e) => onQty(item.id, Number(e.target.value))}
              className="w-16 shrink-0 rounded-lg border border-slate-200 px-2 py-1 text-sm outline-none focus:border-brand"
            />
            <span className="shrink-0 text-xs text-muted">{item.unit}</span>
            <button
              onClick={() => onDelete(item.id)}
              disabled={busy}
              title="Удалить позицию"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-60"
            >
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-3 flex items-center gap-2">
        <select
          value={skuId ?? ""}
          onChange={(e) => setSkuId(Number(e.target.value))}
          className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-brand"
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
          className="w-16 shrink-0 rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-brand"
        />
        <button
          onClick={onAdd}
          disabled={busy || !skuId}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          <Plus size={16} /> Добавить
        </button>
      </div>
    </div>
  );
}
