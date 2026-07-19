import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Тестируем компонент изолированно: сетевые функции моканы, чистые (formatNh,
// nhTotal, normForProduct, coverageForProduct, zayavkiCounts, coverageTone,
// stageLabel/stageTone) остаются настоящими — считают по-честному.
vi.mock("@/lib/production-zayavki", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/production-zayavki")>();
  return {
    ...actual,
    fetchOrders: vi.fn(),
    createOrder: vi.fn(),
    updateOrderStage: vi.fn(),
  };
});
vi.mock("@/lib/production-norms", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/production-norms")>();
  return { ...actual, fetchNorms: vi.fn() };
});
vi.mock("@/lib/production-bom", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/production-bom")>();
  return { ...actual, fetchBoms: vi.fn() };
});

import { ZayavkiTable } from "@/components/erp/zayavki-table";
import { fetchBoms, type Bom } from "@/lib/production-bom";
import { fetchNorms, type Norm } from "@/lib/production-norms";
import { createOrder, fetchOrders, type Order, updateOrderStage } from "@/lib/production-zayavki";

const fetchOrdersMock = fetchOrders as ReturnType<typeof vi.fn>;
const fetchNormsMock = fetchNorms as ReturnType<typeof vi.fn>;
const fetchBomsMock = fetchBoms as ReturnType<typeof vi.fn>;
const createOrderMock = createOrder as ReturnType<typeof vi.fn>;
const updateOrderStageMock = updateOrderStage as ReturnType<typeof vi.fn>;

function order(over: Partial<Order>): Order {
  return {
    id: 1,
    number: "ПН-000",
    product: "Изделие",
    qty: 1,
    progress: 0,
    priority: "Средний",
    owner: "",
    stage: "queue",
    due_date: null,
    insight: "",
    nh_per_unit: 0,
    made_qty: 0,
    ...over,
  };
}

// Стеллаж — очередь, есть норма+BOM (запускаемо, покрытие 95%);
// Верстак — очередь, БЕЗ нормы и BOM (запуск недоступен, «нет нормы»/«нет BOM»);
// Шкаф — в работе (assembly), есть норма+BOM (в inProgress, кнопки запуска нет).
const ORDERS: Order[] = [
  order({ id: 1, number: "ПН-001", product: "Стеллаж", qty: 3, stage: "queue", nh_per_unit: 2.5, priority: "Высокий", due_date: "2026-08-01" }),
  order({ id: 2, number: "ПН-002", product: "Верстак", qty: 2, stage: "queue", nh_per_unit: 3 }),
  order({ id: 3, number: "ПН-003", product: "Шкаф", qty: 1, stage: "assembly", nh_per_unit: 4, owner: "Мастер" }),
];

const NORMS: Norm[] = [
  { id: 1, kind: "product", title: "Стеллаж", nh: 2.5, status: "approved", note: "" },
  { id: 2, kind: "product", title: "Шкаф", nh: 4, status: "approved", note: "" },
  // на утверждении, а не approved → normForProduct для Верстака вернёт null
  { id: 3, kind: "product", title: "Верстак", nh: 3, status: "pending", note: "" },
];

const BOMS: Bom[] = [
  { id: 1, product: "Стеллаж", version: "v1", status: "approved", note: "", item_count: 5, coverage: 95 },
  { id: 2, product: "Шкаф", version: "v1", status: "approved", note: "", item_count: 3, coverage: 100 },
];

// строку таблицы находим по её номеру наряда и поднимаемся до <tr>
function rowByNumber(num: string): HTMLElement {
  return screen.getByText(num).closest("tr") as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  // useEffect на маунте перечитывает данные с клиента — отдаём те же фикстуры,
  // чтобы доска не обнулилась после гидратации.
  fetchOrdersMock.mockResolvedValue(ORDERS);
  fetchNormsMock.mockResolvedValue(NORMS);
  fetchBomsMock.mockResolvedValue(BOMS);
  createOrderMock.mockResolvedValue(order({ id: 99 }));
  updateOrderStageMock.mockResolvedValue(true);
});

function renderTable(orders: Order[] = ORDERS, norms: Norm[] = NORMS, boms: Bom[] = BOMS) {
  return render(<ZayavkiTable initialOrders={orders} initialNorms={norms} initialBoms={boms} />);
}

describe("ZayavkiTable", () => {
  it("рендерит KPI и все строки заявок", () => {
    renderTable();
    // «Заявок всего» = 3 (родитель-плитка label+value)
    const totalTile = screen.getByText("Заявок всего").parentElement as HTMLElement;
    expect(totalTile).toHaveTextContent("3");
    expect(screen.getByText("ПН-001")).toBeInTheDocument();
    expect(screen.getByText("Верстак")).toBeInTheDocument();
    expect(screen.getByText("Шкаф")).toBeInTheDocument();
  });

  it("KPI «Без нормы», «Без BOM», «В работе» считают реально по фикстурам", () => {
    const { container } = renderTable();
    // KPI-плитки лежат в первой сетке grid-cols-4; «В работе» вне неё — это ещё
    // и сегмент-кнопка, и бейдж статуса, поэтому ищем метку строго в этой сетке.
    const kpiGrid = container.querySelector(".grid.grid-cols-4") as HTMLElement;
    const noNorm = within(kpiGrid).getByText("Без нормы").parentElement as HTMLElement;
    const noBom = within(kpiGrid).getByText("Без BOM").parentElement as HTMLElement;
    const inProgress = within(kpiGrid).getByText("В работе").parentElement as HTMLElement;
    expect(noNorm).toHaveTextContent("1"); // Верстак — норма pending, не approved
    expect(noBom).toHaveTextContent("1"); // Верстак — нет спецификации
    expect(inProgress).toHaveTextContent("1"); // Шкаф — assembly
  });

  it("бейдж «нет нормы» — только у изделия без утверждённой нормы", () => {
    renderTable();
    // Верстак единственный без approved-нормы → ровно один бейдж
    expect(screen.getAllByText(/нет нормы/).length).toBe(1);
    // бейдж внутри строки Верстака, не Стеллажа
    expect(within(rowByNumber("ПН-002")).getByText(/нет нормы/)).toBeInTheDocument();
    expect(within(rowByNumber("ПН-001")).queryByText(/нет нормы/)).not.toBeInTheDocument();
  });

  it("обеспеченность из BOM: процент — где есть спецификация, «нет BOM» — где нет", () => {
    renderTable();
    expect(within(rowByNumber("ПН-001")).getByText("95%")).toBeInTheDocument();
    expect(within(rowByNumber("ПН-003")).getByText("100%")).toBeInTheDocument();
    expect(within(rowByNumber("ПН-002")).getByText("нет BOM")).toBeInTheDocument();
  });

  it("нормо-часы итого = норма/шт × кол-во в русском формате (настоящий formatNh)", () => {
    renderTable();
    // Стеллаж: 2.5 × 3 = 7.5 → «7,5» (запятая, не точка)
    expect(within(rowByNumber("ПН-001")).getByText("7,5")).toBeInTheDocument();
    // Шкаф: 4 × 1 = 4 → «4»
    expect(within(rowByNumber("ПН-003")).getByText("4")).toBeInTheDocument();
  });

  it("поиск фильтрует строки по изделию", () => {
    renderTable();
    fireEvent.change(screen.getByPlaceholderText("Поиск по № или изделию"), {
      target: { value: "верстак" },
    });
    expect(screen.getByText("Верстак")).toBeInTheDocument();
    expect(screen.queryByText("Стеллаж")).not.toBeInTheDocument();
    expect(screen.queryByText("Шкаф")).not.toBeInTheDocument();
  });

  it("пустой поиск показывает «Ничего не найдено» (заявки есть, но не совпали)", () => {
    renderTable();
    fireEvent.change(screen.getByPlaceholderText("Поиск по № или изделию"), {
      target: { value: "нетакого" },
    });
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("сегмент по этапу «В работе» оставляет только наряды в сборке", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "В работе" }));
    expect(screen.getByText("Шкаф")).toBeInTheDocument();
    expect(screen.queryByText("Стеллаж")).not.toBeInTheDocument();
    expect(screen.queryByText("Верстак")).not.toBeInTheDocument();
  });

  it("«В работу» доступна только в очереди при утверждённой норме", () => {
    renderTable();
    // Стеллаж (queue + норма) → кнопка активна; Верстак (queue, без нормы) → disabled
    const launchOk = within(rowByNumber("ПН-001")).getByRole("button", { name: /В работу/ });
    const launchBlocked = within(rowByNumber("ПН-002")).getByRole("button", { name: /В работу/ });
    expect(launchOk).not.toBeDisabled();
    expect(launchBlocked).toBeDisabled();
    // у наряда в сборке кнопки запуска нет вовсе
    expect(within(rowByNumber("ПН-003")).queryByRole("button", { name: /В работу/ })).toBeNull();
  });

  it("клик «В работу» переводит наряд из очереди в сборку (updateOrderStage)", async () => {
    renderTable();
    fireEvent.click(within(rowByNumber("ПН-001")).getByRole("button", { name: /В работу/ }));
    await waitFor(() => expect(updateOrderStageMock).toHaveBeenCalledWith(1, "assembly"));
    // после мутации доска перечитывается
    await waitFor(() => expect(fetchOrdersMock).toHaveBeenCalledTimes(2));
  });

  it("создание заявки шлёт createOrder с изделием и дефолтами (кол-во 1, приоритет Средний)", async () => {
    renderTable();
    fireEvent.change(screen.getByPlaceholderText("Изделие новой заявки"), {
      target: { value: "Тумба" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Заявка/ }));
    await waitFor(() =>
      expect(createOrderMock).toHaveBeenCalledWith(
        expect.objectContaining({ product: "Тумба", qty: 1, priority: "Средний" }),
      ),
    );
  });

  it("создание с пустым изделием не зовёт createOrder и подсвечивает поле", () => {
    renderTable();
    const input = screen.getByPlaceholderText("Изделие новой заявки");
    fireEvent.click(screen.getByRole("button", { name: /Заявка/ }));
    expect(createOrderMock).not.toHaveBeenCalled();
    expect(input.className).toMatch(/amber/); // рамка-ошибка
  });
});
