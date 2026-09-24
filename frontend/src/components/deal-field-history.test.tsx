import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { DealFieldHistory } from "./deal-field-history";

afterEach(() => vi.unstubAllGlobals());

it("shows the exact deal's author, time and field values before and after", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    deal_id: 7, next_before_id: null, items: [{ id: 5, actor: "manager", changed_at: "2026-09-24T13:00:00",
      deal_number: "CRM-7", organization_id: null,
      changes: { title: { before: "Старое", after: "Новое" }, amount: { before: "10.00", after: "12.00" } } }],
  }) });
  vi.stubGlobal("fetch", fetchMock);
  render(<DealFieldHistory dealId="7" />);
  fireEvent.click(screen.getByRole("button", { name: "История изменений" }));
  expect(await screen.findByText("Описание: было «Старое», стало «Новое».")).toBeInTheDocument();
  expect(screen.getByText("Сумма: было «10.00», стало «12.00».")).toBeInTheDocument();
  expect(screen.getByText("Сделка CRM-7 · 2026-09-24T13:00:00 · manager")).toBeInTheDocument();
  expect(screen.getByText("Юрлицо на момент правки не установлено.")).toBeInTheDocument();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/sales/deals/7/field-history?limit=20");
  fireEvent.click(screen.getByRole("button", { name: "История изменений" }));
  fireEvent.click(screen.getByRole("button", { name: "История изменений" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
});

it("does not display a response for another deal", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    deal_id: 8, next_before_id: null, items: [],
  }) }));
  render(<DealFieldHistory dealId="7" />);
  fireEvent.click(screen.getByRole("button", { name: "История изменений" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("история другой сделки");
  expect(screen.queryByText("Записанных изменений пока нет.")).toBeNull();
  await waitFor(() => expect(screen.getByRole("button", { name: "Повторить" })).toBeEnabled());
});
