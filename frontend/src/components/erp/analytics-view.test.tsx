import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalyticsView } from "@/components/erp/analytics-view";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const context = (id = 7) => ({ configuration: "AIOS_SELLER_UNP", organization: { id, name: "Synthetic company", unp: "100000001" } });
const row = (id: number) => ({ id, number: `TEST-${id}`, supplier: "Synthetic supplier", stage: "need", item: "Synthetic item", quantity: "1", planned_amount: "0", due_date: null });
const page = (items = [row(1), row(2), row(3)], org = 7, cursor: number | null = null) => ({ organization_id: org, items, next_after_id: cursor });
const ok = (data: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
const companyURL = "/api/system/instance-organization";
const purchaseURL = (id = 7) => `/api/procurement/organizations/${id}/owned-sources?kind=request`;
type Reply = ReturnType<typeof ok>;
function wire(route?: (url: string, init?: RequestInit) => Reply | Promise<Reply> | undefined) {
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), custom = route?.(url, init);
    if (custom !== undefined) return custom;
    return ok(url === companyURL ? context() : url.includes("/owned-sources") ? page() : [row(1), row(2), row(3)]);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}
const card = (label: string) => within(screen.getByRole("region", { name: label, exact: true }));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

describe("AnalyticsView", () => {
  it("рендерит карточки и читает закупки только в подтверждённой компании", async () => {
    const f = wire(); render(<AnalyticsView />);
    expect(screen.getByRole("heading", { name: "Аналитика", exact: true })).toBeInTheDocument();
    expect(screen.getByText("Сделки")).toBeInTheDocument(); expect(screen.getByText("Платежи")).toBeInTheDocument();
    expect(await card("Закупки").findByText("3", { exact: true })).toBeInTheDocument();
    expect(card("Сделки").getByText("3", { exact: true })).toBeInTheDocument();
    expect(f.mock.calls.some(([url]) => url === purchaseURL())).toBe(true);
    expect(f.mock.calls.some(([url]) => String(url).includes("/procurement/requests"))).toBe(false);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText("Показаны загруженные записи. Это не общий итог по всем данным.")).toBeInTheDocument();
  });
  it("заменяет ошибку загрузки явной недоступностью вместо вечного ожидания", async () => {
    wire(() => Promise.reject(new Error("private transport details"))); render(<AnalyticsView />);
    expect(await card("Сделки").findByRole("alert")).toHaveTextContent("Не удалось загрузить данные.");
    await waitFor(() => expect(screen.queryByText("Загрузка данных…")).not.toBeInTheDocument());
    expect(card("Сделки").queryByText("0", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText(/private transport/)).not.toBeInTheDocument();
  });
  it("не запрашивает закупки без настроенной компании и не блокирует другие карточки", async () => {
    const f = wire(url => url === companyURL ? ok(null, 503) : undefined); render(<AnalyticsView />);
    expect(await card("Закупки").findByRole("alert")).toHaveTextContent("Юрлицо установки не настроено");
    expect(card("Сделки").getByText("3", { exact: true })).toBeInTheDocument();
    expect(f.mock.calls.some(([url]) => String(url).includes("/api/procurement/"))).toBe(false);
    expect(card("Закупки").queryByText("0", { exact: true })).not.toBeInTheDocument();
    expect(card("Закупки").getByRole("link", { name: "Настройки организации" })).toHaveAttribute("href", "/erp/settings");
  });
  it("обозначает страницу из 50 заявок как неполную и не догружает её автоматически", async () => {
    const f = wire(url => url === purchaseURL() ? ok(page(Array.from({ length: 50 }, (_, i) => row(i + 1)), 7, 50)) : undefined);
    render(<AnalyticsView />);
    expect(await card("Закупки").findByText("50", { exact: true })).toBeInTheDocument();
    expect(card("Закупки").getByText("Есть ещё заявки")).toBeInTheDocument();
    expect(card("Закупки").getByText("Загружено заявок")).toBeInTheDocument();
    expect(f.mock.calls.filter(([url]) => String(url).includes("/owned-sources"))).toHaveLength(1);
  });
  it("показывает ноль для валидной пустой завершённой страницы", async () => {
    wire(url => url === purchaseURL() ? ok(page([])) : undefined); render(<AnalyticsView />);
    expect(await card("Закупки").findByText("0", { exact: true })).toBeInTheDocument();
    expect(card("Закупки").queryByText("Есть ещё заявки")).not.toBeInTheDocument();
    expect(card("Закупки").queryByRole("alert")).not.toBeInTheDocument();
  });
  it.each([
    ["wrong company", page([row(1)], 8)],
    ["wrong shape", { organization_id: 7, items: {}, next_after_id: null }],
    ["duplicate IDs", page([row(1), row(1)])],
    ["unsorted IDs", page([row(2), row(1)])],
    ["invalid cursor", page([], 7, 1)],
    ["unsafe integer ID", page([row(Number.MAX_SAFE_INTEGER + 1)])],
    ["more than 50 rows", page(Array.from({ length: 51 }, (_, i) => row(i + 1)))],
  ])("не принимает некорректную страницу: %s", async (_reason, value) => {
    wire(url => url === purchaseURL() ? ok(value) : undefined); render(<AnalyticsView />);
    expect(await card("Закупки").findByRole("alert")).toHaveTextContent("Источник вернул некорректные данные.");
    expect(card("Закупки").queryByText("0", { exact: true })).not.toBeInTheDocument();
  });
  it("не превращает неизвестную форму другого источника в ноль", async () => {
    wire(url => url === "/api/sales/deals" ? ok({ count: 0 }) : undefined); render(<AnalyticsView />);
    expect(await card("Сделки").findByRole("alert")).toHaveTextContent("Источник вернул некорректные данные.");
    expect(card("Сделки").queryByText("0", { exact: true })).not.toBeInTheDocument();
  });
  it("показывает безопасный отказ доступа без тела ошибки сервера", async () => {
    wire(url => url === purchaseURL() ? ok({ detail: "private server payload" }, 403) : undefined); render(<AnalyticsView />);
    expect(await card("Закупки").findByRole("alert")).toHaveTextContent("Нет доступа к данным.");
    expect(screen.queryByText(/private server payload/)).not.toBeInTheDocument();
  });
  it("повторяет только ошибочную карточку и обновляет её результат", async () => {
    let fail = true;
    const f = wire(url => url === purchaseURL() ? ok(page([row(1)]), fail ? 500 : 200) : undefined); render(<AnalyticsView />);
    await card("Закупки").findByRole("alert");
    const otherCalls = f.mock.calls.filter(([url]) => url !== purchaseURL()).length; fail = false;
    fireEvent.click(card("Закупки").getByRole("button", { name: "Повторить загрузку: Закупки" }));
    expect(await card("Закупки").findByText("1", { exact: true })).toBeInTheDocument();
    expect(card("Закупки").queryByRole("alert")).not.toBeInTheDocument();
    expect(f.mock.calls.filter(([url]) => url !== purchaseURL())).toHaveLength(otherCalls);
    expect(f.mock.calls.filter(([url]) => url === purchaseURL())).toHaveLength(2);
  });
  it("отменяет старый запрос и игнорирует поздний JSON после смены контекста", async () => {
    const oldJSON = deferred<unknown>(); let oldSignal: AbortSignal | undefined, company = 7, jsonStarted = false;
    wire((url, init) => {
      if (url === companyURL) return ok(context(company));
      if (url === purchaseURL(7)) {
        oldSignal = init?.signal as AbortSignal;
        return { ...ok(null), json: () => { jsonStarted = true; return oldJSON.promise; } };
      }
      if (url === purchaseURL(8)) return ok(page([row(1), row(2)], 8));
    });
    const oldView = render(<AnalyticsView />); await waitFor(() => expect(jsonStarted).toBe(true));
    oldView.unmount(); expect(oldSignal?.aborted).toBe(true); company = 8; render(<AnalyticsView />);
    await card("Закупки").findByText("2", { exact: true });
    await act(async () => { oldJSON.resolve(page(Array.from({ length: 9 }, (_, i) => row(i + 1)))); });
    expect(card("Закупки").getByText("2", { exact: true })).toBeInTheDocument();
    expect(card("Закупки").queryByText("9", { exact: true })).not.toBeInTheDocument();
    expect(card("Закупки").queryByRole("alert")).not.toBeInTheDocument();
  });
});
