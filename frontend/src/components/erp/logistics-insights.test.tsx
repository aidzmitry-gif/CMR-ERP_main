import { configureCompany,render,resetCompany,waitForCompany } from "@/test/installation-company";
import { act,cleanup,fireEvent,screen,waitFor,within } from "@testing-library/react";
import { afterEach,beforeEach,beforeEach as configureBeforeEach,describe,expect,it,vi } from "vitest";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

vi.mock("@/lib/logistics-owned-costs", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/logistics-owned-costs")>(),
  fetchCostCatalog: vi.fn(), fetchOwnedCostReview: vi.fn(),
}));

import { LogisticsInsights } from "@/components/erp/logistics-insights";
import { LogisticsReadError } from "@/lib/logistics-api";
import * as api from "@/lib/logistics-owned-costs";

function catalog(principal = "A"): api.CostCatalog {
  return { version: 1, principal, items: [{ id: 1, name: "Company One", unp: "111111111" }, { id: 2, name: "Company Two", unp: "222222222" }] };
}
function review(org = 1, principal = "A", amount = "17000.00", average = "8500.00"): api.OwnedCostReview {
  return { version: 1, organization_id: org, principal, status: "partial", complete_cost_coverage: false,
    source: "explicit_own_logistics_imports", posting_status: "not_verified", unavailable_sections: ["tariffs", "tenders", "audit"],
    import_freight: { status: "known", qualified_import_count: 3, warehouse_import_count: 2, known_count: 2,
      unpriced_count: 0, excluded_nonwarehouse_count: 1, known_total: amount, total: amount, known_average: average } };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  return { promise: new Promise<T>(done => { resolve = done; }), resolve: (value: T) => resolve(value) };
}
async function choose(org = "1") {
  const select = await waitForCompany();
  await configureCompany(org);
  return select;
}
async function knownShown(amount = "17000.00") {
  await waitFor(() => expect(within(screen.getByText("Известный фрахт").parentElement!).getByText(moneyText(amount))).toBeInTheDocument());
}
function moneyText(amount: string) { return api.formatFreightByn(amount).replace(/\s/g, " "); }
function noAmount(amount = "17000.00") { expect(screen.queryAllByText(moneyText(amount))).toHaveLength(0); }

beforeEach(() => {
  vi.mocked(api.fetchCostCatalog).mockReset().mockResolvedValue(catalog());
  vi.mocked(api.fetchOwnedCostReview).mockReset().mockImplementation(async selected => review(selected.organization_id, selected.principal));
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("company-owned LogisticsInsights", () => {
  it("waits for the authorized company catalog", async () => {
    vi.mocked(api.fetchCostCatalog).mockReturnValue(new Promise(() => {}));
    render(<LogisticsInsights />);
  await waitForCompany();
    expect(await screen.findByText("Проверка доступа к юрлицам…")).toBeInTheDocument();
    expect(api.fetchOwnedCostReview).not.toHaveBeenCalled();
  });
  it("requires an explicit company selection", async () => {
    render(<LogisticsInsights />);
  await waitForCompany();
    expect(screen.queryByRole("combobox", { name: /Юрлицо|Организация|Компания ячеек|Юридическое лицо/ })).not.toBeInTheDocument();
    expect(api.fetchOwnedCostReview).not.toHaveBeenCalled();
    await choose(); await knownShown();
    expect(api.fetchOwnedCostReview).toHaveBeenCalledWith({ organization_id: 1, principal: "A" }, expect.any(AbortSignal));
  });
  it("keeps an empty company catalog separate from zero expenses", async () => {
    vi.mocked(api.fetchCostCatalog).mockResolvedValue({ ...catalog(), items: [] });
    render(<LogisticsInsights />);
  await waitForCompany();
    expect(await screen.findByText("Нет доступных юрлиц для просмотра затрат.")).toBeInTheDocument();
    expect(api.fetchOwnedCostReview).not.toHaveBeenCalled();
    expect(screen.queryByText(/0,00 Br/)).not.toBeInTheDocument();
  });
  it("shows a catalog denial without any cost data", async () => {
    vi.mocked(api.fetchCostCatalog).mockRejectedValue(new LogisticsReadError(403));
    render(<LogisticsInsights />);
  await waitForCompany();
    expect(await screen.findByRole("alert")).toHaveTextContent("Недостаточно прав");
    expect(api.fetchOwnedCostReview).not.toHaveBeenCalled();
    noAmount();
  });
  it("shows exact qualified amounts and explicitly unavailable remaining sections", async () => {
    render(<LogisticsInsights />);
  await waitForCompany(); await choose(); await knownShown();
    expect(within(screen.getByText("Средний известный фрахт").parentElement!).getByText(moneyText("8500.00"))).toBeInTheDocument();
    expect(within(screen.getByText("Поставок с известной ценой").parentElement!).getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/Охват затрат неполный/)).toBeInTheDocument();
    expect(screen.getByText(/Бухгалтерские проводки этим отчётом не подтверждены/)).toBeInTheDocument();
    expect(screen.getAllByText(/Показатель не определён/)).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /демо/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "5 кг" })).not.toBeInTheDocument();
  });
  it("shows unknown amounts when no source has been qualified", async () => {
    const value = review();
    value.import_freight = { status: "unknown", qualified_import_count: 0, warehouse_import_count: 0,
      known_count: 0, unpriced_count: 0, excluded_nonwarehouse_count: 0, known_total: null, total: null, known_average: null };
    vi.mocked(api.fetchOwnedCostReview).mockResolvedValue(value);
    render(<LogisticsInsights />);
  await waitForCompany(); await choose();
    expect(await screen.findByText(/Нет подтверждённых источников для расчёта/)).toBeInTheDocument();
    expect(within(screen.getByText("Известный фрахт").parentElement!).getByText("Не определён")).toBeInTheDocument();
    expect(screen.queryByText(/0,00 Br/)).not.toBeInTheDocument();
  });
  it("keeps a known subtotal while the whole qualified total is unknown", async () => {
    const value = review();
    Object.assign(value.import_freight, { status: "partial", qualified_import_count: 4, warehouse_import_count: 3, unpriced_count: 1, total: null });
    vi.mocked(api.fetchOwnedCostReview).mockResolvedValue(value);
    render(<LogisticsInsights />);
  await waitForCompany(); await choose(); await knownShown();
    expect(screen.getByRole("alert")).toHaveTextContent("Не оценён фрахт поставок: 1");
    expect(within(screen.getByText("Итог по подтверждённым поставкам").parentElement!).getByText("Не определён")).toBeInTheDocument();
  });
  it("removes A amounts immediately while company B is loading", async () => {
    const pending = deferred<api.OwnedCostReview>();
    vi.mocked(api.fetchOwnedCostReview).mockResolvedValueOnce(review()).mockReturnValueOnce(pending.promise);
    render(<LogisticsInsights />);
  await waitForCompany(); await choose(); await knownShown();
    await configureCompany("2");
    noAmount(); expect(screen.getByText("Загрузка фрахта выбранного юрлица…")).toBeInTheDocument();
    await act(async () => pending.resolve(review(2, "A", "600.00", "300.00")));
    await knownShown("600.00"); noAmount();
  });
  it("ignores delayed responses across A-B-A including identical company IDs", async () => {
    const oldA = deferred<api.OwnedCostReview>(), oldB = deferred<api.OwnedCostReview>();
    vi.mocked(api.fetchOwnedCostReview).mockReturnValueOnce(oldA.promise).mockReturnValueOnce(oldB.promise)
      .mockResolvedValueOnce(review(1, "A", "200.00", "100.00"));
    render(<LogisticsInsights />);
  await waitForCompany(); await choose();
    await waitFor(() => expect(api.fetchOwnedCostReview).toHaveBeenCalledTimes(1));
    await configureCompany("2");
    await waitFor(() => expect(api.fetchOwnedCostReview).toHaveBeenCalledTimes(2));
    await configureCompany("1"); await knownShown("200.00");
    await act(async () => { oldA.resolve(review()); oldB.resolve(review(2, "A", "600.00", "300.00")); });
    await knownShown("200.00"); noAmount(); noAmount("600.00");
  });
  it("clears accepted amounts before a refresh that denies access", async () => {
    render(<LogisticsInsights />);
  await waitForCompany(); await choose(); await knownShown();
    vi.mocked(api.fetchOwnedCostReview).mockRejectedValueOnce(new LogisticsReadError(403));
    fireEvent.click(screen.getByRole("button", { name: "Обновить" })); noAmount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Недостаточно прав"); noAmount();
  });
  it("hides on blur and reloads authorization and costs on focus", async () => {
    render(<LogisticsInsights />);
  await waitForCompany(); await choose(); await knownShown();
    fireEvent.blur(window);
    expect(screen.getByText("Данные скрыты до проверки доступа.")).toBeInTheDocument(); noAmount();
    fireEvent.focus(window);
    await waitFor(() => expect(api.fetchCostCatalog).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.fetchOwnedCostReview).toHaveBeenCalledTimes(2)); await knownShown();
  });
  it.each([["B", true], ["A", false]] as const)("revalidates the principal and qualifies response owner %s", async (responsePrincipal, accepted) => {
    render(<LogisticsInsights />);
    await waitForCompany(); await choose(); await knownShown();
    const freshCatalog = deferred<api.CostCatalog>();
    const freshReview = deferred<api.OwnedCostReview>();
    vi.mocked(api.fetchCostCatalog).mockReturnValueOnce(freshCatalog.promise);
    vi.mocked(api.fetchOwnedCostReview).mockReturnValueOnce(freshReview.promise);
    fireEvent.blur(window); fireEvent.focus(window);
    await waitFor(() => expect(api.fetchCostCatalog).toHaveBeenCalledTimes(2));
    expect(api.fetchOwnedCostReview).toHaveBeenCalledTimes(1);
    noAmount();

    await act(async () => freshCatalog.resolve(catalog("B")));
    await waitFor(() => expect(api.fetchOwnedCostReview).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.fetchOwnedCostReview).mock.calls.at(-1)?.[0]).toEqual({ organization_id: 1, principal: "B" });
    expect(screen.queryByRole("combobox", { name: /Юрлицо|Организация|Компания ячеек|Юридическое лицо/ })).not.toBeInTheDocument();
    noAmount(); noAmount("600.00");

    await act(async () => freshReview.resolve(review(1, responsePrincipal, "600.00", "300.00")));
    if (accepted) await knownShown("600.00");
    else {
      expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось подтвердить владельца ответа");
      noAmount("600.00");
    }
    noAmount();
    expect(api.fetchOwnedCostReview).toHaveBeenCalledTimes(2);
  });
  it("ignores a catalog from the previous focus epoch", async () => {
    const old = deferred<api.CostCatalog>();
    vi.mocked(api.fetchCostCatalog).mockReturnValueOnce(old.promise).mockResolvedValueOnce({
      ...catalog("B"), items: [{ id: 2, name: "Fresh current company", unp: "" }],
    });
    render(<LogisticsInsights />);
  await waitForCompany();
    await waitFor(() => expect(api.fetchCostCatalog).toHaveBeenCalledTimes(1));
    fireEvent.blur(window); fireEvent.focus(window);
    expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа к данным юрлица установки.");
    await act(async () => old.resolve(catalog("A")));
    expect(screen.queryByRole("combobox", { name: /Юрлицо/ })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Нет доступа к данным юрлица установки.");
    expect(api.fetchOwnedCostReview).not.toHaveBeenCalled();
  });
  it("refuses an envelope that belongs to another selected identity", async () => {
    vi.mocked(api.fetchOwnedCostReview).mockResolvedValue(review(2));
    render(<LogisticsInsights />);
  await waitForCompany(); await choose();
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось подтвердить владельца ответа"); noAmount();
  });
});

configureBeforeEach(() => resetCompany(1));
