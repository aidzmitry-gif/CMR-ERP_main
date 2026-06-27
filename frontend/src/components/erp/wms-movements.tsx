"use client";

import clsx from "clsx";
import { ArrowDownToLine, ArrowLeftRight, ArrowUpFromLine, RefreshCw, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { formatNumber } from "@/lib/format";
import {
  adjustment,
  fetchMovements,
  locationLabel,
  receipt,
  reasonLabel,
  shipment,
  type StockMovement,
  transfer,
  type WmsLocation,
} from "@/lib/wms-ops";

type OpKind = "receipt" | "shipment" | "transfer" | "adjustment";

const OPS: { id: OpKind; label: string; Icon: typeof ArrowDownToLine }[] = [
  { id: "receipt", label: "Приёмка", Icon: ArrowDownToLine },
  { id: "shipment", label: "Отгрузка", Icon: ArrowUpFromLine },
  { id: "transfer", label: "Перемещение", Icon: ArrowLeftRight },
  { id: "adjustment", label: "Коррекция", Icon: SlidersHorizontal },
];

const EMPTY = { sku: "", qty: "", warehouse: "Главный", loc: "", locTo: "", batch: "", note: "" };

export function WmsMovements({
  initial,
  locations,
}: {
  initial: StockMovement[];
  locations: WmsLocation[];
}) {
  const [rows, setRows] = useState<StockMovement[]>(initial);
  const [op, setOp] = useState<OpKind>("receipt");
  const [f, setF] = useState({ ...EMPTY });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const locsForWh = useMemo(
    () => locations.filter((l) => l.is_active && (!f.warehouse || l.warehouse === f.warehouse)),
    [locations, f.warehouse],
  );

  async function refresh() {
    setRows(await fetchMovements());
  }

  async function submit() {
    const qty = Number(f.qty.replace(",", "."));
    if (!f.sku.trim() || !qty) {
      setMsg({ ok: false, text: "Укажите SKU и количество" });
      return;
    }
    setBusy(true);
    const loc = f.loc ? Number(f.loc) : null;
    const base = { sku_code: f.sku.trim(), qty, warehouse: f.warehouse.trim() || "Главный", batch_ref: f.batch.trim(), note: f.note.trim() };
    let ok = false;
    if (op === "receipt") ok = await receipt({ ...base, location_id: loc });
    else if (op === "shipment") ok = await shipment({ ...base, location_id: loc });
    else if (op === "adjustment") ok = await adjustment({ ...base, location_id: loc });
    else ok = await transfer({ ...base, from_location_id: loc, to_location_id: f.locTo ? Number(f.locTo) : null });
    setBusy(false);
    setMsg({ ok, text: ok ? "Движение записано" : "Не удалось записать (проверьте данные/права)" });
    if (ok) {
      setF({ ...EMPTY, warehouse: f.warehouse });
      await refresh();
    }
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Складские операции пишутся движениями в <b>журнал WMS</b> (дубль факта). Остаток 1С
          не меняется — оперативный остаток смотрите в «Остатках (из движений)».
        </p>
        <div className="flex items-center gap-2">
          <Link href="/erp/wms/balances" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken">
            Остаток из движений →
          </Link>
          <button onClick={refresh} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken">
            <RefreshCw size={15} /> Обновить
          </button>
        </div>
      </div>

      {/* Панель операции */}
      <div className="mt-4 rounded-xl border border-line bg-surface p-4">
        <div className="inline-flex rounded-lg border border-line bg-sunken p-1">
          {OPS.map((o) => (
            <button
              key={o.id}
              onClick={() => { setOp(o.id); setMsg(null); }}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
                op === o.id ? "bg-surface text-accent-ink shadow-sm" : "text-muted",
              )}
            >
              <o.Icon size={15} /> {o.label}
            </button>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <input value={f.sku} onChange={(e) => setF({ ...f, sku: e.target.value })} placeholder="Код SKU*" className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
          <input value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} inputMode="decimal" placeholder={op === "adjustment" ? "Кол-во (±)" : "Кол-во*"} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
          <input value={f.warehouse} onChange={(e) => setF({ ...f, warehouse: e.target.value })} placeholder="Склад" className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
          <select value={f.loc} onChange={(e) => setF({ ...f, loc: e.target.value })} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent">
            <option value="">{op === "transfer" ? "Из ячейки" : "Ячейка"}</option>
            {locsForWh.map((l) => <option key={l.id} value={l.id}>{locationLabel(l)}</option>)}
          </select>
          {op === "transfer" ? (
            <select value={f.locTo} onChange={(e) => setF({ ...f, locTo: e.target.value })} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent">
              <option value="">В ячейку</option>
              {locsForWh.map((l) => <option key={l.id} value={l.id}>{locationLabel(l)}</option>)}
            </select>
          ) : (
            <input value={f.batch} onChange={(e) => setF({ ...f, batch: e.target.value })} placeholder="Партия" className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
          )}
          <button onClick={submit} disabled={busy} className="rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60">
            Записать
          </button>
        </div>
        {msg && (
          <p className={clsx("mt-2 text-xs", msg.ok ? "text-green-600" : "text-red-600")}>{msg.text}</p>
        )}
      </div>

      {/* Журнал движений */}
      <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 font-medium">Операция</th>
              <th className="px-4 py-2 font-medium">Склад</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
              <th className="px-4 py-2 font-medium">Документ</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted">Движений пока нет</td>
              </tr>
            )}
            {rows.map((m) => (
              <tr key={m.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{m.sku_code}</td>
                <td className="px-4 py-2.5 text-ink">{reasonLabel(m.reason)}</td>
                <td className="px-4 py-2.5 text-muted">{m.warehouse}</td>
                <td className={clsx("px-4 py-2.5 text-right font-semibold tabular-nums", m.kind === "in" ? "text-green-600" : "text-red-600")}>
                  {m.kind === "in" ? "+" : "−"}{formatNumber(m.qty)}
                </td>
                <td className="px-4 py-2.5 text-faint">{m.doc_ref || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
