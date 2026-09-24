import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ProcurementReceiptDrafts } from "./procurement-receipt-drafts";
import { ProcurementReceipts } from "./procurement-receipts";

afterEach(() => vi.unstubAllGlobals());

it("requires an explicit legal entity before opening supplier invoices", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => [
    { id: 7, name: "Белакб", unp: "123456789" },
  ] }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceipts />);
  expect(await screen.findByRole("option", { name: /Белакб/ })).toBeInTheDocument();
  expect(screen.getByLabelText("Юрлицо поступления")).toHaveValue("");
  expect(screen.getByText("Выберите юрлицо перед просмотром или созданием накладной.")).toBeInTheDocument();
  expect(screen.queryByText("Новая первичная накладная")).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("shows draft and posted invoices from every date in the procurement register", async () => {
  const document = (invoice_reference: string, supplier: string, document_date: string) => ({
    currency: "BYN", invoice_reference, document_date, operation_date: document_date,
    supplier, contract: "Contract", warehouse: "Warehouse", explanation: "Goods", items: [],
  });
  const rows = [
    { id: 2, version: 1, status: "posted", posting: { entry_id: 42, version: 1 },
      revisions: [{ version: 1, actor: "accountant", created_at: "2026-08-01", document: document("INV-OLD", "Acme", "2026-08-01") }] },
    { id: 3, version: 1, status: "draft", posting: null,
      revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: document("INV-NEW", "Beta", "2026-09-24") }] },
  ];
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("purchase-ownership") ? [] : rows }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceiptDrafts org="7" date="2026-09-24" />);
  expect(await screen.findByText("Показано 2 из 2 накладных выбранного юрлица за все даты.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /INV-OLD/ })).toHaveTextContent("2026-08-01 · Acme");
  expect(screen.getByText("Проведена · версия 1")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Открыть проведённую накладную" })).toHaveAttribute(
    "href", "/erp/procurement/receipts/posted/42?org=7",
  );
  expect(screen.getByText("Черновик · версия 1")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Поиск накладных"), { target: { value: "Acme" } });
  expect(screen.getByText("Показано 1 из 2 накладных выбранного юрлица за все даты.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /INV-NEW/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Статус накладной"), { target: { value: "draft" } });
  expect(screen.getByText("Накладных по выбранному фильтру нет.")).toBeInTheDocument();
});

it("requires a selected supplier and saves its directory snapshot in a new receipt", async () => {
  let submitted: Record<string, unknown> | null = null;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик из каталога", unp: "190000001" }], truncated: false,
    }) };
    if (init?.method === "POST") {
      submitted = JSON.parse(String(init.body));
      return { ok: true, json: async () => ({ id: 41, version: 1, status: "draft", posting: null,
        revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: submitted!.document }] }) };
    }
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Выберите поставщика накладной из справочника");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик из каталога · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  await waitFor(() => expect(submitted).not.toBeNull());
  expect(submitted!.document).toMatchObject({ supplier: "Поставщик из каталога", supplier_id: 19,
    supplier_unp: "190000001" });
  expect(await screen.findByText("Накладная № 41: сохранена версия 1.")).toBeInTheDocument();
  expect(screen.getByLabelText("Номер первичной накладной")).toBeInTheDocument();
});

it("warns before replacing an unsaved new receipt", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [] })));
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-UNSAVED" } });
  fireEvent.click(screen.getByRole("button", { name: "Новая первичная накладная" }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-UNSAVED");
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Новая первичная накладная" }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("");
});

it("keeps the legal entity when an unsaved receipt switch is cancelled", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("unlinked-primary") ? { rows: [], next_after_id: null } : url.endsWith("receipt-organizations") ? [
      { id: 7, name: "Белакб", unp: "123456789" }, { id: 8, name: "Второе ООО", unp: "987654321" },
    ] : [] })));
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<ProcurementReceipts initialOrganization="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-UNSAVED" } });
  fireEvent.change(screen.getByLabelText("Юрлицо поступления"), { target: { value: "8" } });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Юрлицо поступления")).toHaveValue("7");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-UNSAVED");
  confirm.mockReturnValue(true);
  fireEvent.change(screen.getByLabelText("Юрлицо поступления"), { target: { value: "8" } });
  expect(screen.getByLabelText("Юрлицо поступления")).toHaveValue("8");
});

it("closes a new receipt only after the server confirms its saved version", async () => {
  let releaseSave!: () => void;
  const savePending = new Promise<void>((resolve) => { releaseSave = resolve; });
  let rows: Record<string, unknown>[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик из каталога", unp: "190000001" }], truncated: false,
    }) };
    if (init?.method === "POST") {
      const saved = JSON.parse(String(init.body));
      await savePending;
      const row = { id: 41, version: 1, status: "draft", posting: null,
        revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: saved.document }] };
      rows = [row];
      return { ok: true, json: async () => row };
    }
    return { ok: true, json: async () => rows };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик из каталога · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-41" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-41");
  expect(screen.getByRole("button", { name: "Сохранить и закрыть" })).toBeDisabled();
  releaseSave();
  expect(await screen.findByText("Накладная № 41: сохранена версия 1, форма закрыта.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Номер первичной накладной")).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: /INV-41/ }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-41");
});

it("keeps an edited receipt open after the server rejects Save and Close", async () => {
  const original = {
    currency: "BYN", invoice_reference: "INV-OLD", document_date: "2026-09-24",
    operation_date: "2026-09-24", supplier: "Поставщик", supplier_id: 19,
    supplier_unp: "190000001", contract: "", warehouse: "", explanation: "", items: [],
  };
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: original }] };
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => init?.method === "PUT"
    ? { ok: false, status: 409, json: async () => ({ detail: "Version changed" }) }
    : { ok: true, json: async () => _url.includes("purchase-ownership") ? [] : [row] }));
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-EDIT" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Версия или ключ документа уже изменены");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-EDIT");
  expect(screen.getByRole("button", { name: "Сохранить и закрыть" })).toBeEnabled();
});

it.each([
  { caseName: "another receipt", returnedId: 42, returnedVersion: 2 },
  { caseName: "the old version", returnedId: 41, returnedVersion: 1 },
])("does not close when a successful HTTP response names $caseName", async ({ returnedId, returnedVersion }) => {
  const original = {
    currency: "BYN", invoice_reference: "INV-OLD", document_date: "2026-09-24",
    operation_date: "2026-09-24", supplier: "Поставщик", supplier_id: 19,
    supplier_unp: "190000001", contract: "", warehouse: "", explanation: "", items: [],
  };
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: original }] };
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => init?.method === "PUT"
    ? { ok: true, json: async () => ({ ...row, id: returnedId, version: returnedVersion,
      revisions: returnedVersion === 1 ? row.revisions : [...row.revisions,
        { version: 2, actor: "buyer", created_at: "2026-09-24", document: original }] }) }
    : { ok: true, json: async () => _url.includes("purchase-ownership") ? [] : [row] }));
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-EDIT" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Сервер не подтвердил сохранённую версию этой накладной");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-EDIT");
});

it("shows who changed receipt fields and their prior and new saved values", async () => {
  const first = {
    currency: "BYN", invoice_reference: "INV-41", document_date: "2026-09-23",
    operation_date: "2026-09-24", supplier: "Первый поставщик", supplier_id: 11,
    supplier_unp: "190000011", contract: "Договор А", warehouse: "Склад",
    explanation: "Товар", items: [{ order_id: null, sku: "AKB", unit: "шт",
      lot: "L1", quantity: "1.000000", net_amount: "100.00", vat_rate: "20.00",
      vat_amount: "20.00", vat_basis: "ОСН" }],
  };
  const second = { ...first, contract: "Договор Б", supplier: "Новый поставщик",
    supplier_id: 19, supplier_unp: "190000019",
    items: [{ ...first.items[0], quantity: "2.000000" }, { ...first.items[0], sku: "CHG",
      lot: "L2", vat_amount: "8.00" }] };
  const row = { id: 41, version: 2, status: "draft", posting: null, revisions: [
    { version: 1, actor: "Закупщик", created_at: "2026-09-23 10:00", document: first },
    { version: 2, actor: "Бухгалтер", created_at: "2026-09-24 11:00", document: second },
  ] };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("purchase-ownership") ? [] : [row] })));
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-41/ }));
  fireEvent.click(screen.getByText("История накладной № 41"));
  expect(screen.getByText("Версия 2 · Бухгалтер · 2026-09-24 11:00")).toBeInTheDocument();
  expect(screen.getByText("Договор накладной: было «Договор А», стало «Договор Б».")).toBeInTheDocument();
  expect(screen.getByText("Строка 1 · Количество: было «1.000000», стало «2.000000».")).toBeInTheDocument();
  expect(screen.getByText("Строка 2 · Сумма НДС: было «—», стало «8.00».")).toBeInTheDocument();
  expect(screen.getByText(/Поставщик: было «Первый поставщик · УНП 190000011 · ID 11»/)).toBeInTheDocument();
});
