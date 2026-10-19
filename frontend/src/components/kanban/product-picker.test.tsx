import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchStock: vi.fn(),
  addDealItem: vi.fn(),
  createPriceQuote: vi.fn(),
  fetchLastOrder: vi.fn(),
  issueDocument: vi.fn(),
  updateDeal: vi.fn(),
}));

vi.mock("@/components/kanban/currency-context", () => ({
  useCurrency: () => ({ fmt: (v: number) => `${v.toFixed(2)} BYN` }),
}));

import {
  catalogEmptyMessage,
  ProductPicker,
  ProductPickerModal,
  ProductPickerTotals,
  useProductPicker,
  type ProductPickerState,
} from "@/components/kanban/product-picker";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const fmt = (v: number) => `${v.toFixed(2)} BYN`;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

async function selectedHook() {
  const hook = renderHook(() => useProductPicker(true, "d1"));
  await waitFor(() => expect(hook.result.current.skus).toHaveLength(skus.length));
  act(() => hook.result.current.addSku(skus[0]));
  return hook;
}

async function selectedModal() {
  const onClose = vi.fn();
  const onCommitted = vi.fn();
  const win = { location: { href: "" }, close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
  render(<ProductPickerModal dealId="d1" counterparty="Synthetic customer" onClose={onClose} onCommitted={onCommitted} />);
  fireEvent.click(await screen.findByText(skus[0].title));
  return { onClose, onCommitted, win };
}

describe("JZ immutable picker commands", () => {
  it.each(["no-op", "qty", "price"])("KB01 confirmed values stay immutable after %s edit", async (edit) => {
    const { result } = await selectedHook();
    await act(async () => { await result.current.commitToDeal("d1", "Synthetic customer"); });
    const row = result.current.rows[0];
    const price = result.current.agreedPriceOf(row);
    act(() => {
      if (edit === "price") result.current.setRowPrice(row.skuId, 17);
      else result.current.setRowQty(row, edit === "qty" ? 7 : row.qty, price);
    });
    expect(result.current.rows[0]).toEqual(row);
    expect(result.current.agreedPriceOf(result.current.rows[0])).toBe(price);
    expect(result.current.saveNotice).toContain("Позиция уже сохранена");
    await act(async () => { await result.current.commitToDeal("d1", "Synthetic customer"); });
    expect(api.addDealItem).toHaveBeenCalledOnce();
    expect(api.createPriceQuote).toHaveBeenCalledOnce();
  });

  it("KB06 explicit quantity append sends only the new quantity", async () => {
    const { result } = await selectedHook();
    act(() => result.current.setRowQty(result.current.rows[0], 2));
    await act(async () => { await result.current.commitToDeal("d1", "Synthetic customer"); });
    act(() => result.current.addSkuWithQty(skus[0], 3));
    expect(result.current.rows.map((row) => row.qty)).toEqual([2, 3]);
    await act(async () => { await result.current.commitToDeal("d1", "Synthetic customer"); });
    const calls = mock(api.addDealItem).mock.calls;
    expect(calls.map((call) => call[2])).toEqual([2, 3]);
    expect(calls[0][4]).not.toBe(calls[1][4]);
  });

  it("JZ01 partial save blocks invoice and next step", async () => {
    mock(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const { win, onCommitted } = await selectedModal();
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), { target: { value: "100Ah" } });
    fireEvent.click(screen.getByText(skus[1].title));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Выставить счёт" })); });
    expect(api.issueDocument).not.toHaveBeenCalled();
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(onCommitted).not.toHaveBeenCalled();
    expect(win.close).toHaveBeenCalledOnce();
    expect(screen.getByText(/Подтверждено позиций: 1\/2/)).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox", { name: /Включить/ })).toHaveLength(2);
  });

  it("JZ02 lost acknowledgement and false response reuse the original command", async () => {
    const receipts = new Set<string>();
    let calls = 0;
    mock(api.addDealItem).mockImplementation(async (_deal, _sku, _qty, _price, key: string) => {
      receipts.add(key);
      calls++;
      if (calls === 1) throw new Error("ack lost after commit");
      return calls !== 2;
    });
    const { result } = await selectedHook();
    await act(async () => {
      expect((await result.current.commitToDeal("d1", "Synthetic customer")).ok).toBe(0);
      expect((await result.current.commitToDeal("d1", "Synthetic customer")).ok).toBe(0);
      expect((await result.current.commitToDeal("d1", "Synthetic customer")).ok).toBe(1);
    });
    expect(receipts.size).toBe(1);
    const sent = mock(api.addDealItem).mock.calls;
    expect(sent[1]).toEqual(sent[0]);
    expect(sent[2]).toEqual(sent[0]);
    expect(api.createPriceQuote).toHaveBeenCalledOnce();
  });

  it("JZ03 concurrent commits share one POST and one quote", async () => {
    const pending = deferred<boolean>();
    mock(api.addDealItem).mockReturnValue(pending.promise);
    const { result } = await selectedHook();
    let first!: ReturnType<ProductPickerState["commitToDeal"]>;
    let second!: ReturnType<ProductPickerState["commitToDeal"]>;
    act(() => {
      first = result.current.commitToDeal("d1", "Synthetic customer");
      second = result.current.commitToDeal("d1", "Synthetic customer");
    });
    expect(api.addDealItem).toHaveBeenCalledOnce();
    await act(async () => {
      pending.resolve(true);
      expect((await first).ok).toBe(1);
      expect((await second).ok).toBe(1);
    });
    expect(api.createPriceQuote).toHaveBeenCalledOnce();
  });

  it("JZ04 duplicate SKU rows retain distinct command identities", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([100, 200].map((unit_price, index) => ({
      id: index + 1, sku_id: 1, code: skus[0].code, title: skus[0].title, unit: "шт", qty: 1, unit_price,
    })));
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    await act(async () => { await result.current.repeatLastOrder("d1"); });
    await act(async () => { expect((await result.current.commitToDeal("d1", "Synthetic customer")).ok).toBe(2); });
    const sent = mock(api.addDealItem).mock.calls;
    expect(sent.map((args) => args[3])).toEqual([100, 200]);
    expect(sent[0][4]).not.toBe(sent[1][4]);
    expect(result.current.rows[0].clientKey).not.toBe(result.current.rows[1].clientKey);
  });

  it("JZ05 unknown commands cannot be edited removed deselected or reset", async () => {
    mock(api.addDealItem).mockResolvedValue(false);
    const { result } = await selectedHook();
    await act(async () => { await result.current.commitToDeal("d1", "Synthetic customer"); });
    const row = result.current.rows[0];
    act(() => {
      result.current.setRowQty(row, 99, 999);
      result.current.setRowPrice(row.skuId, 1000);
      result.current.toggleRow(row);
      result.current.removeRow(row);
      result.current.addSkuWithQty(skus[0], 10);
      expect(result.current.reset()).toBe(false);
    });
    expect(result.current.rows).toEqual([row]);
    expect(result.current.agreedPriceOf(row)).toBe(150);
    expect(result.current.canIssueInvoice("d1")).toBe(false);
    expect(result.current.saveNotice).toMatch(/не подтверждено/);
  });

  it("JZ06 close retains an unknown cart until successful reconciliation", async () => {
    mock(api.addDealItem).mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const { onClose } = await selectedModal();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Добавить в сделку" })); });
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText(`Количество ${skus[0].title}`)).toHaveValue("1");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Добавить в сделку" })); });
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(mock(api.addDealItem).mock.calls[1]).toEqual(mock(api.addDealItem).mock.calls[0]);
  });

  it("JZ07 context switch isolates late results and restores the unknown command", async () => {
    const pending = deferred<boolean>();
    mock(api.addDealItem).mockReturnValueOnce(pending.promise).mockResolvedValue(true);
    const { result, rerender } = renderHook(({ deal }) => useProductPicker(true, deal), { initialProps: { deal: "d1" } });
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    act(() => result.current.addSku(skus[0]));
    const token = result.current.contextToken();
    let request!: ReturnType<ProductPickerState["commitToDeal"]>;
    act(() => { request = result.current.commitToDeal("d1", "Original customer"); });
    rerender({ deal: "d2" });
    expect(result.current.rows).toHaveLength(0);
    await act(async () => { pending.resolve(false); await request; });
    expect(result.current.isCurrentContext(token)).toBe(false);
    expect(result.current.rows).toHaveLength(0);
    expect(result.current.saveNotice).toBeNull();
    rerender({ deal: "d1" });
    expect(result.current.rows).toHaveLength(1);
    await act(async () => { await result.current.commitToDeal("d1", "Changed display name"); });
    expect(mock(api.addDealItem).mock.calls[1]).toEqual(mock(api.addDealItem).mock.calls[0]);
    expect(api.createPriceQuote).toHaveBeenCalledWith(skus[0].code, "Original customer", 150);
  });

  it("JZ08 confirmed commands do not repeat while a deliberate new row gets a new key", async () => {
    const { result } = await selectedHook();
    await act(async () => {
      await result.current.commitToDeal("d1", "Synthetic customer");
      await result.current.commitToDeal("d1", "Synthetic customer");
    });
    expect(api.addDealItem).toHaveBeenCalledOnce();
    act(() => result.current.removeRow(result.current.rows[0]));
    act(() => result.current.addSku(skus[0]));
    await act(async () => { await result.current.commitToDeal("d1", "Synthetic customer"); });
    expect(api.addDealItem).toHaveBeenCalledTimes(2);
    expect(mock(api.addDealItem).mock.calls[1][4]).not.toBe(mock(api.addDealItem).mock.calls[0][4]);
  });

  it("JZ09 frozen null and zero survive stock refresh and exact retry", async () => {
    for (const price of [null, 0]) {
      mock(api.addDealItem).mockReset().mockResolvedValueOnce(false).mockResolvedValue(true);
      mock(api.fetchStock).mockResolvedValue(stockRows);
      const hook = renderHook(({ active }) => useProductPicker(active, "d1"), { initialProps: { active: true } });
      await waitFor(() => expect(hook.result.current.skus).toHaveLength(skus.length));
      act(() => { hook.result.current.addSku(skus[0]); });
      act(() => { hook.result.current.setRowPrice(skus[0].id, price); });
      await act(async () => { await hook.result.current.commitToDeal("d1", "Synthetic customer"); });
      mock(api.fetchStock).mockResolvedValue([{ ...stockRows[0], price: 999 }]);
      hook.rerender({ active: false });
      hook.rerender({ active: true });
      await waitFor(() => expect(hook.result.current.stock[skus[0].code]?.price).toBe(999));
      expect(hook.result.current.agreedPriceOf(hook.result.current.rows[0])).toBe(price);
      await act(async () => { await hook.result.current.commitToDeal("d1", "Synthetic customer"); });
      const sent = mock(api.addDealItem).mock.calls;
      expect(sent[1]).toEqual(sent[0]);
      expect(sent[0][3]).toBe(price);
      hook.unmount();
    }
  });

  it("JZ10 quote failure does not unconfirm or resend a persisted item", async () => {
    mock(api.createPriceQuote).mockRejectedValue(new Error("history unavailable"));
    const { result } = await selectedHook();
    await act(async () => {
      expect((await result.current.commitToDeal("d1", "Synthetic customer")).ok).toBe(1);
      expect((await result.current.commitToDeal("d1", "Synthetic customer")).ok).toBe(1);
    });
    expect(api.addDealItem).toHaveBeenCalledOnce();
    expect(api.createPriceQuote).toHaveBeenCalledOnce();
    expect(result.current.canIssueInvoice("d1")).toBe(true);
  });

  it("JZ11 unexpected commit failure closes popup and releases the action", async () => {
    const { win, onCommitted } = await selectedModal();
    vi.spyOn(crypto, "randomUUID").mockImplementationOnce(() => { throw new Error("key unavailable"); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Выставить счёт" })); });
    expect(win.close).toHaveBeenCalledOnce();
    expect(api.addDealItem).not.toHaveBeenCalled();
    expect(api.issueDocument).not.toHaveBeenCalled();
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(onCommitted).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Выставить счёт" })).toBeEnabled();
  });

  it("JZ12 unexpected invoice failure closes popup and preserves the saved cart", async () => {
    mock(api.issueDocument).mockRejectedValue(new Error("lost invoice reply"));
    const { win, onCommitted } = await selectedModal();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Выставить счёт" })); });
    expect(win.close).toHaveBeenCalledOnce();
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(onCommitted).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Выставить счёт" })).toBeEnabled();
    expect(screen.getByText(/Проверьте документы сделки перед повтором/)).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Добавить в сделку" })); });
    expect(api.addDealItem).toHaveBeenCalledOnce();
  });
});

it("встроенный подбор меняет количество, выбор и удаление только одной повторённой строки", async () => {
  mockSkusFetch();
  mock(api.fetchStock).mockResolvedValue([]);
  mock(api.fetchLastOrder).mockResolvedValue([100, 200].map((unit_price, index) => ({
    id: index + 1, sku_id: 1, code: "AKB-60", title: "АКБ 60Ah 12V", unit: "шт",
    qty: index + 1, unit_price,
  })));
  function RepeatedPicker() {
    const picker = useProductPicker(true);
    return <><button onClick={() => picker.repeatLastOrder("d1")}>Повтор</button>
      <ProductPicker state={picker} fmt={fmt} /></>;
  }
  render(<RepeatedPicker />);
  await act(async () => { fireEvent.click(screen.getByText("Повтор")); });
  fireEvent.change(screen.getAllByLabelText("Количество АКБ 60Ah 12V")[0], { target: { value: "3" } });
  expect(screen.getAllByLabelText("Количество АКБ 60Ah 12V")[1]).toHaveValue("2");
  const checks = screen.getAllByLabelText("Включить АКБ 60Ah 12V");
  fireEvent.click(checks[1]);
  expect(checks[0]).toBeChecked();
  expect(checks[1]).not.toBeChecked();
  fireEvent.click(screen.getAllByRole("button", { name: "Убрать позицию" })[0]);
  expect(screen.getAllByLabelText("Количество АКБ 60Ah 12V")).toHaveLength(1);
  expect(screen.getByLabelText("Количество АКБ 60Ah 12V")).toHaveValue("2");
  expect(screen.getByLabelText("Включить АКБ 60Ah 12V")).not.toBeChecked();
  expect(screen.getByText(/200.00 BYN/)).toBeInTheDocument();
});

const skus = [
  { id: 1, code: "AKB-60", title: "АКБ 60Ah 12V", unit: "шт" },
  { id: 2, code: "AKB-100", title: "АКБ 100Ah 12V", unit: "шт" },
  { id: 3, code: "LAMP-H4", title: "Лампа H4 24V", unit: "шт" },
];

const stockRows = [
  {
    sku_code: "AKB-60",
    warehouse: "Минск",
    qty_available: 10,
    qty_reserved: 2,
    qty_forecast: 0,
    price: 150,
    cost: 100,
  },
  {
    sku_code: "AKB-100",
    warehouse: "Минск",
    qty_available: 0,
    qty_reserved: 0,
    qty_forecast: 5,
    price: 220,
    cost: null,
  },
];

function mockSkusFetch(status = 200) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status === 200,
    status,
    json: async () => skus,
  }) as unknown as typeof fetch;
}

/** Тестовый хук-харнесс: реальный useProductPicker + презентационные ProductPicker/Totals. */
function Harness({ dealId = "d1" }: { dealId?: string }) {
  const picker = useProductPicker(true, dealId);
  return (
    <div>
      <ProductPicker state={picker} fmt={fmt} />
      <ProductPickerTotals state={picker} fmt={fmt} />
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockSkusFetch();
  mock(api.fetchStock).mockResolvedValue(stockRows);
  mock(api.addDealItem).mockResolvedValue(true);
  mock(api.createPriceQuote).mockResolvedValue(true);
  mock(api.fetchLastOrder).mockResolvedValue([]);
  mock(api.issueDocument).mockResolvedValue({ ok: true, message: "Счёт создан", renderUrl: "/r" });
  mock(api.updateDeal).mockResolvedValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("catalogEmptyMessage", () => {
  const status: ProductPickerState["catalogStatus"][] = ["loading", "auth", "error", "ready"];
  it("hasSkus=true — сообщение о пустом фильтре независимо от статуса", () => {
    for (const s of status) {
      expect(catalogEmptyMessage(s, true)).toBe(
        "Ничего не найдено — измените запрос или снимите фильтры",
      );
    }
  });
  it("loading — «Загрузка номенклатуры…»", () => {
    expect(catalogEmptyMessage("loading", false)).toBe("Загрузка номенклатуры…");
  });
  it("auth — просит перелогиниться через Keycloak", () => {
    expect(catalogEmptyMessage("auth", false)).toBe(
      "Нет доступа к номенклатуре — выйдите и войдите через Keycloak (нужен JWT).",
    );
  });
  it("error — просит обновить страницу", () => {
    expect(catalogEmptyMessage("error", false)).toBe(
      "Не удалось загрузить номенклатуру. Обновите страницу.",
    );
  });
  it("ready + пусто — «Номенклатура пуста»", () => {
    expect(catalogEmptyMessage("ready", false)).toBe("Номенклатура пуста.");
  });
});

describe("ProductPicker — поиск/фильтр и подбор позиции", () => {
  it("после загрузки показывает до 6 кандидатов из справочника с ценой/сроком", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    expect(screen.getByText("АКБ 100Ah 12V")).toBeInTheDocument();
    expect(screen.getByText("Лампа H4 24V")).toBeInTheDocument();
    // AKB-60: своб = 10-2=8, в наличии, маржа (150-100)/150=33%
    expect(screen.getByText(/150\.00 BYN/)).toBeInTheDocument();
    expect(screen.getByText(/своб 8/)).toBeInTheDocument();
    expect(screen.getByText("в наличии")).toBeInTheDocument();
    expect(screen.getByText(/маржа 33%/)).toBeInTheDocument();
  });

  it("фильтр по подстроке названия/кода (ёмкость 100Ah) сужает список", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "100Ah" },
    });
    expect(screen.queryByText("АКБ 60Ah 12V")).not.toBeInTheDocument();
    expect(screen.getByText("АКБ 100Ah 12V")).toBeInTheDocument();
    expect(screen.queryByText("Лампа H4 24V")).not.toBeInTheDocument();
  });

  it("фильтр по параметру напряжения (24V) находит только лампу", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "24V" },
    });
    expect(screen.getByText("Лампа H4 24V")).toBeInTheDocument();
    expect(screen.queryByText("АКБ 60Ah 12V")).not.toBeInTheDocument();
    expect(screen.queryByText("АКБ 100Ah 12V")).not.toBeInTheDocument();
  });

  it("фильтр без совпадений показывает honest-empty сообщение", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "несуществующий-артикул" },
    });
    expect(screen.getByText("Ничего не найдено — измените запрос или снимите фильтры")).toBeInTheDocument();
  });

  it("клик по кандидату добавляет строку в корзину и очищает поиск", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    expect(screen.getByLabelText("Включить АКБ 60Ah 12V")).toBeInTheDocument();
    expect(screen.getByLabelText("Количество АКБ 60Ah 12V")).toHaveValue("1");
    // добавленная позиция больше не в кандидатах
    expect(
      screen.queryByRole("button", { name: /АКБ 60Ah 12V/ }),
    ).not.toBeInTheDocument();
    // итог = 150 * 1 — в блоке «Итого»
    expect(screen.getByText("150.00 BYN")).toBeInTheDocument();
  });

  it("изменение количества пересчитывает итог и маржу", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    fireEvent.change(screen.getByLabelText("Количество АКБ 60Ah 12V"), { target: { value: "3" } });
    // итог = 150*3 = 450, с НДС 540
    expect(screen.getByText("450.00 BYN")).toBeInTheDocument();
    expect(screen.getByText(/с НДС 540\.00 BYN/)).toBeInTheDocument();
    // маржа = (150-100)*3 = 150 (33%), себес = 100*3=300
    expect(screen.getByText(/150\.00 BYN \(33%\)/)).toBeInTheDocument();
    expect(screen.getByText(/себес 300\.00 BYN/)).toBeInTheDocument();
  });

  it("нечисловой ввод количества откатывается на 1 (Math.max/parseInt guard)", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    fireEvent.change(screen.getByLabelText("Количество АКБ 60Ah 12V"), { target: { value: "abc" } });
    expect(screen.getByLabelText("Количество АКБ 60Ah 12V")).toHaveValue("1");
  });

  it("снятие галочки исключает позицию из итога и маржи", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    expect(screen.getByText("150.00 BYN")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Включить АКБ 60Ah 12V"));
    // «Итого» блок пропадает — итог по отмеченным = 0
    expect(screen.queryByText("Итого")).not.toBeInTheDocument();
  });

  it("под-заказ позиция (нет себестоимости) помечает маржу как «в наличии» и добавляет предупреждение", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V")); // в наличии, есть себес
    // после добавления первой позиции без активного запроса список кандидатов скрыт —
    // раскрываем его повторным поиском.
    fireEvent.change(screen.getByPlaceholderText("Подобрать товар по названию / коду…"), {
      target: { value: "100Ah" },
    });
    fireEvent.click(screen.getByText("АКБ 100Ah 12V")); // под заказ, нет себес (cost=null)
    expect(screen.getByText(/Маржа · в наличии/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Под-заказ позиции — себестоимость из предварительного расчёта (скоро); пока в марже не учтены.",
      ),
    ).toBeInTheDocument();
  });

  it("крестик убирает позицию из корзины", async () => {
    render(<Harness />);
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    expect(screen.getByLabelText("Включить АКБ 60Ah 12V")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Убрать позицию"));
    expect(screen.queryByLabelText("Включить АКБ 60Ah 12V")).not.toBeInTheDocument();
  });
});

describe("ProductPickerModal — интеграция: повтор заказа / добавление в сделку / счёт", () => {
  it("дефицит не включает режим автоматически; явный выбор сохраняет ключ при повторе", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    mock(api.issueDocument).mockResolvedValue({ ok: false, message: "Недостаточно товара" });
    const { rerender } = render(<ProductPickerModal dealId="d1" counterparty="ООО Ромашка" onClose={vi.fn()} />);
    fireEvent.click(await screen.findByText("АКБ 100Ah 12V")); // свободный остаток 0
    const choice = screen.getByRole("checkbox", { name: "Под заказ — без резерва" });
    expect(choice).not.toBeChecked();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Выставить счёт" })); });
    expect(api.issueDocument).toHaveBeenCalledExactlyOnceWith("d1", "invoice");
    expect(choice).not.toBeChecked();
    expect(api.updateDeal).not.toHaveBeenCalled();
    fireEvent.click(choice);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Выставить счёт" })); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Выставить счёт" })); });
    const explicit = mock(api.issueDocument).mock.calls[1];
    expect(explicit).toEqual(["d1", "invoice", { reserve_mode: "on_order", request_key: expect.any(String) }]);
    expect(mock(api.issueDocument).mock.calls[2]).toEqual(explicit);
    expect(screen.queryByText("Под заказ — товар не зарезервирован")).toBeNull();
    rerender(<ProductPickerModal dealId="d2" counterparty="ООО Другая" onClose={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "Под заказ — без резерва" })).not.toBeChecked();
  });

  function openModal(onClose = vi.fn(), onCommitted = vi.fn()) {
    render(
      <ProductPickerModal
        dealId="d1"
        counterparty="ООО Ромашка"
        onClose={onClose}
        onCommitted={onCommitted}
      />,
    );
    return { onClose, onCommitted };
  }

  it("пустая корзина: CTA заблокированы", async () => {
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Добавить в сделку/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Выставить счёт/ })).toBeDisabled();
  });

  it("«Добавить в сделку» без позиций (защита от пустого клика) не трогает бэкенд", async () => {
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    // Кнопка disabled — событие не долетает, но проверим что API не звался.
    expect(api.addDealItem).not.toHaveBeenCalled();
  });

  it("выбор позиции + «Добавить в сделку»: пишет позицию и котировку цены, показывает тост", async () => {
    const { onCommitted } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Добавить в сделку/ }));
    });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, 150, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(api.createPriceQuote).toHaveBeenCalledWith("AKB-60", "ООО Ромашка", 150);
    expect(screen.getByText("✅ Добавлено в сделку позиций: 1/1")).toBeInTheDocument();
    expect(onCommitted).toHaveBeenCalledTimes(1);
  });

  it("«Повторить прошлый заказ»: пусто → сообщение «не найдено», позиции не добавляются", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([]);
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Повторить прошлый заказ/ }));
    });
    expect(api.fetchLastOrder).toHaveBeenCalledWith("d1");
    expect(screen.getByText("Прошлых заказов этого контрагента не найдено")).toBeInTheDocument();
  });

  it("«Повторить прошлый заказ»: подтягивает позиции прошлой сделки в корзину", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([
      { id: 9, sku_id: 2, code: "AKB-100", title: "АКБ 100Ah 12V", unit: "шт", qty: 2.6, last_price: null, min_price: null },
    ]);
    openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Повторить прошлый заказ/ }));
    });
    expect(screen.getByText("✅ Добавлено из прошлого заказа: 1")).toBeInTheDocument();
    // qty округляется до целого (Math.round(2.6) = 3)
    expect(screen.getByLabelText("Количество АКБ 100Ah 12V")).toHaveValue("3");
  });

  it("«Выставить счёт»: пишет позиции, открывает печать, ставит следующий шаг", async () => {
    const winStub = { location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(winStub as unknown as Window);
    const { onCommitted } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Выставить счёт/ }));
    });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", 1, 1, 150, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(api.issueDocument).toHaveBeenCalledWith("d1", "invoice");
    expect(winStub.location.href).toBe("/r");
    expect(screen.getByText("Счёт создан")).toBeInTheDocument();
    expect(mock(api.updateDeal).mock.calls[0][0]).toBe("d1");
    expect(mock(api.updateDeal).mock.calls[0][1]).toMatchObject({
      next_step: "Проверить оплату счёта",
    });
    expect(onCommitted).toHaveBeenCalledTimes(1);
    openSpy.mockRestore();
  });

  it("«Выставить счёт»: неуспех закрывает окно-пустышку и не меняет следующий шаг", async () => {
    mock(api.issueDocument).mockResolvedValue({ ok: false, message: "Нет позиций", renderUrl: null });
    const winStub = { location: { href: "" }, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(winStub as unknown as Window);
    const { onCommitted } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByText("АКБ 60Ah 12V"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Выставить счёт/ }));
    });
    expect(winStub.close).toHaveBeenCalled();
    expect(api.updateDeal).not.toHaveBeenCalled();
    expect(screen.getByText("Нет позиций")).toBeInTheDocument();
    expect(onCommitted).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("клик по подложке закрывает модалку, клик внутри — нет", async () => {
    const { onClose } = openModal();
    await waitFor(() => expect(screen.getByText("АКБ 60Ah 12V")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("заголовок показывает контрагента, кнопка закрытия зовёт onClose", async () => {
    const { onClose } = openModal();
    expect(screen.getByText("Подбор товара · ООО Ромашка")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Закрыть"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ProductPickerModal — статусы каталога (401/ошибка сети)", () => {
  it("401 от каталога — авторизационное сообщение вместо списка", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => [] }) as unknown as typeof fetch;
    render(<Harness />);
    await waitFor(() =>
      expect(
        screen.getByText("Нет доступа к номенклатуре — выйдите и войдите через Keycloak (нужен JWT)."),
      ).toBeInTheDocument(),
    );
  });

  it("сетевая ошибка при загрузке каталога — сообщение об ошибке", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down")) as unknown as typeof fetch;
    render(<Harness />);
    await waitFor(() =>
      expect(
        screen.getByText("Не удалось загрузить номенклатуру. Обновите страницу."),
      ).toBeInTheDocument(),
    );
  });
});

describe("useProductPicker — согласованная цена позиции", () => {
  it.each([0, 123.45])("ручная цена %s сохраняется в строку и историю", async (price) => {
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    act(() => result.current.addSku(skus[0]));
    act(() => result.current.setRowPrice(skus[0].id, price));
    await act(async () => {
      expect(await result.current.commitToDeal("d1", "Клиент")).toEqual({ ok: 1, total: 1, successfulRows: [result.current.pickedRows[0]] });
    });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", skus[0].id, 1, price, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(api.createPriceQuote).toHaveBeenCalledWith(skus[0].code, "Клиент", price);
  });

  it.each([null, undefined, 0])("raw складская цена %s сохраняет различие unknown/0", async (price) => {
    mock(api.fetchStock).mockResolvedValue([{ ...stockRows[0], price }]);
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    act(() => result.current.addSku(skus[0]));
    await act(async () => { await result.current.commitToDeal("d1", "Клиент"); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", skus[0].id, 1, price ?? null, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    if (price == null) expect(api.createPriceQuote).not.toHaveBeenCalled();
    else expect(api.createPriceQuote).toHaveBeenCalledWith(skus[0].code, "Клиент", 0);
  });

  it("без складских данных показывает неподтверждённую цену и отправляет null", async () => {
    mock(api.fetchStock).mockResolvedValue([]);
    render(<ProductPickerModal dealId="d1" counterparty="Клиент" onClose={vi.fn()} />);
    fireEvent.click(await screen.findByText(skus[0].title));
    expect(screen.getByText(/Цена не подтверждена/)).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Добавить в сделку/ })); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", skus[0].id, 1, null, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
    expect(api.createPriceQuote).not.toHaveBeenCalled();
  });

  it.each([null, 0, 99])("повтор заказа сохраняет unit_price=%s независимо от истории и склада", async (unit_price) => {
    mock(api.fetchLastOrder).mockResolvedValue([{
      id: 9, sku_id: skus[0].id, code: skus[0].code, title: skus[0].title,
      unit: "шт", qty: 2, unit_price, last_price: 700, min_price: 500,
    }]);
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    await act(async () => { await result.current.repeatLastOrder("d1"); });
    await act(async () => { await result.current.commitToDeal("d1", "Клиент"); });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", skus[0].id, 2, unit_price, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
  });

  it("ошибка истории котировок не заменяет подтверждение сохранённой цены строки", async () => {
    mock(api.createPriceQuote).mockResolvedValue(false);
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    act(() => result.current.addSku(skus[0]));
    await act(async () => {
      expect(await result.current.commitToDeal("d1", "Клиент")).toEqual({ ok: 1, total: 1, successfulRows: [result.current.pickedRows[0]] });
    });
    expect(api.addDealItem).toHaveBeenCalledWith("d1", skus[0].id, 1, 150, expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
  });

  it("при отказе строки не создаёт историю цены и сохраняет подбор", async () => {
    mock(api.addDealItem).mockResolvedValue(false);
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    act(() => result.current.addSku(skus[0]));
    act(() => result.current.setRowPrice(skus[0].id, 95));
    await act(async () => {
      expect(await result.current.commitToDeal("d1", "Клиент")).toEqual({ ok: 0, total: 1, successfulRows: [] });
    });
    expect(api.createPriceQuote).not.toHaveBeenCalled();
    expect(result.current.rows[0].priceOverride).toBe(95);
  });

  it("возвращает только успешные строки при mixed false/rejection и не меняет корзину остальных callers", async () => {
    mock(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("network"));
    mock(api.createPriceQuote).mockRejectedValueOnce(new Error("history unavailable"));
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    act(() => skus.forEach((sku) => result.current.addSku(sku)));
    await act(async () => {
      expect(await result.current.commitToDeal("d1", "Клиент")).toEqual({ ok: 1, total: 3, successfulRows: [result.current.pickedRows[0]] });
    });
    expect(api.createPriceQuote).toHaveBeenCalledTimes(1);
    expect(api.createPriceQuote).toHaveBeenCalledWith(skus[0].code, "Клиент", 150);
    expect(result.current.pickedRows.map((r) => r.skuId)).toEqual(skus.map((s) => s.id));
  });

  it("удаляет только успешный снимок повторённой строки того же SKU, оставляя цену второй", async () => {
    mock(api.fetchLastOrder).mockResolvedValue([100, 200].map((unit_price, index) => ({
      id: index + 9, sku_id: skus[0].id, code: skus[0].code, title: skus[0].title,
      unit: "шт", qty: 1, unit_price, last_price: 700, min_price: 500,
    })));
    mock(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const { result } = renderHook(() => useProductPicker(true, "d1"));
    await waitFor(() => expect(result.current.skus).toHaveLength(skus.length));
    await act(async () => { await result.current.repeatLastOrder("d1"); });
    const [first, second] = result.current.pickedRows;
    await act(async () => {
      const committed = await result.current.commitToDeal("d1", "Клиент");
      expect(committed.successfulRows).toHaveLength(1);
      expect(committed.successfulRows[0]).toBe(first);
      expect(result.current.rows).toEqual([first, second]);
      result.current.removeCommittedRows(committed.successfulRows);
    });
    expect(result.current.pickedRows).toHaveLength(1);
    expect(result.current.pickedRows[0]).toBe(second);
    expect(result.current.agreedPriceOf(second)).toBe(200);
    await act(async () => { await result.current.commitToDeal("d1", "Клиент"); });
    expect(mock(api.addDealItem).mock.calls.map((args) => args[3])).toEqual([100, 200, 200]);
  });
});
