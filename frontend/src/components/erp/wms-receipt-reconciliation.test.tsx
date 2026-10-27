import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WmsReceiptReconciliation } from "./wms-receipt-reconciliation";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const receipt = { id: 7, number: "ПРМ-7", counterparty: "Поставщик", warehouse: "Склад", entity_ref: "purchase:7" };
const json = (body: unknown) => ({ ok: true, json: async () => body }) as Response;

it("requires reviewed detail and evidence, locks organization during assignment, then refreshes queue", async () => {
  let finish!: (value: Response) => void;
  let assigned = false;
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("receipt-organizations")) return json([{ id: 1, name: "Компания", unp: "999999999" }]);
    if (url.includes("receipts-unassigned/7")) return json({ ...receipt, lines: [{ id: 1, sku_code: "A", sku_title: "Товар", expected_qty: "1.25" }] });
    if (init?.method === "POST") return new Promise<Response>((resolve) => { finish = resolve; });
    return json({ items: assigned ? [] : [receipt], next_after_id: null });
  });
  vi.stubGlobal("fetch", mock);
  render(<WmsReceiptReconciliation />);
  await screen.findByRole("option", { name: /Компания/ });
  expect(mock).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText("Юрлицо для подтверждения"), { target: { value: "1" } });
  fireEvent.click(await screen.findByRole("button", { name: "Проверить № 7" }));
  await screen.findByText("A · Товар · 1.25");
  expect(screen.getByRole("button", { name: "Подтвердить владельца" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Основание принадлежности"), { target: { value: "Накладная проверена" } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить владельца" }));
  expect(screen.getByLabelText("Юрлицо для подтверждения")).toBeDisabled();
  const post = mock.mock.calls.find((call) => call[1]?.method === "POST")!;
  expect(JSON.parse(post[1]!.body as string)).toEqual({ organization_id: 1, evidence: "Накладная проверена" });
  assigned = true; finish(json({ ...receipt, organization_id: 1 }));
  await screen.findByText("Нет документов для сопоставления.");
  await waitFor(() => expect(screen.getByLabelText("Юрлицо для подтверждения")).not.toBeDisabled());
  expect(screen.queryByRole("region", { name: "Проверка владельца приёмки" })).not.toBeInTheDocument();
});

it("shows access errors without claiming the queue is empty", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("receipt-organizations") ? json([{ id: 1, name: "Компания", unp: "9" }]) : { ok: false, status: 403 }));
  render(<WmsReceiptReconciliation />);
  await screen.findByRole("option", { name: /Компания/ });
  fireEvent.change(screen.getByLabelText("Юрлицо для подтверждения"), { target: { value: "1" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Нужны права главбуха");
  expect(screen.queryByText("Нет документов для сопоставления.")).not.toBeInTheDocument();
});
it.each([{ id: 8, organization_id: 1 }, { id: 7, organization_id: 2 }])("does not accept a mismatched assignment response %j", async (saved) => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("receipt-organizations")) return json([{ id: 1, name: "Компания", unp: "9" }]);
    if (init?.method === "POST") return json(saved);
    if (url.includes("receipts-unassigned/7")) return json({ ...receipt, lines: [] });
    return json({ items: [receipt], next_after_id: null });
  }));
  render(<WmsReceiptReconciliation />);
  await screen.findByRole("option", { name: /Компания/ });
  fireEvent.change(screen.getByLabelText("Юрлицо для подтверждения"), { target: { value: "1" } });
  fireEvent.click(await screen.findByRole("button", { name: "Проверить № 7" }));
  fireEvent.change(await screen.findByLabelText("Основание принадлежности"), { target: { value: "Проверенная накладная" } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить владельца" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Ответ не подтверждает владельца");
  expect(screen.queryByText("Владелец подтверждён. Документ исключён из очереди.")).not.toBeInTheDocument();
});
