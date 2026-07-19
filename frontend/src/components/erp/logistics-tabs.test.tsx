import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/erp/logistics-delivery", () => ({
  LogisticsDelivery: () => <div data-testid="panel-delivery">Панель: Рейсы</div>,
}));
vi.mock("@/components/erp/logistics-tender", () => ({
  LogisticsTender: () => <div data-testid="panel-tender">Панель: Тендеры</div>,
}));
vi.mock("@/components/erp/logistics-tariffs", () => ({
  LogisticsTariffs: () => <div data-testid="panel-tariffs">Панель: Тарифы</div>,
}));
vi.mock("@/components/erp/logistics-fleet", () => ({
  LogisticsFleet: () => <div data-testid="panel-fleet">Панель: Парк</div>,
}));
vi.mock("@/components/erp/logistics-import", () => ({
  LogisticsImport: () => <div data-testid="panel-import">Панель: Импорт</div>,
}));
vi.mock("@/components/erp/logistics-audit", () => ({
  LogisticsAudit: () => <div data-testid="panel-audit">Панель: Аудит счетов</div>,
}));
vi.mock("@/components/erp/logistics-scorecard", () => ({
  LogisticsScorecard: () => <div data-testid="panel-scorecard">Панель: Scorecard</div>,
}));
vi.mock("@/components/erp/logistics-insights", () => ({
  LogisticsInsights: () => <div data-testid="panel-insights">Панель: Экономия</div>,
}));

import { LogisticsTabs } from "@/components/erp/logistics-tabs";

describe("LogisticsTabs", () => {
  it("по умолчанию показывает вкладку «Рейсы» активной и рендерит её панель", () => {
    render(<LogisticsTabs />);

    expect(screen.getByTestId("panel-delivery")).toBeInTheDocument();
    expect(screen.queryByTestId("panel-tender")).not.toBeInTheDocument();

    const active = screen.getByRole("button", { name: "Рейсы" });
    expect(active.className).toContain("font-semibold");
    expect(active.className).toContain("text-accent-ink");

    const inactive = screen.getByRole("button", { name: "Тендеры" });
    expect(inactive.className).toContain("text-muted");
    expect(inactive.className).not.toContain("font-semibold");
  });

  it("рендерит все 8 вкладок с корректными подписями в заданном порядке", () => {
    render(<LogisticsTabs />);

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      "Рейсы",
      "Тендеры",
      "Тарифы",
      "Парк",
      "Импорт",
      "Аудит счетов",
      "Scorecard",
      "Экономия",
    ]);
  });

  it("клик по вкладке «Тарифы» переключает активную панель и снимает активность с предыдущей", () => {
    render(<LogisticsTabs />);

    fireEvent.click(screen.getByRole("button", { name: "Тарифы" }));

    expect(screen.queryByTestId("panel-delivery")).not.toBeInTheDocument();
    expect(screen.getByTestId("panel-tariffs")).toBeInTheDocument();

    const tariffsBtn = screen.getByRole("button", { name: "Тарифы" });
    expect(tariffsBtn.className).toContain("font-semibold");
    const deliveryBtn = screen.getByRole("button", { name: "Рейсы" });
    expect(deliveryBtn.className).not.toContain("font-semibold");
    expect(deliveryBtn.className).toContain("text-muted");
  });

  it("клик по вкладке «Scorecard» рендерит только её панель среди всех восьми", () => {
    render(<LogisticsTabs />);

    fireEvent.click(screen.getByRole("button", { name: "Scorecard" }));

    expect(screen.getByTestId("panel-scorecard")).toBeInTheDocument();
    for (const testId of [
      "panel-delivery",
      "panel-tender",
      "panel-tariffs",
      "panel-fleet",
      "panel-import",
      "panel-audit",
      "panel-insights",
    ]) {
      expect(screen.queryByTestId(testId)).not.toBeInTheDocument();
    }
  });

  it("рендерит заголовок и описание с валютой BYN", () => {
    render(<LogisticsTabs />);

    expect(screen.getByRole("heading", { name: "Логистика" })).toBeInTheDocument();
    expect(screen.getByText(/Валюта — бел\. руб\. \(BYN\)\./)).toBeInTheDocument();
  });
});
