import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DocsRegistry, OrganizationRegistry } from "./docs-registry";

const request = vi.fn();
const context = { configuration: "AIOS_SELLER_UNP", organization: { id: 1, name: "Организация А", unp: "111111111" } };
const row = (id = 1, org = 1) => ({ id, organization_id: org, source: "1c", kind: "Document_СчетНаОплатуКлиенту", number: `SOURCE-${id}`, date: "2026-08-31", amount: "12.50", currency: "BYN", status: "SOURCE_ONLY", revision: 1, client: null, deal_id: null, original_available: false });
const page = (items = [row()], number = 1, total = 1, org = 1) => ({ organization_id: org, source: "1c", page: number, limit: 50, total, pages: Math.max(1, Math.ceil(total/50)), items, kinds: [row().kind] });
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const preview = { ...row(), explanation: "Предпросмотр данных 1С. Не является оригиналом.", source_sha256: "a".repeat(64), source_guid: "guid", native_posted: false, holds: ["FINANCIAL_POSTING_NOT_ACCEPTED"], line_page: 1, line_pages: 1, line_total: 1, lines: [{ name: "Аккумулятор", fields: { Количество: "2", Цена: "6.25" } }] };
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("fetch", request);
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
async function waitForOrganization() {
  await screen.findByText("Организация А · УНП 111111111");
}

it("uses the installation company and never shows demo documents or role switching", async () => {
  let finish!: (value: Response) => void;
  request.mockImplementation((path: string) => path.endsWith("/instance-organization")
    ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(response(page())));
  render(<DocsRegistry />);
  expect(request).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("combobox", { name: "Организация" })).not.toBeInTheDocument();
  expect(screen.queryByText(/СЧ-0461|Я вошёл как/)).not.toBeInTheDocument();
  await act(async () => { finish(response(context)); });
  await screen.findByText(/SOURCE-1/);
  expect(request.mock.calls.some(([path]) => String(path).includes("/organizations/2/"))).toBe(false);
});

it("paginates real results and resets to page one on submitted search", async () => {
  request.mockImplementation(async (path: string) => {
    if (path.endsWith("/instance-organization")) return response(context);
    const params = new URL(path, "https://example.invalid").searchParams;
    return response(page([row(params.get("page") === "2" ? 51 : 1)], Number(params.get("page")), params.get("q") ? 1 : 51));
  });
  render(<DocsRegistry />); await waitForOrganization(); await screen.findByText(/Показано 1–50/);
  fireEvent.click(screen.getAllByRole("button", { name: "Далее", exact: true })[0]);
  await screen.findByText(/Показано 51–51/);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: " SOURCE-1 " } });
  fireEvent.click(screen.getByRole("button", { name: "Найти", exact: true }));
  await screen.findByText(/Показано 1–1/);
  const query = new URL(request.mock.calls.at(-1)![0], "https://example.invalid").searchParams;
  expect(query.get("page")).toBe("1"); expect(query.get("q")).toBe("SOURCE-1");
});
it("opens source preview with contents and a clear original/posting distinction", async () => {
  request.mockImplementation(async (path: string) => response(path.endsWith("/instance-organization") ? context : path.includes("/source/1?") ? preview : page()));
  render(<DocsRegistry />); await waitForOrganization();
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("Аккумулятор")).toBeInTheDocument();
  expect(within(dialog).getByText(/Не является оригиналом/)).toBeInTheDocument();
  expect(dialog.querySelector("iframe")).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть документ" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("links_source_preview_client_only_after_authorized_preview", async () => {
  const confirmedPreview = { ...preview, client: { id: 42, name: "Synthetic confirmed company" } };
  request.mockImplementation(async (path: string) => path.endsWith("/instance-organization") ? response(context)
    : path.includes("/source/1?") ? response(confirmedPreview) : response(page([row()])));
  render(<DocsRegistry />); await waitForOrganization();
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  const dialog = await screen.findByRole("dialog");
  const link = await within(dialog).findByRole("link", { name: "Открыть связанную карточку" });
  expect(link).toHaveAttribute("href", "/erp/spravochniki/counterparty/42#counterparty-relationships");
});
it("drops an old registry response when a new search is applied", async () => {
  let finish!: (value: Response) => void;
  request.mockImplementation((path: string) => {
    if (path.endsWith("/instance-organization")) return Promise.resolve(response(context));
    const query = new URL(path, "https://example.invalid").searchParams;
    return query.get("q") ? Promise.resolve(response(page([row(99)])))
      : new Promise<Response>(resolve => { finish = resolve; });
  });
  render(<DocsRegistry />); await waitForOrganization();
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "SOURCE-99" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти", exact: true }));
  await screen.findByText(/SOURCE-99/);
  await act(async () => finish(response(page())));
  expect(screen.queryByText(/SOURCE-1$/)).not.toBeInTheDocument();
  expect(screen.getByText(/SOURCE-99/)).toBeInTheDocument();
});

it("uses the protected native original route and an empty iframe sandbox", async () => {
  const native = { ...row(7), source: "erp", kind: "invoice", status: "issued", deal_id: 9, original_available: true };
  request.mockImplementation(async (path: string) => path.endsWith("/original") ? new Response("<h1>Saved original</h1>", { headers: { "Content-Type": "text/html" } }) : response(path.endsWith("/instance-organization") ? context : { ...page(), source: "erp", items: [native] }));
  render(<DocsRegistry />); await waitForOrganization();
  fireEvent.click(screen.getByRole("button", { name: "Документы сделок ERP" }));
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  await waitFor(() => expect(screen.getByTitle("Оригинал документа SOURCE-7")).toHaveAttribute("srcdoc", "<h1>Saved original</h1>"));
  expect(screen.getByTitle("Оригинал документа SOURCE-7")).toHaveAttribute("sandbox", "");
  expect(screen.getByRole("link", { name: "Открыть документ в сделке" })).toHaveAttribute("href", "/crm/deals/9?org=1&invoice=7#document-register");
  expect(request.mock.calls.some(([path]) => path === "/api/sales/organizations/1/deals/9/documents/7/original")).toBe(true);
});
it("shows denied access as an error and does not claim an empty register", async () => {
  request.mockImplementation(async (path: string) => response(path.endsWith("/instance-organization") ? context : {}, path.endsWith("/instance-organization") ? 200 : 403));
  render(<DocsRegistry />); await waitForOrganization();
  expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
  expect(screen.queryByText("Документов по выбранным условиям нет.")).not.toBeInTheDocument();
});

const realization = { ...row(), kind: "Document_РеализацияТоваровУслуг" };
const realizationPage = (items = [realization], number = 1, total = 1) => page(items, number, total);

it("keeps the realization source, type and start date on pagination, search and reset", async () => {
  request.mockImplementation(async (path: string) => {
    const query = new URL(path, "https://example.invalid").searchParams;
    return response(realizationPage([{ ...realization, id: query.get("page") === "2" ? 51 : 1 }], Number(query.get("page")), 51));
  });
  render(<OrganizationRegistry org="1" realizationOnly />);
  await screen.findByText(/Показано 1–50/);
  expect(screen.queryByRole("group", { name: "Источник документов" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Тип")).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Далее", exact: true })[0]);
  await screen.findByText(/Показано 51–51/);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: " SOURCE & 1 " } });
  fireEvent.submit(screen.getByRole("button", { name: "Найти", exact: true }).closest("form")!);
  await screen.findByText(/Показано 1–50/);
  const search = new URL(request.mock.calls.at(-1)![0], "https://example.invalid").searchParams;
  expect(search.get("q")).toBe("SOURCE & 1"); expect(search.get("page")).toBe("1");
  fireEvent.click(screen.getByRole("button", { name: "Сбросить", exact: true }));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(4));
  for (const [path] of request.mock.calls) {
    const query = new URL(path, "https://example.invalid").searchParams;
    expect(query.get("source")).toBe("1c");
    expect(query.get("kind")).toBe(realization.kind);
    expect(query.get("date_from")).toBe("2026-07-01");
  }
});

it.each(["", "2026-06-30"])("rejects the invalid realization start %s without a new request", async start => {
  request.mockResolvedValue(response(realizationPage()));
  render(<OrganizationRegistry org="1" realizationOnly />);
  await screen.findByText(/SOURCE-1/);
  fireEvent.change(screen.getByLabelText("Дата с"), { target: { value: start } });
  fireEvent.submit(screen.getByRole("button", { name: "Найти", exact: true }).closest("form")!);
  expect(await screen.findByRole("alert")).toHaveTextContent("не ранее 01.07.2026");
  expect(request).toHaveBeenCalledTimes(1);
});

it.each([
  { kind: "Document_РегламентнаяОперация" }, { date: "2026-06-30" }, { date: null },
  { date: "2026-07-32" }, { organization_id: 2 }, { source: "erp" },
])("rejects a mismatched realization page %j", async delta => {
  request.mockResolvedValue(response(realizationPage([{ ...realization, ...delta }])));
  render(<OrganizationRegistry org="1" realizationOnly />);
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: /№ SOURCE-1/ })).not.toBeInTheDocument();
  expect(screen.queryByText("Документов по выбранным условиям нет.")).not.toBeInTheDocument();
});

it.each([
  { kind: "Document_РегламентнаяОперация" }, { date: "2026-06-30" }, { revision: 2 },
  { number: "FOREIGN" }, { id: 2 }, { organization_id: 2 },
])("does not show unrelated preview content %j", async delta => {
  request.mockImplementation(async (path: string) => response(path.includes("/source/1?")
    ? { ...preview, kind: realization.kind, ...delta } : realizationPage()));
  render(<OrganizationRegistry org="1" realizationOnly />);
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByRole("alert");
  expect(within(dialog).queryByText("Аккумулятор")).not.toBeInTheDocument();
});

it.each([null, ""])("opens an unnumbered realization whose source number is %j", async number => {
  request.mockImplementation(async (path: string) => response(path.includes("/source/1?")
    ? { ...preview, kind: realization.kind, number } : realizationPage([{ ...realization, number: "Без номера" }])));
  render(<OrganizationRegistry org="1" realizationOnly />);
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("Аккумулятор")).toBeInTheDocument();
  expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
});

it("retries denied realization reads without falling back to an empty or CRM view", async () => {
  request.mockResolvedValueOnce(response({}, 403)).mockImplementation(async () => response(realizationPage()));
  render(<OrganizationRegistry org="1" realizationOnly />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
  fireEvent.click(screen.getByRole("button", { name: "Обновить", exact: true }));
  await screen.findByText(/SOURCE-1/);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(request.mock.calls.every(([path]) => !String(path).includes("/journal"))).toBe(true);
});

it("opens an exact realization preview and drops its delayed content after close", async () => {
  let finish!: (value: Response) => void;
  request.mockImplementation((path: string) => path.includes("/source/1?")
    ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(response(realizationPage())));
  render(<OrganizationRegistry org="1" realizationOnly />);
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Закрыть документ" }));
  await act(async () => finish(response({ ...preview, kind: realization.kind })));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Открыть / предпросмотр" }));
  await act(async () => finish(response({ ...preview, kind: realization.kind })));
  expect(await within(screen.getByRole("dialog")).findByText("Аккумулятор")).toBeInTheDocument();
});
