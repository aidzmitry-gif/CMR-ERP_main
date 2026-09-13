import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WmsPrimaryReceipt } from "./wms-primary-receipt";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });
const source = { organization_id: 1, source_receipt_id: 9, source_version: 2, source_warehouse: "По документу", lines: [{ position: 1, sku: "Материал", lot: "Партия", quantity: "2.00", unit: "кг" }] };
async function fill() {
  await screen.findByText("Строка 1: Материал");
  fireEvent.change(screen.getByLabelText("Склад приёмки"), { target: { value: "Склад А" } });
  fireEvent.change(screen.getByLabelText("Основание сопоставления"), { target: { value: "Проверено по накладной" } });
  fireEvent.change(screen.getByLabelText("Складской SKU строки 1"), { target: { value: "MAT" } });
  fireEvent.change(screen.getByLabelText("Количество приёмки строки 1"), { target: { value: "1.25" } });
}
it("restores the identical command after unknown delivery and verifies saved receipt", async () => {
  const bodies: string[] = [];
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      bodies.push(options.body as string);
      if (bodies.length === 1) throw new Error("Network lost");
      return { ok: true, json: async () => ({ organization_id: 1, source_receipt_id: 9, source_version: 2, request_key: JSON.parse(options.body as string).request_key, receipt_id: 12 }) };
    }
    return { ok: true, json: async () => url.endsWith("/receipts/12") ? { id: 12, organization_id: 1, entity_ref: "procurement:receipt:9:2" } : source };
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<WmsPrimaryReceipt org="1" receipt="9" version="2" />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Создать приёмку для QC" }));
  await screen.findByText("Network lost");
  expect(screen.getByLabelText("Склад приёмки")).toBeDisabled();
  view.unmount();
  render(<WmsPrimaryReceipt org="1" receipt="9" version="2" />);
  fireEvent.click(await screen.findByRole("button", { name: "Повторить ту же команду" }));
  expect(await screen.findByRole("link", { name: "Открыть контроль качества" })).toHaveAttribute("href", "/erp/wms/receipts/12");
  expect(bodies[0]).toBe(bodies[1]);
  expect(sessionStorage.getItem("wms-primary-receipt:1:9:2")).toBeNull();
});
it("allows fixing an explicitly rejected warehouse SKU without claiming creation", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url: string, options?: RequestInit) => options?.method === "POST"
    ? { ok: false, status: 409, json: async () => ({ detail: "Select an existing warehouse SKU with the exact primary unit" }) }
    : { ok: true, json: async () => source }));
  render(<WmsPrimaryReceipt org="1" receipt="9" version="2" />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Создать приёмку для QC" }));
  await screen.findByText(/Команда отклонена до сохранения/);
  expect(screen.getByLabelText("Складской SKU строки 1")).toBeEnabled();
  expect(screen.queryByRole("link", { name: "Открыть контроль качества" })).not.toBeInTheDocument();
});
