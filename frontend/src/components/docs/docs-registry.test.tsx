import { configureCompany,render,resetCompany,waitForCompany } from "@/test/installation-company";
import { act,fireEvent,screen,waitFor,within } from "@testing-library/react";
import { beforeEach,beforeEach as configureBeforeEach,expect,it,vi } from "vitest";
import { DocsRegistry } from "./docs-registry";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

const request = vi.fn();
const organizations = [{ id: 1, name: "Организация А", unp: "111111111" }, { id: 2, name: "Организация Б", unp: "222222222" }];
const row = (id = 1, org = 1) => ({ id, organization_id: org, source: "1c", kind: "Document_СчетНаОплатуКлиенту", number: `SOURCE-${id}`, date: "2026-08-31", amount: "12.50", currency: "BYN", status: "SOURCE_ONLY", revision: 1, client: null, deal_id: null, original_available: false });
const page = (items = [row()], number = 1, total = 1, org = 1) => ({ organization_id: org, source: "1c", page: number, limit: 50, total, pages: Math.max(1, Math.ceil(total/50)), items, kinds: [row().kind] });
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const preview = { ...row(), explanation: "Предпросмотр данных 1С. Не является оригиналом.", source_sha256: "a".repeat(64), source_guid: "guid", native_posted: false, holds: ["FINANCIAL_POSTING_NOT_ACCEPTED"], line_page: 1, line_pages: 1, line_total: 1, lines: [{ name: "Аккумулятор", fields: { Количество: "2", Цена: "6.25" } }] };
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal("fetch", request);
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
async function selectOrganization(value = "1") {
  await waitForCompany();
  await configureCompany(value);
}

it("requires a verified installation company and never shows demo documents or role switching", async () => {
  resetCompany(0); render(<DocsRegistry />);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(request).not.toHaveBeenCalled();
  expect(screen.queryByText(/СЧ-0461|Я вошёл как/)).not.toBeInTheDocument();
});

it("paginates real results and resets to page one on submitted search", async () => {
  request.mockImplementation(async (path: string) => {
    if (path.endsWith("/organizations")) return response(organizations);
    const params = new URL(path, "https://example.invalid").searchParams;
    return response(page([row(params.get("page") === "2" ? 51 : 1)], Number(params.get("page")), params.get("q") ? 1 : 51));
  });
  render(<DocsRegistry />);
  await waitForCompany(); await selectOrganization(); await screen.findByText(/Показано 1–50/);
  fireEvent.click(screen.getAllByRole("button", { name: "Далее", exact: true })[0]);
  await screen.findByText(/Показано 51–51/);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: " SOURCE-1 " } });
  fireEvent.click(screen.getByRole("button", { name: "Найти", exact: true }));
  await screen.findByText(/Показано 1–1/);
  const query = new URL(request.mock.calls.at(-1)![0], "https://example.invalid").searchParams;
  expect(query.get("page")).toBe("1"); expect(query.get("q")).toBe("SOURCE-1");
});
it("opens source preview with contents and a clear original/posting distinction", async () => {
  request.mockImplementation(async (path: string) => response(path.endsWith("/organizations") ? organizations : path.includes("/source/1?") ? preview : page()));
  render(<DocsRegistry />);
  await waitForCompany(); await selectOrganization();
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
  request.mockImplementation(async (path: string) => path.endsWith("/organizations") ? response(organizations)
    : path.includes("/source/1?") ? response(confirmedPreview) : response(page([row()])));
  render(<DocsRegistry />);
  await waitForCompany(); await selectOrganization();
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  const dialog = await screen.findByRole("dialog");
  const link = await within(dialog).findByRole("link", { name: "Открыть связанную карточку" });
  expect(link).toHaveAttribute("href", "/erp/spravochniki/counterparty/42#counterparty-relationships");
});
it("drops an old response and preview when the organization changes", async () => {
  let finish!: (value: Response) => void;
  request.mockImplementation((path: string) => {
    if (path.endsWith("/organizations")) return Promise.resolve(response(organizations));
    if (path.includes("/organizations/1/")) return new Promise<Response>(resolve => { finish = resolve; });
    return Promise.resolve(response(page([row(99, 2)], 1, 1, 2)));
  });
  render(<DocsRegistry />);
  await waitForCompany(); await selectOrganization(); await selectOrganization("2");
  await screen.findByText(/SOURCE-99/);
  await act(async () => finish(response(page())));
  expect(screen.queryByText(/SOURCE-1$/)).not.toBeInTheDocument();
  expect(screen.getByText(/SOURCE-99/)).toBeInTheDocument();
});
it("uses the protected native original route and an empty iframe sandbox", async () => {
  const native = { ...row(7), source: "erp", kind: "invoice", status: "issued", deal_id: 9, original_available: true };
  request.mockImplementation(async (path: string) => path.endsWith("/original") ? new Response("<h1>Saved original</h1>", { headers: { "Content-Type": "text/html" } }) : response(path.endsWith("/organizations") ? organizations : { ...page(), source: "erp", items: [native] }));
  render(<DocsRegistry />);
  await waitForCompany(); await selectOrganization();
  fireEvent.click(screen.getByRole("button", { name: "Документы сделок ERP" }));
  fireEvent.click(await screen.findByRole("button", { name: "Открыть / предпросмотр" }));
  await waitFor(() => expect(screen.getByTitle("Оригинал документа SOURCE-7")).toHaveAttribute("srcdoc", "<h1>Saved original</h1>"));
  expect(screen.getByTitle("Оригинал документа SOURCE-7")).toHaveAttribute("sandbox", "");
  expect(screen.getByRole("link", { name: "Открыть документ в сделке" })).toHaveAttribute("href", "/crm/deals/9?org=1&invoice=7#document-register");
  expect(request.mock.calls.some(([path]) => path === "/api/sales/organizations/1/deals/9/documents/7/original")).toBe(true);
});
it("shows denied access as an error and does not claim an empty register", async () => {
  request.mockImplementation(async (path: string) => response(path.endsWith("/organizations") ? organizations : {}, path.endsWith("/organizations") ? 200 : 403));
  render(<DocsRegistry />);
  await waitForCompany(); await selectOrganization();
  expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
  expect(screen.queryByText("Документов по выбранным условиям нет.")).not.toBeInTheDocument();
});

configureBeforeEach(() => resetCompany(1));
