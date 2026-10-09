import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { saleAccountFields, SalesPostingPolicyFields } from "./sales-posting-policy-fields";

afterEach(() => vi.unstubAllGlobals());
const rows = saleAccountFields.map(([, label, code, category]) => ({ organization_id: 1, code, title: label, category, cash: false, quantity_tracking: false }));
const reply = (data: unknown) => ({ ok: true, json: async () => data });

it("requires five explicitly chosen compatible accounts and resets organization scope", async () => {
  const onChange = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(rows)));
  const view = render(<SalesPostingPolicyFields org="1" effectiveDate="2026-09-01" onChange={onChange} />);
  expect(onChange).toHaveBeenLastCalledWith({ scope: "1:2026-09-01", enabled: false, value: null });
  fireEvent.click(screen.getByLabelText("Настроить счета реализации"));
  await screen.findByRole("option", { name: "62 · Покупатель" });
  expect(onChange).toHaveBeenLastCalledWith({ scope: "1:2026-09-01", enabled: true, value: null });
  for (const [, label] of saleAccountFields) expect(screen.getByLabelText(`Автоматический счёт реализации · ${label}`)).toHaveValue("");
  for (const [, label, code] of saleAccountFields) fireEvent.change(screen.getByLabelText(`Автоматический счёт реализации · ${label}`), { target: { value: code } });
  await waitFor(() => expect(onChange.mock.lastCall?.[0].value).toEqual(Object.fromEntries(saleAccountFields.map(([field, , code]) => [field, code]))));
  view.rerender(<SalesPostingPolicyFields org="2" effectiveDate="2026-09-01" onChange={onChange} />);
  expect(screen.getByLabelText("Настроить счета реализации")).not.toBeChecked();
  expect(onChange).toHaveBeenLastCalledWith({ scope: "2:2026-09-01", enabled: false, value: null });
});

it.each(["foreign", "missing-flag", "cash", "quantitative", "wrong-role"])("does not admit %s accounts", async kind => {
  const onChange = vi.fn();
  const values = rows.map(row => ({ ...row,
    ...(kind === "foreign" ? { organization_id: 2 } : {}),
    ...(kind === "missing-flag" ? { cash: undefined } : {}),
    ...(kind === "cash" ? { cash: true } : {}),
    ...(kind === "quantitative" ? { quantity_tracking: true } : {}),
    ...(kind === "wrong-role" ? { category: "equity" } : {}),
  }));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(values)));
  render(<SalesPostingPolicyFields org="1" effectiveDate="2026-09-01" onChange={onChange} />);
  await act(async () => fireEvent.click(screen.getByLabelText("Настроить счета реализации")));
  expect(onChange).toHaveBeenLastCalledWith({ scope: "1:2026-09-01", enabled: true, value: null });
  expect(screen.queryByRole("option", { name: "62 · Покупатель" })).toBeNull();
});
