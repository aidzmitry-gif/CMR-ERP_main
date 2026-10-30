import { render,resetCompany,waitForCompany } from "@/test/installation-company";
import { cleanup,fireEvent,screen,waitFor } from "@testing-library/react";
import { afterEach,beforeEach as configureBeforeEach,expect,it,vi } from "vitest";
import { WarehouseExecutionSettings } from "./warehouse-execution-settings";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const warehouse = { id: 7, organization_id: 1, name: "W1", title: "Первый склад", wms_enabled: false, prohibit_negative_stock: true };
const response = (data: unknown, ok = true, status = ok ? 200 : 409) => ({ ok, status, json: async () => data });

async function chooseOrganization() {
  await waitForCompany();
  await waitForCompany();
}

it("uses the installation company and confirms the exact warehouse and prior mode", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response({ organization_id: 1, items: [warehouse], truncated: false }))
    .mockResolvedValueOnce(response({ ...warehouse, wms_enabled: true }));
  vi.stubGlobal("fetch", fetcher);
  render(<WarehouseExecutionSettings />);
  await waitForCompany();
  await waitForCompany();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  await chooseOrganization();
  fireEvent.click(await screen.findByRole("button", { name: "Включить WMS" }));
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить изменение режима" }));
  expect(await screen.findByRole("status")).toHaveTextContent("WMS включён");
  expect(fetcher).toHaveBeenLastCalledWith("/api/wms/organizations/1/warehouses/7/execution-mode", expect.objectContaining({
    method: "PATCH", body: JSON.stringify({ wms_enabled: true, expected_wms_enabled: false }),
  }));
});

it.each([undefined, "false"])("does not treat unknown mode %s as disabled", async value => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(response({ organization_id: 1, items: [{ ...warehouse, wms_enabled: value }] })));
  render(<WarehouseExecutionSettings />);
  await waitForCompany();
  await chooseOrganization();
  expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждены сервером");
  expect(screen.queryByRole("button", { name: "Включить WMS" })).not.toBeInTheDocument();
});

it("does not claim success when unfinished operations block the switch", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(response({ organization_id: 1, items: [warehouse] }))
    .mockResolvedValueOnce(response({ detail: "warehouse_has_open_operations" }, false)));
  render(<WarehouseExecutionSettings />);
  await waitForCompany();
  await chooseOrganization();
  fireEvent.click(await screen.findByRole("button", { name: "Включить WMS" }));
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить изменение режима" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("warehouse_has_open_operations");
  expect(screen.getByText("W1 · WMS выключен")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("defaults the policy to checked and patches only the selected organization and warehouse", async () => {
  const legacyWarehouse = { id: 7, organization_id: 1, name: "W1", title: "Первый склад", wms_enabled: false };
  const secondWarehouse = { ...warehouse, id: 8, name: "W2", title: "Второй склад" };
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response({ organization_id: 1, items: [legacyWarehouse, secondWarehouse], truncated: false }))
    .mockResolvedValueOnce(response({ accepted: true }))
    .mockResolvedValueOnce(response({ organization_id: 1, items: [
      { ...legacyWarehouse, prohibit_negative_stock: false }, secondWarehouse,
    ], truncated: false }));
  vi.stubGlobal("fetch", fetcher);
  render(<WarehouseExecutionSettings />);
  await waitForCompany();
  await chooseOrganization();
  const first = await screen.findByRole("checkbox", { name: "Запрещать отрицательные остатки для склада Первый склад" });
  const second = screen.getByRole("checkbox", { name: "Запрещать отрицательные остатки для склада Второй склад" });
  expect(first).toBeChecked();
  expect(second).toBeChecked();
  fireEvent.click(first);
  await waitFor(() => expect(first).not.toBeChecked());
  expect(second).toBeChecked();
  expect(fetcher.mock.calls[1][0]).toBe("/api/wms/organizations/1/warehouses/7/stock-policy");
  expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "PATCH", body: JSON.stringify({
    expected_prohibit_negative_stock: true, prohibit_negative_stock: false,
  }) });
  expect(await screen.findByRole("status")).toHaveTextContent("отрицательные остатки разрешены");
});

it("retains the confirmed checkbox value and reports stale or refused policy updates", async () => {
  for (const failure of [
    { status: 409, detail: "stale_stock_policy" },
    { status: 403, detail: "warehouse_mode_admin_required" },
  ]) {
    cleanup();
    const fetcher = vi.fn()
      .mockResolvedValueOnce(response({ organization_id: 1, items: [warehouse], truncated: false }))
      .mockResolvedValueOnce(response({ detail: failure.detail }, false, failure.status))
      .mockResolvedValueOnce(response({ organization_id: 1, items: [warehouse], truncated: false }));
    vi.stubGlobal("fetch", fetcher);
    render(<WarehouseExecutionSettings />);
  await waitForCompany();
    await chooseOrganization();
    const checkbox = await screen.findByRole("checkbox", { name: "Запрещать отрицательные остатки для склада Первый склад" });
    fireEvent.click(checkbox);
    expect(await screen.findByRole("alert")).toHaveTextContent(failure.detail);
    await waitFor(() => expect(checkbox).toBeChecked());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fetcher.mock.calls[1][0]).toBe("/api/wms/organizations/1/warehouses/7/stock-policy");
  }
});

configureBeforeEach(() => resetCompany(1));
