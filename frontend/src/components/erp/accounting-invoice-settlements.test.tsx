import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingInvoiceSettlements } from "./accounting-invoice-settlements";

afterEach(() => vi.unstubAllGlobals());
const receipt = { id: 11, direction: "receipt", amount: "123.45", bank_entry_id: 31, refund_of: null, evidence: "Платёжное поручение 44", snapshot: { bank: { entry_id: 31, digest: "bank-sha", amount: "123.45", direction: "receipt", operation_date: "2026-09-09", statement_reference: "Выписка 99 / строка 1", settlement_dimensions: { settlement_document: "sales:document:77" }, currency: "BYN" }, invoice: { version: 2, content_sha256: "invoice-sha", number: "СЧ-77", amount: "123.45", currency: "BYN" } } };
const register = { received: "123.45", refunded: "0.00", net_received: "123.45", cancellation_authorized: false, reconciliation_required: true, items: [receipt] };
const empty = { ...register, received: "0", refunded: "0", net_received: "0", items: [] };
const invoice = { id: 77, number: "СЧ-77", version: 2, deal_id: 8, amount: "123.45", status: "posted", currency: "BYN", counterparty: "Покупатель", issued_at: "2026-09-09", valid_until: null, superseded_by_id: null, available_for_settlement: true, unavailable_reason: null };
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
const failure = (status: number) => ({ ok: false, status, json: async () => ({ detail: "Server detail" }) });
function deferred() { let resolve!: (value: unknown) => void; return { promise: new Promise((r) => { resolve = r; }), resolve: (value: unknown) => resolve(value) }; }
function open(id = "77") { fireEvent.change(screen.getByLabelText("ID счёта"), { target: { value: id } }); fireEvent.click(screen.getByRole("button", { name: "Открыть расчёты счёта" })); }
function fill(amount = "123.45") {
  for (const [label, value] of [["ID банковской проводки", "31"], ["Сумма распределения", amount], ["Ключ распределения", "statement-99-row1-invoice77-part1"], ["Первичное основание", "Платёжное поручение 44"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

it("does not infer an organization or invoice; displays exact totals and primary evidence", async () => {
  const fetchMock = vi.fn().mockResolvedValue(ok(register)); vi.stubGlobal("fetch", fetchMock);
  const view = render(<AccountingInvoiceSettlements org="" />);
  expect(screen.getByLabelText("ID счёта")).toBeDisabled(); expect(fetchMock).not.toHaveBeenCalled();
  view.rerender(<AccountingInvoiceSettlements org="7" />); expect(fetchMock).not.toHaveBeenCalled(); open();
  await screen.findByText("Выписка: Выписка 99 / строка 1");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/sales/organizations/7/invoices/77/settlements");
  expect(screen.getByText("Основание: Платёжное поручение 44")).toBeInTheDocument();
  expect(screen.getByText("SHA-256 счёта: invoice-sha")).toBeInTheDocument();
  expect(screen.getByText("Хеш банковской проводки: bank-sha")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Итоги расчётов")).getAllByText("123.45 BYN")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: /отмен|аннулир/i })).not.toBeInTheDocument();
});

it.each(["0", "0.00", "-1", "1e2", "1,50", "1.001", "NaN", "Infinity", "1000000000000000000", " 1.00", "01.00"])("rejects non-exact or invalid amount %s before POST", async (amount) => {
  const fetchMock = vi.fn().mockResolvedValue(ok(register)); vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" />); open(); await screen.findByLabelText("Сумма распределения"); fill(amount);
  expect(screen.getByRole("button", { name: "Подтвердить распределение" })).toBeDisabled(); expect(fetchMock).toHaveBeenCalledOnce();
});

it("locks duplicate clicks and retries the identical exact decimal payload after network failure", async () => {
  const pending = deferred();
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(register)).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ok({ id: 12 })).mockResolvedValueOnce(ok(register)); vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" />); open(); await screen.findByLabelText("Сумма распределения"); fill("999999999999999999.99");
  const button = screen.getByRole("button", { name: "Подтвердить распределение" });
  act(() => { fireEvent.click(button); fireEvent.click(button); }); expect(fetchMock).toHaveBeenCalledTimes(2);
  await act(async () => pending.resolve({ ok: true, status: 200, json: async () => { throw new Error("network"); } }));
  await screen.findByRole("alert"); expect(screen.getByLabelText("Ключ распределения")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить с тем же ключом" }));
  await screen.findByText("Распределение № 12 подтверждено.");
  expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[2][1].body);
  expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ source_key: "statement-99-row1-invoice77-part1", bank_entry_id: 31, amount: "999999999999999999.99", refund_of: null, evidence: "Платёжное поручение 44" });
  expect(screen.getByRole("button", { name: "Повторить с тем же ключом" })).toBeDisabled();
});

it("requires an original receipt for refund and sends its allocation ID, not the bank ID", async () => {
  const refund = { ...receipt, id: 12, direction: "refund", amount: "20.00", bank_entry_id: 32, refund_of: 11 };
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(register)).mockResolvedValueOnce(ok({ id: 12 })).mockResolvedValueOnce(ok({ ...register, refunded: "20.00", net_received: "103.45", items: [receipt, refund] })); vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" />); open(); await screen.findByLabelText("Сумма распределения"); fill("20.00");
  fireEvent.change(screen.getByLabelText("Вид распределения"), { target: { value: "refund" } });
  expect(screen.getByRole("button", { name: "Подтвердить распределение" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Исходное поступление"), { target: { value: "11" } });
  fireEvent.change(screen.getByLabelText("ID банковской проводки"), { target: { value: "32" } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  await screen.findByText("Исходное поступление № 11");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ refund_of: 11, amount: "20.00", bank_entry_id: 32 });
  expect(screen.getByText("103.45 BYN")).toBeInTheDocument();
});

it.each([403, 409, 422])("keeps GET %s distinct from empty/zero totals", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(failure(status))); render(<AccountingInvoiceSettlements org="7" />); open();
  expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`);
  expect(screen.queryByLabelText("Итоги расчётов")).not.toBeInTheDocument(); expect(screen.queryByText(/Подтверждённых распределений/)).not.toBeInTheDocument();
});

it.each([403, 409, 422])("shows POST %s without replacing confirmed totals or reporting success", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(ok(register)).mockResolvedValueOnce(failure(status)));
  render(<AccountingInvoiceSettlements org="7" />); open(); await screen.findByLabelText("Сумма распределения"); fill(); fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`); expect(screen.getByLabelText("Итоги расчётов")).toHaveTextContent("123.45 BYN");
  expect(screen.queryByText(/Распределение № .* подтверждено/)).not.toBeInTheDocument();
});

it("does not promise cancellation for an empty register or a full refund", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(empty)).mockResolvedValueOnce(ok({ ...register, refunded: "123.45", net_received: "0.00" })); vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" />); open(); await screen.findByLabelText("Итоги расчётов");
  expect(screen.getByText(/Исторические оплаты требуют/)).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Обновить расчёты" })); await screen.findByText("0.00 BYN");
  expect(screen.getByText(/Отмена счёта недоступна/)).toBeInTheDocument(); expect(screen.queryByRole("button", { name: /отмен|аннулир/i })).not.toBeInTheDocument();
});

it.each(["invoice", "organization"])("ignores a late GET after switching %s", async (kind) => {
  const pending = deferred(); const fetchMock = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ok(empty)); vi.stubGlobal("fetch", fetchMock);
  const view = render(<AccountingInvoiceSettlements org="7" />); open();
  if (kind === "organization") view.rerender(<AccountingInvoiceSettlements org="8" />);
  open("88"); await screen.findByLabelText("Итоги расчётов");
  await act(async () => pending.resolve(ok(register)));
  expect(screen.queryByText("Выписка: Выписка 99 / строка 1")).not.toBeInTheDocument(); expect(screen.getByText(`Счёт ID 88 · юрлицо ${kind === "organization" ? "8" : "7"}`)).toBeInTheDocument();
});

it("ignores late POST success after an externally forced organization change", async () => {
  const pending = deferred(); const fetchMock = vi.fn().mockResolvedValueOnce(ok(register)).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ok(empty)); vi.stubGlobal("fetch", fetchMock);
  const view = render(<AccountingInvoiceSettlements org="7" />); open(); await screen.findByLabelText("Сумма распределения"); fill(); fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  view.rerender(<AccountingInvoiceSettlements org="8" />);
  open("88"); await screen.findByLabelText("Итоги расчётов"); await act(async () => pending.resolve(ok({ id: 100 })));
  expect(screen.queryByText(/Распределение № 100/)).not.toBeInTheDocument(); expect(fetchMock).toHaveBeenCalledTimes(3); expect(screen.getByLabelText("Ключ распределения")).toHaveValue("");
});

it("locks invoice navigation and new allocations until an uncertain POST is resolved", async () => {
  const changed = vi.fn();
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(register)).mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce(ok({ id: 100 })).mockResolvedValueOnce(ok(register));
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" onBusyChange={changed} />);
  open(); await screen.findByLabelText("Сумма распределения"); fill("10.00");
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  await screen.findByText("Connection lost");
  expect(screen.getByLabelText("ID счёта")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Найти счета" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Новое распределение" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Обновить расчёты" })).toBeDisabled();
  expect(changed).toHaveBeenLastCalledWith(true);
  open("88"); expect(screen.getByText("Счёт ID 77 · юрлицо 7")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить с тем же ключом" }));
  await screen.findByText("Распределение № 100 подтверждено.");
  expect(fetchMock.mock.calls[2][1].body).toBe(fetchMock.mock.calls[1][1].body);
  expect(changed).toHaveBeenLastCalledWith(false);
});

it.each([403, 404, 409, 422])("preserves an uncertain operation after retry rejection %s", async (status) => {
  const changed = vi.fn();
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(register)).mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce(failure(status)).mockResolvedValueOnce(ok({ id: 100 })).mockResolvedValueOnce(ok(register));
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" onBusyChange={changed} />);
  open(); await screen.findByLabelText("Сумма распределения"); fill("10.00");
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  await screen.findByText("Connection lost");
  fireEvent.click(screen.getByRole("button", { name: "Повторить с тем же ключом" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`);
  expect(screen.getByLabelText("Ключ распределения")).toBeDisabled();
  expect(screen.getByLabelText("ID счёта")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Обновить расчёты" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Новое распределение" })).toBeDisabled();
  expect(changed).toHaveBeenLastCalledWith(true);
  fireEvent.click(screen.getByRole("button", { name: "Повторить с тем же ключом" }));
  await screen.findByText("Распределение № 100 подтверждено.");
  expect(fetchMock.mock.calls[2][1].body).toBe(fetchMock.mock.calls[1][1].body);
  expect(fetchMock.mock.calls[3][1].body).toBe(fetchMock.mock.calls[1][1].body);
  expect(changed).toHaveBeenLastCalledWith(false);
});

it("keeps POST success distinct from a failed subsequent register refresh", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(register)).mockResolvedValueOnce(ok({ id: 12 })).mockResolvedValueOnce(failure(409)); vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" />); open(); await screen.findByLabelText("Сумма распределения"); fill(); fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  await screen.findByText("Распределение № 12 подтверждено."); expect(await screen.findByRole("alert")).toHaveTextContent("409:"); expect(screen.queryByLabelText("Итоги расчётов")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("searches literal invoice numbers, paginates and selects exact IDs while disabling unavailable rows", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(ok({ items: [invoice, { ...invoice, id: 78, available_for_settlement: false, unavailable_reason: "Нужен оригинал" }], next_after_id: 78 })).mockResolvedValueOnce(ok({ items: [{ ...invoice, id: 79 }], next_after_id: null })).mockResolvedValueOnce(ok(empty)); vi.stubGlobal("fetch", fetchMock);
  render(<AccountingInvoiceSettlements org="7" />); fireEvent.change(screen.getByLabelText("Номер счёта для поиска"), { target: { value: "СЧ-%" } }); fireEvent.click(screen.getByRole("button", { name: "Найти счета" }));
  expect(await screen.findByRole("button", { name: "Выбрать счёт ID 78" })).toBeDisabled(); expect(screen.getByText("Нужен оригинал")).toBeInTheDocument();
  expect(new URL(fetchMock.mock.calls[0][0], "https://test.invalid").searchParams.get("q")).toBe("СЧ-%");
  fireEvent.click(screen.getByRole("button", { name: "Ещё счета" })); fireEvent.click(await screen.findByRole("button", { name: "Выбрать счёт ID 79" }));
  await screen.findByLabelText("Итоги расчётов"); expect(fetchMock.mock.calls[1][0]).toContain("after_id=78"); expect(fetchMock.mock.calls[2][0]).toBe("/api/sales/organizations/7/invoices/79/settlements");
});

it("drops late search results after changing the query or organization", async () => {
  const oldQuery = deferred(), oldOrg = deferred(); const fetchMock = vi.fn().mockReturnValueOnce(oldQuery.promise).mockReturnValueOnce(oldOrg.promise); vi.stubGlobal("fetch", fetchMock);
  const view = render(<AccountingInvoiceSettlements org="7" />); fireEvent.click(screen.getByRole("button", { name: "Найти счета" }));
  fireEvent.change(screen.getByLabelText("Номер счёта для поиска"), { target: { value: "new" } }); await act(async () => oldQuery.resolve(ok({ items: [invoice], next_after_id: null })));
  expect(screen.queryByRole("button", { name: "Выбрать счёт ID 77" })).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Найти счета" })); view.rerender(<AccountingInvoiceSettlements org="8" />);
  await act(async () => oldOrg.resolve(ok({ items: [invoice], next_after_id: null }))); expect(screen.queryByRole("button", { name: "Выбрать счёт ID 77" })).not.toBeInTheDocument();
});

it("shows search access failure without claiming no invoices exist", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(failure(403))); render(<AccountingInvoiceSettlements org="7" />); fireEvent.click(screen.getByRole("button", { name: "Найти счета" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("403:"); expect(screen.queryByText("Счета по запросу не найдены.")).not.toBeInTheDocument();
});
