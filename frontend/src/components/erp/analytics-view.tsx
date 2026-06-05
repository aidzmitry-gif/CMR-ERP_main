"use client";

import { useEffect, useState } from "react";

const SOURCES = [
  { label: "Сделки", endpoint: "/sales/deals" },
  { label: "Закупки", endpoint: "/procurement/requests" },
  { label: "Произв. наряды", endpoint: "/production/orders" },
  { label: "Складские операции", endpoint: "/wms/ops" },
  { label: "Отгрузки", endpoint: "/logistics/shipments" },
  { label: "Платежи", endpoint: "/finance/payments" },
  { label: "Кампании", endpoint: "/marketing/campaigns" },
  { label: "Обращения", endpoint: "/service/tickets" },
  { label: "Кандидаты", endpoint: "/hr/candidates" },
  { label: "Документы офиса", endpoint: "/office/docs" },
  { label: "Юр. дела", endpoint: "/legal/cases" },
  { label: "Курсы обучения", endpoint: "/knowledge/courses" },
];

export function AnalyticsView() {
  const [counts, setCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    SOURCES.forEach(async (s) => {
      try {
        const r = await fetch(`/api${s.endpoint}`, { cache: "no-store" });
        if (r.ok) {
          const d = await r.json();
          setCounts((c) => ({ ...c, [s.endpoint]: Array.isArray(d) ? d.length : 0 }));
        }
      } catch {
        /* ignore */
      }
    });
  }, []);

  return (
    <main className="flex-1 overflow-auto p-6">
      <h1 className="text-xl font-bold text-ink">Аналитика</h1>
      <p className="mt-1 text-sm text-muted">
        Сводка по модулям. Глубокая аналитика — в Metabase поверх PostgreSQL.
      </p>
      <div className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        {SOURCES.map((s) => (
          <div key={s.endpoint} className="rounded-2xl bg-white p-5 shadow-card">
            <div className="text-sm text-muted">{s.label}</div>
            <div className="mt-2 text-2xl font-bold text-ink">{counts[s.endpoint] ?? "…"}</div>
          </div>
        ))}
      </div>
    </main>
  );
}
