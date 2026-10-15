import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WarehouseExecutionSettings } from "./warehouse-execution-settings";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const warehouse = { id: 7, organization_id: 1, name: "W1", title: "Первый склад", wms_enabled: false };
const response = (data: unknown, ok = true) => ({ ok, json: async () => data });

async function chooseOrganization() {
  await screen.findByRole("option", { name: "Организация 1" });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "1" } });
}

it("requires an explicit organization and confirms the exact warehouse and prior mode", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response([{ id: 1, name: "Организация 1" }]))
    .mockResolvedValueOnce(response({ organization_id: 1, items: [warehouse], truncated: false }))
    .mockResolvedValueOnce(response({ ...warehouse, wms_enabled: true }));
  vi.stubGlobal("fetch", fetcher);
  render(<WarehouseExecutionSettings />);
  await screen.findByRole("option", { name: "Организация 1" });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "Включить WMS" })).not.toBeInTheDocument();
  await chooseOrganization();
  fireEvent.click(await screen.findByRole("button", { name: "Включить WMS" }));
  expect(fetcher).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить изменение режима" }));
  expect(await screen.findByRole("status")).toHaveTextContent("WMS включён");
  expect(fetcher).toHaveBeenLastCalledWith("/api/wms/organizations/1/warehouses/7/execution-mode", expect.objectContaining({
    method: "PATCH", body: JSON.stringify({ wms_enabled: true, expected_wms_enabled: false }),
  }));
});

it.each([undefined, "false"])("does not treat unknown mode %s as disabled", async value => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response([{ id: 1, name: "Организация 1" }]))
    .mockResolvedValueOnce(response({ organization_id: 1, items: [{ ...warehouse, wms_enabled: value }] })));
  render(<WarehouseExecutionSettings />);
  await chooseOrganization();
  expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждены сервером");
  expect(screen.queryByRole("button", { name: "Включить WMS" })).not.toBeInTheDocument();
});

it("does not claim success when unfinished operations block the switch", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response([{ id: 1, name: "Организация 1" }]))
    .mockResolvedValueOnce(response({ organization_id: 1, items: [warehouse] }))
    .mockResolvedValueOnce(response({ detail: "warehouse_has_open_operations" }, false)));
  render(<WarehouseExecutionSettings />);
  await chooseOrganization();
  fireEvent.click(await screen.findByRole("button", { name: "Включить WMS" }));
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить изменение режима" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("warehouse_has_open_operations");
  expect(screen.getByText("W1 · WMS выключен")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
