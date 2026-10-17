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
  fireEvent.click(await screen.findByRole("button", { name: "Создать черновик исправления" }));

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

it("waits for journal recovery before enabling actions and keeps creation singleflight", async () => {
  const recoveryCallbacks: VoidFunction[] = [];
  const nativeQueueMicrotask = globalThis.queueMicrotask.bind(globalThis);
  vi.stubGlobal("queueMicrotask", (callback: VoidFunction) => {
    if (new Error().stack?.includes("procurement-posted-receipt.tsx")) recoveryCallbacks.push(callback);
    else nativeQueueMicrotask(callback);
  });

  const bodies: string[] = [];
  let resolvePost: ((value: ReturnType<typeof response>) => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === postedPath) return response(source);
    if (url === correctionPath && init?.method === "POST") {
      bodies.push(String(init.body));
      return await new Promise<ReturnType<typeof response>>((resolve) => { resolvePost = resolve; });
    }
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementPostedReceipt org="7" entry="42" />);
  expect(await screen.findByText("SUP-81 · версия 3")).toBeInTheDocument();
  await waitFor(() => expect(recoveryCallbacks).toHaveLength(1));
  expect(screen.getByText("Проверяем журнал ранее отправленного запроса…")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Создать черновик исправления" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Повторить тот же запрос" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);

  await act(async () => { recoveryCallbacks.shift()!(); });
  const createButton = await screen.findByRole("button", { name: "Создать черновик исправления" });
  act(() => {
    fireEvent.click(createButton);
    fireEvent.click(createButton);
  });
  await waitFor(() => expect(resolvePost).toBeDefined());
  expect(bodies).toHaveLength(1);
  const savedBody = JSON.parse(bodies[0]);
  expect(savedBody).toEqual({ key: expect.any(String), expected_version: 3, expected_entry_id: 42 });
  expect(sessionStorage.getItem("procurement-receipt-correction:v1:7:81")).toBe(JSON.stringify({
    org: "7", originalReceiptId: 81, expectedVersion: 3, expectedEntryId: 42,
    key: savedBody.key, body: bodies[0],
  }));

  await act(async () => { resolvePost!(response(correction(96, savedBody.key))); });
  expect(await screen.findByText("Черновик исправления № 96, версия 1, создан.")).toBeInTheDocument();
  expect(sessionStorage.getItem("procurement-receipt-correction:v1:7:81")).toBeNull();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});
