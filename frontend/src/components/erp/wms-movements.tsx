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
  REASON_LABELS,
  reasonLabel,
  receipt,
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

// ponytail: client-side cap 50; add server-side cursor pagination when journal grows large
const PAGE_SIZE = 50;

function MovementsLog({ rows }: { rows: StockMovement[] }) {
  const [reasonFilter, setReasonFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const visible = useMemo(
    () =>
      rows
        .filter(
          (m) =>
            (!reasonFilter || m.reason === reasonFilter) &&
            (!dateFrom || (m.created_at && m.created_at >= dateFrom)) &&
            (!dateTo || (m.created_at && m.created_at <= dateTo + "T23:59:59")),
        )
        .slice(0, PAGE_SIZE),
    [rows, reasonFilter, dateFrom, dateTo],
  );

  return (
    <div className="mt-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <select
          value={reasonFilter}
          onChange={(e) => setReasonFilter(e.target.value)}
          className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
        >
          <option value="">Все типы</option>
          {Object.entries(REASON_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
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
              <th className="px-4 py-2 font-medium">Юрлицо</th>
              <th className="px-4 py-2 font-medium">Дата</th>
              <th className="px-4 py-2 font-medium">Тип</th>
              <th className="px-4 py-2 font-medium">SKU</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
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
                <td className="px-4 py-2.5 text-xs text-muted">{m.organization_id ? `Юрлицо №${m.organization_id}` : "Не определено"}</td>
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
                    {reasonLabel(m.reason)}
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
  organizations = [],
}: {
  initial: StockMovement[];
  locations: WmsLocation[];
  organizations?: { id: number; name: string }[];
}) {
  const [organizationId, setOrganizationId] = useState("");
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
    setBusy(true);
    try {
      setRows(await fetchMovements());
      setMsg(null);
    } catch {
      setMsg({ ok: false, text: "Не удалось обновить журнал. Показаны ранее загруженные движения." });
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!organizationId) {
      setMsg({ ok: false, text: "Выберите юрлицо операции" });
      return;
    }
    const quantity = f.qty.trim().replace(",", ".");
    if (!/^-?\d{1,12}(\.\d{1,2})?$/.test(quantity) || (op !== "adjustment" && quantity.startsWith("-"))) {
      setMsg({ ok: false, text: "Укажите корректное количество, не более двух знаков после запятой" });
      return;
    }
    const qty = Number(quantity);
    if (!f.sku.trim() || !qty) {
      setMsg({ ok: false, text: "Укажите SKU и количество" });
      return;
    }
    setBusy(true);
    const loc = f.loc ? Number(f.loc) : null;
    const base = { organization_id: Number(organizationId), sku_code: f.sku.trim(), qty, warehouse: f.warehouse.trim() || "Главный", batch_ref: f.batch.trim(), note: f.note.trim() };
    try {
      let ok = false;
      if (op === "receipt") ok = await receipt({ ...base, location_id: loc });
      else if (op === "shipment") ok = await shipment({ ...base, location_id: loc });
      else if (op === "adjustment") ok = await adjustment({ ...base, location_id: loc });
      else ok = await transfer({ ...base, from_location_id: loc, to_location_id: f.locTo ? Number(f.locTo) : null });
      if (!ok) {
        setMsg({ ok: false, text: "Не удалось подтвердить запись. Обновите журнал перед повторной отправкой." });
        return;
      }
      setF({ ...EMPTY, warehouse: f.warehouse });
      try {
        setRows(await fetchMovements());
        setMsg({ ok: true, text: "Движение записано" });
      } catch {
        setMsg({ ok: false, text: "Движение записано, но журнал не обновился. Нажмите «Обновить»; повторно записывать операцию не нужно." });
      }
    } catch {
      setMsg({ ok: false, text: "Не удалось подтвердить запись. Обновите журнал перед повторной отправкой." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Складские операции записываются в <b>журнал движений ERP</b> с указанием юрлица.
          Физический остаток рассчитывается по этим движениям. Первичные накладные на поступление находятся в закупках.
        </p>
        <div className="flex items-center gap-2">
          <Link href="/erp/wms/balances" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken">
            Остаток из движений →
          </Link>
          <button disabled={busy} onClick={refresh} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken">
            <RefreshCw size={15} /> Обновить
          </button>
        </div>
      </div>

      <label className="mt-4 block text-sm">Юрлицо операции
        <select aria-label="Юрлицо операции" value={organizationId} disabled={busy} onChange={(event) => setOrganizationId(event.target.value)} className="ml-2 rounded-lg border border-line bg-surface p-2">
          <option value="">Выберите юрлицо</option>
          {organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
        </select>
      </label>
      {/* Панель операции */}
      <fieldset disabled={busy} className="mt-4 rounded-xl border border-line bg-surface p-4">
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
          <input value={f.warehouse} onChange={(e) => setF({ ...f, warehouse: e.target.value, loc: "", locTo: "" })} placeholder="Склад" className="rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent" />
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
          <p role="alert" className={clsx("mt-2 text-xs", msg.ok ? "text-green-600" : "text-red-600")}>{msg.text}</p>
        )}
      </fieldset>

      {/* Журнал движений */}
      <MovementsLog rows={rows} />
    </div>
  );
}
