"use client";

import { useEffect, useState } from "react";

import { Card, KpiTile, Loading, Pill } from "@/components/erp/logistics-ui";
import { ShipmentDrawer } from "@/components/erp/logistics-shipment-drawer";
import { fetchCosts, fetchDashboard, fetchShipments, logisticsReadMessage, type Costs, type Dashboard, type Shipment } from "@/lib/logistics-api";
import { formatByn, formatNumber } from "@/lib/format";

const TRACKING_LABELS: Record<string, string> = {
  in_transit: "В пути",
  delivery_in_transit: "Доставка",
  import_in_transit: "Импорт в пути",
  at_customs: "На таможне",
  delivered: "Доставлено",
};

export function LogisticsDelivery() {
  const [shipments, setShipments] = useState<Shipment[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [costs, setCosts] = useState<Costs | null>(null);
  const [loading, setLoading] = useState(true);
  const [readErrors, setReadErrors] = useState<string[]>([]);
  const [shipmentsAvailable, setShipmentsAvailable] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([fetchShipments(), fetchDashboard(), fetchCosts()])
      .then(([s, d, c]) => {
        if (!alive) return;
        setShipmentsAvailable(s.status === "fulfilled");
        setShipments(s.status === "fulfilled" ? s.value : []);
        setDashboard(d.status === "fulfilled" ? d.value : null);
        setCosts(c.status === "fulfilled" ? c.value : null);
        const errors = [s, d, c].flatMap((result) => result.status === "rejected"
          ? [logisticsReadMessage(result.reason)] : []);
        if (d.status === "fulfilled" && d.value === null) errors.push("Сводка логистики недоступна.");
        if (c.status === "fulfilled" && c.value === null) errors.push("Затраты на логистику недоступны.");
        setReadErrors([...new Set(errors)]);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <Loading />;
  const byCarrier = costs?.by_carrier ?? dashboard?.cost_by_carrier ?? [];

  return (
    <div className="space-y-4">
      {readErrors.map((message) => <p key={message} role="alert" className="rounded-xl bg-surface p-4 text-sm text-muted">{message}</p>)}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <KpiTile label="В пути" value={dashboard?.in_transit ?? "—"} tone="brand" />
        <KpiTile label="На таможне" value={dashboard?.at_customs ?? "—"} tone="amber" />
        <KpiTile label="Доставлено" value={dashboard?.delivered_total ?? "—"} tone="emerald" />
        <KpiTile label="В срок" value={dashboard ? `${dashboard.on_time_pct}%` : "—"} />
        <KpiTile label="Срок доставки" value={dashboard ? `${dashboard.avg_delivery_days} дн` : "—"} />
        <KpiTile
          label="Затраты на логистику"
          value={dashboard ? formatByn(dashboard.logistics_cost) : "—"}
        />
      </div>

      {shipmentsAvailable && <Card title="Отгрузки и доставки" hint={`Всего записей: ${formatNumber(shipments.length)}`}>
        {shipments.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">
            Доставок пока нет — появятся после оформления отгрузок в сделках CRM.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">№</th>
                  <th className="px-3 py-2 font-medium">Получатель</th>
                  <th className="px-3 py-2 font-medium">Маршрут</th>
                  <th className="px-3 py-2 font-medium">Перевозчик</th>
                  <th className="px-3 py-2 text-right font-medium">Вес, кг</th>
                  <th className="px-3 py-2 text-right font-medium">Сумма</th>
                  <th className="px-3 py-2 font-medium">Трекинг</th>
                  <th className="px-3 py-2 font-medium">ETA</th>
                </tr>
              </thead>
              <tbody>
                {shipments.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => setOpenId(s.id)}
                    className="cursor-pointer border-b border-line last:border-0 hover:bg-sunken"
                  >
                    <td className="px-3 py-2 text-muted">{s.number}</td>
                    <td className="px-3 py-2 font-medium text-ink">{s.customer}</td>
                    <td className="px-3 py-2 text-muted">
                      {s.route_from} → {s.route_to}
                    </td>
                    <td className="px-3 py-2 text-muted">{s.carrier}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-muted">{formatNumber(s.weight_kg)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink">{formatByn(s.amount)}</td>
                    <td className="px-3 py-2">
                      <Pill
                        text={TRACKING_LABELS[s.tracking_status ?? ""] ?? s.tracking_status ?? s.status}
                        tone={s.tracking_status === "at_customs" ? "amber" : s.status === "delivered" ? "emerald" : "blue"}
                      />
                    </td>
                    <td className="px-3 py-2 text-muted">{s.eta ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>}

      {byCarrier.length > 0 && (
        <Card title="Затраты по перевозчикам">
          <div className="space-y-2">
            {byCarrier.map((c) => {
              const max = Math.max(...byCarrier.map((x) => x.cost), 1);
              return (
                <div key={c.carrier} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 truncate text-sm text-ink">{c.carrier}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-sunken">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${(c.cost / max) * 100}%` }} />
                  </div>
                  <span className="w-44 shrink-0 text-right text-sm tabular-nums text-muted">
                    {c.shipments} отгр. · {formatByn(c.cost)}
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {openId != null && (() => {
        const ship = shipments.find((s) => s.id === openId);
        if (!ship) return null;
        return (
          <ShipmentDrawer
            shipment={ship}
            onClose={() => setOpenId(null)}
            onUpdated={(updated) =>
              setShipments((list) => list.map((s) => (s.id === updated.id ? updated : s)))
            }
          />
        );
      })()}
    </div>
  );
}
