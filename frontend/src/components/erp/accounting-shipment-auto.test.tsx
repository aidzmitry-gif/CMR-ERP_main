import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingShipmentPreview } from "./accounting-shipment-preview";

afterEach(() => vi.unstubAllGlobals());
const key = "00000000-0000-4000-8000-000000000001", source = `wms:physical-shipment:1:${key}`;
const snapshot = { digest: "a".repeat(64), source_key: key, snapshot: { organization_id: 1, document_id: 27, operation_date: "2026-09-01", lines: [{ source: "line1", line_no: 7, warehouse: "W", sku_code: "A", qty: "1" }] } };
const configured = { buyer_account: "62", revenue_account: "90.1", vat_revenue_account: "90.2", vat_payable_account: "68.2", expense_account: "90.4" };
const accounts = ["41.2", ...Object.values(configured)].map(code => ({ code, title: code, required_dimensions: code === "90.4" ? ["order"] : [] }));
const props = { org: "1", source, accounts, date: "2026-09-01", policyId: 3, disabled: false, onDate: vi.fn() };
const basis = "b".repeat(64);
const reply = (data: unknown) => Promise.resolve({ ok: true, json: async () => data });
const result = { organization_id: 1, source, status: "preview", posted: false, confirmation_available: true, basis_digest: basis,
  net_byn: "20.00", vat_byn: "4.00", gross_byn: "24.00", mapping: [], postings: [{ posting: { lines: [{ account: "62", side: "debit", amount: "24.00", quantity: null, dimensions: {} }] } }] };
function resolved(body: string) {
  const command = JSON.parse(body);
  return { ...command, allocations: command.allocations.map((row: object) => ({ ...row, expense_account: configured.expense_account })),
    commercial_lines: command.commercial_lines.map((row: object) => ({ ...row, buyer_account: configured.buyer_account, revenue_account: configured.revenue_account, vat_revenue_account: configured.vat_revenue_account, vat_payable_account: configured.vat_payable_account })) };
}
function fill(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
async function complete() {
  await screen.findByLabelText("Партия 1");
  fireEvent.click(screen.getByLabelText("Использовать счета из учётной политики"));
  await screen.findByText("Счёт себестоимости 1: 90.4");
  for (const [label, value] of Object.entries({ "Дата первичного документа": "2026-09-01", "Содержание операции": "Отгрузка", "Основание признания выручки": "Договор", "Основание соответствия единиц": "Штуки", "Распределение стоимости": "cumulative_floor_last", "Округление НДС": "commercial_line_half_up", "Счёт запасов 1": "41.2", "Партия 1": "L", "Расход 1 · Заказ": "Z", "Без НДС, BYN · строка 7": "20.00", "Ставка НДС, % · строка 7": "20", "Основание НДС · строка 7": "Проверено", "Покупатель строки 7 · Контрагент": "Buyer", "Покупатель строки 7 · Договор": "C" })) fill(label, value);
}
function fetcher(preview?: (body: string) => unknown) {
  return vi.fn().mockImplementation((url: string, options?: { body: string }) => url.endsWith("/source") ? reply(snapshot)
    : url.includes("/auto-rules?") ? reply({ organization_id: 1, policy_id: 3, accounts: configured })
      : reply(preview?.(options!.body) ?? { ...result, resolved_command: resolved(options!.body) }));
}

it("resolves accounts without per-line account input and freezes automatic retry across parent scope changes", async () => {
  let confirmations = 0;
  const mock = fetcher();
  const ordinary = mock.getMockImplementation()!;
  mock.mockImplementation((url: string, options?: { body: string }) => {
    if (!url.endsWith("/auto-confirm")) return ordinary(url, options);
    if (++confirmations === 1) return Promise.reject(new Error("lost response"));
    return reply({ organization_id: 1, source, posted: true, basis_digest: basis, receipt_id: 4, entry_ids: [8] });
  });
  vi.stubGlobal("fetch", mock);
  const view = render(<AccountingShipmentPreview {...props} />);
  await complete();
  expect(screen.queryByLabelText("Покупатель · строка 7")).toBeNull();
  expect(screen.queryByLabelText("Счёт себестоимости 1")).toBeNull();
  fireEvent.click(screen.getByText("Рассчитать проводки отгрузки"));
  fireEvent.click(await screen.findByText("Подтвердить проводки отгрузки"));
  await screen.findByText("Повторить подтверждение");
  expect(screen.getByLabelText("Использовать счета из учётной политики")).toBeDisabled();
  const preview = mock.mock.calls.find(([url]) => url.endsWith("/auto-preview"))!;
  const input = JSON.parse(preview[1].body);
  expect(input.allocations[0]).not.toHaveProperty("expense_account");
  expect(input.commercial_lines[0]).not.toHaveProperty("buyer_account");
  expect(input.allocations[0]).toMatchObject({ account: "41.2", lot: "L", quantity: "1", expense_dimensions: { order: "Z" } });
  expect(input.commercial_lines[0]).toMatchObject({ net_amount: "20.00", vat_rate: "20", vat_basis: "Проверено", buyer_dimensions: { contract: "C" } });
  view.rerender(<AccountingShipmentPreview {...props} org="2" date="2026-09-02" />);
  fireEvent.click(screen.getByText("Повторить подтверждение"));
  await screen.findByRole("status", { name: "" });
  await waitFor(() => expect(confirmations).toBe(2));
  const calls = mock.mock.calls.filter(([url]) => url.endsWith("/auto-confirm"));
  expect(calls[0]).toEqual(calls[1]);
  expect(JSON.parse(calls[0][1].body)).toMatchObject({ ...resolved(preview[1].body), expected_basis_digest: basis });
});

it.each(["missing-command", "wrong-date", "wrong-account", "confirmation-held"])("withholds confirmation on %s", async kind => {
  const mock = fetcher(body => ({ ...result,
    ...(kind === "confirmation-held" ? { confirmation_available: false } : {}),
    ...(kind === "missing-command" ? {} : { resolved_command: { ...resolved(body),
      ...(kind === "wrong-date" ? { posting_date: "2026-09-02" } : {}),
      ...(kind === "wrong-account" ? { commercial_lines: [{ ...resolved(body).commercial_lines[0], buyer_account: "51" }] } : {}),
    } }),
  }));
  vi.stubGlobal("fetch", mock);
  render(<AccountingShipmentPreview {...props} />);
  await complete();
  fireEvent.click(screen.getByText("Рассчитать проводки отгрузки"));
  if (kind === "confirmation-held") await screen.findByRole("region", { name: "Расчёт отгрузки" });
  else expect(await screen.findByRole("alert")).toHaveTextContent("проверенную команду");
  expect(screen.queryByText("Подтвердить проводки отгрузки")).toBeNull();
});

it("does not accept late rules from another organization", async () => {
  let finish!: (value: unknown) => void;
  const mock = vi.fn().mockImplementation((url: string) => url.endsWith("/source") ? reply(snapshot) : new Promise(resolve => { finish = resolve; }));
  vi.stubGlobal("fetch", mock);
  const view = render(<AccountingShipmentPreview {...props} />);
  await screen.findByLabelText("Партия 1");
  fireEvent.click(screen.getByLabelText("Использовать счета из учётной политики"));
  view.rerender(<AccountingShipmentPreview {...props} org="2" />);
  await act(async () => finish(reply({ organization_id: 1, policy_id: 3, accounts: configured })));
  expect(screen.queryByText("Счёт себестоимости 1: 90.4")).toBeNull();
});
