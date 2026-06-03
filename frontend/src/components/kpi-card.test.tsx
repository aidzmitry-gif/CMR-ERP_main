import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KpiCard } from "@/components/kpi-card";
import type { Kpi } from "@/lib/types";

const baseKpi: Kpi = {
  id: "calls",
  label: "Звонки ключевым клиентам",
  value: 24,
  target: 40,
  percent: 60,
  icon: "phone",
  tone: "blue",
};

describe("KpiCard", () => {
  it("показывает метку и процент выполнения", () => {
    render(<KpiCard kpi={baseKpi} />);
    expect(screen.getByText("Звонки ключевым клиентам")).toBeInTheDocument();
    expect(screen.getByText(/60% выполнено/)).toBeInTheDocument();
  });

  it("кнопка +1 вызывает onLog для счётного KPI", () => {
    const onLog = vi.fn();
    render(<KpiCard kpi={baseKpi} onLog={onLog} />);
    fireEvent.click(screen.getByTitle("Отметить (+1)"));
    expect(onLog).toHaveBeenCalledOnce();
  });

  it("для денежного KPI кнопки +1 нет", () => {
    render(<KpiCard kpi={{ ...baseKpi, money: true, icon: "ruble", tone: "green" }} onLog={() => {}} />);
    expect(screen.queryByTitle("Отметить (+1)")).toBeNull();
  });
});
