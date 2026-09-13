import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingInvoiceMoneyReconciliation } from "./accounting-invoice-money-reconciliation";
import { confirmMoneyHistory, fetchMoneyReview, type MoneyReview } from "@/lib/invoice-money-reconciliation-api";

afterEach(() => vi.unstubAllGlobals());
const digest = "a".repeat(64);
const review: MoneyReview = { organization_id: 7, document_id: 77, review_date: "2026-09-09", basis_digest: digest, money_state: "no_receipts", blockers: [], required_history_from: "2026-09-01", required_history_through: "2026-09-09", can_confirm_money_history: true, fulfillment_required: true, records: [] };
const receipt = { id: 4, organization_id: 7, document_id: 77, basis_digest: digest, history_from: "2026-09-01", history_through: "2026-09-09", actor: "chief", created_at: "2026-09-09T12:00:00Z", evidence: "Выписки проверены", source_references: ["Банк 1", "Касса 2"] };
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
const fail = (status: number) => ({ ok: false, status });
function deferred() { let resolve!: (v: unknown) => void; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }
function props() { return { org: "7", document: "77", acquire: vi.fn(() => true), release: vi.fn(), onBusyChange: vi.fn() }; }
function launch() { fireEvent.click(screen.getByRole("button", { name: "Открыть сверку денежной истории" })); }
async function fill() {
  await screen.findByLabelText("Ключ сверки");
  for (const [label, value] of [["Ключ сверки", "review-1"], ["Основание сверки", "Выписки проверены"], ["Документальные ссылки", "Банк 1\nКасса 2"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByLabelText("Все денежные источники проверены"));
}
const submit = () => fireEvent.click(screen.getByRole("button", { name: "Подтвердить денежную историю" }));

it("loads only after explicit open; checkbox and evidence never auto-confirm", async () => {
  const f = vi.fn().mockResolvedValue(ok(review)); vi.stubGlobal("fetch", f); render(<AccountingInvoiceMoneyReconciliation {...props()} />); expect(f).not.toHaveBeenCalled(); launch();
  expect(await screen.findByLabelText("Все денежные источники проверены")).not.toBeChecked(); expect(screen.getByLabelText("Ключ сверки")).toHaveValue(""); expect(screen.getByRole("button", { name: "Подтвердить денежную историю" })).toBeDisabled();
  expect(f.mock.calls[0][0]).toBe("/api/sales/organizations/7/invoices/77/money-reconciliation"); expect(screen.queryByRole("button", { name: /Отменить счёт/ })).not.toBeInTheDocument();
});
it.each(["funds_held", "history_unknown", "future"])("blocks %s history", async (state) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ...review, money_state: state === "future" ? "fully_refunded" : state, required_history_through: state === "future" ? "2026-09-10" : "2026-09-09", can_confirm_money_history: false, blockers: [state === "future" ? "future_money_history_requires_review" : "test_blocker"] })));
  render(<AccountingInvoiceMoneyReconciliation {...props()} />); launch(); expect(await screen.findByLabelText("Все денежные источники проверены")).toBeDisabled(); expect(screen.getByRole("button", { name: "Подтвердить денежную историю" })).toBeDisabled();
});
it.each(["no_receipts", "fully_refunded"])("allows documentary confirmation of %s but receipt alone is not current", async (state) => {
  const pending = deferred(); const r = { ...review, money_state: state };
  const f = vi.fn().mockResolvedValueOnce(ok(r)).mockResolvedValueOnce(ok(r)).mockResolvedValueOnce(ok(receipt)).mockReturnValueOnce(pending.promise); vi.stubGlobal("fetch", f);
  render(<AccountingInvoiceMoneyReconciliation {...props()} />); launch(); await fill(); submit(); await screen.findByText(/Сверка № 4 сохранена. Проверяем/);
  expect(screen.queryByText(/Актуальна на момент/)).not.toBeInTheDocument();
  await act(async () => pending.resolve(ok({ ...r, records: [{ ...receipt, current: true }] }))); await screen.findByText(/Сверка № 4 · Актуальна на момент/);
  expect(screen.getByText(/не разрешает отмену счёта/)).toBeInTheDocument();
});
it.each(["day", "digest", "blocked"])("preflight %s change requires fresh review without POST", async (kind) => {
  const changed = { ...review, ...(kind === "day" ? { review_date: "2026-09-10", required_history_through: "2026-09-10" } : kind === "digest" ? { basis_digest: "b".repeat(64) } : { can_confirm_money_history: false, blockers: ["new_blocker"] }) };
  const f = vi.fn().mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok(changed)); vi.stubGlobal("fetch", f); const p = props(); render(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); await fill(); submit();
  await screen.findByText(/Факты или серверный день изменились/); expect(screen.getByLabelText("Все денежные источники проверены")).not.toBeChecked(); expect(f.mock.calls.every(([, init]) => init.method === "GET")).toBe(true); expect(p.onBusyChange).toHaveBeenLastCalledWith(false);
});
it.each([403, 404, 409, 422])("first POST %s invalidates review and releases lock", async (status) => {
  const f = vi.fn().mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(fail(status)).mockResolvedValueOnce(ok(review)); vi.stubGlobal("fetch", f); const p = props(); render(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); await fill(); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`); expect(screen.queryByLabelText("Ключ сверки")).not.toBeInTheDocument(); expect(p.onBusyChange).toHaveBeenLastCalledWith(false);
  fireEvent.click(screen.getByRole("button", { name: "Обновить сверку" })); expect(await screen.findByLabelText("Все денежные источники проверены")).not.toBeChecked();
});
it.each(["network", "5xx", "malformed"])("uncertain %s freezes same payload; subsequent 403 cannot release uncertainty", async (kind) => {
  const f = vi.fn().mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok(review));
  if (kind === "network") f.mockRejectedValueOnce(new TypeError("offline")); else f.mockResolvedValueOnce(kind === "5xx" ? fail(503) : ok({ id: 4 }));
  f.mockResolvedValueOnce(fail(403)).mockResolvedValueOnce(ok(receipt)).mockResolvedValueOnce(ok({ ...review, review_date: "2026-09-10", required_history_through: "2026-09-10", records: [{ ...receipt, current: false }] })); vi.stubGlobal("fetch", f);
  const p = props(); render(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); await fill(); submit();
  fireEvent.click(await screen.findByRole("button", { name: "Повторить сверку с тем же ключом" })); expect(await screen.findByRole("alert")).toHaveTextContent("403:"); expect(p.onBusyChange).toHaveBeenLastCalledWith(true); expect(screen.getByLabelText("Ключ сверки")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить сверку с тем же ключом" })); await screen.findByText(/Сверка № 4 · Требуется новая сверка/);
  const posts = f.mock.calls.filter(([, init]) => init.method === "POST"); expect(posts).toHaveLength(3); expect(new Set(posts.map(([, init]) => init.body)).size).toBe(1); expect(p.onBusyChange).toHaveBeenLastCalledWith(false);
});
it("double click issues one preflight and POST", async () => {
  const pending = deferred(); const f = vi.fn().mockResolvedValueOnce(ok(review)).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ok(receipt)).mockResolvedValueOnce(ok(review)); vi.stubGlobal("fetch", f);
  render(<AccountingInvoiceMoneyReconciliation {...props()} />); launch(); await fill(); const button = screen.getByRole("button", { name: "Подтвердить денежную историю" }); act(() => { fireEvent.click(button); fireEvent.click(button); }); expect(f).toHaveBeenCalledTimes(2);
  await act(async () => pending.resolve(ok(review))); await screen.findByRole("button", { name: "Новая сверка" }); expect(f.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1);
});
it("receipt followed by GET failure does not assert current or empty records", async () => {
  const f = vi.fn().mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok(receipt)).mockResolvedValueOnce(fail(503)); vi.stubGlobal("fetch", f); const p = props(); render(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); await fill(); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("Запись сохранена, актуальность не проверена"); expect(screen.queryByText(/Актуальна на момент|Последние 0 записей/)).not.toBeInTheDocument(); expect(p.onBusyChange).toHaveBeenLastCalledWith(false);
});
it("focus rechecks server day and clears checkbox", async () => {
  const f = vi.fn().mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok({ ...review, review_date: "2026-09-10", required_history_through: "2026-09-10", records: [{ ...receipt, current: false }] })); vi.stubGlobal("fetch", f); render(<AccountingInvoiceMoneyReconciliation {...props()} />); launch(); await fill(); fireEvent.focus(window);
  await screen.findByText("Серверная дата проверки: 2026-09-10"); expect(screen.getByLabelText("Все денежные источники проверены")).not.toBeChecked(); expect(screen.getByText(/Требуется новая сверка/)).toBeInTheDocument();
});
it.each(["GET", "POST"])("ignores late %s after forced context change", async (kind) => {
  const pending = deferred(); const f = vi.fn(); if (kind === "GET") f.mockReturnValueOnce(pending.promise); else f.mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok(review)).mockReturnValueOnce(pending.promise);
  vi.stubGlobal("fetch", f); const p = props(); const view = render(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); if (kind === "POST") { await fill(); submit(); await waitFor(() => expect(f).toHaveBeenCalledTimes(3)); }
  view.rerender(<AccountingInvoiceMoneyReconciliation {...p} org="8" document="88" />); await act(async () => pending.resolve(ok(kind === "GET" ? review : receipt)));
  expect(screen.queryByText(/Сверка № 4|Серверная дата проверки/)).not.toBeInTheDocument();
});
it("does not fetch invalid identity and preflight network error releases ownership without POST", async () => {
  const f = vi.fn().mockResolvedValueOnce(ok(review)).mockRejectedValueOnce(new TypeError("offline")); vi.stubGlobal("fetch", f); const p = props(); const view = render(<AccountingInvoiceMoneyReconciliation {...p} document="" />);
  expect(screen.getByRole("button", { name: "Открыть сверку денежной истории" })).toBeDisabled(); expect(f).not.toHaveBeenCalled(); view.rerender(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); await fill(); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("сеть недоступна"); expect(p.onBusyChange).toHaveBeenLastCalledWith(false); expect(f.mock.calls.every(([, init]) => init.method === "GET")).toBe(true);
});
it("does not preflight or POST when another mutation owns the same-tick guard", async () => {
  const f = vi.fn().mockResolvedValue(ok(review)); vi.stubGlobal("fetch", f); const p = { ...props(), acquire: vi.fn(() => false) }; render(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); await fill(); submit(); expect(f).toHaveBeenCalledOnce(); expect(p.onBusyChange).not.toHaveBeenCalledWith(true);
});
it("foreign receipt does not unlock or establish success, and sends strict boolean", async () => {
  const f = vi.fn().mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok(review)).mockResolvedValueOnce(ok({ ...receipt, document_id: 88 })); vi.stubGlobal("fetch", f); const p = props(); render(<AccountingInvoiceMoneyReconciliation {...p} />); launch(); await fill(); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("другой счёт/юрлицо"); expect(p.onBusyChange).toHaveBeenLastCalledWith(true); expect(screen.queryByRole("button", { name: "Новая сверка" })).not.toBeInTheDocument(); expect(JSON.parse(f.mock.calls[2][1].body).all_money_sources_checked).toBe(true);
});
it.each(["string boolean", "duplicate references", "bad date"])("API rejects invalid confirmation %s before network", async (kind) => {
  const f = vi.fn(); vi.stubGlobal("fetch", f);
  await expect(confirmMoneyHistory("7", "77", { source_key: "R1", expected_basis_digest: digest, history_from: "2026-09-01", history_through: kind === "bad date" ? "2026-02-31" : "2026-09-09", evidence: "Checked", source_references: kind === "duplicate references" ? ["A", "A"] : ["A"], all_money_sources_checked: kind === "string boolean" ? "true" as unknown as boolean : true })).rejects.toThrow(); expect(f).not.toHaveBeenCalled();
});
it.each([403, 404, 409, 503])("GET %s remains an error", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fail(status))); render(<AccountingInvoiceMoneyReconciliation {...props()} />); launch(); expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`); expect(screen.queryByText(/Последние 0/)).not.toBeInTheDocument();
});
it.each(["organization", "document", "date", "record", "falsecurrent"])("rejects invalid response %s", async (kind) => {
  const bad = { ...review, ...(kind === "organization" ? { organization_id: 8 } : kind === "document" ? { document_id: 88 } : kind === "date" ? { review_date: "2026-02-31" } : { records: [{ ...receipt, document_id: kind === "record" ? 88 : 77, basis_digest: kind === "falsecurrent" ? "b".repeat(64) : digest, current: true }] }) };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok(bad))); await expect(fetchMoneyReview("7", "77")).rejects.toThrow(/Некорректный ответ/);
});
it.each(["unchecked", "duplicate", "empty", "future", "short"])("rejects invalid form %s without preflight", async (kind) => {
  const f = vi.fn().mockResolvedValue(ok(review)); vi.stubGlobal("fetch", f); render(<AccountingInvoiceMoneyReconciliation {...props()} />); launch(); await fill();
  if (kind === "unchecked") fireEvent.click(screen.getByLabelText("Все денежные источники проверены"));
  else if (kind === "duplicate" || kind === "empty") fireEvent.change(screen.getByLabelText("Документальные ссылки"), { target: { value: kind === "duplicate" ? "same\nsame" : " " } });
  else fireEvent.change(screen.getByLabelText("История по"), { target: { value: kind === "future" ? "2026-09-10" : "2026-09-08" } });
  expect(screen.getByRole("button", { name: "Подтвердить денежную историю" })).toBeDisabled(); expect(f).toHaveBeenCalledOnce();
});
