import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ScopedWmsDashboard, WmsDashboard } from "./wms-dashboard";
import type { Dashboard } from "@/lib/wms-warehouse";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>,
}));
const dashboard: Dashboard = {
  organization_id: 7, report_date: "2026-07-01", period_start: "2026-07-01T00:00:00",
  period_end: "2026-07-02T00:00:00", period_basis: "stored_registration_date",
  receipts_pending_qc: 3, tasks_putaway_open: 0, tasks_pick_open: 0, inventories_open: 0,
  movement_rows_today_in: 5, movement_rows_today_out: 2,
  alerts_count: null, alerts_deficit_value: null, inventory_value: null,
  recon_max_diff_value: null, recon_total_diff_value: null,
  movements_today_in: null, movements_today_out: null,
  valuation_unavailable_reason: "organization_valuation_unavailable",
  quantity_unavailable_reason: "unit_snapshot_unavailable", gateway: false,
};
const company = (id = 7) => ({ configuration: "AIOS_SELLER_UNP",
  organization: { id, name: "Synthetic company", unp: "123456789" } });
const reply = (data: unknown, status = 200) => ({ ok: status === 200, status, json: async () => data });
function install(value: Dashboard = dashboard) {
  const fn = vi.fn().mockImplementation(async (input: unknown) => {
    const url = String(input);
    if (url === "/api/system/instance-organization") return reply(company());
    if (url === "/api/wms/dashboard?organization_id=7") return reply(value);
    throw Error("Unexpected request");
  });
  vi.stubGlobal("fetch", fn); return fn;
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("достоверность сводки склада", () => {
  it("при отказе API не показывает подтверждённые нулевые остатки и задачи", () => {
    render(<WmsDashboard initial={null} />);
    expect(screen.getByRole("alert")).toHaveTextContent("неизвестны");
    expect(screen.queryByText("0 BYN")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить загрузку" })).toBeEnabled();
  });
  it("без шлюза скрывает только зависимые метрики, сохраняя реальные задачи ERP", () => {
    render(<WmsDashboard initial={dashboard} />);
    expect(within(screen.getByRole("region", { name: "Стоимость остатка" })).getByText("—")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Расхождение с 1С" })).getByText("—")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /^Приёмки в очереди QC/ })).getByText("3")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Стоимость остатка" })).not.toBeInTheDocument();
  });
  it("успешно прочитанный нулевой остаток отличается от неизвестного", () => {
    // Synthetic presentation only: the current API does not yet qualify monetary sources.
    render(<WmsDashboard initial={{ ...dashboard, gateway: true, valuation_unavailable_reason: null,
      alerts_count: 0, alerts_deficit_value: 0, inventory_value: 0, recon_max_diff_value: 0, recon_total_diff_value: 0 }} />);
    expect(within(screen.getByRole("region", { name: "Стоимость остатка" })).getByText("0 BYN")).toBeInTheDocument();
  });
  it("reads only configured company without selector", async () => {
    const fn = install(); render(<ScopedWmsDashboard />);
    expect(await screen.findByText(/Synthetic company/)).toBeInTheDocument();
    const counter = await screen.findByRole("link", { name: /^Приёмки в очереди QC/ });
    expect(counter).toHaveAccessibleName(/Приёмки в очереди QC.*3/);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(fn).toHaveBeenCalledWith("/api/wms/dashboard?organization_id=7", expect.objectContaining({ cache: "no-store" }));
    expect(fn.mock.calls.some(([url]) => String(url) === "/api/wms/dashboard")).toBe(false);
  });
  it("configuration failure gates reads and can retry", async () => {
    let failed = false;
    const fn = vi.fn().mockImplementation(async (input: unknown) => {
      if (String(input) === "/api/system/instance-organization") {
        if (!failed) { failed = true; return reply({}, 503); }
        return reply(company());
      }
      return reply(dashboard);
    });
    vi.stubGlobal("fetch", fn); render(<ScopedWmsDashboard />);
    await screen.findByRole("alert");
    expect(fn).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: /^Приёмки в очереди QC/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку юрлица" }));
    await screen.findByRole("link", { name: /^Приёмки в очереди QC/ });
    expect(fn).toHaveBeenCalledTimes(3);
  });
  it("scoped read failure retries without reloading company", async () => {
    let reads = 0;
    const fn = vi.fn().mockImplementation(async (input: unknown) => {
      if (String(input) === "/api/system/instance-organization") return reply(company());
      reads++; return reads === 1 ? reply({}, 503) : reply(dashboard);
    });
    vi.stubGlobal("fetch", fn); render(<ScopedWmsDashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("неизвестны");
    fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
    await screen.findByRole("link", { name: /^Приёмки в очереди QC/ });
    expect(reads).toBe(2);
    expect(fn.mock.calls.filter(([url]) => String(url) === "/api/system/instance-organization")).toHaveLength(1);
  });
  it("late response from old context is ignored", async () => {
    let configReads = 0;
    let finish!: (value: ReturnType<typeof reply>) => void;
    const fn = vi.fn().mockImplementation(async (input: unknown) => {
      const url = String(input);
      if (url === "/api/system/instance-organization") return reply(company(++configReads === 1 ? 7 : 8));
      if (url.endsWith("=7")) return new Promise(resolve => { finish = resolve; });
      return reply({ ...dashboard, organization_id: 8, receipts_pending_qc: 9 });
    });
    vi.stubGlobal("fetch", fn);
    const view = render(<ScopedWmsDashboard key="old" />);
    await waitFor(() => expect(fn.mock.calls.some(([url]) => String(url).endsWith("=7"))).toBe(true));
    view.rerender(<ScopedWmsDashboard key="new" />);
    const card = await screen.findByRole("link", { name: /^Приёмки в очереди QC/ });
    expect(within(card).getByText("9")).toBeInTheDocument();
    await act(async () => finish(reply({ ...dashboard, receipts_pending_qc: 777 })));
    expect(within(card).getByText("9")).toBeInTheDocument();
    expect(screen.queryByText("777")).not.toBeInTheDocument();
  });
  it("labels movement rows and recorded-date period without quantity sum", async () => {
    install(); render(<ScopedWmsDashboard />);
    const incoming = await screen.findByRole("link", { name: /^Записей прихода за дату/ });
    expect(within(incoming).getByText("5")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: /^Записей расхода за дату/ })).getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/01.07.2026.*по журналу ERP/)).toBeInTheDocument();
    expect(screen.getByText(/количества товаров с разными единицами не складываются/)).toBeInTheDocument();
    expect(screen.queryByText("Приход сегодня")).not.toBeInTheDocument();
  });
});
