import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BankPostingPolicyFields } from "./bank-posting-policy-fields";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const accounts = [{ organization_id: 1, code: "60.01", title: "Поставщики", category: "liability", cash: false, quantity_tracking: false },
  { organization_id: 1, code: "51", title: "Банк", category: "asset", cash: true, quantity_tracking: false },
  { organization_id: 1, code: "41", title: "Запасы", category: "asset", cash: false, quantity_tracking: true }];
it("requires explicit operation fields, blocks duplicate keys and clears selection on scope change", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => accounts }));
  const changed = vi.fn();
  const view = render(<BankPostingPolicyFields org="1" effectiveDate="2026-09-01" onChange={changed} />);
  fireEvent.click(screen.getByLabelText("Настроить правила банковских операций"));
  fireEvent.click(screen.getByText("Добавить банковское правило"));
  await screen.findByRole("option", { name: "60.01 · Поставщики" });
  expect(screen.queryByRole("option", { name: "51 · Банк" })).not.toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "41 · Запасы" })).not.toBeInTheDocument();
  expect(changed.mock.lastCall?.[0].value).toBeNull();
  for (const [label, value] of [["Ключ", "supplier_payment"], ["Название", "Оплата поставщику"], ["Направление", "payment"], ["Счёт", "60.01"], ["Поток", "operating"]])
    fireEvent.change(screen.getByLabelText(`${label} банковской операции 1`), { target: { value } });
  await waitFor(() => expect(changed.mock.lastCall?.[0].value?.rules.supplier_payment).toEqual({ title: "Оплата поставщику", direction: "payment", settlement_account: "60.01", cash_activity: "operating" }));
  fireEvent.click(screen.getByText("Добавить банковское правило"));
  for (const [label, value] of [["Ключ", "supplier_payment"], ["Название", "Дубль"], ["Направление", "payment"], ["Счёт", "60.01"], ["Поток", "operating"]])
    fireEvent.change(screen.getByLabelText(`${label} банковской операции 2`), { target: { value } });
  expect(changed.mock.lastCall?.[0].value).toBeNull();
  view.rerender(<BankPostingPolicyFields org="2" effectiveDate="2026-09-01" onChange={changed} />);
  expect(changed.mock.lastCall?.[0]).toEqual({ scope: "2:2026-09-01", enabled: false, value: null });
});
it("holds accounts returned for another organization", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => accounts.map(a => ({ ...a, organization_id: 2 })) }));
  const changed = vi.fn();
  render(<BankPostingPolicyFields org="1" effectiveDate="2026-09-01" onChange={changed} />);
  fireEvent.click(screen.getByLabelText("Настроить правила банковских операций"));
  expect(await screen.findByRole("alert")).toHaveTextContent("выбранного юрлица");
  expect(changed.mock.lastCall?.[0].value).toBeNull();
});
it("does not admit account rows with missing role flags", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [{ organization_id: 1, code: "60", title: "Broken", category: "liability" }] }));
  const changed = vi.fn(); render(<BankPostingPolicyFields org="1" effectiveDate="2026-09-01" onChange={changed} />);
  fireEvent.click(screen.getByLabelText("Настроить правила банковских операций"));
  expect(await screen.findByRole("alert")).toHaveTextContent("выбранного юрлица");
  expect(changed.mock.lastCall?.[0].value).toBeNull();
});
