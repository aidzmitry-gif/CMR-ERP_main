import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CatalogPickerModal } from "./catalog-picker-modal";
import { useProductPicker } from "./product-picker";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  fetchStock: vi.fn(), addDealItem: vi.fn(), createPriceQuote: vi.fn(),
  fetchLastOrder: vi.fn(), issueDocument: vi.fn(), updateDeal: vi.fn(), requestApproval: vi.fn(),
}));
vi.mock("./currency-context", () => ({
  useCurrency: () => ({ fmt: (price: number) => `${price.toFixed(2)} BYN` }),
}));

const sku = { id: 1, code: "A1", title: "Товар А", unit: "шт" };
const stock = { sku_code: "A1", warehouse: "Основной", qty_available: 10, qty_reserved: 0, qty_forecast: 0, price: 150 };

it("JZ15 late transfer does not approve or close another deal", async () => {
  let resolve!: (value: boolean) => void;
  vi.mocked(api.addDealItem).mockReturnValueOnce(new Promise<boolean>((done) => { resolve = done; }));
  const onCommitted = vi.fn();
  const { rerender } = render(<Harness onCommitted={onCommitted} />);
  fireEvent.click(await screen.findByText(sku.title));
  fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "125" } });
  fireEvent.click(screen.getByRole("button", { name: "ОК" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]);
  expect(api.addDealItem).toHaveBeenCalledOnce();
  rerender(<Harness dealId="d2" onCommitted={onCommitted} />);
  await act(async () => { resolve(true); });
  expect(onCommitted).not.toHaveBeenCalled();
  expect(api.requestApproval).not.toHaveBeenCalled();
  expect(screen.queryByText(/✅ Перенесено/)).toBeNull();
  expect(screen.getAllByRole("button", { name: "Перенести в документ" })[0]).toBeDisabled();
});

function Harness({ onClose = vi.fn(), onCommitted = vi.fn(), dealId = "d1" }: { onClose?: () => void; onCommitted?: () => void; dealId?: string }) {
  const picker = useProductPicker(true, dealId);
  return <CatalogPickerModal state={picker} dealId={dealId} counterparty="Клиент" onClose={onClose} onCommitted={onCommitted} />;
}

it("KB04 discounted partial transfer retains approval across A B A", async () => {
  const second = { ...sku, id: 2, code: "B2", title: "Товар Б" };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [sku, second] }));
  vi.mocked(api.fetchStock).mockResolvedValue([
    { ...stock, price: 100, cost: 100 },
    { ...stock, sku_code: second.code, price: 100, cost: 0 },
  ]);
  vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
  const onCommitted = vi.fn();
  const { rerender } = render(<Harness onCommitted={onCommitted} />);
  fireEvent.click(await screen.findByText(sku.title));
  fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: "ОК" }));
  fireEvent.click(screen.getByText(second.title));
  fireEvent.click(screen.getByRole("button", { name: "ОК" }));
  fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]);
  await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Да, перенести (на согласование)" })[0]); });
  expect(screen.getByRole("alert")).toHaveTextContent("Результат остальных позиций не подтверждён");
  const retry = vi.mocked(api.addDealItem).mock.calls[1];
  rerender(<Harness dealId="d2" onCommitted={onCommitted} />);
  expect(api.requestApproval).not.toHaveBeenCalled();
  rerender(<Harness dealId="d1" onCommitted={onCommitted} />);
  await waitFor(() => expect(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]).toBeEnabled());
  await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]); });
  expect(api.addDealItem).toHaveBeenCalledTimes(3);
  expect(vi.mocked(api.addDealItem).mock.calls[2]).toEqual(retry);
  expect(api.requestApproval).toHaveBeenCalledExactlyOnceWith("d1", "deal.discount");
  expect(onCommitted).toHaveBeenCalledOnce();
});

function ScopeHarness({ scope, dealId }: { scope: string; dealId?: string }) {
  const picker = useProductPicker(true, scope);
  return <><output data-testid="scope-cart-count">{picker.rows.length}</output>
    <CatalogPickerModal state={picker} dealId={dealId} onClose={vi.fn()} /></>;
}

function ConfirmedHarness() {
  const picker = useProductPicker(true, "d1");
  return <>
    <button onClick={() => picker.commitToDeal("d1", "Synthetic customer")}>Сохранить снимок</button>
    <output data-testid="confirmed-values">{picker.rows.map((row) => `${row.qty}:${picker.agreedPriceOf(row)}`).join(",")}</output>
    <CatalogPickerModal state={picker} dealId="d1" onClose={vi.fn()} />
  </>;
}

it("KB07 confirmed edit shows refusal without success mutation or another POST", async () => {
  vi.mocked(api.fetchStock).mockResolvedValue([stock]);
  render(<ConfirmedHarness />);
  const modal = within(screen.getByRole("dialog", { name: "Подбор товара", exact: true }));
  const cart = within(modal.getByText("Корзина", { exact: true }).closest("aside")!);
  const popup = () => within(modal.getByRole("button", { name: "ОК", exact: true }).parentElement!.parentElement!);
  fireEvent.click(await screen.findByText(sku.title));
  fireEvent.change(popup().getByLabelText("Количество товара"), { target: { value: "2" } });
  fireEvent.click(popup().getByRole("button", { name: "ОК", exact: true }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Сохранить снимок" })); });
  expect(api.addDealItem).toHaveBeenCalledOnce();
  expect(api.createPriceQuote).toHaveBeenCalledOnce();
  fireEvent.click(cart.getByTitle("Изменить количество/цену"));
  fireEvent.change(popup().getByLabelText("Количество товара"), { target: { value: "4" } });
  fireEvent.change(popup().getByLabelText("Цена за единицу"), { target: { value: "17" } });
  fireEvent.click(popup().getByRole("button", { name: "ОК", exact: true }));
  expect(popup().getByRole("alert")).toHaveTextContent("Позиция уже сохранена");
  expect(modal.queryByText(/✓ Подобрано/)).toBeNull();
  expect(modal.getByRole("button", { name: "ОК", exact: true })).toBeInTheDocument();
  expect(screen.getByTestId("confirmed-values")).toHaveTextContent("2:150");
  fireEvent.click(popup().getByRole("button", { name: "Отмена", exact: true }));
  expect(modal.queryByRole("button", { name: "ОК", exact: true })).toBeNull();
  fireEvent.click(cart.getByRole("button", { name: "+", exact: true }));
  fireEvent.click(cart.getByRole("button", { name: "−", exact: true }));
  expect(modal.getByRole("alert")).toHaveTextContent("Позиция уже сохранена");
  expect(screen.getByTestId("confirmed-values")).toHaveTextContent("2:150");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Сохранить снимок" })); });
  expect(api.addDealItem).toHaveBeenCalledOnce();
  expect(api.createPriceQuote).toHaveBeenCalledOnce();
});

it.each(["deal", "lead"])("KB05 stale quantity popup cannot add after %s context switch", async (kind) => {
  const { rerender } = render(<ScopeHarness scope={`${kind}:a`} dealId={kind === "deal" ? "a" : undefined} />);
  fireEvent.click(await screen.findByText(sku.title));
  const oldOk = screen.getByRole("button", { name: "ОК" });
  rerender(<ScopeHarness scope={`${kind}:b`} dealId={kind === "deal" ? "b" : undefined} />);
  expect(screen.queryByRole("button", { name: "ОК" })).toBeNull();
  fireEvent.click(oldOk);
  expect(screen.getByTestId("scope-cart-count")).toHaveTextContent("0");
  expect(api.addDealItem).not.toHaveBeenCalled();
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [sku] }));
  vi.mocked(api.fetchStock).mockResolvedValue([]);
  vi.mocked(api.addDealItem).mockResolvedValue(true);
  vi.mocked(api.createPriceQuote).mockResolvedValue(true);
  vi.mocked(api.requestApproval).mockResolvedValue(true);
});
afterEach(() => vi.unstubAllGlobals());

describe("CatalogPickerModal — цена подбора", () => {
  it("независимо редактирует цену и количество двух повторённых строк одного SKU", async () => {
    vi.mocked(api.fetchLastOrder).mockResolvedValue([100, 200].map((unit_price, index) => ({
      id: index + 9, sku_id: sku.id, code: sku.code, title: sku.title, unit: sku.unit,
      qty: index + 1, unit_price, last_price: 700, min_price: 500,
    })));
    render(<Harness />);
    await screen.findByText(sku.title);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Прошлый заказ" })); });
    fireEvent.click(screen.getAllByTitle("Изменить количество/цену")[0]);
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("100");
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "125.50" } });
    fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    fireEvent.click(screen.getAllByTitle("Изменить количество/цену")[1]);
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("200");
    expect(screen.getByLabelText("Количество товара")).toHaveValue("2");
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    fireEvent.click(screen.getAllByTitle("Изменить количество/цену")[0]);
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("125.5");
    expect(screen.getByLabelText("Количество товара")).toHaveValue("3");
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenNthCalledWith(1, "d1", 1, 3, 125.5, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(api.addDealItem).toHaveBeenNthCalledWith(2, "d1", 1, 4, 0, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
  });

  it.each(["125.50", "0"])("сохраняет ручную цену %s без складской базы", async (price) => {
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("");
    expect(screen.getByLabelText("Скидка, %")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: price } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    fireEvent.click(screen.getByTitle("Изменить количество/цену"));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue(String(Number(price)));
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, Number(price), expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
  });

  it("пустая правка известной цены остаётся null при повторном открытии и переносе", async () => {
    vi.mocked(api.fetchStock).mockResolvedValue([stock]);
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("150");
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    expect(screen.getAllByText(/Цена не подтверждена/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTitle("Изменить количество/цену"));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, null, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(api.createPriceQuote).not.toHaveBeenCalled();
  });

  it.each(["-1", "ошибка"])("не подтверждает некорректную цену %s", async (price) => {
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: price } });
    expect(screen.getByRole("alert")).toHaveTextContent("Укажите цену не меньше нуля");
    expect(screen.getByRole("button", { name: "ОК" })).toBeDisabled();
    expect(api.addDealItem).not.toHaveBeenCalled();
  });

  it("скидка рассчитывает net-цену один раз, перенос сохраняет её", async () => {
    vi.mocked(api.fetchStock).mockResolvedValue([stock]);
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Скидка, %"), { target: { value: "20" } });
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("120");
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, 120, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
  });

  it.each([
    [100.50, "5", 95.48],
    [100.50, "0", 100.50],
    [1.005, "0", 1.01],
    [10.075, "0", 10.08],
    [1.0049, "0", 1],
  ])("округляет скидку HALF_UP до копеек: %s минус %s%% → %s", async (base, discount, price) => {
    vi.mocked(api.fetchStock).mockResolvedValue([{ ...stock, price: base }]);
    render(<Harness />);
    fireEvent.click(await screen.findByText(sku.title));
    if (discount === "0") fireEvent.change(screen.getByLabelText("Скидка, %"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Скидка, %"), { target: { value: discount } });
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue(String(price));
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, price, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
  });

  it("при частичном переносе оставляет false/rejected строки и повторяет только их", async () => {
    const skus = [sku, { ...sku, id: 2, code: "B2", title: "Товар Б" }, { ...sku, id: 3, code: "C3", title: "Товар В" }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => skus }));
    const add = vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("network"));
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    for (const selected of skus) {
      fireEvent.click(await screen.findByText(selected.title));
      fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "125.50" } });
      fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    }
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("Подтверждено позиций: 1/3");
    expect(screen.getAllByTitle("Изменить количество/цену")).toHaveLength(2);
    expect(screen.getByRole("dialog", { name: "Подбор товара" })).toBeInTheDocument();
    expect(screen.queryByText(/✅ Перенесено/)).toBeNull();
    expect(onCommitted).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(add.mock.calls.map((args) => args[1])).toEqual([1, 2, 3, 2, 3]);
    expect(add).toHaveBeenNthCalledWith(4, "d1", 2, 1, 125.5, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(add).toHaveBeenNthCalledWith(5, "d1", 3, 1, 125.5, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("rejection снимает busy, сохраняет ввод и разрешает успешный повтор", async () => {
    let rejectWrite!: (error: Error) => void;
    vi.mocked(api.addDealItem).mockReturnValueOnce(new Promise<boolean>((_, reject) => { rejectWrite = reject; }));
    const onClose = vi.fn();
    const onCommitted = vi.fn();
    render(<Harness onClose={onClose} onCommitted={onCommitted} />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    const transfer = screen.getAllByRole("button", { name: "Перенести в документ" })[0];
    fireEvent.click(transfer);
    expect(transfer).toBeDisabled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => { rejectWrite(new Error("network")); });
    expect(screen.getByRole("alert")).toHaveTextContent("Подтверждено позиций: 0/1");
    expect(transfer).toBeEnabled();
    expect(onCommitted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTitle("Изменить количество/цену"));
    expect(screen.getByLabelText("Цена за единицу")).toHaveValue("0");
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    await act(async () => { fireEvent.click(transfer); });
    expect(api.addDealItem).toHaveBeenCalledTimes(2);
    expect(api.addDealItem).toHaveBeenLastCalledWith("d1", 1, 1, 0, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("повтор заказа с одним SKU по 100/200 оставляет отказавшую строку 200 и переносит её повторно", async () => {
    vi.mocked(api.fetchLastOrder).mockResolvedValue([100, 200].map((unit_price, index) => ({
      id: index + 9, sku_id: sku.id, code: sku.code, title: sku.title, unit: sku.unit,
      qty: 1, unit_price, last_price: 700, min_price: 500,
    })));
    vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    await screen.findByText(sku.title);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Прошлый заказ" })); });
    expect(screen.getAllByTitle("Изменить количество/цену")).toHaveLength(2);
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("Подтверждено позиций: 1/2");
    expect(screen.getByTitle("Изменить количество/цену")).toHaveTextContent("200.00 BYN");
    expect(onCommitted).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ" })[0]); });
    expect(vi.mocked(api.addDealItem).mock.calls.map((args) => args[3])).toEqual([100, 200, 200]);
    expect(api.addDealItem).toHaveBeenLastCalledWith("d1", 1, 1, 200, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("после частичного переноса сохраняет необходимость согласования уже перенесённых строк", async () => {
    const second = { ...sku, id: 2, code: "B2", title: "Товар Б" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [sku, second] }));
    vi.mocked(api.fetchStock).mockResolvedValue([
      { ...stock, price: 100, cost: 100 },
      { ...stock, sku_code: second.code, price: 100, cost: 0 },
    ]);
    vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    fireEvent.click(screen.getByText(second.title));
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]);
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Да, перенести (на согласование)" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("Подтверждено позиций: 1/2");
    expect(api.requestApproval).not.toHaveBeenCalled();
    expect(onCommitted).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]); });
    expect(vi.mocked(api.addDealItem).mock.calls.map((args) => args[1])).toEqual([1, 2, 2]);
    expect(api.requestApproval).toHaveBeenCalledExactlyOnceWith("d1", "deal.discount");
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it.each(["false", "rejection"])("повторяет только согласование после %s без повторного POST товара", async (failure) => {
    vi.mocked(api.fetchStock).mockResolvedValue([{ ...stock, cost: 145 }]);
    const approval = vi.mocked(api.requestApproval);
    if (failure === "false") approval.mockResolvedValueOnce(false);
    else approval.mockRejectedValueOnce(new Error("network"));
    const onCommitted = vi.fn();
    render(<Harness onCommitted={onCommitted} />);
    fireEvent.click(await screen.findByText(sku.title));
    fireEvent.click(screen.getByRole("button", { name: "ОК" }));
    fireEvent.click(screen.getAllByRole("button", { name: /Перенести → согласовать скидку/ })[0]);
    expect(api.addDealItem).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Да, перенести (на согласование)" })[0]); });
    expect(screen.getByRole("alert")).toHaveTextContent("не удалось отправить скидку на согласование");
    expect(screen.queryByText(/✅/)).toBeNull();
    expect(onCommitted).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: "Повторить согласование" })[0]).toBeEnabled();
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Повторить согласование" })[0]); });
    expect(api.addDealItem).toHaveBeenCalledTimes(1);
    expect(approval).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onCommitted).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/✅ Позиции сохранены · скидка отправлена/)).toBeInTheDocument();
  });

  it("Escape вызывает актуальное сохранение родителя", async () => {
    const first = vi.fn();
    const next = vi.fn();
    const { rerender } = render(<Harness onClose={first} />);
    await screen.findByText(sku.title);
    rerender(<Harness onClose={next} />);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(next).toHaveBeenCalledTimes(1));
    expect(first).not.toHaveBeenCalled();
  });
});
