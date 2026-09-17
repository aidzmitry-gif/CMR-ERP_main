import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/logistics-api", () => ({
  fetchAudit: vi.fn(),
  fetchScorecard: vi.fn(),
  patchScorecardMetrics: vi.fn(),
  recomputeScorecard: vi.fn(),
  seedScorecard: vi.fn(),
}));

import { LogisticsScorecard } from "@/components/erp/logistics-scorecard";
import type { AuditReport, Scorecard } from "@/lib/logistics-api";
import * as api from "@/lib/logistics-api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const carrierA: Scorecard = {
  carrier_code: "CARRIER-A",
  period: "2026-06",
  otd_pct: 96,
  otif_pct: 95,
  damage_free_pct: 98,
  billing_accuracy_pct: 97,
  claims_ratio_pct: 1,
  cost_per_delivery: 120.5,
  shipments: 12,
  // 0/empty grade intentionally exercises the honest client fallback.
  score: 0,
  grade: "",
};

const carrierB: Scorecard = {
  carrier_code: "CARRIER-B",
  period: "2026-06",
  otd_pct: 70,
  otif_pct: 72,
  damage_free_pct: 75,
  billing_accuracy_pct: 80,
  claims_ratio_pct: 20,
  cost_per_delivery: 80,
  shipments: 8,
  score: 80,
  grade: "B",
};

const audit: AuditReport = {
  period: "2026-06",
  checked: 4,
  discrepancies: 2,
  to_recover: 15,
  items: [
    {
      id: 1,
      shipment_code: "S-1",
      carrier_code: "CARRIER-A",
      invoice_amount: 100,
      expected_amount: 90,
      variance: 10,
      reason: "overcharge",
      status: "open",
    },
    {
      id: 2,
      shipment_code: "S-2",
      carrier_code: "CARRIER-A",
      invoice_amount: 75,
      expected_amount: 70,
      variance: 5,
      reason: "overcharge",
      status: "open",
    },
    {
      id: 3,
      shipment_code: "S-3",
      carrier_code: "CARRIER-B",
      invoice_amount: 60,
      expected_amount: 65,
      variance: -5,
      reason: "undercharge",
      status: "closed",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mock(api.fetchScorecard).mockResolvedValue([carrierA, carrierB]);
  mock(api.fetchAudit).mockResolvedValue(audit);
  mock(api.seedScorecard).mockResolvedValue([carrierA]);
  mock(api.recomputeScorecard).mockResolvedValue([carrierA, carrierB]);
  mock(api.patchScorecardMetrics).mockResolvedValue(carrierA);
});

describe("LogisticsScorecard", () => {
  it("показывает состояние загрузки до ответа backend", () => {
    mock(api.fetchScorecard).mockReturnValue(new Promise(() => undefined));
    render(<LogisticsScorecard />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
  });

  it("сортирует перевозчиков и суммирует переплаты аудита", async () => {
    render(<LogisticsScorecard />);
    await waitFor(() => expect(screen.getByText("Scorecard перевозчиков")).toBeInTheDocument());
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("CARRIER-A");
    expect(rows[2]).toHaveTextContent("CARRIER-B");
    expect(screen.getAllByText("15 BYN").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Всего к возврату за 2026-06/)).toBeInTheDocument();
  });

  it("показывает пустое состояние и запускает засев демо-данных", async () => {
    mock(api.fetchScorecard).mockResolvedValue([]);
    mock(api.fetchAudit).mockResolvedValue(null);
    render(<LogisticsScorecard />);
    await waitFor(() => expect(screen.getByText("Scorecard за 2026-06 ещё не рассчитан.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Заполнить демо-данными" }));
    await waitFor(() => expect(api.seedScorecard).toHaveBeenCalledOnce());
  });

  it("редактирует KPI, отправляет только числовые значения и поддерживает пересчёт периода", async () => {
    render(<LogisticsScorecard />);
    await waitFor(() => expect(screen.getByText("CARRIER-A")).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("button", { name: "✏" })[0]);
    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "99" } });
    fireEvent.change(inputs[1], { target: { value: "not-a-number" } });
    fireEvent.click(screen.getByRole("button", { name: "✓" }));

    await waitFor(() =>
      expect(api.patchScorecardMetrics).toHaveBeenCalledWith("CARRIER-A", "2026-06", {
        otd_pct: 99,
        damage_free_pct: 98,
        billing_accuracy_pct: 97,
        claims_ratio_pct: 1,
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Пересчитать" }));
    await waitFor(() => expect(api.recomputeScorecard).toHaveBeenCalledOnce());

    fireEvent.change(screen.getByPlaceholderText("ГГГГ-ММ"), { target: { value: "2026-07" } });
    await waitFor(() => expect(api.fetchScorecard).toHaveBeenCalledWith("2026-07"));
  });

  it("показывает ошибку, если backend не сохранил KPI, и позволяет отменить редактирование", async () => {
    mock(api.patchScorecardMetrics).mockResolvedValue(null);
    render(<LogisticsScorecard />);
    await waitFor(() => expect(screen.getByText("CARRIER-A")).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("button", { name: "✏" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "✓" }));
    await waitFor(() => expect(screen.getByText("Не удалось сохранить KPI.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "✕" }));
    expect(screen.getAllByRole("button", { name: "✏" }).length).toBe(2);
  });
});
