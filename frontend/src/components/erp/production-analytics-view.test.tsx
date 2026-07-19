import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевую загрузку (fetchAnalytics) — чистые форматтеры/kpiTone
// оставляем настоящими, чтобы тесты проверяли реальные подписи (н.ч/%/BYN) и цвета.
vi.mock("@/lib/production-analytics", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/production-analytics")>();
  return { ...actual, fetchAnalytics: vi.fn() };
});

import { ProductionAnalyticsView } from "@/components/erp/production-analytics-view";
import { type AnalyticsData, fetchAnalytics } from "@/lib/production-analytics";

const fetchAnalyticsMock = fetchAnalytics as ReturnType<typeof vi.fn>;

function makeData(overrides: Partial<AnalyticsData> = {}): AnalyticsData {
  return {
    vyrabotka_fact_nh: 1234.5,
    vyrabotka_plan_nh: 1500,
    efficiency_pct: 85, // "high" ≥80 → green
    fpy_pct: 92,
    pass_rate_pct: 70, // "high" 60..80 → amber
    scrap_pct: 3, // "low" ≤5 → green
    premium_fot_byn: 12345.67,
    plan_fact_by_month: [
      { month: 1, plan_nh: 100, fact_nh: 80 },
      { month: 2, plan_nh: 120, fact_nh: 130 },
    ],
    scrap_reasons: [
      { reason: "Скол", count: 3 },
      { reason: "Трещина", count: 1 },
    ],
    team_contribution: [
      { name: "Иванов", nh_output: 100, share_pct: 40 },
      { name: "Петров", nh_output: 60, share_pct: 24 },
    ],
    top_products: [
      { product: "Изделие A", fact_nh: 500 },
      { product: "Изделие B", fact_nh: 400 },
      { product: "Изделие C", fact_nh: 300 },
      { product: "Изделие D", fact_nh: 200 },
      { product: "Изделие E", fact_nh: 100 },
      { product: "Изделие F", fact_nh: 50 },
    ],
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("ProductionAnalyticsView", () => {
  it("без данных показывает сообщение о недоступности, а не пустой экран", () => {
    render(<ProductionAnalyticsView initial={null} />);
    expect(
      screen.getByText(/Данные аналитики недоступны/),
    ).toBeInTheDocument();
    // KPI-карточек нет — компонент вышел рано
    expect(screen.queryByText("Эффективность")).not.toBeInTheDocument();
  });

  it("рендерит KPI реальными форматтерами: н.ч, %, BYN и план в подписи", () => {
    render(<ProductionAnalyticsView initial={makeData()} />);
    // Выработка факт = fmtNh(1234.5) + " н.ч"; подпись — план fmtNh(1500)
    expect(screen.getByText("1234,5 н.ч")).toBeInTheDocument();
    expect(screen.getByText("план: 1500,0 н.ч")).toBeInTheDocument();
    // Проценты и деньги — по реальным форматтерам
    expect(screen.getByText("85,0%")).toBeInTheDocument();
    expect(screen.getByText("12 345,67 р.")).toBeInTheDocument();
  });

  it("цвет KPI зависит от значения: эффективность 85 — зелёная, пропускаемость 70 — янтарная", () => {
    render(<ProductionAnalyticsView initial={makeData()} />);
    const effValue = within(
      screen.getByText("Эффективность").parentElement as HTMLElement,
    ).getByText("85,0%");
    expect(effValue.className).toMatch(/text-green-600/);

    const passValue = within(
      screen.getByText("Пропускаемость").parentElement as HTMLElement,
    ).getByText("70,0%");
    expect(passValue.className).toMatch(/text-amber-600/);
  });

  it("таблица причин брака считает долю от суммы (3 из 4 = 75%, 1 из 4 = 25%)", () => {
    render(<ProductionAnalyticsView initial={makeData()} />);
    const scrapHeading = screen.getByText("Причины брака");
    const scrapBlock = scrapHeading.parentElement as HTMLElement;
    expect(within(scrapBlock).getByText("Скол")).toBeInTheDocument();
    expect(within(scrapBlock).getByText("75%")).toBeInTheDocument();
    expect(within(scrapBlock).getByText("25%")).toBeInTheDocument();
  });

  it("пустые списки показывают «Нет данных» вместо таблиц", () => {
    render(
      <ProductionAnalyticsView
        initial={makeData({ scrap_reasons: [], team_contribution: [], top_products: [] })}
      />,
    );
    expect(screen.getAllByText("Нет данных")).toHaveLength(3);
    // заголовков-колонок таблицы брака нет, раз данных нет
    expect(screen.queryByText("Причина")).not.toBeInTheDocument();
  });

  it("топ изделий обрезается до 5 строк даже если пришло больше", () => {
    render(<ProductionAnalyticsView initial={makeData()} />);
    const topHeading = screen.getByText(/Топ изделий/);
    const topBlock = topHeading.parentElement as HTMLElement;
    expect(within(topBlock).getByText("Изделие A")).toBeInTheDocument();
    expect(within(topBlock).getByText("Изделие E")).toBeInTheDocument();
    // 6-е изделие отброшено slice(0, 5)
    expect(within(topBlock).queryByText("Изделие F")).not.toBeInTheDocument();
  });

  it("вклад сборщика показывает его долю и выработку в н.ч", () => {
    render(<ProductionAnalyticsView initial={makeData()} />);
    const heading = screen.getByText("Вклад сборщиков");
    const block = heading.parentElement as HTMLElement;
    expect(within(block).getByText("Иванов")).toBeInTheDocument();
    expect(within(block).getByText("40%")).toBeInTheDocument();
    expect(within(block).getByText("100,0 н.ч")).toBeInTheDocument();
  });

  it("клик по «‹» грузит предыдущий год и обновляет данные и заголовок года", async () => {
    const startYear = new Date().getFullYear();
    fetchAnalyticsMock.mockResolvedValue(
      makeData({ vyrabotka_fact_nh: 999.9, efficiency_pct: 50 }),
    );
    render(<ProductionAnalyticsView initial={makeData()} />);
    expect(screen.getByText(String(startYear))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "‹" }));

    await waitFor(() => expect(fetchAnalytics).toHaveBeenCalledWith(startYear - 1));
    // заголовок года переключился и данные подменились (эффективность 50 → красная)
    expect(await screen.findByText(String(startYear - 1))).toBeInTheDocument();
    expect(screen.getByText("999,9 н.ч")).toBeInTheDocument();
    const effValue = within(
      screen.getByText("Эффективность").parentElement as HTMLElement,
    ).getByText("50,0%");
    expect(effValue.className).toMatch(/text-red-600/);
  });

  it("во время загрузки года показывает индикатор «Загрузка…», затем прячет его", async () => {
    let resolveFetch: (d: AnalyticsData) => void = () => {};
    fetchAnalyticsMock.mockImplementation(
      () => new Promise<AnalyticsData>((r) => (resolveFetch = r)),
    );
    render(<ProductionAnalyticsView initial={makeData()} />);
    expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "›" }));
    expect(await screen.findByText("Загрузка…")).toBeInTheDocument();

    await act(async () => {
      resolveFetch(makeData());
    });
    await waitFor(() => expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument());
  });
});
