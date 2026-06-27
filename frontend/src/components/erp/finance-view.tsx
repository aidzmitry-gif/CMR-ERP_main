"use client";

import { useEffect, useState } from "react";

import { formatByn } from "@/lib/format";

// ── Контракт ответа /finance/summary (см. modules/finance/summary.py) ──
interface FinanceSummary {
  currency: string;
  margin: { revenue: number; landed: number; freight: number; gross: number; pct: number | null };
  cash: {
    inflow: number;
    outflow: number;
    net: number;
    received: number;
    pending_receivable: number;
    freight_refund: number;
  };
  costs: { kind: string; label: string; amount: number }[];
}

interface Payment {
  id: number;
  ref: string;
  amount: number;
  status: string;
  kind: string;
}

// Доход (receivable) — приток; всё остальное (freight/landed) — отток. freight_refund хранится
// отрицательной суммой, поэтому по знаку сам встаёт на сторону притока.
function isInflow(p: Payment): boolean {
  return p.kind === "receivable" ? p.amount >= 0 : p.amount < 0;
}

const KIND_LABEL: Record<string, string> = {
  receivable: "Счёт к получению",
  freight: "Фрахт",
  freight_refund: "Возврат фрахта",
  landed: "Себестоимость",
};

function Card({ title, value, tone }: { title: string; value: string; tone?: "pos" | "neg" }) {
  const color = tone === "pos" ? "text-emerald-600" : tone === "neg" ? "text-rose-600" : "text-ink";
  return (
    <div className="rounded-xl bg-surface p-4 shadow-card">
      <div className="text-xs font-medium text-muted">{title}</div>
      <div className={`mt-1 text-lg font-bold ${color}`}>{value}</div>
    </div>
  );
}

export function FinanceView() {
  const [summary, setSummary] = useState<FinanceSummary | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch("/api/finance/summary", { cache: "no-store" }).then((r) =>
        r.ok ? (r.json() as Promise<FinanceSummary>) : Promise.reject(),
      ),
      fetch("/api/finance/payments", { cache: "no-store" }).then((r) =>
        r.ok ? (r.json() as Promise<Payment[]>) : Promise.reject(),
      ),
    ])
      .then(([s, p]) => {
        if (!alive) return;
        setSummary(s);
        setPayments(p);
        setError(false);
      })
      .catch(() => alive && setError(true))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <main className="flex-1 overflow-auto p-6">
      <div>
        <h1 className="text-xl font-bold text-ink">Финансы</h1>
        <p className="mt-1 text-sm text-muted">
          Операционный срез: касса (ДДС-lite), фактическая маржа по фактам и движение платежей.
          Учёт/НДС/ЭСЧФ остаются в 1С.
        </p>
      </div>

      {loading && <p className="mt-6 text-sm text-muted">Загрузка…</p>}

      {!loading && error && (
        <p className="mt-6 rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
          Нет связи с финансовым модулем — эндпоинт недоступен.
        </p>
      )}

      {!loading && !error && summary && (
        <>
          {/* Касса — ДДС-lite */}
          <h2 className="mt-6 text-sm font-semibold text-muted">Касса (ДДС-lite)</h2>
          <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card title="Поступления" value={formatByn(summary.cash.inflow)} tone="pos" />
            <Card title="Расходы" value={formatByn(summary.cash.outflow)} tone="neg" />
            <Card
              title="Сальдо"
              value={formatByn(summary.cash.net)}
              tone={summary.cash.net >= 0 ? "pos" : "neg"}
            />
            <Card title="К поступлению (счета)" value={formatByn(summary.cash.pending_receivable)} />
          </div>

          {/* Фактическая маржа */}
          <h2 className="mt-6 text-sm font-semibold text-muted">Фактическая маржа (по фактам)</h2>
          <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card title="Выручка" value={formatByn(summary.margin.revenue)} />
            <Card title="Себестоимость (landed)" value={formatByn(summary.margin.landed)} />
            <Card title="Фрахт (нетто)" value={formatByn(summary.margin.freight)} />
            <Card
              title={`Валовая прибыль${summary.margin.pct != null ? ` · ${summary.margin.pct.toFixed(1)}%` : ""}`}
              value={formatByn(summary.margin.gross)}
              tone={summary.margin.gross >= 0 ? "pos" : "neg"}
            />
          </div>
          {summary.margin.revenue === 0 && (
            <p className="mt-2 text-xs text-muted">
              Выручки по фактам пока нет — маржа появится после первых проведённых счетов.
            </p>
          )}

          {/* Затраты по типам */}
          <h2 className="mt-6 text-sm font-semibold text-muted">Затраты по типам</h2>
          <div className="mt-2 overflow-hidden rounded-xl bg-surface shadow-card">
            <table className="w-full text-sm">
              <tbody>
                {summary.costs.map((c) => (
                  <tr key={c.kind} className="border-b border-line last:border-0">
                    <td className="px-4 py-2.5 text-ink">{c.label}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                      {formatByn(c.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Платежи in/out */}
          <h2 className="mt-6 text-sm font-semibold text-muted">Движение платежей</h2>
          <div className="mt-2 overflow-hidden rounded-xl bg-surface shadow-card">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Назначение</th>
                  <th className="px-4 py-2.5 font-medium">Тип</th>
                  <th className="px-4 py-2.5 font-medium">Статус</th>
                  <th className="px-4 py-2.5 text-right font-medium">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {payments.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-muted">
                      Платежей пока нет
                    </td>
                  </tr>
                )}
                {payments.map((p) => (
                  <tr key={p.id} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-4 py-2.5 text-ink">{p.ref}</td>
                    <td className="px-4 py-2.5 text-muted">{KIND_LABEL[p.kind] ?? p.kind}</td>
                    <td className="px-4 py-2.5">
                      <span className="rounded-md bg-sunken px-2 py-0.5 text-xs font-medium text-muted">
                        {p.status}
                      </span>
                    </td>
                    <td
                      className={`px-4 py-2.5 text-right tabular-nums ${isInflow(p) ? "text-emerald-600" : "text-rose-600"}`}
                    >
                      {isInflow(p) ? "+" : "−"}
                      {formatByn(Math.abs(p.amount))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}
