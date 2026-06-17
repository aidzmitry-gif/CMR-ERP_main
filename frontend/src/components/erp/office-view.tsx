"use client";

import clsx from "clsx";
import { FileText, Truck } from "lucide-react";
import { useEffect, useState } from "react";

import { OfficeDelivery } from "@/components/erp/office-delivery";
import {
  DEMO_DELIVERIES,
  OFFICE_CARRIERS,
  officeDocToDelivery,
  summarizeDeliveries,
  type Delivery,
  type OfficeCarrier,
  type OfficeDocApi,
} from "@/lib/office-delivery";

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
        active ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-sunken",
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
  const [carriers, setCarriers] = useState<OfficeCarrier[]>(OFFICE_CARRIERS);

  // Живые отгрузки офиса (через /api-прокси): показывают реальный трекинг из логистики
  // (связка Блок 3). При недоступном/пустом backend остаются демо-данные — UI не падает.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch("/api/office/docs", { cache: "no-store" });
        if (!res.ok) return;
        const mapped = ((await res.json()) as OfficeDocApi[]).map(officeDocToDelivery);
        if (alive && mapped.length > 0) setDeliveries(mapped);
      } catch {
        /* fallback на initialDeliveries (демо) */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Справочник перевозчиков office (реальные id для заявки); фолбэк — OFFICE_CARRIERS.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch("/api/office/carriers", { cache: "no-store" });
        if (!res.ok) return;
        const list = (await res.json()) as OfficeCarrier[];
        if (alive && list.length > 0) setCarriers(list);
      } catch {
        /* фолбэк на OFFICE_CARRIERS */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  function assignCarrier(id: number, carrierId: string) {
    const name = carriers.find((c) => c.id === carrierId)?.name ?? carrierId;
    setDeliveries((prev) => prev.map((d) => (d.id === id ? { ...d, carrier: name } : d)));
    // живой документ (есть officeStage) → оформляем заявку перевозчику на backend
    const d = deliveries.find((x) => x.id === id);
    if (d?.officeStage) {
      void (async () => {
        try {
          const res = await fetch(`/api/office/docs/${id}/carrier-request`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ carrier: carrierId, region: d.destination ?? "" }),
          });
          if (!res.ok) console.error("office carrier-request:", res.status);
        } catch (e) {
          console.error("office carrier-request failed", e);
        }
      })();
    }
  }

  const needCarrier = summarizeDeliveries(deliveries).needCarrierRequest;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-1 border-b border-line bg-surface px-6 py-2">
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
          <OfficeDelivery deliveries={deliveries} carriers={carriers} onAssignCarrier={assignCarrier} />
        </div>
      </div>
    </div>
  );
}
