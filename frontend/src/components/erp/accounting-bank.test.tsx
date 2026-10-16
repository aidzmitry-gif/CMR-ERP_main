import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingBank } from "./accounting-bank";

afterEach(() => vi.unstubAllGlobals());

it("uses the latest report period callback when confirmation finishes late", async () => {
  let resolveConfirm!: (value: unknown) => void;
  const pending = new Promise((resolve) => { resolveConfirm = resolve; });
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ lines: [] }) }).mockReturnValueOnce(pending);
  vi.stubGlobal("fetch", fetchMock);
  const oldPeriod = vi.fn(), newPeriod = vi.fn();
  const props = { org: "7", accounts: [{ code: "51", title: "Банк", cash: true, category: "asset", required_dimensions: [] }, { code: "62", title: "Покупатели", cash: false, category: "asset", required_dimensions: [] }], policyId: 4, date: "2026-09-01", onDate: vi.fn() };
  const view = render(<AccountingBank {...props} onPosted={oldPeriod} />);
  for (const [label, value] of [["Банковский источник", "statement-line1"], ["Банковская выписка", "Выписка1"], ["Банковская сумма", "123.45"], ["Назначение платежа", "Оплата покупателя"], ["Банковский счёт", "51"], ["Счёт расчётов", "62"], ["Поток платежа", "operating"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByText("Рассчитать банковские проводки"));
  fireEvent.click(await screen.findByText("Подтвердить банковскую операцию"));
  view.rerender(<AccountingBank {...props} onPosted={newPeriod} />);
  await act(async () => { resolveConfirm({ ok: true, json: async () => ({ id: 3 }) }); });
  expect(oldPeriod).not.toHaveBeenCalled();
  expect(newPeriod).toHaveBeenCalledOnce();
});
it("previews exact bank amounts and confirms the same source document", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 3, lines: [{ account: "51", side: "debit", title: "Банк", amount: "123.45" }] }) });
  vi.stubGlobal("fetch", fetchMock);
  const onPosted = vi.fn();
  render(<AccountingBank org="7" accounts={[{ code: "51", title: "Банк", cash: true, category: "asset", required_dimensions: [] }, { code: "62", title: "Покупатели", cash: false, category: "asset", required_dimensions: [] }]} policyId={4} date="2026-09-01" onDate={vi.fn()} onPosted={onPosted} />);
  for (const [label, value] of [["Банковский источник", "statement-line1"], ["Банковская выписка", "Выписка1"], ["Банковская сумма", "123.45"], ["Назначение платежа", "Оплата покупателя"], ["Банковский счёт", "51"], ["Счёт расчётов", "62"], ["Поток платежа", "operating"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  expect(screen.queryByText("Подтвердить банковскую операцию")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Рассчитать банковские проводки"));
  fireEvent.click(await screen.findByText("Подтвердить банковскую операцию"));
  await screen.findByText("Банковская операция № 3 проведена.");
  expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).amount).toBe("123.45");
  expect(onPosted).toHaveBeenCalledOnce();
});
