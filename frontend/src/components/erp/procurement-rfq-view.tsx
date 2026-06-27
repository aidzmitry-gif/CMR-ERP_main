"use client";

import clsx from "clsx";
import { Award, Plus, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { formatNumber } from "@/lib/format";
import {
  addBid,
  awardRfq,
  createRfq,
  fetchRfqs,
  type Rfq,
  statusLabel,
} from "@/lib/procurement-rfq";

const STATUS_TONE: Record<string, string> = {
  open: "bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  awarded: "bg-green-50 text-green-700 dark:bg-green-500/10 dark:text-green-300",
  cancelled: "bg-sunken text-muted",
};

export function ProcurementRfqView({ initial }: { initial: Rfq[] }) {
  const [rfqs, setRfqs] = useState<Rfq[]>(initial);
  const [selId, setSelId] = useState<number | null>(initial[0]?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newItem, setNewItem] = useState("");
  const [bid, setBid] = useState({ supplier_id: "", price_byn: "", lead_time_days: "", incoterms: "" });

  useEffect(() => {
    void fetchRfqs().then(setRfqs);
  }, []);

  const selected = useMemo(() => rfqs.find((r) => r.id === selId) ?? null, [rfqs, selId]);

  async function refresh(keep?: number) {
    const fresh = await fetchRfqs();
    setRfqs(fresh);
    if (keep) setSelId(keep);
  }

  async function onCreate() {
    if (!newItem.trim()) {
      setError("Укажите позицию запроса");
      return;
    }
    setBusy(true);
    setError("");
    const created = await createRfq({ item: newItem });
    setBusy(false);
    if (!created) {
      setError("Не удалось создать запрос");
      return;
    }
    setNewItem("");
    await refresh(created.id);
  }

  async function onAddBid() {
    if (!selected || !bid.price_byn.trim()) {
      setError("Укажите цену предложения");
      return;
    }
    setBusy(true);
    setError("");
    const updated = await addBid(selected.id, {
      supplier_id: bid.supplier_id ? Number(bid.supplier_id) : null,
      price_byn: Number(bid.price_byn) || 0,
      lead_time_days: bid.lead_time_days ? Number(bid.lead_time_days) : null,
      incoterms: bid.incoterms,
    });
    setBusy(false);
    if (!updated) {
      setError("Не удалось добавить предложение");
      return;
    }
    setBid({ supplier_id: "", price_byn: "", lead_time_days: "", incoterms: "" });
    await refresh(selected.id);
  }

  async function onAward(bidId: number) {
    if (!selected) return;
    setBusy(true);
    setError("");
    const updated = await awardRfq(selected.id, bidId);
    setBusy(false);
    if (!updated) {
      setError("Не удалось выбрать победителя");
      return;
    }
    await refresh(selected.id);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Тендер закупки: запрос цен → предложения поставщиков → выбор победителя по лучшей цене.
        </p>
        <button
          onClick={() => refresh(selId ?? undefined)}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
        >
          <RefreshCw size={15} className={clsx(busy && "animate-spin")} /> Обновить
        </button>
      </div>

      {error && <div className="mt-3 text-sm text-red-600">{error}</div>}

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        {/* Список RFQ */}
        <div>
          <div className="mb-2 flex gap-2">
            <input
              value={newItem}
              onChange={(e) => setNewItem(e.target.value)}
              placeholder="Новый запрос: позиция"
              className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
            <button
              onClick={onCreate}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
            >
              <Plus size={15} />
            </button>
          </div>
          <div className="overflow-hidden rounded-xl border border-line bg-surface">
            {rfqs.length === 0 && <div className="px-4 py-6 text-center text-sm text-muted">Запросов нет</div>}
            {rfqs.map((r) => (
              <button
                key={r.id}
                onClick={() => setSelId(r.id)}
                className={clsx(
                  "flex w-full items-center justify-between border-b border-line px-4 py-2.5 text-left last:border-0 hover:bg-sunken/50",
                  selId === r.id && "bg-sunken/60",
                )}
              >
                <span className="truncate text-sm text-ink">{r.item || `RFQ-${r.id}`}</span>
                <span className="ml-2 shrink-0 text-[11px] text-faint">{r.bids.length} пред.</span>
              </button>
            ))}
          </div>
        </div>

        {/* Карточка RFQ с предложениями */}
        <div>
          {!selected ? (
            <div className="rounded-xl border border-line bg-surface px-4 py-10 text-center text-muted">
              Выберите запрос слева
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-surface">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <div>
                  <div className="font-semibold text-ink">{selected.item || `RFQ-${selected.id}`}</div>
                  <div className="text-[11px] text-faint">
                    {selected.sku_code && `${selected.sku_code} · `}
                    {formatNumber(selected.qty)} шт
                  </div>
                </div>
                <span
                  className={clsx(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    STATUS_TONE[selected.status] ?? "bg-sunken text-muted",
                  )}
                >
                  {statusLabel(selected.status)}
                </span>
              </div>

              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <th className="px-4 py-2 font-medium">Поставщик</th>
                    <th className="px-4 py-2 text-right font-medium">Цена, BYN</th>
                    <th className="px-4 py-2 text-right font-medium">Срок, дн</th>
                    <th className="px-4 py-2 font-medium">Incoterms</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {selected.bids.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-5 text-center text-muted">
                        Предложений пока нет
                      </td>
                    </tr>
                  )}
                  {selected.bids.map((b) => {
                    const isBest = b.id === selected.best_bid_id;
                    return (
                      <tr
                        key={b.id}
                        className={clsx(
                          "border-b border-line last:border-0",
                          b.is_winner && "bg-green-50/50 dark:bg-green-500/5",
                        )}
                      >
                        <td className="px-4 py-2.5 text-muted">
                          {b.supplier_id ? `#${b.supplier_id}` : "—"}
                          {b.is_winner && <span className="ml-1.5 text-[11px] font-semibold text-green-600">победитель</span>}
                        </td>
                        <td
                          className={clsx(
                            "px-4 py-2.5 text-right font-semibold tabular-nums",
                            isBest ? "text-green-600" : "text-ink",
                          )}
                        >
                          {formatNumber(b.price_byn)}
                          {isBest && <span className="ml-1 text-[10px] text-green-600">лучшая</span>}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-muted">{b.lead_time_days ?? "—"}</td>
                        <td className="px-4 py-2.5 text-muted">{b.incoterms || "—"}</td>
                        <td className="px-4 py-2.5 text-right">
                          {selected.status === "open" && (
                            <button
                              onClick={() => onAward(b.id)}
                              disabled={busy}
                              className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs font-medium text-muted hover:bg-sunken disabled:opacity-50"
                            >
                              <Award size={13} /> Выбрать
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {selected.status === "open" && (
                <div className="flex flex-wrap items-end gap-2 border-t border-line p-4">
                  <input
                    value={bid.supplier_id}
                    onChange={(e) => setBid({ ...bid, supplier_id: e.target.value })}
                    placeholder="ID поставщика"
                    className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                  />
                  <input
                    value={bid.price_byn}
                    onChange={(e) => setBid({ ...bid, price_byn: e.target.value })}
                    placeholder="Цена, BYN"
                    type="number"
                    className="w-32 rounded-lg border border-line bg-surface px-3 py-2 text-right text-sm tabular-nums text-ink outline-none focus:border-accent"
                  />
                  <input
                    value={bid.lead_time_days}
                    onChange={(e) => setBid({ ...bid, lead_time_days: e.target.value })}
                    placeholder="Срок, дн"
                    type="number"
                    className="w-24 rounded-lg border border-line bg-surface px-3 py-2 text-right text-sm tabular-nums text-ink outline-none focus:border-accent"
                  />
                  <input
                    value={bid.incoterms}
                    onChange={(e) => setBid({ ...bid, incoterms: e.target.value })}
                    placeholder="Incoterms"
                    className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                  />
                  <button
                    onClick={onAddBid}
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
                  >
                    <Plus size={15} /> Предложение
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
