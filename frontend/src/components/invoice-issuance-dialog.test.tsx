import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InvoiceIssuanceDialog } from "./invoice-issuance-dialog";
import { command, preview, response, result } from "@/test/invoice-issuance-fixtures";
import { loadPending, savePending } from "@/lib/invoice-issuance-api";
import { ownershipCommand, saveOwnership } from "@/lib/deal-ownership-api";

const items = [{ id: 11, code: "SKU", title: "Товар", qty: 2 }];
function mockApi({ failIssue = false, failLoad = false, free = "2.00" as string | null, empty = false, onOrder = false } = {}) {
  let lost = failIssue;
  const issued = onOrder ? { ...result, reservation_digest: null, document: { ...result.document, reserve_mode: "on_order", reserve_status: "unreserved" } } : result;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (failLoad) return response({}, 403);
    if (url.includes("document-register/organizations")) return response([{ id: 7, name: "Юрлицо", unp: "123" }]);
    if (url.endsWith("/items")) return response(empty ? [] : items);
    if (url.endsWith("/ownership-preview")) return response({ assigned: true, snapshot: { deal_id: Number(url.split("/")[6]), number: "D", counterparty: "Buyer", owner_id: null, documents: [] } });
    if (url.includes("/document-register?")) return response({ organization_id: 7, deal_id: Number(url.split("/")[6]), items: [], next_after_id: null,
      client_identity: { status: "confirmed", counterparty_id: 12, snapshot: { id: 12, name: "Buyer", unp: "123", revision: 1, is_active: true, merged_into_id: null } },
      coverage: { sales_documents: "available", settlements: "separate_chief_register", shipments: "unavailable", tn_ttn: "not_connected" }, shipment_documents: [] });
    if (url.endsWith("/invoice-preview")) {
      const body = JSON.parse(init!.body as string); const p = preview();
      p.document_id = body.document_id ?? null; p.deal_id = Number(url.split("/")[4]);
      p.availability.rows[0].free = free; if (free === null) { p.availability.rows[0].physical = null; p.availability.basis_by_warehouse.W = { version: null, cutoff: null }; }
      return response(body.reserve_mode === "on_order" ? { ...p, reserve_mode: "on_order", availability: null } : p);
    }
    if (init?.method === "POST") {
      if (lost) { lost = false; throw new TypeError("response lost"); }
      return response({ ...issued, replayed: failIssue });
    }
    return response([issued.document]);
  });
  vi.stubGlobal("fetch", fetch); return fetch;
}
async function fill(mode = "stock") {
  await screen.findByLabelText("Юрлицо");
  for (const [label, value] of [["Юрлицо", "7"], ["Валюта", "BYN"], ["Дата счёта", "2026-09-10"], ["Действителен до", "2026-09-15"], ["Цена строки 11", "100.00"], ["Ставка строки 11", "0.00"], ["Основание цен и ставок", "Согласовано явно"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  await prepare();
  fireEvent.change(screen.getByLabelText("Режим выпуска"), { target: { value: mode } });
  fireEvent.click(screen.getByText("Получить предпросмотр"));
  await screen.findByText("Проверьте реквизиты и суммы");
}
async function prepare() {
  fireEvent.click(await screen.findByText("Проверить принадлежность"));
  fireEvent.click(await screen.findByText("Продолжить к счёту"));
}
function allocate() {
  fireEvent.change(screen.getByLabelText("Склад распределения 1"), { target: { value: "W" } });
  fireEvent.change(screen.getByLabelText("Основание полноты физического журнала"), { target: { value: "Проверен журнал" } });
  fireEvent.click(screen.getByRole("checkbox"));
}
beforeEach(() => sessionStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("invoice dialog", () => {
  it("requires explicit org, dates, price and VAT with no 20% default", async () => {
    mockApi(); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByLabelText("Юрлицо")).toHaveValue("");
    expect(screen.getByLabelText("Ставка строки 11")).toHaveValue("");
    expect(screen.getByLabelText("Дата счёта")).toHaveValue("");
    expect(screen.getByText("Получить предпросмотр")).toBeDisabled();
  });
  it("shows 403 and does not report an empty deal", async () => {
    mockApi({ failLoad: true }); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("403");
    expect(screen.queryByText(/В сделке нет товарных/)).toBeNull();
  });
  it("states service-only scope without sending issue", async () => {
    const fetch = mockApi({ empty: true }); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByText(/В сделке нет товарных/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
  it("renders exact parties and explicit known allocation then opens a saved original link", async () => {
    const fetch = mockApi(), close = vi.fn(); render(<InvoiceIssuanceDialog dealId="1" onClose={close} />);
    await fill();
    expect(screen.getByText(/Продавец: Точный продавец/)).toBeInTheDocument();
    expect(screen.getByText(/Покупатель: Связанный покупатель/)).toBeInTheDocument();
    expect(screen.getByText("Выпустить счёт и зарезервировать")).toBeDisabled();
    allocate(); fireEvent.click(screen.getByText("Выпустить счёт и зарезервировать"));
    const link = await screen.findByRole("link", { name: "Открыть оригинал" });
    expect(link).toHaveAttribute("href", "/api/sales/documents/22/render");
    const body = JSON.parse(fetch.mock.calls.find(([url, init]) => url.endsWith("/documents") && init?.method === "POST")![1]!.body as string);
    expect(body.allocations).toEqual([{ line_no: 1, warehouse: "W", qty: "2.00" }]);
    expect(body.pricing[0].vat_rate).toBe("0.00");
    fireEvent.click(screen.getByText("Готово")); expect(close).toHaveBeenCalledWith(result);
  });
  it("prepared non-chief deal reaches invoice preview without chief-only GET or POST", async () => {
    const fetch = mockApi(), implementation = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, init) => url.includes("ownership") || url.includes("client-binding") ? Promise.resolve(response({}, 403)) : implementation(url, init));
    render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />); await fill();
    expect(screen.getByText("Проверьте реквизиты и суммы")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([url]) => url.includes("ownership") || url.includes("client-binding"))).toBe(false);
  });
  it.each([null, "-1.00", "0.00"])("blocks unavailable observed stock %s", async free => {
    mockApi({ free }); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />); await fill();
    if (free === null) expect(screen.getByRole("option", { name: /свободно неизвестно/ })).toBeDisabled();
    else allocate();
    expect(screen.getByText("Выпустить счёт и зарезервировать")).toBeDisabled();
  });
  it("invalidates preview and confirmation when prices change", async () => {
    mockApi(); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />); await fill(); allocate();
    fireEvent.change(screen.getByLabelText("Цена строки 11"), { target: { value: "101.00" } });
    expect(screen.queryByText("Проверьте реквизиты и суммы")).toBeNull();
    expect(screen.queryByText("Выпустить счёт и зарезервировать")).toBeNull();
  });
  it("lost response freezes full command and retry does not preview again", async () => {
    const fetch = mockApi({ failIssue: true }); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />); await fill(); allocate();
    fireEvent.click(screen.getByText("Выпустить счёт и зарезервировать"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Результат неизвестен");
    const pending = loadPending("1")!; expect(pending).not.toBeNull();
    expect(screen.queryByLabelText("Цена строки 11")).toBeNull();
    fireEvent.click(screen.getByText("Повторить исходный запрос"));
    await screen.findByText("Подтверждён результат исходного запроса.");
    const sends = fetch.mock.calls.filter(([url, init]) => url.endsWith("/documents") && init?.method === "POST");
    expect(sends).toHaveLength(2); expect(sends[0]).toEqual(sends[1]);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/invoice-preview"))).toHaveLength(1);
    expect(loadPending("1")).toBeNull();
  });
  it("reopens saved command despite a different requested draft, preserving original endpoint", async () => {
    const pending = command(); savePending(pending);
    saveOwnership(ownershipCommand("8", "1", { deal_id: 1, number: "D", counterparty: "Buyer", owner_id: null, documents: [] }, "Earlier ownership"));
    const fetch = mockApi(); render(<InvoiceIssuanceDialog dealId="1" documentId={99} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByText("Повторить исходный запрос"));
    await screen.findByRole("link", { name: "Открыть оригинал" });
    expect(fetch.mock.calls.some(([url, init]) => url === pending.endpoint && init?.body === pending.body)).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.includes("/99/issue"))).toBe(false);
    expect(fetch.mock.calls.some(([url]) => url.includes("ownership") || url.includes("client-binding") || url.includes("/document-register?"))).toBe(false);
  });
  it("blocks preview for an unbound converted deal without hidden ownership or invoice writes", async () => {
    const fetch = mockApi(), implementation = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, init) => url.includes("/document-register?") ? Promise.resolve(response({}, 404)) : url.endsWith("/ownership-preview")
      ? Promise.resolve(response({ assigned: false, snapshot: { deal_id: 1, number: "CRM-LEAD-1", counterparty: "Buyer", owner_id: null, documents: [] } })) : implementation(url, init));
    render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText("Юрлицо"), { target: { value: "7" } });
    expect(screen.getByText("Получить предпросмотр")).toBeDisabled();
    fireEvent.click(await screen.findByText("Проверить принадлежность"));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByText("Подтвердить новую принадлежность"));
    await screen.findByLabelText("Основание принадлежности организации");
    expect(screen.getByText("Получить предпросмотр")).toBeDisabled();
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    expect(screen.queryByText("Продолжить к счёту")).toBeNull();
  });
  it("discards late preview on context change", async () => {
    const fetch = mockApi(); let resolve!: (v: unknown) => void;
    const implementation = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, init) => url.endsWith("/invoice-preview") ? new Promise(r => { resolve = r; }) as ReturnType<typeof implementation> : implementation(url, init));
    const view = render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    await screen.findByLabelText("Юрлицо");
    for (const [label, value] of [["Юрлицо", "7"], ["Валюта", "BYN"], ["Дата счёта", "2026-09-10"], ["Действителен до", "2026-09-15"], ["Цена строки 11", "100"], ["Ставка строки 11", "0"], ["Основание цен и ставок", "Согласовано явно"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    await prepare();
    fireEvent.click(screen.getByText("Получить предпросмотр"));
    await waitFor(() => expect(resolve).toBeDefined());
    view.rerender(<InvoiceIssuanceDialog dealId="2" onClose={vi.fn()} />);
    await act(async () => resolve(response(preview())));
    expect(screen.queryByText("Проверьте реквизиты и суммы")).toBeNull();
    expect(await screen.findByLabelText("Юрлицо")).toHaveValue("");
  });
});


it("on-order reload retry preserves mode and sends no stock claim", async () => {
  const fetch = mockApi({ onOrder: true, failIssue: true, free: "0.00" });
  const first = render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
  await fill("on_order");
  expect(screen.queryByLabelText("Склад распределения 1")).toBeNull();
  expect(screen.queryByLabelText("Основание полноты физического журнала")).toBeNull();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText("Выпустить счёт под заказ"));
  await screen.findByText(/Результат неизвестен/);
  const original = loadPending("1")!;
  expect(original.command.reserve_mode).toBe("on_order");
  expect(original.command.allocations).toEqual([]);
  expect(original.command.journal_complete).toBeUndefined();
  expect(original.command.evidence).toBeUndefined();
  first.unmount();
  render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
  await screen.findByText("Под заказ — без резерва");
  fireEvent.click(screen.getByText(/Повторить исходный запрос/));
  await screen.findByRole("link", { name: "Открыть оригинал" });
  expect(screen.getByText(/выпущен; под заказ — товар не зарезервирован/)).toBeInTheDocument();
  const writes = fetch.mock.calls.filter(([url, init]) => url.endsWith("/documents") && init?.method === "POST");
  expect(writes).toHaveLength(2);
  expect(writes[0][1]!.body).toBe(writes[1][1]!.body);
});
