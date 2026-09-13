import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingView } from "./accounting-view";

afterEach(() => vi.unstubAllGlobals());
const review = { organization_id: 7, document_id: 77, review_date: "2026-09-09", basis_digest: "a".repeat(64), money_state: "no_receipts", blockers: [], required_history_from: "2026-09-01", required_history_through: "2026-09-09", can_confirm_money_history: true, fulfillment_required: true, records: [] };
const receipt = { id: 4, organization_id: 7, document_id: 77, basis_digest: review.basis_digest, history_from: "2026-09-01", history_through: "2026-09-09", actor: "chief", created_at: "2026-09-09", evidence: "Проверено", source_references: ["Выписка"] };
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
function deferred() { let resolve!: (v: unknown) => void; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }
function api(post: (url: string, body?: string) => unknown) {
  return vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "POST") return post(url, init.body as string);
    if (url === "/api/accounting/organizations") return Promise.resolve(ok([{ id: 7, name: "A", unp: "111" }, { id: 8, name: "B", unp: "222" }]));
    if (url.includes("/reports?")) return Promise.resolve(ok({ pending_documents: 0 }));
    if (url.endsWith("/settlements")) return Promise.resolve(ok({ received: "0", refunded: "0", net_received: "0", cancellation_authorized: false, reconciliation_required: true, items: [] }));
    if (url.endsWith("/money-reconciliation")) return Promise.resolve(ok(review));
    return Promise.resolve(ok([]));
  });
}
async function open() {
  render(<AccountingView />); await screen.findByText(/включительно: 0\./); fireEvent.click(screen.getByRole("button", { name: "Открыть: Оплаты и возвраты счетов" }));
  fireEvent.change(screen.getByLabelText("ID счёта"), { target: { value: "77" } }); fireEvent.click(screen.getByRole("button", { name: "Открыть расчёты счёта" }));
  await screen.findByLabelText("Сумма распределения");
  for (const [label, value] of [["ID банковской проводки", "31"], ["Сумма распределения", "10.00"], ["Ключ распределения", "A1"], ["Первичное основание", "Выписка"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Открыть сверку денежной истории" })); await screen.findByLabelText("Ключ сверки");
  for (const [label, value] of [["Ключ сверки", "R1"], ["Основание сверки", "Проверено"], ["Документальные ссылки", "Выписка"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByLabelText("Все денежные источники проверены"));
}
it("uncertain reconciliation locks allocation, selection and accounting navigation until receipt", async () => {
  const pending = deferred(); let calls = 0; const f = api(() => ++calls === 1 ? pending.promise : Promise.resolve(ok(receipt))); vi.stubGlobal("fetch", f); await open();
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить денежную историю" }));
  expect(screen.getByLabelText("Организация")).toBeDisabled(); expect(screen.getByLabelText("ID счёта")).toBeDisabled(); expect(screen.getByRole("button", { name: "Рабочее место" })).toBeDisabled(); expect(screen.getByRole("button", { name: "Подтвердить распределение" })).toBeDisabled(); expect(screen.getByRole("button", { name: "Обновить расчёты" })).toBeDisabled();
  await act(async () => pending.resolve({ ok: false, status: 503 })); await screen.findByRole("button", { name: "Повторить сверку с тем же ключом" });
  expect(screen.getByLabelText("Организация")).toBeDisabled(); expect(screen.getByLabelText("Номер счёта для поиска")).toBeDisabled(); expect(screen.getByLabelText("Ключ распределения")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить сверку с тем же ключом" })); await screen.findByRole("button", { name: "Новая сверка" }); expect(screen.getByLabelText("Организация")).toBeEnabled(); expect(screen.getByRole("button", { name: "Подтвердить распределение" })).toBeEnabled();
});
it("uncertain allocation blocks already open reconciliation without its read cleanup unlocking navigation", async () => {
  const pending = deferred(); vi.stubGlobal("fetch", api(() => pending.promise)); await open(); fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" }));
  expect(screen.getByRole("button", { name: "Подтвердить денежную историю" })).toBeDisabled(); await act(async () => pending.resolve({ ok: false, status: 503 }));
  expect(screen.getByLabelText("Организация")).toBeDisabled(); expect(screen.getByRole("button", { name: "Обновить сверку" })).toBeDisabled(); expect(screen.getByRole("button", { name: "Подтвердить денежную историю" })).toBeDisabled();
});
it.each(["allocation", "reconciliation"])("same-tick competing mutations: %s acquires sole ownership", async (first) => {
  const pending = deferred(); const f = api(() => pending.promise); vi.stubGlobal("fetch", f); await open();
  const a = screen.getByRole("button", { name: "Подтвердить распределение" }); const r = screen.getByRole("button", { name: "Подтвердить денежную историю" });
  act(() => { fireEvent.click(first === "allocation" ? a : r); fireEvent.click(first === "allocation" ? r : a); });
  await act(async () => {});
  const posts = f.mock.calls.filter(([, init]) => init?.method === "POST"); expect(posts).toHaveLength(1); expect(posts[0][0]).toMatch(first === "allocation" ? /\/settlements$/ : /\/money-reconciliation$/);
  await act(async () => pending.resolve({ ok: false, status: 503 })); expect(screen.getByLabelText("Организация")).toBeDisabled();
});
it("confirmed allocation refreshes money review and clears previous completeness checkbox", async () => {
  vi.stubGlobal("fetch", api(() => Promise.resolve(ok({ id: 6, direction: "receipt", amount: "10.00" })))); await open();
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" })); await screen.findByText("Распределение № 6 подтверждено.");
  await act(async () => {}); expect(screen.getByLabelText("Все денежные источники проверены")).not.toBeChecked(); expect(screen.getByRole("button", { name: "Подтвердить денежную историю" })).toBeDisabled();
});
it("late money GET predating an allocation cannot replace the refreshed facts", async () => {
  const stale = deferred(); const base = api(() => Promise.resolve(ok({ id: 6, direction: "receipt", amount: "10.00" }))); let reads = 0;
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("money-reconciliation") && init?.method !== "POST") {
      reads += 1; if (reads === 2) return stale.promise;
      if (reads >= 3) return Promise.resolve(ok({ ...review, money_state: "funds_held", can_confirm_money_history: false, blockers: ["funds_not_fully_refunded"] }));
    }
    return base(url, init);
  }));
  await open(); fireEvent.focus(window); fireEvent.click(screen.getByRole("button", { name: "Подтвердить распределение" })); await screen.findByText("Полученные средства возвращены не полностью.");
  await act(async () => stale.resolve(ok(review))); expect(screen.getByText("Полученные средства возвращены не полностью.")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Подтвердить денежную историю" })).toBeDisabled();
});
