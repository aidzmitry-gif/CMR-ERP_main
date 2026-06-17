"use client";

import clsx from "clsx";
import { Check, Send, Wrench, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  createDecision,
  decisionLabel,
  fetchDecisions,
  fetchStats,
  formatPassRate,
  type QcDecision,
  type QcRecord,
  type QcStats,
  REWORK_REASONS,
} from "@/lib/production-otk";

const DECISION_STYLES: Record<QcDecision, string> = {
  accept: "bg-green-50 text-green-600",
  rework: "bg-amber-50 text-amber-600",
  scrap: "bg-red-50 text-red-600",
};

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={clsx("mt-1 text-2xl font-bold", tone ?? "text-ink")}>{value}</div>
    </div>
  );
}

export function OtkPanel({
  initialStats,
  initialJournal,
}: {
  initialStats: QcStats;
  initialJournal: QcRecord[];
}) {
  const [stats, setStats] = useState<QcStats>(initialStats);
  const [journal, setJournal] = useState<QcRecord[]>(initialJournal);
  const [product, setProduct] = useState("");
  const [order, setOrder] = useState("");
  const [inspector, setInspector] = useState("Никита");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    const [s, j] = await Promise.all([fetchStats(), fetchDecisions()]);
    setStats(s);
    setJournal(j);
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function decide(decision: QcDecision) {
    setBusy(true);
    await createDecision({
      decision,
      product: product.trim(),
      order_code: order.trim(),
      inspector: inspector.trim(),
      reason: decision === "accept" ? "" : reason.trim(),
    });
    setReason("");
    await refresh();
    setBusy(false);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="grid grid-cols-4 gap-3">
        <Kpi label="Pass-rate" value={formatPassRate(stats.pass_rate)} tone="text-green-600" />
        <Kpi label="Принято" value={String(stats.accepted)} />
        <Kpi label="Доработка" value={String(stats.rework)} tone="text-amber-600" />
        <Kpi label="Брак" value={String(stats.scrap)} tone="text-red-600" />
      </div>

      <div className="mt-5 rounded-xl border border-line bg-surface p-4">
        <div className="text-sm font-semibold text-ink">Решение ОТК</div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={order}
            onChange={(e) => setOrder(e.target.value)}
            placeholder="№ наряда"
            className="w-28 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <input
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            placeholder="Изделие"
            className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <input
            value={inspector}
            onChange={(e) => setInspector(e.target.value)}
            placeholder="Контролёр"
            className="w-32 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            list="otk-reasons"
            placeholder="Причина (для доработки/брака) — можно выбрать или ввести свою"
            className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <datalist id="otk-reasons">
            {REWORK_REASONS.map((r) => (
              <option key={r} value={r} />
            ))}
          </datalist>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => decide("accept")}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-60"
          >
            <Check size={16} /> Принять
          </button>
          <button
            onClick={() => decide("rework")}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-2 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-60"
          >
            <Wrench size={16} /> На доработку
          </button>
          <button
            onClick={() => decide("scrap")}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
          >
            <X size={16} /> Брак · акт
          </button>
          <span className="ml-1 inline-flex items-center gap-1 text-xs text-muted">
            <Send size={13} /> брак уходит претензией в закупки
          </span>
        </div>
      </div>

      <div className="mt-5 text-sm font-semibold text-ink">Журнал ОТК</div>
      <div className="mt-2 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">№</th>
              <th className="px-4 py-2 font-medium">Изделие</th>
              <th className="px-4 py-2 font-medium">Решение</th>
              <th className="px-4 py-2 font-medium">Причина</th>
              <th className="px-4 py-2 font-medium">Контролёр</th>
            </tr>
          </thead>
          <tbody>
            {journal.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted">
                  Решений пока нет
                </td>
              </tr>
            )}
            {journal.map((r) => (
              <tr key={r.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-muted">{r.order_code || "—"}</td>
                <td className="px-4 py-2.5 text-muted">{r.product || "—"}</td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                      DECISION_STYLES[r.decision],
                    )}
                  >
                    {decisionLabel(r.decision)}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-muted">{r.reason || "—"}</td>
                <td className="px-4 py-2.5 text-muted">{r.inspector || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
