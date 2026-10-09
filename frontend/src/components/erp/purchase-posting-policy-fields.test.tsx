import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PurchasePostingPolicyFields } from "./purchase-posting-policy-fields";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const accounts = [
  { organization_id: 7, code: "41.01", title: "Товары", category: "asset", cash: false, quantity_tracking: true },
  { organization_id: 7, code: "60.01", title: "Расчёты", category: "liability", cash: false, quantity_tracking: false },
  { organization_id: 7, code: "18.03", title: "НДС", category: "asset", cash: false, quantity_tracking: false }];
it("emits explicit configured defaults and blocks incomplete or duplicate overrides", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.includes("purchase-posting-selector") ? { organization_id: 7, kind: "sku", id: 4, title: "Товар 4" } : accounts })));
  const changed = vi.fn();
  render(<PurchasePostingPolicyFields org="7" effectiveDate="2026-09-01" onChange={changed} />);
  fireEvent.click(screen.getByLabelText("Настроить автоматический выбор счетов"));
  await screen.findByRole("option", { name: "41.01 · Товары" });
  fireEvent.change(screen.getByLabelText("Общий счёт запасов"), { target: { value: "41.01" } });
  fireEvent.change(screen.getByLabelText("Общий счёт расчётов с поставщиками"), { target: { value: "60.01" } });
  await waitFor(() => expect(changed.mock.lastCall?.[0].value?.purchase.default_inventory_account).toBe("41.01"));
  fireEvent.click(screen.getByRole("button", { name: "Добавить индивидуальное правило" }));
  expect(changed.mock.lastCall?.[0].value).toBeNull();
  fireEvent.change(screen.getByLabelText("Идентификатор правила 1"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("Счёт правила 1"), { target: { value: "41.01" } });
  expect(changed.mock.lastCall?.[0].value).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Проверить карточку 1" }));
  await screen.findByText("Товар 4");
  expect(changed.mock.lastCall?.[0].value.purchase.inventory_by_sku).toEqual({ "4": "41.01" });
  fireEvent.click(screen.getByRole("button", { name: "Добавить индивидуальное правило" }));
  fireEvent.change(screen.getByLabelText("Идентификатор правила 2"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("Счёт правила 2"), { target: { value: "41.01" } });
  expect(changed.mock.lastCall?.[0].value).toBeNull();
  fireEvent.change(screen.getByLabelText("Вид правила 1"), { target: { value: "inventory_by_category" } });
  expect(screen.getByLabelText("Идентификатор правила 1")).toHaveValue("");
  expect(screen.queryByText("Товар 4")).not.toBeInTheDocument();
});
it("rejects accounts belonging to a different organization", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => accounts.map(a => ({ ...a, organization_id: 8 })) }));
  const changed = vi.fn();
  render(<PurchasePostingPolicyFields org="7" effectiveDate="2026-09-01" onChange={changed} />);
  fireEvent.click(screen.getByLabelText("Настроить автоматический выбор счетов"));
  expect(await screen.findByRole("alert")).toHaveTextContent("выбранного юрлица");
  expect(changed.mock.lastCall?.[0].value).toBeNull();
});
