import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingPurchase } from "./accounting-purchase";

afterEach(() => vi.unstubAllGlobals());
const props = { org: "7", accounts: [{ code: "41.1", title: "Товары", category: "asset", cash: false, quantity_tracking: true }, { code: "18", title: "НДС", category: "asset", cash: false, quantity_tracking: false }, { code: "60", title: "Поставщики", category: "liability", cash: false, quantity_tracking: false }], policyId: 4, date: "2026-09-01", onDate: vi.fn(), onPosted: vi.fn() };
function fill() {
  for (const [label, value] of [["Источник поступления", "invoice1"], ["Накладная", "INV1"], ["Поставщик", "supplier1"], ["Договор поставки", "contract1"], ["Склад поступления", "warehouse1"], ["Счёт поставщика", "60"], ["Счёт входного НДС", "18"], ["Содержание поступления", "Товары по накладной"], ["Счёт запасов 1", "41.1"], ["Номенклатура 1", "sku1"], ["Партия 1", "lot1"], ["Количество 1", "2.000001"], ["Стоимость без НДС 1", "9007199254740993.01"], ["Ставка НДС % 1", "20"], ["Сумма НДС 1", "1801439850948198.60"], ["Основание НДС 1", "synthetic"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
it("confirms exactly the reviewed document without losing decimal precision", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 5, lines: [] }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingPurchase {...props} />);
  fill();
  fireEvent.click(screen.getByText("Рассчитать поступление"));
  fireEvent.click(await screen.findByText("Подтвердить поступление"));
  await screen.findByText("Поступление № 5 проведено.");
  expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
  const body = JSON.parse(fetchMock.mock.calls[1][1].body);
  expect(body.items[0].net_amount).toBe("9007199254740993.01");
  expect(body.items[0].quantity).toBe("2.000001");
  expect(body.policy_id).toBe(4);
});
it("invalidates preview on line edits and encodes explicit zero VAT as null", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ lines: [] }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingPurchase {...props} />);
  fill();
  fireEvent.click(screen.getByText("Рассчитать поступление"));
  await screen.findByText("Подтвердить поступление");
  fireEvent.change(screen.getByLabelText("Счёт входного НДС"), { target: { value: "none" } });
  for (const label of ["Ставка НДС % 1", "Сумма НДС 1"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "0" } });
  expect(screen.queryByText("Подтвердить поступление")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Рассчитать поступление"));
  await screen.findByText("Подтвердить поступление");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).vat_account).toBeNull();
  fireEvent.click(screen.getByText("Добавить позицию"));
  expect(screen.queryByText("Подтвердить поступление")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Номенклатура 2")).toHaveValue("");
});
it("ignores a late preview after the posting date changes", async () => {
  let resolve!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise((done) => { resolve = done; })));
  const view = render(<AccountingPurchase {...props} />);
  fill();
  fireEvent.click(screen.getByText("Рассчитать поступление"));
  view.rerender(<AccountingPurchase {...props} date="2026-10-01" />);
  await act(async () => { resolve({ ok: true, json: async () => ({ lines: [] }) }); });
  expect(screen.queryByText("Подтвердить поступление")).not.toBeInTheDocument();
  expect(screen.getByText("Рассчитать поступление")).toBeEnabled();
});

it("refreshes the current list after a successful confirmation across a date change", async () => {
  let resolve!: (value: unknown) => void;
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ lines: [] }) }).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  vi.stubGlobal("fetch", fetchMock);
  const oldRefresh = vi.fn(), currentRefresh = vi.fn();
  const view = render(<AccountingPurchase {...props} onPosted={oldRefresh} />);
  fill();
  fireEvent.click(screen.getByText("Рассчитать поступление"));
  fireEvent.click(await screen.findByText("Подтвердить поступление"));
  view.rerender(<AccountingPurchase {...props} date="2026-09-04" onPosted={currentRefresh} />);
  await act(async () => { resolve({ ok: true, json: async () => ({ id: 55 }) }); });
  expect(currentRefresh).toHaveBeenCalledOnce();
  expect(oldRefresh).not.toHaveBeenCalled();
  expect(screen.queryByText("Подтвердить поступление")).not.toBeInTheDocument();
});
