"use client";

import clsx from "clsx";
import { RefreshCw, Ship } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { formatByn, formatNumber, plural } from "@/lib/format";
import {
  daysToEta,
  fetchOpenOrders,
  type OpenOrder,
  orderTotals,
  statusLabel,
} from "@/lib/procurement-orders";

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-faint">{hint}</div>}
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  ordered: "bg-sunken text-muted",
  shipped: "bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  customs: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
};

/** ETA с цветовой подсказкой: просрочено — красным, ≤7 дней — янтарным. */
function EtaCell({ eta }: { eta: string | null }) {
  const days = daysToEta(eta);
  if (!eta || days === null) return <span className="text-faint">—</span>;
  const tone = days < 0 ? "text-red-600" : days <= 7 ? "text-amber-600" : "text-ink";
  const note =
    days < 0
      ? `просрочено на ${-days} ${plural(-days, ["день", "дня", "дней"])}`
      : days === 0
        ? "сегодня"
        : `через ${days} ${plural(days, ["день", "дня", "дней"])}`;
  return (
    <span className={clsx("tabular-nums", tone)}>
      {eta} <span className="text-[11px] text-faint">· {note}</span>
    </span>
  );
}

export function ProcurementOpenOrdersTable({ initial }: { initial: OpenOrder[] }) {
  const [orders, setOrders] = useState<OpenOrder[]>(initial);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // первичные данные с SSR; тихо перечитываем актуальные на клиенте
    void fetchOpenOrders().then(setOrders);
  }, []);

  async function refresh() {
    setBusy(true);
    setOrders(await fetchOpenOrders());
    setBusy(false);
  }

  const totals = useMemo(() => orderTotals(orders), [orders]);

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Размещённые заказы поставщикам, по которым товар <b>ещё не принят</b> (заказан / отгружен /
          таможня) — «в пути». Продажи вычитают это в нетто-доступности по номенклатуре.
        </p>
        <button
          onClick={refresh}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
        >
          <RefreshCw size={15} className={clsx(busy && "animate-spin")} /> Обновить
        </button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Открытых заказов" value={formatNumber(totals.orders)} />
        <Kpi label="Позиций в пути" value={formatNumber(totals.positions)} />
        <Kpi label="Товар в пути" value={formatByn(totals.goods)} />
        <Kpi label="Фрахт в пути" value={formatByn(totals.freight)} />
      </div>

      <div className="mt-5 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Заказ</th>
              <th className="px-4 py-2 font-medium">Поставщик</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 font-medium">ETA</th>
              <th className="px-4 py-2 font-medium">Позиции</th>
              <th className="px-4 py-2 text-right font-medium">Товар, BYN</th>
              <th className="px-4 py-2 text-right font-medium">Фрахт, BYN</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  <Ship size={18} className="mx-auto mb-1 text-faint" />
                  Открытых заказов нет — всё принято или ничего не в пути.
                </td>
              </tr>
            )}
            {orders.map((o) => {
              const goods = o.lines.reduce((s, l) => s + l.goods_value_byn, 0);
              return (
                <tr key={o.id} className="border-b border-line align-top last:border-0">
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{o.number}</td>
                  <td className="px-4 py-2.5 text-ink">{o.supplier || "—"}</td>
                  <td className="px-4 py-2.5">
                    <span
                      className={clsx(
                        "rounded-full px-2 py-0.5 text-xs font-medium",
                        STATUS_TONE[o.status] ?? "bg-sunken text-muted",
                      )}
                    >
                      {statusLabel(o.status)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-sm">
                    <EtaCell eta={o.eta_date} />
                  </td>
                  <td className="px-4 py-2.5 text-muted">
                    {o.lines.length === 0 ? (
                      <span className="text-faint">—</span>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        {o.lines.map((l, i) => (
                          <span key={`${l.sku_code}-${i}`} className="text-xs">
                            <span className="font-mono text-faint">{l.sku_code}</span>
                            <span className="text-muted"> × {formatNumber(l.qty)}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(goods)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                    {o.freight_byn ? formatNumber(o.freight_byn) : "—"}
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
