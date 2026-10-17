"use client";

import clsx from "clsx";
import { FileText, Truck } from "lucide-react";
import { useEffect, useState } from "react";

import { OfficeDelivery } from "@/components/erp/office-delivery";
import {
  isOfficeCarrierList,
  isOfficeDocList,
  officeDocToDelivery,
  type Delivery,
  type OfficeCarrier,
} from "@/lib/office-delivery";

type Tab = "docs" | "delivery";
type ListStatus = "loading" | "success" | "error";
type LoadState = { status: ListStatus; error: string | null };

function TabButton({
  active,
  onClick,
  icon: Icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ size?: number }>;
  children: React.ReactNode;
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
    </button>
  );
}

function httpError(label: string, status: number): string {
  if (status === 401 || status === 403) return `${label}: доступ не подтверждён (HTTP ${status}).`;
  return `${label}: сервер вернул HTTP ${status}.`;
}

function errorMessage(error: unknown, label: string): string {
  if (error instanceof Error && error.message) return `${label}: ${error.message}`;
  return `${label}: не удалось загрузить данные.`;
}

/** Office page: the list is sourced from the API; no demo rows or static carrier catalog are rendered. */
export function OfficeView({
  board,
  initialDeliveries = [],
}: {
  board: React.ReactNode;
  initialDeliveries?: Delivery[];
}) {
  const [tab, setTab] = useState<Tab>("docs");
  const [deliveries, setDeliveries] = useState<Delivery[]>(initialDeliveries);
  const [carriers, setCarriers] = useState<OfficeCarrier[]>([]);
  const [deliveriesLoad, setDeliveriesLoad] = useState<LoadState>({ status: "loading", error: null });
  const [carriersLoad, setCarriersLoad] = useState<LoadState>({ status: "loading", error: null });
  const [deliveryAttempt, setDeliveryAttempt] = useState(0);
  const [carrierAttempt, setCarrierAttempt] = useState(0);
  const [carrierRequestError, setCarrierRequestError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    void (async () => {
      try {
        const response = await fetch("/api/office/docs", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(httpError("Список документов", response.status));
        const body: unknown = await response.json();
        if (controller.signal.aborted) return;
        if (!isOfficeDocList(body)) throw new Error("получен некорректный список документов.");
        setDeliveries(body.map(officeDocToDelivery));
        setDeliveriesLoad({ status: "success", error: null });
      } catch (error) {
        if (controller.signal.aborted) return;
        setDeliveriesLoad({ status: "error", error: errorMessage(error, "Загрузка документов") });
      }
    })();

    return () => controller.abort();
  }, [deliveryAttempt]);

  useEffect(() => {
    const controller = new AbortController();

    void (async () => {
      try {
        const response = await fetch("/api/office/carriers", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(httpError("Справочник вариантов", response.status));
        const body: unknown = await response.json();
        if (controller.signal.aborted) return;
        if (!isOfficeCarrierList(body)) throw new Error("получен некорректный справочник вариантов.");
        setCarriers(body.map(({ id, name }) => ({ id, name })));
        setCarriersLoad({ status: "success", error: null });
      } catch (error) {
        if (controller.signal.aborted) return;
        setCarriersLoad({ status: "error", error: errorMessage(error, "Загрузка справочника") });
      }
    })();

    return () => controller.abort();
  }, [carrierAttempt]);

  function retryDeliveries() {
    setDeliveriesLoad({ status: "loading", error: null });
    setDeliveryAttempt((attempt) => attempt + 1);
  }

  function retryCarriers() {
    setCarriersLoad({ status: "loading", error: null });
    setCarrierAttempt((attempt) => attempt + 1);
  }

  async function assignCarrier(id: number, carrierId: string): Promise<boolean> {
    const delivery = deliveries.find((item) => item.id === id);
    if (!delivery || delivery.officeStage !== "ready") {
      setCarrierRequestError("Заявку можно отправить только для документа на стадии «Готово к отгрузке».");
      return false;
    }

    setCarrierRequestError(null);
    try {
      const response = await fetch(`/api/office/docs/${id}/carrier-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ carrier: carrierId, region: delivery.destination ?? "" }),
      });
      if (!response.ok) {
        setCarrierRequestError(`Заявка не принята сервером (HTTP ${response.status}). Данные формы сохранены.`);
        return false;
      }
      setCarrierRequestError("Ответ сервера не подтверждает назначение перевозчика. Данные формы сохранены.");
      return false;
    } catch {
      setCarrierRequestError("Не удалось отправить заявку из-за сетевой ошибки. Данные формы сохранены.");
      return false;
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-1 border-b border-line bg-surface px-6 py-2">
        <TabButton active={tab === "docs"} onClick={() => setTab("docs")} icon={FileText}>
          Документы
        </TabButton>
        <TabButton active={tab === "delivery"} onClick={() => setTab("delivery")} icon={Truck}>
          Доставка
        </TabButton>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className={tab === "docs" ? "contents" : "hidden"}>{board}</div>
        <div className={tab === "delivery" ? "contents" : "hidden"}>
          <OfficeDelivery
            deliveries={deliveries}
            carriers={carriers}
            deliveriesStatus={deliveriesLoad.status}
            deliveriesError={deliveriesLoad.error}
            carriersStatus={carriersLoad.status}
            carriersError={carriersLoad.error}
            carrierRequestError={carrierRequestError}
            onRetryDeliveries={retryDeliveries}
            onRetryCarriers={retryCarriers}
            onAssignCarrier={assignCarrier}
          />
        </div>
      </div>
    </div>
  );
}
