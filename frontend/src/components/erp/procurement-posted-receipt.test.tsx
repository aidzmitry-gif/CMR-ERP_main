import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ProcurementPostedReceipt } from "./procurement-posted-receipt";

vi.mock("next/link", () => ({ default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => <a href={href} {...props}>{children}</a> }));

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

const source = {
  organization_id: 7, receipt_id: 81, entry_id: 42, version: 3,
  document: { invoice_reference: "SUP-81", document_date: "2026-09-24", operation_date: "2026-09-24",
    supplier: "Поставщик", supplier_id: 19, supplier_unp: "190000001", contract: "D-1",
    warehouse: "Основной", explanation: "Поступление", items: [{
      sku: "SKU-1", lot: "LOT-1", quantity: "2.000000", net_amount: "100.00",
      vat_amount: "20.00", vat_rate: "20.00", vat_basis: "НДС 20%", order_id: 17,
    }] },
};
const response = (value: unknown, ok = true, status = 200) => ({ ok, status, json: async () => value });
const postedPath = "/api/procurement/organizations/7/receipt-postings/42";
const correctionPath = "/api/procurement/organizations/7/receipt-documents/81/correction-drafts";
const relation = { receipt_id: 81, version: 3, entry_id: 42 };
const correction = (id: number, key: string, extra: Record<string, unknown> = {}) => ({
  id, organization_id: 7, key, version: 1, status: "draft", posting: null, correction_of: relation,
  revisions: [{ version: 1, document: source.document }], ...extra,
});

it("creates a separate linked correction draft and returns to it through the register", async () => {
  let command: Record<string, unknown> | null = null;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === postedPath) return response(source);
    if (url === correctionPath && init?.method === "POST") {
      command = JSON.parse(String(init.body));
      return response(correction(92, String(command.key)));
    }
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementPostedReceipt org="7" entry="42" />);
  expect(await screen.findByText("SUP-81 · версия 3")).toBeInTheDocument();
  expect(screen.getByText(/Будет создан отдельный связанный черновик/)).toBeInTheDocument();
  expect(screen.getByText(/пока нельзя провести или передать в WMS/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Создать черновик исправления" }));

  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Черновик исправления № 92, версия 1, создан."));
  expect(command).toMatchObject({ expected_version: 3, expected_entry_id: 42 });
  expect(typeof command?.key).toBe("string");
  expect(screen.getByRole("link", { name: "Открыть черновик исправления в реестре накладных" })).toHaveAttribute(
    "href", "/erp/procurement/receipts?org=7&receipt=92",
  );
  expect(sessionStorage.getItem("procurement-receipt-correction:v1:7:81")).toBeNull();
});

it("retries an unknown creation result after reload with the exact saved key and body", async () => {
  const bodies: string[] = [];
  let postCount = 0;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === postedPath) return response(source);
    if (url === correctionPath && init?.method === "POST") {
      bodies.push(String(init.body));
      postCount += 1;
      if (postCount === 1) throw new TypeError("Network connection lost");
      return response(correction(93, JSON.parse(String(init.body)).key));
    }
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);

  const first = render(<ProcurementPostedReceipt org="7" entry="42" />);
  fireEvent.click(await screen.findByRole("button", { name: "Создать черновик исправления" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Результат запроса неизвестен");
  const saved = sessionStorage.getItem("procurement-receipt-correction:v1:7:81");
  expect(saved).not.toBeNull();
  const exactBody = bodies[0];
  first.unmount();

  render(<ProcurementPostedReceipt org="7" entry="42" />);
  expect(await screen.findByText(/Восстановлен неподтверждённый запрос/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить тот же запрос" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Черновик исправления № 93"));
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toBe(exactBody);
  expect(JSON.parse(bodies[1])).toEqual({ key: JSON.parse(saved!).key, expected_version: 3, expected_entry_id: 42 });
});

it("keeps the command and blocks navigation when the returned relation does not match", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === postedPath) return response(source);
    if (url === correctionPath && init?.method === "POST") return response(correction(94, JSON.parse(String(init.body)).key,
      { correction_of: { receipt_id: 81, version: 2, entry_id: 42 } }));
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementPostedReceipt org="7" entry="42" />);
  fireEvent.click(await screen.findByRole("button", { name: "Создать черновик исправления" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("не совпадает с юрлицом и исходной накладной");
  expect(screen.queryByRole("link", { name: "Открыть черновик исправления в реестре накладных" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Повторить тот же запрос" })).toBeInTheDocument();
  expect(sessionStorage.getItem("procurement-receipt-correction:v1:7:81")).not.toBeNull();
});

it("does not offer correction creation for a source response from another organization", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...source, organization_id: 8 })));
  render(<ProcurementPostedReceipt org="7" entry="42" />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("другого юрлица"));
  expect(screen.queryByRole("button", { name: "Создать черновик исправления" })).not.toBeInTheDocument();
});

it("keeps the exact command when the server returns another correction key", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === postedPath) return response(source);
    if (url === correctionPath && init?.method === "POST") return response(correction(95, crypto.randomUUID()));
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementPostedReceipt org="7" entry="42" />);
  fireEvent.click(await screen.findByRole("button", { name: "Создать черновик исправления" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("не совпадает с юрлицом и исходной накладной");
  expect(screen.queryByRole("link", { name: "Открыть черновик исправления в реестре накладных" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Повторить тот же запрос" })).toBeInTheDocument();
  expect(sessionStorage.getItem("procurement-receipt-correction:v1:7:81")).not.toBeNull();
});

it("fails closed before rendering malformed receipt lines", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...source, document: { ...source.document, items: [null] } })));
  render(<ProcurementPostedReceipt org="7" entry="42" />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("неполные исходные данные"));
  expect(screen.queryByRole("button", { name: "Создать черновик исправления" })).not.toBeInTheDocument();
});


it("recovers the saved command before exposing a create action and only retries its exact body", async () => {
  const journalKey = "procurement-receipt-correction:v1:7:81";
  const savedKey = crypto.randomUUID();
  const body = JSON.stringify({ key: savedKey, expected_version: 3, expected_entry_id: 42 });
  sessionStorage.setItem(journalKey, JSON.stringify({ org: "7", originalReceiptId: 81,
    expectedVersion: 3, expectedEntryId: 42, key: savedKey, body }));
  let resolveSource!: (value: typeof source) => void;
  const sourceReply = new Promise<typeof source>((resolve) => { resolveSource = resolve; });
  const bodies: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === postedPath) return { ok: true, status: 200, json: () => sourceReply };
    if (url === correctionPath && init?.method === "POST") {
      bodies.push(String(init.body));
      return response(correction(95, savedKey));
    }
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  let createVisibleDuringRecovery: boolean | null = null;
  const originalGet = Storage.prototype.getItem;
  const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, key: string) {
    if (key === journalKey && createVisibleDuringRecovery === null)
      createVisibleDuringRecovery = screen.queryByRole("button", { name: "Создать черновик исправления" }) !== null;
    return originalGet.call(this, key);
  });
  try {
    render(<ProcurementPostedReceipt org="7" entry="42" />);
    expect(screen.queryByRole("button", { name: "Создать черновик исправления" })).not.toBeInTheDocument();
    expect(bodies).toHaveLength(0);
    await act(async () => { resolveSource(source); });
    const retry = await screen.findByRole("button", { name: "Повторить тот же запрос" });
    expect(createVisibleDuringRecovery).toBe(false);
    expect(screen.queryByRole("button", { name: "Создать черновик исправления" })).not.toBeInTheDocument();
    expect(bodies).toHaveLength(0);
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Черновик исправления № 95"));
    expect(bodies).toEqual([body]);
    expect(sessionStorage.getItem(journalKey)).toBeNull();
  } finally { read.mockRestore(); }
});
