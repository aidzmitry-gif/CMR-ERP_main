import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Единственная НЕчистая зависимость компонента — сетевые PATCH'и логистики. Мокаем их;
// доменную логику переходов (logistics-domain) и форматтеры (format) НЕ мокаем — они
// чистые и участвуют в проверяемом поведении (кнопки переходов, «Доставлено» и т.п.).
vi.mock("@/lib/logistics-api", () => ({
  patchShipmentStatus: vi.fn(),
  patchShipmentTracking: vi.fn(),
}));

import { ShipmentDrawer } from "@/components/erp/logistics-shipment-drawer";
import * as api from "@/lib/logistics-api";
import type { Shipment } from "@/lib/logistics-api";

const base: Shipment = {
  id: 7,
  number: "РЕЙС-7",
  customer: "ООО Ромашка",
  address: "Сделка CRM-42",
  route_from: "Минск",
  route_to: "Брест",
  carrier: "Белтранс",
  carrier_code: "BT",
  cargo: "Металлопрокат",
  weight_kg: 1250,
  amount: 3400,
  status: "in_transit",
  tracking_status: "",
  eta: "",
};

function renderDrawer(overrides: Partial<Shipment> = {}) {
  const onClose = vi.fn();
  const onUpdated = vi.fn();
  render(
    <ShipmentDrawer
      shipment={{ ...base, ...overrides }}
      onClose={onClose}
      onUpdated={onUpdated}
    />,
  );
  return { onClose, onUpdated };
}

beforeEach(() => vi.clearAllMocks());

describe("ShipmentDrawer", () => {
  it("показывает реквизиты рейса: клиент, маршрут, перевозчик и сумму в BYN", () => {
    renderDrawer();
    expect(screen.getByText("ООО Ромашка")).toBeInTheDocument();
    expect(screen.getByText("Белтранс")).toBeInTheDocument();
    expect(screen.getByText("Минск → Брест")).toBeInTheDocument();
    // formatByn: ru-RU группирует пробелом-неразрывником → матч по числу + BYN
    expect(
      screen.getByText((t) => t.replace(/\s/g, "").includes("3400BYN")),
    ).toBeInTheDocument();
  });

  it("отмечает текущий этап доставки пилюлей «сейчас» и рендерит все стадии", () => {
    renderDrawer({ status: "in_transit" });
    // все подписи потока присутствуют
    expect(screen.getByText("Запланирована")).toBeInTheDocument();
    expect(screen.getByText("В пути")).toBeInTheDocument();
    expect(screen.getByText("Доставлено")).toBeInTheDocument();
    // «сейчас» ровно одна — у текущего статуса
    expect(screen.getAllByText("сейчас")).toHaveLength(1);
  });

  it("предлагает только разрешённые переходы (из in_transit — на таможню и доставлено)", () => {
    renderDrawer({ status: "in_transit" });
    // allowedDeliveryTransitions(in_transit) = [at_customs, delivered]; назад — нельзя
    expect(screen.getByRole("button", { name: "→ На таможне" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "→ Доставлено" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Запланирована/ })).not.toBeInTheDocument();
  });

  it("для доставленного рейса переходов нет — показывает «Доставка завершена»", () => {
    renderDrawer({ status: "delivered" });
    expect(screen.getByText("Доставка завершена.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /→/ })).not.toBeInTheDocument();
  });

  it("клик по переходу зовёт patchShipmentStatus и прокидывает обновление в onUpdated", async () => {
    const updated: Shipment = { ...base, status: "delivered" };
    (api.patchShipmentStatus as ReturnType<typeof vi.fn>).mockResolvedValue(updated);
    const { onUpdated } = renderDrawer({ status: "in_transit" });

    fireEvent.click(screen.getByRole("button", { name: "→ Доставлено" }));

    await waitFor(() => expect(api.patchShipmentStatus).toHaveBeenCalledWith(7, "delivered"));
    expect(onUpdated).toHaveBeenCalledWith(updated);
    // ошибки нет
    expect(screen.queryByText(/Не удалось сменить статус/)).not.toBeInTheDocument();
  });

  it("сбой смены статуса показывает ошибку и НЕ трогает onUpdated", async () => {
    (api.patchShipmentStatus as ReturnType<typeof vi.fn>).mockResolvedValue(null);
    const { onUpdated } = renderDrawer({ status: "in_transit" });

    fireEvent.click(screen.getByRole("button", { name: "→ На таможне" }));

    expect(
      await screen.findByText("Не удалось сменить статус. Попробуйте ещё раз."),
    ).toBeInTheDocument();
    expect(onUpdated).not.toHaveBeenCalled();
  });

  it("сохранение трекинга шлёт введённый текст и ETA (eta пустой → null)", async () => {
    (api.patchShipmentTracking as ReturnType<typeof vi.fn>).mockResolvedValue({ ...base });
    const { onUpdated } = renderDrawer({ tracking_status: "", eta: "" });

    fireEvent.change(screen.getByPlaceholderText(/Прошла таможню/), {
      target: { value: "Прошла таможню, в пути" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить трекинг" }));

    await waitFor(() =>
      expect(api.patchShipmentTracking).toHaveBeenCalledWith(7, {
        tracking_status: "Прошла таможню, в пути",
        eta: null,
      }),
    );
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("сохранение трекинга передаёт непустой ETA как есть", async () => {
    (api.patchShipmentTracking as ReturnType<typeof vi.fn>).mockResolvedValue({ ...base });
    renderDrawer({ tracking_status: "у перевозчика", eta: "2026-08-01" });

    // значения проинициализированы из shipment — сохраняем без правок
    fireEvent.click(screen.getByRole("button", { name: "Сохранить трекинг" }));

    await waitFor(() =>
      expect(api.patchShipmentTracking).toHaveBeenCalledWith(7, {
        tracking_status: "у перевозчика",
        eta: "2026-08-01",
      }),
    );
  });

  it("сбой сохранения трекинга показывает ошибку", async () => {
    (api.patchShipmentTracking as ReturnType<typeof vi.fn>).mockResolvedValue(null);
    const { onUpdated } = renderDrawer();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить трекинг" }));

    expect(await screen.findByText("Не удалось сохранить трекинг.")).toBeInTheDocument();
    expect(onUpdated).not.toHaveBeenCalled();
  });

  it("и кнопка «Закрыть», и затемнённый фон зовут onClose", () => {
    const { onClose } = renderDrawer();
    // две кнопки закрытия: текстовая в шапке + фон-оверлей с aria-label «Закрыть»
    const closers = screen.getAllByRole("button", { name: "Закрыть" });
    expect(closers).toHaveLength(2);
    closers.forEach((b) => fireEvent.click(b));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
