import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Изолируем компонент от сети: три фетча логистики — моки (значения задаём в тестах).
vi.mock("@/lib/logistics-api", () => ({
  fetchShipments: vi.fn(),
  fetchDashboard: vi.fn(),
  fetchCosts: vi.fn(),
}));

// Дровер рейса — тяжёлый дочерний компонент со своими PATCH-вызовами. Подменяем на
// лёгкую заглушку, чтобы проверять ТОЛЬКО факт открытия/закрытия из таблицы.
vi.mock("@/components/erp/logistics-shipment-drawer", () => ({
  ShipmentDrawer: ({
    shipment,
    onClose,
  }: {
    shipment: { number: string };
    onClose: () => void;
  }) => (
    <div role="dialog">
      Рейс {shipment.number}
      <button onClick={onClose}>Закрыть</button>
    </div>
  ),
}));

import { LogisticsDelivery } from "@/components/erp/logistics-delivery";
import { fetchCosts, fetchDashboard, fetchShipments, type Costs, type Dashboard, type Shipment } from "@/lib/logistics-api";

const mockShipments = fetchShipments as ReturnType<typeof vi.fn>;
const mockDashboard = fetchDashboard as ReturnType<typeof vi.fn>;
const mockCosts = fetchCosts as ReturnType<typeof vi.fn>;

function makeShipment(over: Partial<Shipment> = {}): Shipment {
  return {
    id: 1,
    number: "SH-001",
    customer: "ООО Ромашка",
    address: "Минск, пр. Независимости 1",
    route_from: "Минск",
    route_to: "Брест",
    carrier: "Белпочта",
    carrier_code: "bp",
    cargo: "АКБ",
    weight_kg: 320,
    amount: 850, // < 1000 → без разделителя разрядов, стабильно в ru-RU
    status: "in_transit",
    tracking_status: "in_transit",
    eta: "2026-08-01",
    ...over,
  };
}

const dashboard: Dashboard = {
  in_transit: 3,
  delivery_in_transit: 2,
  import_in_transit: 1,
  at_customs: 1,
  delivered_total: 7,
  avg_delivery_days: 4,
  on_time_pct: 95,
  logistics_cost: 500,
  shipping_cost_company: 0,
  carriers: [],
  cost_by_carrier: [],
};

const costs: Costs = {
  total: 1200,
  company: 900,
  client: 300,
  import_cost: 0,
  by_carrier: [
    { carrier: "Белпочта", shipments: 5, cost: 900 },
    { carrier: "СДЭК", shipments: 2, cost: 300 },
  ],
};

// Значение KPI-плитки по её подписи (внутри грид-контейнера — вне таблицы/пилюль,
// чтобы совпадения текста «В пути»/«Доставлено» в таблице не мешали).
function kpiValue(grid: HTMLElement, label: string): string {
  const labelEl = within(grid).getByText(label);
  const tile = labelEl.parentElement as HTMLElement;
  return (tile.querySelector(".text-xl")?.textContent ?? "").trim();
}

beforeEach(() => {
  vi.clearAllMocks();
  mockShipments.mockResolvedValue([makeShipment()]);
  mockDashboard.mockResolvedValue(dashboard);
  mockCosts.mockResolvedValue(costs);
});

describe("LogisticsDelivery", () => {
  it("показывает индикатор загрузки до прихода данных", () => {
    render(<LogisticsDelivery />);
    // фетчи ещё не разрешились (микротаск) → на экране заглушка загрузки
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    expect(screen.queryByText("Отгрузки и доставки")).not.toBeInTheDocument();
  });

  it("рендерит KPI из дашборда backend (источник истины, а не сводка списка)", async () => {
    // список даёт inTransit=1, delivered=0 — если бы KPI считались из него, значения
    // разошлись бы с дашбордом. Дашборд должен победить.
    render(<LogisticsDelivery />);
    const grid = (await screen.findByText("Отгрузки и доставки")).closest(".space-y-4")
      ?.querySelector(".grid") as HTMLElement;

    expect(kpiValue(grid, "В пути")).toBe("3");
    expect(kpiValue(grid, "На таможне")).toBe("1");
    expect(kpiValue(grid, "Доставлено")).toBe("7");
    expect(kpiValue(grid, "В срок")).toBe("95%");
    expect(kpiValue(grid, "Срок доставки")).toBe("4 дн");
    expect(kpiValue(grid, "Затраты на логистику")).toBe("500 BYN");
  });

  it("считает KPI из списка доставок, когда дашборд недоступен (fallback)", async () => {
    mockDashboard.mockResolvedValue(null);
    mockCosts.mockResolvedValue(null);
    // два in_transit + один delivered → summary: inTransit=2, delivered=1, atCustoms=0
    mockShipments.mockResolvedValue([
      makeShipment({ id: 1, status: "in_transit" }),
      makeShipment({ id: 2, status: "assigned", tracking_status: undefined }),
      makeShipment({ id: 3, status: "delivered", tracking_status: undefined }),
    ]);

    render(<LogisticsDelivery />);
    const grid = (await screen.findByText("Отгрузки и доставки")).closest(".space-y-4")
      ?.querySelector(".grid") as HTMLElement;

    // status !== planned и !== delivered → inTransit: in_transit + assigned = 2
    expect(kpiValue(grid, "В пути")).toBe("2");
    expect(kpiValue(grid, "Доставлено")).toBe("1");
    // без дашборда числовые метрики недоступны → прочерк
    expect(kpiValue(grid, "В срок")).toBe("—");
    expect(kpiValue(grid, "Затраты на логистику")).toBe("—");
  });

  it("показывает ошибку связи, когда всё пусто (дашборд+затраты null, список пуст)", async () => {
    mockShipments.mockResolvedValue([]);
    mockDashboard.mockResolvedValue(null);
    mockCosts.mockResolvedValue(null);

    render(<LogisticsDelivery />);
    expect(await screen.findByText(/Не удалось загрузить рейсы и дашборд/)).toBeInTheDocument();
    // таблицы/KPI при провале нет
    expect(screen.queryByText("Отгрузки и доставки")).not.toBeInTheDocument();
  });

  it("показывает ошибку связи при отказе промиса (catch-ветка)", async () => {
    mockShipments.mockRejectedValue(new Error("network down"));
    render(<LogisticsDelivery />);
    expect(await screen.findByText(/Проверьте подключение к сервису логистики/)).toBeInTheDocument();
  });

  it("рендерит строку доставки: получатель, маршрут, сумма BYN и русский трекинг-статус", async () => {
    render(<LogisticsDelivery />);
    expect(await screen.findByText("ООО Ромашка")).toBeInTheDocument();
    expect(screen.getByText("Минск → Брест")).toBeInTheDocument();
    expect(screen.getByText("850 BYN")).toBeInTheDocument();
    // tracking_status "in_transit" маппится на подпись "В пути" (в таблице-пилюле)
    const row = screen.getByText("ООО Ромашка").closest("tr") as HTMLElement;
    expect(within(row).getByText("В пути")).toBeInTheDocument();
    // счётчик записей в шапке карточки
    expect(screen.getByText(/Всего записей: 1/)).toBeInTheDocument();
  });

  it("маппит трекинг-статусы: at_customs → «На таможне», неизвестный падает на status", async () => {
    mockShipments.mockResolvedValue([
      makeShipment({ id: 1, customer: "ООО Таможня", tracking_status: "at_customs", status: "in_transit" }),
      makeShipment({ id: 2, customer: "ООО Назначен", tracking_status: undefined, status: "assigned" }),
    ]);
    render(<LogisticsDelivery />);

    const customsRow = (await screen.findByText("ООО Таможня")).closest("tr") as HTMLElement;
    expect(within(customsRow).getByText("На таможне")).toBeInTheDocument();
    // нет ни label, ни tracking_status → показываем сырой status "assigned"
    const assignedRow = screen.getByText("ООО Назначен").closest("tr") as HTMLElement;
    expect(within(assignedRow).getByText("assigned")).toBeInTheDocument();
  });

  it("показывает пустое состояние доставок, когда список пуст, но дашборд есть", async () => {
    mockShipments.mockResolvedValue([]);
    render(<LogisticsDelivery />);
    expect(await screen.findByText(/Доставок пока нет/)).toBeInTheDocument();
    // это НЕ ошибка связи — дашборд пришёл, KPI на месте
    expect(screen.queryByText(/Не удалось загрузить/)).not.toBeInTheDocument();
    expect(screen.getByText("Отгрузки и доставки")).toBeInTheDocument();
  });

  it("строит секцию затрат по перевозчикам с длиной полос пропорционально максимуму", async () => {
    render(<LogisticsDelivery />);
    expect(await screen.findByText("Затраты по перевозчикам")).toBeInTheDocument();
    expect(screen.getByText(/5 отгр\. · 900 BYN/)).toBeInTheDocument();
    expect(screen.getByText(/2 отгр\. · 300 BYN/)).toBeInTheDocument();

    const bars = document.querySelectorAll(".bg-accent");
    expect(bars).toHaveLength(2);
    // max=900 → первый 100%, второй 300/900 ≈ 33% (строго меньше первого и >0)
    expect((bars[0] as HTMLElement).style.width).toBe("100%");
    const second = parseFloat((bars[1] as HTMLElement).style.width);
    expect(second).toBeGreaterThan(0);
    expect(second).toBeLessThan(100);
  });

  it("берёт затраты из dashboard.cost_by_carrier, когда costs=null (fallback источника)", async () => {
    mockCosts.mockResolvedValue(null);
    mockDashboard.mockResolvedValue({
      ...dashboard,
      cost_by_carrier: [{ carrier: "ЖД-Карго", shipments: 4, cost: 1234 }],
    });
    render(<LogisticsDelivery />);
    expect(await screen.findByText("Затраты по перевозчикам")).toBeInTheDocument();
    expect(screen.getByText(/ЖД-Карго/)).toBeInTheDocument();
  });

  it("скрывает секцию затрат, когда данных по перевозчикам нет", async () => {
    mockCosts.mockResolvedValue({ ...costs, by_carrier: [] });
    mockDashboard.mockResolvedValue({ ...dashboard, cost_by_carrier: [] });
    render(<LogisticsDelivery />);
    await screen.findByText("Отгрузки и доставки");
    expect(screen.queryByText("Затраты по перевозчикам")).not.toBeInTheDocument();
  });

  it("клик по строке открывает дровер рейса, закрытие его убирает", async () => {
    render(<LogisticsDelivery />);
    const row = (await screen.findByText("ООО Ромашка")).closest("tr") as HTMLElement;
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(row);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Рейс SH-001/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
