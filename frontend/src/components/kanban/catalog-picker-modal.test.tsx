import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  requestApproval: vi.fn(),
}));

vi.mock("@/components/kanban/currency-context", () => ({
  useCurrency: () => ({ fmt: (value: number) => `${value.toFixed(2)} BYN` }),
}));

import { CatalogPickerModal } from "@/components/kanban/catalog-picker-modal";
import type { ProductPickerState, PickerRow } from "@/components/kanban/product-picker";
import type { SkuOption } from "@/lib/api";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const battery: SkuOption = { id: 1, code: "AKB-60", title: "АКБ 60Ah 12V", unit: "шт" };
const lamp: SkuOption = { id: 2, code: "LAMP-H4", title: "Лампа H4 24V", unit: "шт" };

const batteryStock = {
  price: 150,
  cost: 100,
  free: 4,
  forecast: 2,
  warehouses: [{ name: "Минск", free: 4, forecast: 2 }],
};

const row: PickerRow = {
  skuId: battery.id,
  code: battery.code,
  title: battery.title,
  unit: battery.unit,
  qty: 1,
  picked: true,
};

function makeState(overrides: Record<string, unknown> = {}) {
  const state = {
    skus: [battery, lamp],
    catalogStatus: "ready" as const,
    stock: {
      [battery.code]: batteryStock,
      [lamp.code]: { price: 80, cost: null, free: 0, forecast: 5, warehouses: [] },
    },
    warehouseStock: {
      [battery.code]: {
        code: battery.code,
        price: 150,
        cost: 100,
        rows: [{ warehouse: "Минск", on: 6, reserved: 2, free: 4, forecast: 2 }],
      },
    },
    rows: [] as PickerRow[],
    query: "",
    setQuery: vi.fn(),
    candidates: [],
    addSku: vi.fn(),
    addSkuWithQty: vi.fn(),
    setRowQty: vi.fn(),
    setRowPrice: vi.fn(),
    toggleRow: vi.fn(),
    removeRow: vi.fn(),
    reset: vi.fn(),
    repeatLastOrder: vi.fn().mockResolvedValue(0),
    pickedRows: [] as PickerRow[],
    orderTotal: 0,
    costedRows: [] as PickerRow[],
    costedRevenue: 0,
    orderCost: 0,
    orderMargin: 0,
    hasUnderOrder: false,
    commitToDeal: vi.fn().mockResolvedValue({ ok: 1, total: 1 }),
  };
  return { ...state, ...overrides } as unknown as ProductPickerState;
}

function renderModal(
  stateOverrides: Record<string, unknown> = {},
  props: Partial<React.ComponentProps<typeof CatalogPickerModal>> = {},
) {
  const state = makeState(stateOverrides);
  const onClose = props.onClose ?? vi.fn();
  const onCommitted = props.onCommitted ?? vi.fn();
  render(
    <CatalogPickerModal
      dealId={props.dealId}
      counterparty={props.counterparty ?? "ООО Ромашка"}
      onClose={onClose}
      onCommitted={onCommitted}
      state={state}
    />,
  );
  return { state, onClose, onCommitted };
}

beforeEach(() => {
  vi.clearAllMocks();
  mock(api.requestApproval).mockResolvedValue({ ok: true });
});

describe("CatalogPickerModal — реальный UI стейта подбора", () => {
  it("фильтрует по строке и переключателю только наличия", () => {
    renderModal();

    const search = screen.getByPlaceholderText("Название / артикул — напр. «6СТ-190»");
    fireEvent.change(search, { target: { value: "лампа" } });
    expect(screen.getByRole("row", { name: /Лампа H4 24V/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /АКБ 60Ah 12V/ })).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "" } });
    fireEvent.click(screen.getByLabelText("только в наличии"));
    expect(screen.getByRole("row", { name: /АКБ 60Ah 12V/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Лампа H4 24V/ })).not.toBeInTheDocument();
  });

  it("обрабатывает точный поиск, клавишу вверх и подбор услуги без складских остатков", () => {
    const { state } = renderModal();
    const search = screen.getByPlaceholderText("Название / артикул — напр. «6СТ-190»");
    fireEvent.change(search, { target: { value: "a" } });
    fireEvent.click(screen.getByLabelText("по точному соответствию"));
    fireEvent.keyDown(search, { key: "ArrowDown" });
    fireEvent.keyDown(search, { key: "ArrowUp" });

    const lampRow = screen.getByRole("row", { name: /Лампа H4 24V/ });
    expect(lampRow).toBeInTheDocument();
    expect(lampRow.querySelector("mark")).toBeNull();
    fireEvent.click(lampRow);
    expect(screen.getByText(/нет данных по складам/)).toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue("1"), { target: { value: "2" } });
    fireEvent.change(screen.getByDisplayValue("80"), { target: { value: "72" } });
    fireEvent.change(screen.getByDisplayValue("10"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));

    expect(state.addSkuWithQty).toHaveBeenCalledWith(lamp, 2);
    expect(state.setRowPrice).toHaveBeenCalledWith(lamp.id, 72);
  });

  it("показывает честное сообщение доступа и ссылку на Keycloak", () => {
    renderModal({ skus: [], catalogStatus: "auth" });

    expect(screen.getByText(/Нет доступа к номенклатуре/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Войти через Keycloak" })).toHaveAttribute("href", "/login");
  });

  it("открывает попап клавиатурой, выбирает складское количество и сохраняет цену", () => {
    const { state } = renderModal();
    const search = screen.getByPlaceholderText("Название / артикул — напр. «6СТ-190»");

    fireEvent.keyDown(search, { key: "ArrowDown" });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(screen.getByText("Количество")).toBeInTheDocument();
    expect(screen.getByText("Минск")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "1 →" }));
    fireEvent.change(screen.getByDisplayValue("150"), { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));

    expect(state.addSkuWithQty).toHaveBeenCalledWith(battery, 4);
    expect(state.setRowPrice).toHaveBeenCalledWith(battery.id, 120);
    expect(screen.queryByText("Количество")).not.toBeInTheDocument();
  });

  it("для новой сделки оставляет выбранные строки в общем стейте и закрывает окно", () => {
    const onClose = vi.fn();
    const state = makeState({ pickedRows: [row], rows: [row], orderTotal: 150 });
    renderModal({ pickedRows: [row], rows: [row], orderTotal: 150 }, { onClose, dealId: undefined });

    fireEvent.click(screen.getAllByRole("button", { name: /Перенести/ })[0]);
    expect(state.commitToDeal).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("для существующей сделки коммитит позиции и уведомляет вызывающую сторону", async () => {
    const { state, onCommitted } = renderModal({ pickedRows: [row], rows: [row], orderTotal: 150 }, { dealId: "deal-7" });

    fireEvent.click(screen.getAllByRole("button", { name: /Перенести в документ/ })[0]);
    await waitFor(() => expect(state.commitToDeal).toHaveBeenCalledWith("deal-7", "ООО Ромашка"));
    expect(onCommitted).toHaveBeenCalledOnce();
  });

  it("при марже ниже порога сначала просит подтверждение и отправляет approval", async () => {
    const { state } = renderModal(
      {
        pickedRows: [row],
        rows: [row],
        orderTotal: 100,
        costedRows: [row],
        costedRevenue: 100,
        orderMargin: 10,
      },
      { dealId: "deal-low-margin" },
    );

    fireEvent.click(screen.getAllByRole("button", { name: /согласовать скидку/ })[0]);
    expect(screen.getByText(/Маржа 10% ниже порога 12%/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Да, перенести/ })[0]);

    await waitFor(() => {
      expect(state.commitToDeal).toHaveBeenCalledWith("deal-low-margin", "ООО Ромашка");
      expect(api.requestApproval).toHaveBeenCalledWith("deal-low-margin", "deal.discount");
    });
  });

  it("повтор заказа различает отсутствие сделки и пустой прошлый заказ", async () => {
    const { onClose } = renderModal({}, { dealId: undefined, onClose: vi.fn() });
    fireEvent.click(screen.getByRole("button", { name: /Прошлый заказ/ }));
    expect(screen.getByText(/только для существующей сделки/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    // Тот же реальный обработчик с идентификатором сделки — backend вернул 0 строк.
    const repeatLastOrder = vi.fn().mockResolvedValue(0);
    renderModal({ repeatLastOrder }, { dealId: "deal-empty" });
    fireEvent.click(screen.getAllByRole("button", { name: /Прошлый заказ/ })[1]);
    await waitFor(() => expect(screen.getByText(/Прошлых заказов этого контрагента/)).toBeInTheDocument());
  });

  it("редактирует уже добавленную строку через корзину и может снять её", () => {
    const { state } = renderModal({ rows: [row], pickedRows: [row], orderTotal: 150 });

    fireEvent.click(screen.getAllByRole("button", { name: "+" })[0]);
    expect(state.setRowQty).toHaveBeenCalledWith(battery.id, 2);
    fireEvent.click(screen.getByRole("button", { name: "Убрать из корзины" }));
    expect(state.removeRow).toHaveBeenCalledWith(battery.id);
  });

  it("редактирует количество существующей строки, исключает её из счёта и закрывается Escape", () => {
    const existing = { ...row, qty: 2 };
    const { state, onClose } = renderModal({ rows: [existing], pickedRows: [existing], orderTotal: 300 });

    const tableRow = screen.getByRole("row", { name: /АКБ 60Ah 12V/ });
    fireEvent.click(within(tableRow).getByText("2"));
    expect(screen.getByText("Количество")).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue("2"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    expect(state.setRowQty).toHaveBeenCalledWith(battery.id, 3);

    fireEvent.click(screen.getByLabelText("Включить в счёт"));
    expect(state.toggleRow).toHaveBeenCalledWith(battery.id);
    const minusButtons = screen.getAllByRole("button", { name: "−" });
    fireEvent.click(minusButtons[minusButtons.length - 1]);
    expect(state.setRowQty).toHaveBeenCalledWith(battery.id, 1);

    fireEvent.click(screen.getByRole("button", { name: /150\.00 BYN/ }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("Количество")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
