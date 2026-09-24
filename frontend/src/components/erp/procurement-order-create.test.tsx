import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProcurementOrderCreate } from "./procurement-order-create";

const ok = (body: unknown, status = 200) => ({ ok: true, status, json: async () => body });

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

it("requires a catalog selection and creates the order with an immutable SKU snapshot", async () => {
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("receipt-organizations")) return ok([{ id: 1, name: "Компания", unp: "123" }]);
    if (path.endsWith("request-plan-context")) return ok({ organization_id: 1, principal: "tester", can_manage: true });
    if (path.includes("/sku-options?q=")) return ok({ organization_id: 1, items: [{ id: 42, code: "SKU-A", title: "Товар А", unit: "шт" }], truncated: false });
    if (path.includes("/owned-sources?kind=")) return ok({ organization_id: 1, items: [], next_after_id: null });
    if (init?.method === "POST" && path.endsWith("/orders")) {
      const command = JSON.parse(String(init.body));
      const line = command.document.lines[0];
      return ok({ organization_id: 1, request_key: command.request_key, principal: "tester", outcome: "created",
        order_id: 7, ownership_id: 9, number: "PO-2026-000007", status: "draft", supplier: command.document.supplier,
        eta_date: command.document.eta_date, freight_byn: command.document.freight_byn,
        lines: [{ id: 11, sku_code: line.sku_code, qty: line.qty, goods_value_byn: line.goods_value_byn, weight: line.weight, volume: line.volume }],
        request_id: null, request_ownership_id: null, link_id: null, request_snapshot: null }, 201);
    }
    if (path.includes("/orders/7?after_line_id=")) return ok({ organization_id: 1, id: 7, number: "PO-2026-000007", supplier: "Поставщик",
      status: "draft", eta_date: null, freight_byn: "0.00", lines: [{ id: 11, sku_code: "SKU-A", qty: "1.00", goods_value_byn: "0.00", weight: "0.000", volume: "0.0000" }], next_after_line_id: null });
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementOrderCreate />);
  await screen.findByRole("option", { name: "Компания · 123" });
  fireEvent.change(screen.getByLabelText("Юрлицо заказа"), { target: { value: "1" } });
  await screen.findByRole("option", { name: "SKU-A · Товар А · шт" });
  fireEvent.change(screen.getByLabelText("Основание заказа"), { target: { value: "standalone" } });
  fireEvent.change(screen.getByLabelText("Поставщик заказа"), { target: { value: "Поставщик" } });
  fireEvent.change(screen.getByLabelText("Основание выбора юрлица заказа"), { target: { value: "Проверено" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать заказ" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Выберите номенклатуру");
  expect(fetcher.mock.calls.filter(([, init]) => init?.method)).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("Номенклатура из справочника 1"), { target: { value: "42" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать заказ" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Создан заказ PO-2026-000007"));
  const command = JSON.parse(String(fetcher.mock.calls.find(([path, init]) => path.endsWith("/orders") && init?.method)?.[1]?.body));
  expect(command.document.lines[0]).toMatchObject({ sku_id: 42, sku_code: "SKU-A", sku_title: "Товар А", sku_unit: "шт" });
});
