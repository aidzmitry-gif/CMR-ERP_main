import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingFixedAssets } from "./accounting-fixed-assets";

afterEach(() => vi.unstubAllGlobals());
const digest = "b".repeat(64);
const asset = { id: 7, asset_key: "asset:equipment:001", name: "Станок", inventory_number: "ОС-001", source_entry_id: 41, source_line_id: 4, digest, commissioning_date: "2026-09-01", depreciation_start: "2026-09-01", cost: "1200.00", residual_value: "0.00", useful_life_months: 12, depreciation_method: "straight_line", asset_account: "01.1", accumulated_account: "02.1", expense_account: "26", dimensions: {} };
const ok = (body: unknown) => ({ ok: true, json: async () => body });

it("loads the fixed-asset register and previews a monthly depreciation", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/fixed-assets")) return ok({ organization_id: 1, rows: [asset], statutory_certified: false });
    if (url.endsWith("/depreciation-preview")) return ok({ organization_id: 1, asset_id: 7, month: "2026-09", status: "reviewed_fixed_asset_depreciation", digest, posting_available: true, calculation: { amount: "100.00", remaining_value: "1100.00" }, statutory_certified: false, final_cost_certified: false });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingFixedAssets org="1" month="2026-09" policyId="3" onEntry={vi.fn()} />);
  expect(await screen.findByText("ОС-001 · Станок")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Основание амортизации ОС-001"), { target: { value: "Расчёт за месяц и проверка бухгалтером" } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить амортизацию" }));
  expect(await screen.findByText(/К начислению: 100.00 BYN/)).toBeInTheDocument();
});

it("requires an explicit acquisition source before preparing an asset registration", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/fixed-assets")) return ok({ organization_id: 1, rows: [], statutory_certified: false });
    throw new Error(url);
  }));
  render(<AccountingFixedAssets org="1" month="2026-09" policyId="3" onEntry={vi.fn()} />);
  await screen.findByText("Зарегистрированных ОС нет.");
  fireEvent.click(screen.getByRole("button", { name: "Проверить регистрацию ОС" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Укажите источник, digest");
});
