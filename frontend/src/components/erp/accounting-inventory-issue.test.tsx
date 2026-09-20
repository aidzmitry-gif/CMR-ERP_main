import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingInventoryIssue } from "./accounting-inventory-issue";

afterEach(() => vi.unstubAllGlobals());
const accounts = [{ code: "41", title: "Goods", category: "asset", cash: false, quantity_tracking: true, required_dimensions: [] }, { code: "43", title: "Finished goods", category: "asset", cash: false, quantity_tracking: true, required_dimensions: [] }, { code: "90.4", title: "Cost", category: "expense", cash: false, quantity_tracking: false, required_dimensions: [] }];
const props = { org: "1", date: "2026-09-01", policyId: 1, accounts, onDate: vi.fn(), onBusyChange: vi.fn(), onPosted: vi.fn() };
const calculation = { cost: { basis_digest: "basis", book_quantity: "3.000000", book_value_byn: "10.00", remaining_quantity: "1.500000", remaining_value_byn: "5.00", evidence: [{ entry_id: 2, line_id: 3, source: "receipt", source_version: 1, amount_byn: "10.00", quantity: "3.000000" }] }, digest: "posting", posting: { lines: [{ side: "debit", account: "90.4", amount: "5.00", quantity: null, dimensions: {} }, { side: "credit", account: "41", amount: "5.00", quantity: "1.500000", dimensions: { lot: "LOT" } }] } };
function fill(sale = false) {
  for (const [label, value] of [["Идентификатор основания", "ISSUE-1"], ["Склад партии", "W"], ["Номенклатура партии", "SKU"], ["Партия", "LOT"], ["Количество списания", "1,5"], [sale ? "Содержание продажи" : "Содержание списания", "Test issue"], ["Счёт запасов", "41"], ["Счёт расходов", "90.4"]]) fireEvent.change(screen.getByLabelText(label === "Партия" ? /^Партия/ : label, { exact: true }), { target: { value } });
}

it("shows the complete zero-cost receipt and confirms without client source IDs", async () => {
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith("confirm")
    ? { kind: "quantity_only_receipt", receipt_id: 77 }
    : { kind: "quantity_only_receipt", posting: null, digest: "zero", cost: { ...calculation.cost, issue_quantity: "1.500000", issue_cost_byn: "0.00" },
      receipt: { zero_byn: true, source_layers: [{ entry_id: 11, line_id: 21, quantity: "1.000000" }, { entry_id: 12, line_id: 22, quantity: "0.500000" }] } } }));
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingInventoryIssue {...props} inventoryMethod="fifo" />);
  fill();
  fireEvent.click(screen.getByText("Рассчитать списание"));
  expect(await screen.findByText(/Количество 1.500000 отражается квитанцией/)).toBeInTheDocument();
  expect(screen.getByText(/операция № 11, строка № 21 · Количество 1.000000/)).toBeInTheDocument();
  expect(screen.getByText(/операция № 12, строка № 22 · Количество 0.500000/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Подтвердить списание"));
  expect(await screen.findByText("Запись списания № 77 зарегистрирована.")).toBeInTheDocument();
  const request = fetcher.mock.calls[1] as unknown as [string, RequestInit];
  expect(JSON.parse(String(request[1].body))).not.toHaveProperty("source_layers");
});

it.each([false, true])("offers finished-goods account 43 for %s", (sale) => {
  render(<AccountingInventoryIssue {...props} sale={sale} />);
  const codes = Array.from((screen.getByLabelText("Счёт запасов") as HTMLSelectElement).options).map((option) => option.value);
  expect(codes).toEqual(expect.arrayContaining(["41", "43"]));
});

it("shows all allocated inventory layers separately from accounting postings", async () => {
  const allocation = { ...calculation, cost: { ...calculation.cost, inventory_layers: [{ lot: "ZERO", quantity: "1.000000", amount_byn: "0.00", dimensions: { warehouse: "W", sku: "SKU" } }, { lot: "COST", quantity: "0.500000", amount_byn: "5.00", dimensions: { warehouse: "W", sku: "SKU" } }] } };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => allocation })));
  render(<AccountingInventoryIssue {...props} />);
  fill();
  fireEvent.click(screen.getByText("Рассчитать списание"));
  expect(await screen.findByText("Слои списания запасов")).toBeInTheDocument();
  expect(screen.getByText(/Партия ZERO · Количество 1.000000 · Себестоимость 0.00 BYN/)).toBeInTheDocument();
  expect(screen.getByText(/Партия COST · Количество 0.500000 · Себестоимость 5.00 BYN/)).toBeInTheDocument();
  expect(screen.getByText(/Кт 41 · 5.00 BYN · Количество 1.500000/)).toBeInTheDocument();
});

it("requires preview and retries confirmation with the same prepared body", async () => {
  let fail = true;
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith("confirm") && fail) throw new Error("Network failure");
    return { ok: true, json: async () => url.endsWith("confirm") ? { id: 7 } : calculation };
  });
  vi.stubGlobal("fetch", fetcher);
  const onPosted = vi.fn();
  render(<AccountingInventoryIssue {...props} onPosted={onPosted} />);
  fill();
  expect(screen.queryByText("Подтвердить списание")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Рассчитать списание"));
  fireEvent.click(await screen.findByText("Подтвердить списание"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Network failure");
  expect(screen.getByLabelText("Количество списания")).toHaveValue("1,5");
  fail = false;
  fireEvent.click(screen.getByText("Подтвердить списание"));
  expect(await screen.findByText("Бухгалтерское списание № 7 проведено.")).toBeInTheDocument();
  expect(onPosted).toHaveBeenCalledTimes(1);
  const first = fetcher.mock.calls[1] as unknown as [string, RequestInit];
  const second = fetcher.mock.calls[2] as unknown as [string, RequestInit];
  expect(first[1].body).toBe(second[1].body);
  expect(JSON.parse(String(first[1].body))).toMatchObject({ quantity: "1.5", basis_digest: "basis", digest: "posting" });
});

it("invalidates a calculation when form or posting date changes", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => calculation })));
  const view = render(<AccountingInventoryIssue {...props} />);
  fill();
  fireEvent.click(screen.getByText("Рассчитать списание"));
  await screen.findByText("Подтвердить списание");
  fireEvent.change(screen.getByLabelText("Количество списания"), { target: { value: "2" } });
  expect(screen.queryByText("Подтвердить списание")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Рассчитать списание"));
  await screen.findByText("Подтвердить списание");
  view.rerender(<AccountingInventoryIssue {...props} date="2026-09-02" />);
  expect(screen.queryByText("Подтвердить списание")).not.toBeInTheDocument();
});

it("shows a zero-value receipt honestly without a phantom posting or entry link", async () => {
  const zero = { kind: "quantity_only_receipt" as const, cost: { ...calculation.cost, issue_cost_byn: "0.00", evidence: [{ entry_id: null, line_id: null, receipt_id: 9, source: "zero", source_version: 1, amount_byn: "0.00", quantity: "0.500000", zero_value_disposal: true }] }, digest: "zero", posting: null, receipt: { source_layer: { entry_id: 2, line_id: 3, quantity: "0.500000" }, zero_byn: true } };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith("confirm") ? { kind: "quantity_only_receipt", receipt_id: 9, registration_token: 10 } : zero })));
  const onEntry = vi.fn();
  const onPosted = vi.fn();
  render(<AccountingInventoryIssue {...props} onEntry={onEntry} onPosted={onPosted} />); fill(); fireEvent.click(screen.getByText("Рассчитать списание"));
  await screen.findByText(/Себестоимость 0.00 BYN/);
  expect(screen.queryByText(/^Дт /)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Операция №/ })).not.toBeInTheDocument();
  expect(screen.getByText(/Остаток после: 1.500000/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Подтвердить списание"));
  expect(await screen.findByText("Запись списания № 9 зарегистрирована.")).toBeInTheDocument();
  expect(onEntry).not.toHaveBeenCalled();
  expect(onPosted).toHaveBeenCalledOnce();
});

it("allows FIFO to value a SKU across explicit lots", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ ...calculation, cost: { ...calculation.cost, method: "fifo" } }) }));
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingInventoryIssue {...props} inventoryMethod="fifo" />);
  for (const [label, value] of [["Идентификатор основания", "FIFO-1"], ["Склад партии", "W"], ["Номенклатура партии", "SKU"], ["Количество списания", "1"], ["Содержание списания", "FIFO issue"], ["Счёт запасов", "41"], ["Счёт расходов", "90.4"]]) fireEvent.change(screen.getByLabelText(label === "Партия" ? /^Партия/ : label, { exact: true }), { target: { value } });
  expect(screen.getByLabelText("Партия (необязательно)")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Рассчитать списание"));
  await screen.findByText(/Метод: ФИФО/);
  const call = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(JSON.parse(String(call[1].body)).lot).toBe("");
});

it("previews sale with exact VAT inputs, invalidates edits and confirms its frozen package", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ ...calculation, net_amount_byn: "20.00", vat_amount_byn: "4.00", gross_amount_byn: "24.00" }) }));
  vi.stubGlobal("fetch", fetcher);
  const saleAccounts = [...accounts, ...[["62", "asset"], ["90.1", "income"], ["90.2", "income"], ["68.2", "liability"]].map(([code, category]) => ({ code, category, title: code, cash: false, quantity_tracking: false, required_dimensions: [] }))];
  render(<AccountingInventoryIssue {...props} sale accounts={saleAccounts} />);
  fill(true);
  for (const [label, value] of [["Стоимость продажи без НДС, BYN", "20,00"], ["Ставка НДС, %", "20"], ["Основание применения НДС", "Approved basis"], ["Счёт покупателя", "62"], ["Счёт выручки", "90.1"], ["Счёт НДС из выручки", "90.2"], ["Счёт расчётов по НДС", "68.2"], ["Покупатель: Контрагент", "buyer"], ["Покупатель: Договор", "contract"], ["Покупатель: Документ расчётов", "sale"]]) fireEvent.change(screen.getByLabelText(label === "Партия" ? /^Партия/ : label, { exact: true }), { target: { value } });
  fireEvent.click(screen.getByText("Рассчитать продажу"));
  await screen.findByText("Подтвердить продажу");
  expect(screen.getByText(/К оплате: 24.00/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Ставка НДС, %"), { target: { value: "10" } });
  expect(screen.queryByText("Подтвердить продажу")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Рассчитать продажу"));
  fireEvent.click(await screen.findByText("Подтвердить продажу"));
  const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
  expect(calls[2][0]).toBe("/api/accounting/organizations/1/sales/confirm");
  expect(JSON.parse(String(calls[2][1].body))).toMatchObject({ net_amount: "20.00", vat_rate: "10", buyer_dimensions: { counterparty: "buyer", contract: "contract", settlement_document: "sale" }, basis_digest: "basis", digest: "posting" });
});

it.each(["account", "date"])("drops hidden revenue analytics when %s changes", async (mode) => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => calculation }));
  vi.stubGlobal("fetch", fetcher);
  const saleAccounts = [...accounts, ...["90.1.1", "90.1.2"].map((code) => ({ code, category: "income", title: code, cash: false, quantity_tracking: false, required_dimensions: code.endsWith("1") ? ["department"] : [] }))];
  const view = render(<AccountingInventoryIssue {...props} sale accounts={saleAccounts} />);
  fireEvent.change(screen.getByLabelText("Счёт выручки", { exact: true }), { target: { value: "90.1.1" } });
  fireEvent.change(screen.getByLabelText("Выручка: Подразделение"), { target: { value: "OLD-DEPARTMENT" } });
  if (mode === "account") fireEvent.change(screen.getByLabelText("Счёт выручки", { exact: true }), { target: { value: "90.1.2" } });
  else view.rerender(<AccountingInventoryIssue {...props} date="2026-09-02" sale accounts={saleAccounts.map((a) => ({ ...a, required_dimensions: [] }))} />);
  expect(screen.queryByLabelText("Выручка: Подразделение")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Рассчитать продажу"));
  const calls = fetcher.mock.calls as unknown as [string, RequestInit][];
  expect(JSON.parse(String(calls[0][1].body)).revenue_dimensions).toEqual({});
});
