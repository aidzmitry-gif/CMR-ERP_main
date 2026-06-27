"use client";

import clsx from "clsx";
import { CheckCircle2, Download, Lock } from "lucide-react";
import { useState } from "react";

import { formatByn, formatNumber } from "@/lib/format";
import {
  completeInventory,
  fetchInventoryDetail,
  type InventoryDetail,
  inventoryStatusLabel,
  populateInventory,
  updateInventoryLine,
  varianceTone,
} from "@/lib/wms-inventory";

const TONE_STYLES: Record<string, string> = {
  none: "text-faint",
  ok: "text-green-600",
  short: "text-red-600 font-semibold",
  over: "text-amber-600 font-semibold",
};

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={clsx("mt-1 text-xl font-bold tabular-nums", tone ?? "text-ink")}>{value}</div>
    </div>
  );
}

export function WmsInventoryDetail({ initial }: { initial: InventoryDetail }) {
  const [doc, setDoc] = useState<InventoryDetail>(initial);
  const [busy, setBusy] = useState(false);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const locked = doc.status !== "open";

  async function refresh() {
    const fresh = await fetchInventoryDetail(doc.id);
    if (fresh) setDoc(fresh);
  }

  async function onPopulate() {
    setBusy(true);
    const fresh = await populateInventory(doc.id);
    if (fresh) setDoc(fresh);
    setBusy(false);
  }

  async function onComplete() {
    setBusy(true);
    const ok = await completeInventory(doc.id);
    setBusy(false);
    if (ok) await refresh();
  }

  async function commitCount(lineId: number) {
    const raw = drafts[lineId];
    if (raw === undefined) return;
    const value = raw.trim() === "" ? null : Number(raw.replace(",", "."));
    if (value !== null && Number.isNaN(value)) return;
    setBusy(true);
    await updateInventoryLine(lineId, { counted_qty: value });
    setDrafts((d) => {
      const next = { ...d };
      delete next[lineId];
      return next;
    });
    await refresh();
    setBusy(false);
  }

  const s = doc.summary;

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-ink">{doc.number}</h1>
            <span
              className={clsx(
                "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
                locked ? "bg-green-50 text-green-600" : "bg-amber-50 text-amber-600",
              )}
            >
              {locked && <Lock size={11} />}
              {inventoryStatusLabel(doc.status)}
            </span>
          </div>
          <p className="mt-0.5 text-sm text-muted">Склад: {doc.warehouse}</p>
        </div>
        <div className="flex items-center gap-2">
          {!locked && (
            <button
              onClick={onPopulate}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
            >
              <Download size={15} /> Подтянуть из 1С
            </button>
          )}
          {!locked && doc.lines.length > 0 && (
            <button
              onClick={onComplete}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
            >
              <CheckCircle2 size={15} /> Провести
            </button>
          )}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Строк / посчитано" value={`${s.counted} / ${s.lines}`} />
        <Kpi label="Недостач" value={formatNumber(s.shortages)} tone={s.shortages ? "text-red-600" : undefined} />
        <Kpi label="Стоимость недостач" value={formatByn(s.shortage_value)} tone={s.shortage_value ? "text-red-600" : undefined} />
        <Kpi label="Стоимость излишков" value={formatByn(s.surplus_value)} tone={s.surplus_value ? "text-amber-600" : undefined} />
      </div>

      {locked && (
        <div className="mt-4 rounded-xl border border-line bg-sunken px-4 py-3 text-sm text-muted">
          Инвентаризация проведена{doc.completed_at ? ` ${new Date(doc.completed_at).toLocaleString("ru-RU")}` : ""}.
          Расхождения зафиксированы как факт; остатки в 1С не корректируются (фаза 1).
        </div>
      )}

      <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 font-medium">Номенклатура</th>
              <th className="px-4 py-2 text-right font-medium">Ожидается (1С)</th>
              <th className="px-4 py-2 text-right font-medium">Факт</th>
              <th className="px-4 py-2 text-right font-medium">Расхождение</th>
              <th className="px-4 py-2 text-right font-medium">В деньгах</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  Строк нет — нажмите «Подтянуть из 1С», чтобы заполнить ожидаемыми остатками.
                </td>
              </tr>
            )}
            {doc.lines.map((l) => {
              const tone = varianceTone(l.variance);
              return (
                <tr key={l.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{l.sku_code}</td>
                  <td className="px-4 py-2.5 text-ink">{l.sku_title || "—"}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                    {formatNumber(l.expected_qty)} <span className="text-faint">{l.unit}</span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {locked ? (
                      <span className="tabular-nums text-ink">
                        {l.counted_qty === null ? "—" : formatNumber(l.counted_qty)}
                      </span>
                    ) : (
                      <input
                        value={drafts[l.id] ?? (l.counted_qty === null ? "" : String(l.counted_qty))}
                        onChange={(e) => setDrafts((d) => ({ ...d, [l.id]: e.target.value }))}
                        onBlur={() => commitCount(l.id)}
                        onKeyDown={(e) => e.key === "Enter" && commitCount(l.id)}
                        inputMode="decimal"
                        placeholder="—"
                        className="w-20 rounded-lg border border-line bg-surface px-2 py-1 text-right text-sm tabular-nums text-ink outline-none focus:border-accent"
                      />
                    )}
                  </td>
                  <td className={clsx("px-4 py-2.5 text-right tabular-nums", TONE_STYLES[tone])}>
                    {l.variance === null ? "—" : l.variance > 0 ? `+${formatNumber(l.variance)}` : formatNumber(l.variance)}
                  </td>
                  <td className={clsx("px-4 py-2.5 text-right tabular-nums", TONE_STYLES[tone])}>
                    {l.variance_value === null ? "—" : formatByn(l.variance_value)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
