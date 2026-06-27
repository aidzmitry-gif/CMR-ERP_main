"use client";

import clsx from "clsx";
import { useState } from "react";

import { LogisticsAudit } from "@/components/erp/logistics-audit";
import { LogisticsDelivery } from "@/components/erp/logistics-delivery";
import { LogisticsFleet } from "@/components/erp/logistics-fleet";
import { LogisticsImport } from "@/components/erp/logistics-import";
import { LogisticsInsights } from "@/components/erp/logistics-insights";
import { LogisticsScorecard } from "@/components/erp/logistics-scorecard";
import { LogisticsTariffs } from "@/components/erp/logistics-tariffs";
import { LogisticsTender } from "@/components/erp/logistics-tender";

type TabKey =
  | "delivery"
  | "tender"
  | "tariffs"
  | "fleet"
  | "import"
  | "audit"
  | "scorecard"
  | "insights";

const TABS: { key: TabKey; label: string }[] = [
  { key: "delivery", label: "Рейсы" },
  { key: "tender", label: "Тендеры" },
  { key: "tariffs", label: "Тарифы" },
  { key: "fleet", label: "Парк" },
  { key: "import", label: "Импорт" },
  { key: "audit", label: "Аудит счетов" },
  { key: "scorecard", label: "Scorecard" },
  { key: "insights", label: "Экономия" },
];

const PANELS: Record<TabKey, () => React.ReactNode> = {
  delivery: () => <LogisticsDelivery />,
  tender: () => <LogisticsTender />,
  tariffs: () => <LogisticsTariffs />,
  fleet: () => <LogisticsFleet />,
  import: () => <LogisticsImport />,
  audit: () => <LogisticsAudit />,
  scorecard: () => <LogisticsScorecard />,
  insights: () => <LogisticsInsights />,
};

export function LogisticsTabs() {
  const [active, setActive] = useState<TabKey>("delivery");

  return (
    <main className="flex-1 overflow-auto bg-canvas p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        <div>
          <h1 className="text-xl font-bold text-ink">Логистика</h1>
          <p className="mt-1 text-sm text-muted">
            Доставка, тарифы, парк, тендеры и контроль счетов перевозчиков. Валюта — бел. руб. (BYN).
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-1 border-b border-line">
          {TABS.map((t) => {
            const isActive = t.key === active;
            return (
              <button
                key={t.key}
                onClick={() => setActive(t.key)}
                className={clsx(
                  "relative px-3 py-2 text-sm",
                  isActive ? "font-semibold text-accent-ink" : "text-muted hover:text-ink",
                )}
              >
                {t.label}
                {isActive && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-accent" />}
              </button>
            );
          })}
        </div>

        {PANELS[active]()}
      </div>
    </main>
  );
}
