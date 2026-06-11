"use client";

import clsx from "clsx";
import { FileText, Truck } from "lucide-react";
import { useState } from "react";

import { OfficeDelivery } from "@/components/erp/office-delivery";
import { DEMO_DELIVERIES, summarizeDeliveries, type Delivery } from "@/lib/office-delivery";

type Tab = "docs" | "delivery";

function TabButton({
  active,
  onClick,
  icon: Icon,
  children,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ size?: number }>;
  children: React.ReactNode;
  badge?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
        active ? "bg-brand-100 text-brand-600" : "text-slate-500 hover:bg-slate-100",
      )}
    >
      <Icon size={16} />
      {children}
      {badge ? (
        <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-semibold text-white">
          {badge}
        </span>
      ) : null}
    </button>
  );
}

/**
 * Офис-менеджер: вкладки «Документы» (общая воронка-доска, передаётся как board)
 * и «Доставка» (секция трекинга + заявка перевозчику). Воронку не трогаем —
 * рендерим переданный элемент через display:contents, чтобы сохранить её layout (main + правая панель).
 */
export function OfficeView({
  board,
  initialDeliveries = DEMO_DELIVERIES,
}: {
  board: React.ReactNode;
  initialDeliveries?: Delivery[];
}) {
  const [tab, setTab] = useState<Tab>("docs");
  const [deliveries, setDeliveries] = useState<Delivery[]>(initialDeliveries);

  function assignCarrier(id: number, carrier: string) {
    setDeliveries((prev) => prev.map((d) => (d.id === id ? { ...d, carrier } : d)));
  }

  const needCarrier = summarizeDeliveries(deliveries).needCarrierRequest;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-1 border-b border-slate-200 bg-white px-6 py-2">
        <TabButton active={tab === "docs"} onClick={() => setTab("docs")} icon={FileText}>
          Документы
        </TabButton>
        <TabButton
          active={tab === "delivery"}
          onClick={() => setTab("delivery")}
          icon={Truck}
          badge={needCarrier}
        >
          Доставка
        </TabButton>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className={tab === "docs" ? "contents" : "hidden"}>{board}</div>
        <div className={tab === "delivery" ? "contents" : "hidden"}>
          <OfficeDelivery deliveries={deliveries} onAssignCarrier={assignCarrier} />
        </div>
      </div>
    </div>
  );
}
