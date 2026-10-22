import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  fetchStock: vi.fn(), fetchDealItems: vi.fn(), addDealItem: vi.fn(),
  createPriceQuote: vi.fn(), requestApproval: vi.fn(),
}));
const { currencyFormat } = vi.hoisted(() => ({ currencyFormat: vi.fn() }));
vi.mock("@/components/kanban/currency-context", () => ({ useCurrency: () => ({ fmt: currencyFormat }) }));

import * as api from "@/lib/api";
import { CrmProductCatalog } from "./crm-product-catalog";

const skus = [
  { id: 17, code: "BATTERY-A", title: "Учебная батарея А", unit: "шт" },
  { id: 18, code: "BATTERY-B", title: "Учебная батарея Б", unit: "шт" },
];
const deals = [
  { id: 101, number: "SYN-A", title: "Сделка А", counterparty: "Учебный покупатель А" },
  { id: 102, number: "SYN-B", title: "Сделка Б", counterparty: "Учебный покупатель Б" },
];
const savedItem = { id: 700, sku_id: 17, code: "BATTERY-A", title: skus[0].title, qty: 3, unit: "шт", unit_price: 25, last_price: null, min_price: null };
const response = (body: unknown, status = 200) => ({ ok: status === 200, status, json: async () => body });
let catalog: unknown, availableDeals: unknown, failure: number | "network" | null;
let dealsFail: boolean;
let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.resetAllMocks(); catalog = skus; availableDeals = deals; failure = null; dealsFail = false;
  currencyFormat.mockImplementation((v: number) => `${v.toFixed(2)} BYN`);
  fetcher = vi.fn(async (url: string) => {
    if (url === "/api/sales/skus?for_picker=1") {
      if (failure === "network") throw new Error("offline");
      return response(catalog, failure ?? 200);
    }
    if (url === "/api/sales/deals") return response(availableDeals, dealsFail ? 503 : 200);
    throw new Error(`Unexpected API route ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => { store.set(key, value); } });
  vi.mocked(api.fetchStock).mockResolvedValue([]);
  vi.mocked(api.addDealItem).mockResolvedValue(true);
  vi.mocked(api.createPriceQuote).mockResolvedValue(true);
  vi.mocked(api.requestApproval).mockResolvedValue(true);
  vi.mocked(api.fetchDealItems).mockResolvedValue([savedItem]);
});
afterEach(() => vi.unstubAllGlobals());

async function selectDeal(id = "101") {
  await screen.findByRole("option", { name: /SYN-A/ });
  fireEvent.change(screen.getByLabelText("Сделка для подбора"), { target: { value: id } });
}
async function openPicker() {
  fireEvent.click(screen.getByRole("button", { name: "Подобрать товары", exact: true }));
  const dialog = await screen.findByRole("dialog", { name: "Подбор товара", exact: true });
  await within(dialog).findByText(skus[0].title);
  return dialog;
}
async function pick(index = 0, qty = 3) {
  const dialog = screen.getByRole("dialog", { name: "Подбор товара", exact: true });
  fireEvent.click(within(dialog).getByText(skus[index].title));
  fireEvent.change(screen.getByLabelText("Количество товара"), { target: { value: String(qty) } });
  fireEvent.change(screen.getByLabelText("Цена за единицу"), { target: { value: "25" } });
  fireEvent.click(screen.getByRole("button", { name: "Добавить в подбор", exact: true }));
}
function transfer() { fireEvent.click(screen.getAllByRole("button", { name: "Перенести в документ", exact: true })[0]); }

it("shows real Sales products without auto-selecting a deal or requesting ERP references", async () => {
  render(<CrmProductCatalog />);
  expect(await screen.findByText(skus[0].title)).toBeInTheDocument();
  expect(screen.getByLabelText("Сделка для подбора")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Подобрать товары" })).toBeDisabled();
  expect(screen.queryByRole("link", { name: /дерево категорий/ })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.every(([url]) => url.startsWith("/api/sales/"))).toBe(true);
});
it("finds a product by its actual code", async () => {
  render(<CrmProductCatalog />); await screen.findByText(skus[0].title);
  fireEvent.change(screen.getByLabelText("Поиск товара"), { target: { value: "battery-b" } });
  expect(screen.getByText(skus[1].title)).toBeInTheDocument();
  expect(screen.queryByText(skus[0].title)).not.toBeInTheDocument();
});
it("finds by name and restores the list when search is cleared", async () => {
  render(<CrmProductCatalog />); await screen.findByText(skus[0].title);
  fireEvent.change(screen.getByLabelText("Поиск товара"), { target: { value: "батарея А" } });
  expect(screen.queryByText(skus[1].title)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Поиск товара"), { target: { value: "" } });
  expect(screen.getByText(skus[1].title)).toBeInTheDocument();
});
it("paginates and resets to the first page for a new search", async () => {
  catalog = Array.from({ length: 51 }, (_, i) => ({ id: i + 1, code: `S-${i}`, title: `Учебный товар ${i}`, unit: "шт" }));
  render(<CrmProductCatalog />); await screen.findByText("Учебный товар 0");
  fireEvent.click(screen.getByRole("button", { name: "Далее" }));
  expect(screen.getByText("Учебный товар 50")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Поиск товара"), { target: { value: "товар 0" } });
  expect(screen.getByText("Учебный товар 0")).toBeInTheDocument();
});
it("distinguishes a confirmed empty catalogue", async () => {
  catalog = []; render(<CrmProductCatalog />);
  expect(await screen.findByText("В каталоге пока нет товаров.")).toBeInTheDocument();
  expect(screen.getByText("Найдено товаров: 0")).toBeInTheDocument();
});
it("distinguishes no search matches from an empty source", async () => {
  render(<CrmProductCatalog />); await screen.findByText(skus[0].title);
  fireEvent.change(screen.getByLabelText("Поиск товара"), { target: { value: "missing" } });
  expect(screen.getByText("По вашему запросу товары не найдены.")).toBeInTheDocument();
  expect(screen.queryByText("В каталоге пока нет товаров.")).not.toBeInTheDocument();
});
it.each([401, 403, 503, "network"] as const)("does not claim zero products after %s", async (value) => {
  failure = value; render(<CrmProductCatalog />);
  expect(await screen.findByRole("alert")).toHaveTextContent(value === 401 || value === 403 ? "Каталог продаж недоступен" : "Количество товаров неизвестно");
  expect(screen.queryByText("Найдено товаров: 0")).not.toBeInTheDocument();
});
it("rejects malformed catalogue data instead of rendering partial rows", async () => {
  catalog = [skus[0], { ...skus[1], id: null }]; render(<CrmProductCatalog />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Количество товаров неизвестно");
  expect(screen.queryByText(skus[0].title)).not.toBeInTheDocument();
});
it("does not allow selection when accessible deals failed to load", async () => {
  dealsFail = true; render(<CrmProductCatalog />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить доступные сделки");
  expect(screen.getByRole("button", { name: "Подобрать товары" })).toBeDisabled();
});
it("does not invent a deal for an empty accessible list", async () => {
  availableDeals = []; render(<CrmProductCatalog />);
  expect(await screen.findByRole("link", { name: "Открыть сделки" })).toHaveAttribute("href", "/crm/deals");
  expect(screen.getByRole("button", { name: "Подобрать товары" })).toBeDisabled();
});
it("opens the existing picker for an explicit deal and clears its basket before another deal", async () => {
  failure = 503;
  render(<CrmProductCatalog />); await selectDeal(); failure = null; await openPicker(); await pick();
  expect(screen.getByLabelText("Сделка для подбора")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Повторить загрузку" })).toBeDisabled();
  fireEvent.click(within(screen.getByRole("dialog", { name: "Подбор товара", exact: true })).getByRole("button", { name: "Отмена", exact: true }));
  await selectDeal("102"); await openPicker();
  expect(screen.getAllByRole("button", { name: "Перенести в документ", exact: true }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
  expect(api.addDealItem).not.toHaveBeenCalled();
});
it("transfers the exact SKU and quantity to the selected deal and shows its readback", async () => {
  currencyFormat.mockImplementation((v: number) => `${(v / 2).toFixed(2)} EUR`);
  render(<CrmProductCatalog />); await selectDeal(); await openPicker(); await pick(); transfer();
  expect(await screen.findByText("Товары выбранной сделки")).toBeInTheDocument();
  expect(api.addDealItem).toHaveBeenCalledWith("101", 17, 3, 25, expect.any(String));
  expect(api.fetchDealItems).toHaveBeenCalledWith("101", { throwOnError: true });
  expect(screen.getByText(/Учебная батарея А · 3 шт · 12.50 EUR/)).toBeInTheDocument();
  expect(currencyFormat).toHaveBeenCalledWith(25);
  expect(screen.getByRole("link", { name: "Открыть сделку" })).toHaveAttribute("href", "/crm/deals/101");
});
it("keeps the basket and original deal when the server refuses transfer", async () => {
  vi.mocked(api.addDealItem).mockResolvedValue(false);
  render(<CrmProductCatalog />); await selectDeal(); await openPicker(); await pick(); transfer();
  expect(await screen.findByText(/Не удалось перенести остальные позиции/)).toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "Подбор товара", exact: true })).toBeInTheDocument();
  expect(screen.getByLabelText("Сделка для подбора")).toHaveValue("101");
  expect(api.fetchDealItems).not.toHaveBeenCalled();
});
it("ignores an old readback even after switching A to B and back to A", async () => {
  let resolve!: (rows: api.DealItemFull[]) => void;
  vi.mocked(api.fetchDealItems).mockImplementation(() => new Promise((done) => { resolve = done; }));
  render(<CrmProductCatalog />); await selectDeal(); await openPicker(); await pick(); transfer();
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Подбор товара", exact: true })).not.toBeInTheDocument());
  await selectDeal("102"); await selectDeal("101");
  await act(async () => { resolve([savedItem]); });
  expect(screen.queryByText("Товары выбранной сделки")).not.toBeInTheDocument();
});
it("retries a failed load without selecting a stale deal", async () => {
  failure = 503; render(<CrmProductCatalog />); await screen.findByRole("alert"); failure = null;
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
  expect(await screen.findByText(skus[0].title)).toBeInTheDocument();
  expect(screen.getByLabelText("Сделка для подбора")).toHaveValue("");
});
it("retries only failed rows after a partial transfer", async () => {
  vi.mocked(api.addDealItem).mockResolvedValueOnce(true).mockResolvedValueOnce(false).mockResolvedValue(true);
  render(<CrmProductCatalog />); await selectDeal(); await openPicker(); await pick(); await pick(1, 2); transfer();
  await screen.findByText(/Перенесено позиций: 1\/2/); transfer();
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Подбор товара", exact: true })).not.toBeInTheDocument());
  expect(vi.mocked(api.addDealItem).mock.calls.map((args) => args.slice(0, 3))).toEqual([["101", 17, 3], ["101", 18, 2], ["101", 18, 2]]);
});
