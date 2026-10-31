import { webcrypto } from "node:crypto";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { OfficeShippingWorkspace } from "@/components/erp/office-shipping-workspace";
import { hash } from "@/lib/expense-control-api";
import type { ConfirmCommand, PrepareCommand, ShippingContext } from "@/lib/office-shipping-api";
import { documentFixture, invoice, shippingFixture } from "@/test/office-shipping-fixtures";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const json = (v: unknown, status = 200) => Response.json(v, { status });
async function fillPreparation() {
  await screen.findByLabelText(/^Вес, кг/);
  for (const [label, value] of [[/^Вес, кг/, "700,5"], [/^Объявленная стоимость/, "4000"], [/^Пункт отправления/, "Минск"], [/^Желаемая дата забора/, "2026-11-03"], [/^Контакт для забора/, "Учебный контакт"], [/^Код перевозчика/, "synthetic-carrier"], [/^Название перевозчика/, "Учебный перевозчик"], [/^Комментарий/, "Перед забором проверить упаковку"]] as const)
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("checkbox", { name: /Я сверил условия/ }));
}
async function savedPreparation(body: PrepareCommand) {
  const value = await shippingFixture({ prepared: true });
  value.request!.request_key = body.request_key; value.request!.payload.intent = body.intent;
  value.request!.payload_sha256 = await hash(value.request!.payload);
  return value;
}
function install(source: () => ShippingContext, post?: (url: string, init: RequestInit) => Promise<Response>) {
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") return post ? post(url, init) : json({}, 500);
    if (url.endsWith("/shipping-source")) return json(source());
    if (url === "/api/office/carriers") return json([]);
    return json({}, 404);
  }); vi.stubGlobal("fetch", fetcher); return fetcher;
}
it("prepares the complete reviewed intent and shows only the subsequently verified saved result", async () => {
  let current = await shippingFixture();
  let finish: (() => Promise<void>) | undefined;
  const fetcher = install(() => current, async (_url, init) => new Promise<Response>(resolve => {
    const body = JSON.parse(String(init.body)) as PrepareCommand;
    finish = async () => { current = await savedPreparation(body); resolve(json(current.request)); };
  }));
  render(<OfficeShippingWorkspace document={documentFixture()} />); await fillPreparation();
  fireEvent.click(screen.getByRole("button", { name: "Подготовить заявку" }));
  await waitFor(() => expect(finish).toBeDefined());
  expect(screen.queryByText("Заявка сохранена")).not.toBeInTheDocument();
  expect(sessionStorage.length).toBe(1);
  await finish!();
  expect(await screen.findByText("Заявка сохранена")).toBeInTheDocument();
  const calls = fetcher.mock.calls.filter(([, init]) => init?.method === "POST"); expect(calls).toHaveLength(1);
  const body = JSON.parse(String(calls[0][1]?.body)) as PrepareCommand;
  expect(body.intent).toMatchObject({ weight_kg: "700.50", declared_value_byn: "4000.00", pickup_date: "2026-11-03", contact: "Учебный контакт", comment: "Перед забором проверить упаковку" });
  expect(body.expected_assignment_revision).toBe(1); expect(sessionStorage.length).toBe(0);
});
it("recovers an uncertain preparation across reload and retries only the exact saved command on explicit action", async () => {
  let current = await shippingFixture(); let attempts = 0;
  const fetcher = install(() => current, async (_url, init) => {
    attempts += 1; if (attempts === 1) throw new TypeError("offline");
    current = await savedPreparation(JSON.parse(String(init.body)) as PrepareCommand); return json(current.request);
  });
  const view = render(<OfficeShippingWorkspace document={documentFixture()} />); await fillPreparation();
  fireEvent.click(screen.getByRole("button", { name: "Подготовить заявку" }));
  await screen.findByRole("button", { name: "Повторить тот же запрос" });
  expect(attempts).toBe(1); view.unmount();
  render(<OfficeShippingWorkspace document={documentFixture()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Повторить тот же запрос" }));
  await screen.findByText("Заявка сохранена");
  const calls = fetcher.mock.calls.filter(([, init]) => init?.method === "POST"); expect(calls).toHaveLength(2);
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body); expect(sessionStorage.length).toBe(0);
});
it("does not send a mutation when the exact command cannot be retained for recovery", async () => {
  const current = await shippingFixture(); const fetcher = install(() => current);
  const storage = sessionStorage;
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => storage.getItem(key),
    setItem: () => { throw new Error("disabled"); },
    removeItem: (key: string) => storage.removeItem(key),
  });
  render(<OfficeShippingWorkspace document={documentFixture()} />); await fillPreparation();
  fireEvent.click(screen.getByRole("button", { name: "Подготовить заявку" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Отправка не выполнена");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});
it("keeps the original UNKNOWN journal after a rejected retry until a late exact result is observed", async () => {
  let current = await shippingFixture(), attempts = 0;
  let original: PrepareCommand | undefined;
  install(() => current, async (_url, init) => {
    attempts += 1;
    if (attempts === 1) { original = JSON.parse(String(init.body)) as PrepareCommand; throw new TypeError("lost response"); }
    current = { ...current, capabilities: { can_request: false, can_associate: false } };
    return json({}, 403);
  });
  render(<OfficeShippingWorkspace document={documentFixture()} />); await fillPreparation();
  fireEvent.click(screen.getByRole("button", { name: "Подготовить заявку" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Повторить тот же запрос" })).not.toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Повторить тот же запрос" }));
  await waitFor(() => expect(attempts).toBe(2));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Недостаточно прав"));
  await screen.findByText("Сохранённая команда ожидает сверки"); expect(sessionStorage.length).toBe(1);
  current = await savedPreparation(original!);
  fireEvent.click(screen.getByRole("button", { name: "Проверить состояние" }));
  expect(await screen.findByText("Результат подтверждён сохранёнными данными сервера.")).toBeInTheDocument();
  expect(sessionStorage.length).toBe(0); expect(attempts).toBe(2);
});
it("keeps a paid document's planned shipment distinct from physical delivery and handles nullable ETA", async () => {
  const current = await shippingFixture({ resolved: true, stage: "paid" }); install(() => current);
  render(<OfficeShippingWorkspace document={documentFixture()} />);
  expect(await screen.findByText("Запланирована")).toBeInTheDocument();
  expect(screen.queryByText("Доставлена")).not.toBeInTheDocument();
  expect(screen.getAllByText("Нет подтверждённых данных").length).toBeGreaterThan(0);
});
it("preserves current reviewer restrictions and provides a real authorized handoff", async () => {
  const current = await shippingFixture({ prepared: true });
  current.is_current_reviewer = false; current.capabilities = { can_request: false, can_associate: false };
  const fetcher = install(() => current); render(<OfficeShippingWorkspace document={documentFixture()} />);
  expect(await screen.findByText(/Передайте сохранённую заявку руководителю/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Юридическое лицо")).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => String(url) === "/api/accounting/organizations")).toBe(false);
});
it("does not adopt a late context from another selected Office document", async () => {
  const old = await shippingFixture(), next = await shippingFixture({ id: 16 }); next.source_snapshot = { ...next.source_snapshot, company: "Второй учебный покупатель" }; next.source_sha256 = await hash(next.source_snapshot);
  let finish: ((response: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async input => {
    const url = String(input);
    if (url.includes("/docs/15/")) return new Promise<Response>(resolve => { finish = resolve; });
    if (url.includes("/docs/16/")) return json(next);
    return json([]);
  }));
  const view = render(<OfficeShippingWorkspace document={documentFixture()} />);
  await waitFor(() => expect(finish).toBeDefined()); view.rerender(<OfficeShippingWorkspace document={documentFixture(16)} />);
  expect(await screen.findByLabelText("Заказчик *")).toHaveValue("Второй учебный покупатель");
  finish!(json(old));
  await waitFor(() => expect(screen.getByLabelText("Заказчик *")).toHaveValue("Второй учебный покупатель"));
});
it("selects an explicit MDM buyer and exact invoice, previews without mutation, confirms separately, then observes internal execution", async () => {
  let current = await shippingFixture({ prepared: true }); let previewBody: ConfirmCommand | null = null;
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/shipping-source")) return json(current);
    if (url === "/api/accounting/organizations") return json([{ id: 7, name: "Учебное юрлицо", unp: "190000007" }]);
    if (url.includes("/sales/buyers?")) return json({ organization_id: 7, items: [{ id: 8, name: "Учебный покупатель", unp: "190000008", revision: 1 }] });
    if (url.includes("/settlement-documents?")) return json({ organization_id: 7, counterparty_id: 8, items: [{ source: "sales", id: 22, number: "УЧ-СЧЁТ-22", version: 3, reference: "sales:document:22", content_sha256: invoice.expected_content_sha256 }] });
    if (url.endsWith("shipping-association-preview")) { previewBody = JSON.parse(String(init?.body)) as ConfirmCommand; return json({ ...current.request, exact_invoice: invoice, intent_digest: previewBody.expected_intent_digest, assignment_revision: 1, verified_invoice: { deal_id: 9 } }); }
    if (url.endsWith("shipping-association-confirm")) {
      expect(init?.body).toBe(JSON.stringify(previewBody));
      const body = JSON.parse(String(init?.body)) as ConfirmCommand; const next = await shippingFixture({ associated: true });
      next.association!.request_key = body.request_key; current = next;
      return json({ association_id: current.association!.association_id, execution_id: current.association!.execution_id, intent_digest: current.association!.intent_digest, replayed: false });
    }
    if (url.endsWith("/intakes/42/resolve")) { current = await shippingFixture({ resolved: true }); return json({ id: 42, state: "resolved", shipment_id: 91, rfq_id: null }); }
    return json({}, 404);
  }); vi.stubGlobal("fetch", fetcher);
  render(<OfficeShippingWorkspace document={documentFixture()} />);
  const book = await screen.findByLabelText("Юридическое лицо"); await waitFor(() => expect(book).not.toBeDisabled()); fireEvent.change(book, { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Покупатель по имени или УНП"), { target: { value: "190000008" } }); fireEvent.click(screen.getByRole("button", { name: "Найти покупателя" }));
  fireEvent.change(await screen.findByLabelText("Точный покупатель"), { target: { value: "8" } });
  fireEvent.change(screen.getByLabelText("Номер счёта или ID"), { target: { value: "УЧ-СЧЁТ" } }); fireEvent.click(screen.getByRole("button", { name: "Найти счёт" }));
  fireEvent.change(await screen.findByLabelText("Счёт покупателя"), { target: { value: "22" } });
  fireEvent.change(screen.getByLabelText(/Основание связи/), { target: { value: "Сверены оригиналы учебного счёта и заявки" } });
  fireEvent.click(screen.getByRole("button", { name: "Сверить счёт и условия" }));
  await screen.findByText("Проверьте перед подтверждением");
  expect(current.association).toBeNull(); expect(sessionStorage.length).toBe(0);
  fireEvent.click(screen.getByRole("checkbox", { name: /Счёт, покупатель и сохранённые условия/ }));
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить связь со счётом" }));
  expect(await screen.findByText("Связь подтверждена")).toBeInTheDocument(); expect(sessionStorage.length).toBe(0);
  fireEvent.click(screen.getByRole("button", { name: "Обработать заявку в логистике" }));
  expect(await screen.findByText("УЧ-ЛОГ-91")).toBeInTheDocument(); expect(screen.getByText("Запланирована")).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(3);
});
