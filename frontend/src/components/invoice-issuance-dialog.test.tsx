import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InvoiceIssuanceDialog } from "./invoice-issuance-dialog";
import { command, preview, response, result } from "@/test/invoice-issuance-fixtures";
import { loadPending, savePending } from "@/lib/invoice-issuance-api";
import { ownershipCommand, saveOwnership } from "@/lib/deal-ownership-api";

const instance = { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Организация установки", unp: "190000007" } };
const items = [{ id: 11, code: "SKU", title: "Товар", qty: 2 }];
function mockApi({ failIssue = false, failLoad = false, free = "2.00" as string | null, empty = false, onOrder = false } = {}) {
  let lost = failIssue;
  const issued = onOrder ? { ...result, reservation_digest: null, document: { ...result.document, reserve_mode: "on_order", reserve_status: "unreserved" } } : result;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (failLoad) return response({}, 403);
    if (url === "/api/system/instance-organization") return response(instance);
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
  await screen.findByLabelText("Валюта");
  for (const [label, value] of [["Валюта", "BYN"], ["Дата счёта", "2026-09-10"], ["Действителен до", "2026-09-15"], ["Цена строки 11", "100.00"], ["Ставка строки 11", "0.00"], ["Основание цен и ставок", "Согласовано явно"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
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
  it("warns before closing unsaved invoice input by button or Escape", async () => {
    const fetch = mockApi(), close = vi.fn(), confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirm);
    render(<InvoiceIssuanceDialog dealId="1" onClose={close} />);
    fireEvent.change(await screen.findByLabelText("Валюта"), { target: { value: "BYN" } });
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Валюта")).toHaveValue("BYN");
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(close).toHaveBeenCalledWith(null);
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
  it("uses configured org and requires explicit dates, price and VAT with no 20% default", async () => {
    mockApi(); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    await screen.findByLabelText("Валюта");
    expect(screen.getByRole("region", { name: "Юрлицо установки" })).toHaveTextContent("Организация установки · УНП 190000007 · #7");
    expect(screen.queryByLabelText("Юрлицо", { selector: "select" })).toBeNull();
    expect(screen.getByLabelText("Ставка строки 11")).toHaveValue("");
    expect(screen.getByLabelText("Дата счёта")).toHaveValue("");
    expect(screen.getByText("Получить предпросмотр")).toBeDisabled();
  });
  it("shows 403 and does not report an empty deal", async () => {
    mockApi({ failLoad: true }); render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Юрлицо установки недоступно");
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
  it("keeps an uncertain issued command when the dialog closes", async () => {
    mockApi({ failIssue: true });
    const close = vi.fn(), confirm = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirm);
    render(<InvoiceIssuanceDialog dealId="1" onClose={close} />);
    await fill(); allocate();
    fireEvent.click(screen.getByText("Выпустить счёт и зарезервировать"));
    await screen.findByText(/Результат неизвестен/);
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(close).toHaveBeenCalledWith(null);
    expect(confirm).not.toHaveBeenCalled();
    expect(loadPending("1")).not.toBeNull();
  });
  it("reopens saved command despite a different requested draft, preserving original endpoint", async () => {
    const pending = command(); savePending(pending);
    saveOwnership(ownershipCommand("8", "1", { deal_id: 1, number: "D", counterparty: "Buyer", owner_id: null, documents: [] }, "Earlier ownership"));
    const fetch = mockApi(); render(<InvoiceIssuanceDialog dealId="1" documentId={99} onClose={vi.fn()} />);
    fireEvent.click(await screen.findByText("Повторить исходный запрос"));
    await screen.findByRole("link", { name: "Открыть оригинал" });
    expect(fetch.mock.calls.some(([url, init]) => url === pending.endpoint && init?.body === pending.body)).toBe(true);
    expect(fetch.mock.calls.some(([url]) => url.includes("/99/issue") || url.endsWith("/items"))).toBe(false);
    expect(fetch.mock.calls.some(([url]) => url.includes("ownership") || url.includes("client-binding") || url.includes("/document-register?"))).toBe(false);
  });
  it("blocks preview for an unbound converted deal without hidden ownership or invoice writes", async () => {
    const fetch = mockApi(), implementation = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, init) => url.includes("/document-register?") ? Promise.resolve(response({}, 404)) : url.endsWith("/ownership-preview")
      ? Promise.resolve(response({ assigned: false, snapshot: { deal_id: 1, number: "CRM-LEAD-1", counterparty: "Buyer", owner_id: null, documents: [] } })) : implementation(url, init));
    render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    await screen.findByLabelText("Валюта");
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
    await screen.findByLabelText("Валюта");
    for (const [label, value] of [["Валюта", "BYN"], ["Дата счёта", "2026-09-10"], ["Действителен до", "2026-09-15"], ["Цена строки 11", "100"], ["Ставка строки 11", "0"], ["Основание цен и ставок", "Согласовано явно"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    await prepare();
    fireEvent.click(screen.getByText("Получить предпросмотр"));
    await waitFor(() => expect(resolve).toBeDefined());
    view.rerender(<InvoiceIssuanceDialog dealId="2" onClose={vi.fn()} />);
    await act(async () => resolve(response(preview())));
    expect(screen.queryByText("Проверьте реквизиты и суммы")).toBeNull();
    await screen.findByLabelText("Валюта");
    expect(screen.getByRole("region", { name: "Юрлицо установки" })).toHaveTextContent("Организация установки · УНП 190000007 · #7");
    expect(screen.queryByLabelText("Юрлицо", { selector: "select" })).toBeNull();
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


describe("configured invoice company", () => {
  it("retries unavailable company before loading any deal data", async () => {
    const fetch = mockApi(), implementation = fetch.getMockImplementation()!;
    let unavailable = true;
    fetch.mockImplementation((url, init) => url === "/api/system/instance-organization" && unavailable ? Promise.resolve(response({}, 503)) : implementation(url, init));
    render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("не настроено или сервис недоступен");
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/system/instance-organization"]);
    unavailable = false;
    fireEvent.click(screen.getByText("Повторить загрузку"));
    await screen.findByLabelText("Валюта");
    expect(screen.getByRole("region", { name: "Юрлицо установки" })).toHaveTextContent("#7");
    expect(fetch.mock.calls.some(([url, init]) => url.includes("document-register/organizations") || init?.method === "POST")).toBe(false);
  });
  it("rejects malformed company without reading items or falling back to an accessible list", async () => {
    const fetch = mockApi(); fetch.mockResolvedValue(response({ ...instance, organization: { ...instance.organization, id: "7" } }));
    render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("некорректное юрлицо");
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/system/instance-organization"]);
    expect(screen.queryByLabelText("Валюта")).toBeNull();
  });
  it.each(["button", "escape"])("configured company alone allows pristine close by %s", async action => {
    mockApi(); const close = vi.fn(), confirm = vi.fn().mockReturnValue(false); vi.stubGlobal("confirm", confirm);
    render(<InvoiceIssuanceDialog dealId="1" onClose={close} />);
    await screen.findByLabelText("Валюта");
    if (action === "button") fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    else fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(close).toHaveBeenCalledWith(null); expect(confirm).not.toHaveBeenCalled();
  });
  it("a pure preparation read leaves the form pristine", async () => {
    const fetch = mockApi(), close = vi.fn(), confirm = vi.fn().mockReturnValue(false); vi.stubGlobal("confirm", confirm);
    render(<InvoiceIssuanceDialog dealId="1" onClose={close} />);
    fireEvent.click(await screen.findByText("Проверить принадлежность"));
    await screen.findByText("Продолжить к счёту");
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(close).toHaveBeenCalledWith(null); expect(confirm).not.toHaveBeenCalled();
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
  it("protects actual child preparation input when closing", async () => {
    const fetch = mockApi(), implementation = fetch.getMockImplementation()!;
    fetch.mockImplementation((url, init) => url.includes("/document-register?") ? Promise.resolve(response({}, 404)) : url.endsWith("/ownership-preview")
      ? Promise.resolve(response({ assigned: false, snapshot: { deal_id: 1, number: "D", counterparty: "Buyer", owner_id: null, documents: [] } })) : implementation(url, init));
    const close = vi.fn(), confirm = vi.fn().mockReturnValue(false); vi.stubGlobal("confirm", confirm);
    render(<InvoiceIssuanceDialog dealId="1" onClose={close} />);
    fireEvent.click(await screen.findByText("Проверить принадлежность")); await screen.findByRole("alert");
    fireEvent.click(screen.getByText("Подтвердить новую принадлежность"));
    fireEvent.change(await screen.findByLabelText("Основание принадлежности организации"), { target: { value: "Synthetic ownership proof" } });
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(confirm).toHaveBeenCalledOnce(); expect(close).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Основание принадлежности организации")).toHaveValue("Synthetic ownership proof");
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
  it("preserves and blocks a foreign invoice command before item reads", async () => {
    const pending = command(); pending.command.organization_id = 8; pending.body = JSON.stringify({ kind: "invoice", ...pending.command }); savePending(pending);
    const before = JSON.stringify(sessionStorage), fetch = mockApi();
    render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("не совпадает с юрлицом установки");
    expect(JSON.stringify(sessionStorage)).toBe(before);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/system/instance-organization"]);
    expect(screen.queryByText("Повторить исходный запрос")).toBeNull();
  });
  it("preserves foreign ownership without offering to switch company or claim again", async () => {
    saveOwnership(ownershipCommand("8", "1", { deal_id: 1, number: "D", counterparty: "Buyer", owner_id: null, documents: [] }, "Synthetic prior confirmation"));
    const before = JSON.stringify(sessionStorage), fetch = mockApi();
    render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("другой организации #8");
    expect(JSON.stringify(sessionStorage)).toBe(before);
    expect(screen.queryByText(/Вернуться к организации/)).toBeNull();
    expect(screen.getByText("Получить предпросмотр")).toBeDisabled();
    expect(fetch.mock.calls.some(([url, init]) => url.includes("ownership") || init?.method === "POST")).toBe(false);
  });
  it("does not read deal data after a late company response to a closed modal", async () => {
    const fetch = mockApi(); let resolve!: (value: ReturnType<typeof response>) => void;
    fetch.mockImplementation(() => new Promise(done => { resolve = done; }));
    const close = vi.fn(), view = render(<InvoiceIssuanceDialog dealId="1" onClose={close} />);
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" })); expect(close).toHaveBeenCalledWith(null); view.unmount();
    await act(async () => resolve(response(instance)));
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/api/system/instance-organization"]);
  });
  it("ignores old company responses across A to B to A scopes", async () => {
    const fetch = mockApi(), implementation = fetch.getMockImplementation()!;
    const resolvers: ((value: ReturnType<typeof response>) => void)[] = [];
    fetch.mockImplementation((url, init) => url === "/api/system/instance-organization" ? new Promise(done => resolvers.push(done)) : implementation(url, init));
    const view = render(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    view.rerender(<InvoiceIssuanceDialog dealId="2" onClose={vi.fn()} />);
    view.rerender(<InvoiceIssuanceDialog dealId="1" onClose={vi.fn()} />);
    expect(resolvers).toHaveLength(3);
    await act(async () => { resolvers[0](response(instance)); resolvers[1](response(instance)); });
    expect(fetch.mock.calls).toHaveLength(3); expect(screen.queryByLabelText("Валюта")).toBeNull();
    await act(async () => resolvers[2](response(instance)));
    await screen.findByLabelText("Валюта");
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/items")).map(([url]) => url)).toEqual(["/api/sales/deals/1/items"]);
    expect(screen.getByLabelText("Валюта")).toHaveValue("");
    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
});
