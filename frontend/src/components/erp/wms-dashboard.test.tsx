import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WmsDashboard } from "./wms-dashboard";
import type { Dashboard } from "@/lib/wms-warehouse";

const dashboard: Dashboard = {
  receipts_pending_qc: 3, tasks_putaway_open: 0, tasks_pick_open: 0, alerts_count: 0,
  alerts_deficit_value: 0, inventory_value: 0, inventories_open: 0,
  recon_max_diff_value: 0, recon_total_diff_value: 0,
  movements_today_in: 0, movements_today_out: 0, gateway: false,
};

describe("достоверность сводки склада", () => {
  it("при отказе API не показывает подтверждённые нулевые остатки и задачи", () => {
    render(<WmsDashboard initial={null} />);
    expect(screen.getByRole("alert")).toHaveTextContent("неизвестны");
    expect(screen.queryByText("0 BYN")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить загрузку" })).toBeEnabled();
  });
  it("без шлюза скрывает только зависимые метрики, сохраняя реальные задачи ERP", () => {
    render(<WmsDashboard initial={dashboard} />);
    expect(within(screen.getByRole("link", { name: /Стоимость остатка/ })).getByText("—")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /Расхождение с 1С/ })).getByText("—")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /Приёмки в очереди QC/ })).getByText("3")).toBeInTheDocument();
  });
  it("успешно прочитанный нулевой остаток отличается от неизвестного", () => {
    render(<WmsDashboard initial={{ ...dashboard, gateway: true }} />);
    expect(within(screen.getByRole("link", { name: /Стоимость остатка/ })).getByText("0 BYN")).toBeInTheDocument();
  });
});
