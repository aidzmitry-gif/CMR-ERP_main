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

const KIND_BADGE: Record<string, string> = {
  receipt: "bg-green-100 text-green-700",
  shipment: "bg-red-100 text-red-700",
  transfer: "bg-blue-100 text-blue-700",
  adjustment: "bg-amber-100 text-amber-700",
  reserve: "bg-purple-100 text-purple-700",
  release: "bg-slate-100 text-slate-600",
  pick: "bg-orange-100 text-orange-700",
  pack: "bg-cyan-100 text-cyan-700",
};

function reasonBadge(reason: string) {
  return KIND_BADGE[reason] ?? "bg-sunken text-muted";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

const REASONS = ["", "receipt", "shipment", "transfer", "adjustment", "reserve", "release", "pick", "pack"];
const REASON_LABELS_LOCAL: Record<string, string> = {
  "": "Все типы",
  receipt: "Приёмка",
  shipment: "Отгрузка",
  transfer: "Перемещение",
  adjustment: "Коррекция",
  reserve: "Резерв",
  release: "Снятие резерва",
  pick: "Подбор",
  pack: "Упаковка",
};

const PAGE_SIZE = 50;

function MovementsLog({ rows }: { rows: StockMovement[] }) {
  const [reasonFilter, setReasonFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const visible = useMemo(() => {
    let out = rows;
    if (reasonFilter) out = out.filter((m) => m.reason === reasonFilter);
    if (dateFrom) out = out.filter((m) => m.created_at && m.created_at >= dateFrom);
    if (dateTo) out = out.filter((m) => m.created_at && m.created_at <= dateTo + "T23:59:59");
    return out.slice(0, PAGE_SIZE);
  }, [rows, reasonFilter, dateFrom, dateTo]);

  return (
    <div className="mt-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select
          value={reasonFilter}
          onChange={(e) => setReasonFilter(e.target.value)}
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          {REASONS.map((r) => (
            <option key={r} value={r}>{REASON_LABELS_LOCAL[r]}</option>
          ))}
        </select>
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
        />
        <span className="text-xs text-faint">—</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
        />
        {visible.length === PAGE_SIZE && (
          <span className="ml-auto text-xs text-faint">Показаны последние {PAGE_SIZE}</span>
        )}
      </div>
      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Дата</th>
              <th className="px-4 py-2 font-medium">Тип</th>
              <th className="px-4 py-2 font-medium">SKU</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
              <th className="px-4 py-2 font-medium">Причина</th>
              <th className="px-4 py-2 font-medium">Документ</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  Движений по фильтру нет
                </td>
              </tr>
            )}
            {visible.map((m) => (
              <tr key={m.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-xs tabular-nums text-muted">
                  {formatDate(m.created_at)}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                      reasonBadge(m.reason),
                    )}
                  >
                    {REASON_LABELS_LOCAL[m.reason] ?? m.reason}
                  </span>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{m.sku_code}</td>
                <td
                  className={clsx(
                    "px-4 py-2.5 text-right font-semibold tabular-nums",
                    m.kind === "in" ? "text-green-600" : "text-red-600",
                  )}
                >
                  {m.kind === "in" ? "+" : "−"}{formatNumber(m.qty)}
                </td>
                <td className="px-4 py-2.5 text-muted">{reasonLabel(m.reason)}</td>
                <td className="px-4 py-2.5 text-faint">{m.doc_ref || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

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
      <MovementsLog rows={rows} />
    </div>
  );
}
