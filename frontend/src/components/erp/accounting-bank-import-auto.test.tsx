import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingBankImport } from "./accounting-bank-import";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const source = { transaction_id: 7, ext_id: "AUTO-7", occurred_on: "2026-09-05", amount: "75.00", currency: "BYN", direction: "payment",
  payer_unp: null, payer_name: "Supplier", purpose: "Оплата", account_code: "main", source_provider: "bank", match_status: "unmatched" };
const accounts = [{ id: 51, code: "51", title: "Банк", cash: true, category: "asset", required_dimensions: [] },
  { id: 60, code: "60", title: "Поставщики", cash: false, category: "liability", required_dimensions: ["counterparty", "contract"] }];
const respond = (body: unknown, ok = true) => Promise.resolve({ ok, json: async () => body });
function setup({ failFirst = false, wrongPreview = false, delayedPreview = false, delayedConfirm = false, normativeVerified = true } = {}) {
  let confirms = 0, resolvePreview: ((body: unknown) => void) | undefined, resolveConfirm: (() => void) | undefined;
  const mock = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
    if (url.endsWith("/bank-import/candidates")) return respond([{ source_snapshot: source, source_digest: "a".repeat(64), binding_status: "own", imported: false, entry_id: null }]);
    if (url.includes("/bank-import/auto-rules?")) return respond({ organization_id: Number(url.split("organizations/")[1].split("/")[0]), policy_id: 3,
      rules: [{ key: "pay", title: "Оплата поставщику", direction: "payment", settlement_account: "60", cash_activity: "operating", required_dimensions: ["counterparty", "contract"] },
        { key: "receipt", title: "Поступление покупателя", direction: "receipt", settlement_account: "62", cash_activity: "operating", required_dimensions: [] }] });
    if (url.includes("/bank-account-mappings?include_closed")) return respond([]);
    if (url.includes("/bank-account-mappings?provider=")) return respond([{ ledger_account_id: 51, dimensions: {} }]);
    if (url.includes("/accounts?on=")) return respond(accounts);
    if (url.endsWith("/bank-import/auto-preview")) {
      const body = JSON.parse(String(options?.body)), { rule_key, ...command } = body;
      const plan = { organization_id: wrongPreview ? 2 : 1, rule_key, resolved_command: { ...command, bank_account: "51", bank_dimensions: {}, settlement_account: "60", cash_activity: "operating" },
        basis_digest: "b".repeat(64), digest: "c".repeat(64), source_snapshot: source, confirmation_available: true, normative_verified: normativeVerified,
        lines: [{ account: "60", title: "Поставщики", side: "debit", amount: "75.00" }, { account: "51", title: "Банк", side: "credit", amount: "75.00" }] };
      if (delayedPreview) return new Promise(resolve => { resolvePreview = () => resolve({ ok: true, json: async () => plan }); });
      return respond(plan);
    }
    if (url.endsWith("/bank-import/auto-confirm")) {
      confirms++;
      if (failFirst && confirms === 1) return Promise.reject(new Error("Connection lost"));
      const receipt = { organization_id: 1, source_transaction_id: 7, entry_id: 99 };
      if (delayedConfirm) return new Promise(resolve => { resolveConfirm = () => resolve({ ok: true, json: async () => receipt }); });
      return respond(receipt);
    }
    throw new Error(url);
  });
  vi.stubGlobal("fetch", mock);
  return { mock, finish: () => resolvePreview?.({}), finishConfirm: () => resolveConfirm?.() };
}
async function calculate() {
  fireEvent.click(await screen.findByRole("button", { name: "Выбрать" }));
  await screen.findByRole("option", { name: "Оплата поставщику" });
  expect(screen.queryByRole("option", { name: "Поступление покупателя" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Банковская операция"), { target: { value: "pay" } });
  fireEvent.change(screen.getByLabelText("Расчёты: counterparty"), { target: { value: "CP" } });
  fireEvent.change(screen.getByLabelText("Расчёты: contract"), { target: { value: "CONTRACT" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Рассчитать проводки" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать проводки" }));
}
it("uses auto by default and retries frozen original organization/command after lost response and scope change", async () => {
  const { mock } = setup({ failFirst: true }); const posted = vi.fn();
  const props = { org: "1", accounts, policyId: 3, date: "2026-09-05", onDate: vi.fn(), onPosted: posted };
  const view = render(<AccountingBankImport {...props} />);
  expect(screen.getByLabelText("Выбрать счета вручную")).not.toBeChecked();
  await calculate();
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить импорт" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
  expect(screen.getByLabelText("Дата отражения импорта")).toBeDisabled();
  view.rerender(<AccountingBankImport {...props} org="2" policyId={99} date="2026-10-05" />);
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить импорт" }));
  await waitFor(() => expect(posted).toHaveBeenCalledOnce());
  const calls = mock.mock.calls.filter(([url]) => String(url).endsWith("/auto-confirm"));
  expect(calls).toHaveLength(2);
  expect(calls[0][0]).toContain("/organizations/1/"); expect(calls[1][0]).toBe(calls[0][0]);
  expect(calls[1][1].body).toBe(calls[0][1].body);
  const body = JSON.parse(calls[0][1].body);
  expect(body.command).toMatchObject({ source_transaction_id: 7, policy_id: 3, posting_date: "2026-09-05", bank_account: "51", settlement_account: "60", settlement_dimensions: { counterparty: "CP", contract: "CONTRACT" }, digest: "c".repeat(64) });
  const preview = JSON.parse(mock.mock.calls.find(([url]) => String(url).endsWith("/auto-preview"))![1].body);
  expect(preview).not.toHaveProperty("bank_account"); expect(preview).not.toHaveProperty("settlement_account");
});
it("rejects a preview for another organization", async () => {
  setup({ wrongPreview: true }); render(<AccountingBankImport org="1" accounts={accounts} policyId={3} date="2026-09-05" onDate={vi.fn()} onPosted={vi.fn()} />);
  await calculate(); expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
  expect(screen.queryByRole("button", { name: "Подтвердить импорт" })).not.toBeInTheDocument();
});
it("discards a late preview after parent date change", async () => {
  const { finish } = setup({ delayedPreview: true });
  const props = { org: "1", accounts, policyId: 3, date: "2026-09-05", onDate: vi.fn(), onPosted: vi.fn() };
  const view = render(<AccountingBankImport {...props} />); await calculate();
  view.rerender(<AccountingBankImport {...props} date="2026-09-06" />);
  await act(async () => { finish(); });
  expect(screen.queryByRole("button", { name: "Подтвердить импорт" })).not.toBeInTheDocument();
});
it("finishes an in-flight old-org confirmation without stranding the new queue or calling an old callback", async () => {
  const { mock, finishConfirm } = setup({ delayedConfirm: true }); const oldPosted = vi.fn(), newPosted = vi.fn();
  const props = { org: "1", accounts, policyId: 3, date: "2026-09-05", onDate: vi.fn(), onPosted: oldPosted };
  const view = render(<AccountingBankImport {...props} />); await calculate();
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить импорт" }));
  view.rerender(<AccountingBankImport {...props} org="2" onPosted={newPosted} />);
  await waitFor(() => expect(screen.queryByText("Загрузка очереди…")).not.toBeInTheDocument());
  await act(async () => { finishConfirm(); });
  await waitFor(() => expect(newPosted).toHaveBeenCalledOnce());
  expect(oldPosted).not.toHaveBeenCalled();
  expect(screen.queryByText("Загрузка очереди…")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Обновить очередь" })).toBeEnabled();
  expect(mock.mock.calls.filter(([url]) => String(url).includes("/organizations/1/bank-import/candidates"))).toHaveLength(1);
});


it("holds confirmation for an inconsistent unverified-policy preview", async () => {
  setup({ normativeVerified: false });
  render(<AccountingBankImport org="1" accounts={accounts} policyId={3} date="2026-09-05" onDate={vi.fn()} onPosted={vi.fn()} />);
  await calculate();
  expect(await screen.findByRole("button", { name: "Подтвердить импорт" })).toBeDisabled();
  expect(screen.getByText("Политика не подтверждена нормативно: подтверждение заблокировано.")).toBeInTheDocument();
});
