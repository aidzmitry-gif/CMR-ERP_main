import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProcurementCompanyDocuments } from "./procurement-company-documents";

const company = { id: 1, name: "Учебная организация", unp: "999999999" };
const json = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body, text: async () => JSON.stringify(body) });
const order = { id: 1, number: "PO-001", supplier: "Учебный поставщик", status: "draft", freight_byn: "12.00", lines: [{ id: 1, sku: "SKU-01", quantity: "3", goods_value_byn: "100.00" }] };
const page = (items = [order], next: number | null = null) => ({ organization_id: 1, items, next_after_id: next });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/system/instance-organization") return json({ configuration: "AIOS_SELLER_UNP", organization: company });
    if (url.includes("owned-sources")) return json(page());
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("автоматически показывает документы компании из настроек без выбора юрлица", async () => {
  render(<ProcurementCompanyDocuments />);
  await screen.findByText("PO-001 · Учебный поставщик");
  expect(screen.getByText("SKU-01 · количество 3 · стоимость 100.00 BYN")).toBeInTheDocument();
  expect(screen.getAllByRole("combobox")).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual(["/api/system/instance-organization", "/api/procurement/organizations/1/owned-sources?kind=order&after_id=0&q="]);
});

it("меняет вид документов сохраняя настроенную компанию", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).includes("kind=request") ? json({ organization_id: 1, items: [{ id: 2, number: "REQ-002", item: "Учебный товар", supplier: "Учебный поставщик", quantity: "2", planned_amount: "50.00", stage: "need" }], next_after_id: null }) as Response : original(url, options));
  render(<ProcurementCompanyDocuments />);
  await screen.findByText("PO-001 · Учебный поставщик");
  fireEvent.change(screen.getByLabelText("Вид документов"), { target: { value: "request" } });
  await screen.findByText("REQ-002 · Учебный поставщик");
  expect(screen.queryByText("PO-001 · Учебный поставщик")).not.toBeInTheDocument();
});

it("поиск кодирует строку и сбрасывает курсор на начало", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).includes("owned-sources") ? json(page([order], String(url).includes("after_id=0") ? 1 : null)) as Response : original(url, options));
  render(<ProcurementCompanyDocuments />);
  fireEvent.click(await screen.findByRole("button", { name: "Следующие документы" }));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("after_id=1"))).toBe(true));
  fireEvent.change(screen.getByLabelText("Поиск документов юрлица"), { target: { value: "Товар & деталь" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти" }));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.at(-1)?.[0]).toBe("/api/procurement/organizations/1/owned-sources?kind=order&after_id=0&q=" + encodeURIComponent("Товар & деталь")));
});

it("перелистывает документы и возвращается к первой странице", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).includes("owned-sources") ? json(String(url).includes("after_id=1") ? page([{ ...order, id: 2, number: "PO-002" }]) : page([order], 1)) as Response : original(url, options));
  render(<ProcurementCompanyDocuments />);
  fireEvent.click(await screen.findByRole("button", { name: "Следующие документы" }));
  await screen.findByText("PO-002 · Учебный поставщик");
  expect(screen.queryByText("PO-001 · Учебный поставщик")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "В начало списка" }));
  await screen.findByText("PO-001 · Учебный поставщик");
});

it("отклоняет страницу чужой организации без показа её данных", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).includes("owned-sources") ? json({ ...page(), organization_id: 2 }) as Response : original(url, options));
  render(<ProcurementCompanyDocuments />);
  expect(await screen.findByRole("alert")).toHaveTextContent("другое юрлицо");
  expect(screen.queryByText("PO-001 · Учебный поставщик")).not.toBeInTheDocument();
});

it.each([0, -1, "2"])("отклоняет невалидный курсор страницы %s", async (cursor) => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, options) => String(url).includes("owned-sources") ? json({ ...page(), next_after_id: cursor }) as Response : original(url, options));
  render(<ProcurementCompanyDocuments />);
  await screen.findByRole("alert");
  expect(screen.queryByText("PO-001 · Учебный поставщик")).not.toBeInTheDocument();
});

it("не запрашивает документы при недоступной организации", async () => {
  vi.mocked(fetch).mockResolvedValue(json({}, 403) as Response);
  render(<ProcurementCompanyDocuments />);
  await screen.findByRole("alert");
  expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toEqual(["/api/system/instance-organization"]);
});

it("игнорирует позднюю страницу предыдущего вида документов", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let resolve!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation((url, options) => {
    if (String(url).includes("kind=order")) return new Promise<Response>(done => { resolve = done; });
    if (String(url).includes("kind=request")) return Promise.resolve(json(page([])) as Response);
    return original(url, options);
  });
  render(<ProcurementCompanyDocuments />);
  await screen.findByText("Загрузка документов…");
  fireEvent.change(screen.getByLabelText("Вид документов"), { target: { value: "request" } });
  await screen.findByText("Подтверждённых документов по этому запросу нет.");
  await act(async () => resolve(json(page()) as Response));
  expect(screen.queryByText("PO-001 · Учебный поставщик")).not.toBeInTheDocument();
});
