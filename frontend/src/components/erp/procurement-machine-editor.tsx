"use client";

import clsx from "clsx";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { formatByn, formatNumber } from "@/lib/format";
import {
  addLine,
  deleteLine,
  emptyLine,
  fetchLandedPreview,
  type LandedPreview,
  type MachineOrder,
  type NewLine,
  updateFreight,
} from "@/lib/procurement-machine";

const STATUS_LABEL: Record<string, string> = {
  draft: "Черновик",
  ordered: "Заказан",
  shipped: "Отгружен",
  customs: "Таможня",
  received: "Принят",
  cancelled: "Отменён",
};

/** Заглушка для блоков прототипа без бэкенда (зал ожидания / версии / back-signal). */
function HonestEmpty({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface px-4 py-3">
      <div className="text-sm font-medium text-muted">{title}</div>
      <div className="mt-0.5 text-[11px] text-faint">{reason}</div>
    </div>
  );
}

export function ProcurementMachineEditor({ initial }: { initial: MachineOrder }) {
  const [order, setOrder] = useState<MachineOrder>(initial);
  const [preview, setPreview] = useState<LandedPreview | null>(null);
  const [freight, setFreight] = useState(String(initial.freight_byn));
  const [draft, setDraft] = useState<NewLine>(emptyLine());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const readonly = order.status === "received" || order.status === "cancelled";

  async function reloadPreview(id: number) {
    setPreview(await fetchLandedPreview(id));
  }

  useEffect(() => {
    void reloadPreview(initial.id);
  }, [initial.id]);

  async function apply(updated: MachineOrder | null, errMsg: string) {
    if (!updated) {
      setError(errMsg);
      return;
    }
    setError("");
    setOrder(updated);
    setFreight(String(updated.freight_byn));
    await reloadPreview(updated.id);
  }

  async function onAddLine() {
    if (!draft.sku_code.trim()) {
      setError("Укажите код номенклатуры позиции");
      return;
    }
    setBusy(true);
    await apply(await addLine(order.id, draft), "Не удалось добавить позицию");
    setBusy(false);
    setDraft(emptyLine());
  }

  async function onDeleteLine(lineId: number) {
    setBusy(true);
    await apply(await deleteLine(order.id, lineId), "Не удалось удалить позицию");
    setBusy(false);
  }

  async function onSaveFreight() {
    const value = Number(freight) || 0;
    if (value === order.freight_byn) return;
    setBusy(true);
    await apply(await updateFreight(order.id, value), "Не удалось сохранить фрахт");
    setBusy(false);
  }

  const unitBySku = new Map(preview?.lines.map((l) => [l.sku_code, l.unit_landed_cost_byn]));

  return (
    <div className="flex-1 overflow-auto p-6">
      {/* Шапка машины */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">Состав заказа {order.number}</h1>
          <div className="mt-0.5 text-sm text-muted">
            {order.supplier || "Поставщик не указан"} ·{" "}
            <span className="rounded-full bg-sunken px-2 py-0.5 text-xs font-medium text-muted">
              {STATUS_LABEL[order.status] ?? order.status}
            </span>
            {order.eta_date && <span className="ml-2 text-faint">ETA {order.eta_date}</span>}
          </div>
        </div>
        <div className="flex items-end gap-2">
          <label className="block">
            <span className="text-[11px] text-muted">Фрахт партии, BYN</span>
            <input
              value={freight}
              onChange={(e) => setFreight(e.target.value)}
              onBlur={onSaveFreight}
              disabled={readonly}
              type="number"
              className="mt-1 w-40 rounded-lg border border-line bg-surface px-3 py-2 text-right text-sm tabular-nums text-ink outline-none focus:border-accent disabled:opacity-60"
            />
          </label>
        </div>
      </div>

      {error && <div className="mt-3 text-sm text-red-600">{error}</div>}
      {readonly && (
        <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
          Заказ {STATUS_LABEL[order.status]?.toLowerCase()} — состав не редактируется.
        </div>
      )}

      {/* Позиции + landed cost */}
      <div className="mt-5 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Номенклатура</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
              <th className="px-4 py-2 text-right font-medium">Товар, BYN</th>
              <th className="px-4 py-2 text-right font-medium">Вес, кг</th>
              <th className="px-4 py-2 text-right font-medium">Объём, м³</th>
              <th className="px-4 py-2 text-right font-medium">Себест/шт, BYN</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {order.lines.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  Позиций нет — добавьте первую ниже.
                </td>
              </tr>
            )}
            {order.lines.map((ln) => (
              <tr key={ln.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{ln.sku_code}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(ln.qty)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(ln.goods_value_byn)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatNumber(ln.weight)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatNumber(ln.volume)}</td>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-accent-ink">
                  {unitBySku.has(ln.sku_code) ? formatNumber(unitBySku.get(ln.sku_code)!) : "—"}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {!readonly && (
                    <button
                      onClick={() => onDeleteLine(ln.id)}
                      disabled={busy}
                      className="text-faint hover:text-red-600 disabled:opacity-50"
                      aria-label="Удалить позицию"
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          {preview && (
            <tfoot>
              <tr className="border-t border-line bg-sunken/40 font-semibold">
                <td className="px-4 py-2.5 text-muted">Итого landed</td>
                <td></td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                  {formatNumber(preview.total_goods_byn)}
                </td>
                <td colSpan={2}></td>
                <td className="px-4 py-2.5 text-right tabular-nums text-ink" colSpan={2}>
                  {formatByn(preview.total_landed_byn)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* Добавление позиции */}
      {!readonly && (
        <div className="mt-4 flex flex-wrap items-end gap-2 rounded-xl border border-line bg-surface p-4">
          <label className="block">
            <span className="text-[11px] text-muted">Код номенклатуры</span>
            <input
              value={draft.sku_code}
              onChange={(e) => setDraft({ ...draft, sku_code: e.target.value })}
              className="mt-1 w-44 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>
          {(["qty", "goods_value_byn", "weight", "volume"] as const).map((f) => (
            <label key={f} className="block">
              <span className="text-[11px] text-muted">
                {{ qty: "Кол-во", goods_value_byn: "Товар, BYN", weight: "Вес, кг", volume: "Объём, м³" }[f]}
              </span>
              <input
                type="number"
                value={String(draft[f])}
                onChange={(e) => setDraft({ ...draft, [f]: Number(e.target.value) || 0 })}
                className="mt-1 w-28 rounded-lg border border-line bg-surface px-3 py-2 text-right text-sm tabular-nums text-ink outline-none focus:border-accent"
              />
            </label>
          ))}
          <button
            onClick={onAddLine}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          >
            <Plus size={15} /> Добавить
          </button>
        </div>
      )}

      <p className="mt-3 text-[11px] text-faint">
        Себестоимость/шт считает бэкенд (тот же движок, что на приёмке): фрахт партии разносится
        на позиции по весу (иначе по стоимости). Фиксация — на приёмке заказа.
      </p>

      {/* Блоки прототипа без бэкенда — honest-empty */}
      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <HonestEmpty title="Зал ожидания позиций" reason="Нет бэкенда: пул не-выкупленных позиций — Горизонт 2." />
        <HonestEmpty title="Версии документов" reason="Нет бэкенда: история инвойсов/ГТД по машине — Горизонт 2." />
        <HonestEmpty title="Сигнал продавцу (back-signal)" reason="Нет бэкенда: уведомление по сделке об изменении состава — Горизонт 2." />
      </div>
    </div>
  );
}
