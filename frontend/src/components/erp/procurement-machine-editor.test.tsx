import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем только сетевой слой домена (fetch к бэку); чистый emptyLine и типы —
// настоящие (importActual), чтобы черновик позиции собирался как в проде.
vi.mock("@/lib/procurement-machine", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/procurement-machine")>();
  return {
    ...actual,
    fetchLandedPreview: vi.fn(),
    addLine: vi.fn(),
    deleteLine: vi.fn(),
    updateFreight: vi.fn(),
  };
});

import { ProcurementMachineEditor } from "@/components/erp/procurement-machine-editor";
import * as pm from "@/lib/procurement-machine";
import type { LandedPreview, MachineOrder } from "@/lib/procurement-machine";

function makeOrder(over: Partial<MachineOrder> = {}): MachineOrder {
  return {
    id: 7,
    number: "ZAK-7",
    supplier: "Shenzhen Co",
    supplier_id: 3,
    status: "draft",
    eta_date: "2026-08-01",
    freight_byn: 100,
    lines: [
      { id: 11, sku_code: "AKB-190", qty: 2, goods_value_byn: 900, weight: 50, volume: 3 },
    ],
    ...over,
  };
}

// числа держим < 1000 — ru-RU разделитель тысяч (nbsp) ломает точный getByText
function makePreview(over: Partial<LandedPreview> = {}): LandedPreview {
  return {
    order_id: 7,
    freight_byn: 100,
    lines: [
      {
        sku_code: "AKB-190",
        goods_byn: 900,
        allocated_byn: 50,
        landed_total_byn: 950,
        unit_landed_cost_byn: 475,
      },
    ],
    total_goods_byn: 900,
    total_landed_byn: 950,
    ...over,
  };
}

const mocked = () => ({
  fetchLandedPreview: pm.fetchLandedPreview as ReturnType<typeof vi.fn>,
  addLine: pm.addLine as ReturnType<typeof vi.fn>,
  deleteLine: pm.deleteLine as ReturnType<typeof vi.fn>,
  updateFreight: pm.updateFreight as ReturnType<typeof vi.fn>,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocked().fetchLandedPreview.mockResolvedValue(makePreview());
});

describe("ProcurementMachineEditor", () => {
  it("рендерит шапку (номер, поставщик, статус) и грузит landed-предпросмотр на маунте", async () => {
    render(<ProcurementMachineEditor initial={makeOrder()} />);

    expect(screen.getByText("Состав заказа ZAK-7")).toBeInTheDocument();
    expect(screen.getByText(/Shenzhen Co/)).toBeInTheDocument();
    expect(screen.getByText("Черновик")).toBeInTheDocument(); // STATUS_LABEL[draft]
    expect(screen.getByText(/ETA 2026-08-01/)).toBeInTheDocument();

    // предпросмотр грузится по initial.id и рисует себестоимость/шт + итоговую строку
    await waitFor(() => expect(mocked().fetchLandedPreview).toHaveBeenCalledWith(7));
    expect(await screen.findByText("475")).toBeInTheDocument(); // unit_landed_cost_byn
    expect(screen.getByText(/950 BYN/)).toBeInTheDocument(); // formatByn(total_landed_byn)
  });

  it("пустой список позиций показывает подсказку добавить первую", async () => {
    render(<ProcurementMachineEditor initial={makeOrder({ lines: [] })} />);
    expect(screen.getByText(/Позиций нет — добавьте первую ниже/)).toBeInTheDocument();
  });

  it("без предпросмотра себестоимость/шт — прочерк (не выдумываем число на фронте)", async () => {
    mocked().fetchLandedPreview.mockResolvedValue(null); // бэк недоступен
    render(<ProcurementMachineEditor initial={makeOrder()} />);
    await waitFor(() => expect(mocked().fetchLandedPreview).toHaveBeenCalled());
    expect(screen.getByText("—")).toBeInTheDocument(); // unitBySku пуст → «—»
    expect(screen.queryByText("Итого landed")).not.toBeInTheDocument(); // tfoot не рисуется без preview
  });

  it("добавление позиции без кода — валидация, addLine не зовётся", async () => {
    render(<ProcurementMachineEditor initial={makeOrder({ lines: [] })} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(await screen.findByText(/Укажите код номенклатуры позиции/)).toBeInTheDocument();
    expect(mocked().addLine).not.toHaveBeenCalled();
  });

  it("добавление валидной позиции зовёт addLine и показывает новую строку", async () => {
    const withLine = makeOrder();
    mocked().addLine.mockResolvedValue(withLine);
    render(<ProcurementMachineEditor initial={makeOrder({ lines: [] })} />);

    fireEvent.change(screen.getByLabelText("Код номенклатуры"), { target: { value: "AKB-190" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    await waitFor(() =>
      expect(mocked().addLine).toHaveBeenCalledWith(
        7,
        expect.objectContaining({ sku_code: "AKB-190" }),
      ),
    );
    // order обновился ответом бэка → строка позиции появилась в таблице
    expect(await screen.findByText("AKB-190")).toBeInTheDocument();
  });

  it("сбой добавления (бэк вернул null) показывает ошибку, а не молчит", async () => {
    mocked().addLine.mockResolvedValue(null);
    render(<ProcurementMachineEditor initial={makeOrder({ lines: [] })} />);
    fireEvent.change(screen.getByLabelText("Код номенклатуры"), { target: { value: "X-1" } });
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(await screen.findByText(/Не удалось добавить позицию/)).toBeInTheDocument();
  });

  it("удаление позиции зовёт deleteLine и убирает строку из таблицы", async () => {
    mocked().deleteLine.mockResolvedValue(makeOrder({ lines: [] }));
    render(<ProcurementMachineEditor initial={makeOrder()} />);

    expect(screen.getByText("AKB-190")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Удалить позицию" }));

    await waitFor(() => expect(mocked().deleteLine).toHaveBeenCalledWith(7, 11));
    expect(await screen.findByText(/Позиций нет/)).toBeInTheDocument();
  });

  it("фрахт: отрицательное значение — ошибка и откат к прежнему, updateFreight не зовётся", async () => {
    render(<ProcurementMachineEditor initial={makeOrder()} />);
    const input = screen.getByLabelText("Фрахт партии, BYN") as HTMLInputElement;

    fireEvent.change(input, { target: { value: "-5" } });
    fireEvent.blur(input);

    expect(await screen.findByText(/Фрахт должен быть неотрицательным/)).toBeInTheDocument();
    expect(input.value).toBe("100"); // мусор не записан, вернулось прежнее order.freight_byn
    expect(mocked().updateFreight).not.toHaveBeenCalled();
  });

  it("фрахт: валидное новое значение сохраняется через updateFreight", async () => {
    mocked().updateFreight.mockResolvedValue(makeOrder({ freight_byn: 200 }));
    render(<ProcurementMachineEditor initial={makeOrder()} />);
    const input = screen.getByLabelText("Фрахт партии, BYN") as HTMLInputElement;

    fireEvent.change(input, { target: { value: "200" } });
    fireEvent.blur(input);

    await waitFor(() => expect(mocked().updateFreight).toHaveBeenCalledWith(7, 200));
  });

  it("фрахт без изменения значения не дёргает бэк (ранний выход)", async () => {
    render(<ProcurementMachineEditor initial={makeOrder()} />);
    const input = screen.getByLabelText("Фрахт партии, BYN") as HTMLInputElement;
    fireEvent.blur(input); // значение то же (100)
    await waitFor(() => expect(mocked().fetchLandedPreview).toHaveBeenCalled());
    expect(mocked().updateFreight).not.toHaveBeenCalled();
  });

  it("завершённый заказ (received) — режим только-чтение: баннер, нет формы и кнопок удаления", async () => {
    render(<ProcurementMachineEditor initial={makeOrder({ status: "received" })} />);

    expect(screen.getByText("Принят")).toBeInTheDocument(); // STATUS_LABEL[received]
    expect(screen.getByText(/состав не редактируется/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Добавить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Удалить позицию" })).not.toBeInTheDocument();

    const freight = screen.getByLabelText("Фрахт партии, BYN") as HTMLInputElement;
    expect(freight).toBeDisabled();
  });
});
