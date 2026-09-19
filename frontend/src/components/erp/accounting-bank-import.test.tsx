import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingBankImport } from "./accounting-bank-import";

afterEach(() => vi.unstubAllGlobals());

it("binds an imported bank source, previews it, and confirms the same package", async () => {
  let bound = false;
  const candidate = {
    source_snapshot: {
      transaction_id: 7, ext_id: "BANK-7", occurred_on: "2026-09-05", amount: "75.00", currency: "BYN",
      payer_unp: null, payer_name: "Buyer", purpose: "Advance", account_code: "main", source_provider: "synthetic-bank", match_status: "unmatched",
    },
    source_digest: "a".repeat(64), binding_status: "unbound", imported: false, entry_id: null,
  };
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/bank-import/candidates")) return Promise.resolve({ ok: true, json: async () => [{ ...candidate, binding_status: bound ? "own" : "unbound" }] });
    if (url.endsWith("/source-bindings")) { bound = true; return Promise.resolve({ ok: true, json: async () => ({ id: 2 }) }); }
    if (url.includes("/bank-account-mappings?provider=synthetic-bank&external_account=main&currency=BYN&at=2026-09-05")) return Promise.resolve({ ok: true, json: async () => [{ ledger_account_id: 51, dimensions: {} }] });
    if (url.endsWith("/accounts?on=2026-09-05")) return Promise.resolve({ ok: true, json: async () => [{ id: 51, code: "51", title: "Historical bank", cash: true, category: "asset", required_dimensions: [] }] });
    if (url.includes("/bank-account-mappings?include_closed=true")) return Promise.resolve({ ok: true, json: async () => [] });
    if (url.endsWith("/bank-import/preview")) return Promise.resolve({ ok: true, json: async () => ({
      basis_digest: "b".repeat(64), digest: "c".repeat(64), source_snapshot: candidate.source_snapshot,
      lines: [{ account: "51", title: "Банк", side: "debit", amount: "75.00", dimensions: { counterparty: "CP-7", contract: "CONTRACT-7" } }],
      confirmation_available: true, normative_verified: true,
    }) });
    if (url.endsWith("/bank-import/confirm")) return Promise.resolve({ ok: true, json: async () => ({ entry_id: 9 }) });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  const posted = vi.fn();
  render(<AccountingBankImport org="1" accounts={[
    { id: 99, code: "999", title: "Текущий иной счёт", cash: true, category: "asset", required_dimensions: [] },
    { id: 62, code: "62", title: "Покупатели", cash: false, category: "asset", required_dimensions: ["counterparty", "contract"] },
  ]} policyId={3} date="2026-09-05" onDate={vi.fn()} onPosted={posted} />);

  fireEvent.click(await screen.findByRole("button", { name: "Привязать" }));
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/source-bindings"))).toBe(true);
  fireEvent.click(await screen.findByRole("button", { name: "Выбрать" }));
  fireEvent.change(screen.getByLabelText("Расчёты: counterparty"), { target: { value: "CP-7" } });
  fireEvent.change(screen.getByLabelText("Расчёты: contract"), { target: { value: "CONTRACT-7" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Рассчитать проводки" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать проводки" }));
  expect(await screen.findByText("contract: CONTRACT-7")).toBeVisible();
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить импорт" }));
  expect(await screen.findByRole("status")).toHaveTextContent("BANK-7");
  expect(posted).toHaveBeenCalledOnce();
  const previewCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/bank-import/preview"));
  const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/bank-import/confirm"));
  expect(JSON.parse(String(previewCall?.[1]?.body)).source_digest).toBe("a".repeat(64));
  expect(JSON.parse(String(previewCall?.[1]?.body)).bank_account).toBe("51");
  expect(JSON.parse(String(previewCall?.[1]?.body)).settlement_dimensions).toEqual({ counterparty: "CP-7", contract: "CONTRACT-7" });
  expect(JSON.parse(String(confirmCall?.[1]?.body)).settlement_dimensions).toEqual({ counterparty: "CP-7", contract: "CONTRACT-7" });
  expect(JSON.parse(String(confirmCall?.[1]?.body)).digest).toBe("c".repeat(64));
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/accounts?on=2026-09-05"))).toBe(true);
});


it("shows invalid money without offering posting", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [{
    source_snapshot: { transaction_id: 8, ext_id: "BROKEN", occurred_on: "2026-09-05", amount: null, currency: "BYN", payer_name: "Buyer" },
    source_digest: null, binding_status: "own", imported: false, entry_id: null,
  }] }));
  render(<AccountingBankImport org="1" accounts={[]} policyId={3} date="2026-09-05" onDate={vi.fn()} onPosted={vi.fn()} />);
  expect(await screen.findByText(/Некорректная сумма/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Выбрать" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Подтвердить импорт" })).not.toBeInTheDocument();
});

it("does not enable source selection before accounts are loaded", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [{
    source_snapshot: { transaction_id: 10, ext_id: "WAIT-ACCOUNTS", occurred_on: "2026-09-05", amount: "25.00", currency: "BYN", payer_name: "Buyer" },
    source_digest: "d".repeat(64), binding_status: "own", imported: false, entry_id: null,
  }] }));
  render(<AccountingBankImport org="1" accounts={[]} policyId={3} date="2026-09-05" onDate={vi.fn()} onPosted={vi.fn()} />);
  const select = await screen.findByRole("button", { name: "Выбрать" });
  expect(select).toBeDisabled();
});

it("ignores a late mapping response after switching to an unmapped bank source", async () => {
  let resolveOld: ((value: unknown) => void) | undefined;
  const sources = ["OLD", "CURRENT"].map((name, index) => ({ source_snapshot: {
    transaction_id: index + 20, ext_id: name, occurred_on: "2026-09-05", amount: "25.00", currency: "BYN",
    account_code: name, source_provider: "synthetic-bank", payer_name: "Buyer", match_status: "unmatched",
  }, source_digest: "e".repeat(64), binding_status: "own" as const, imported: false, entry_id: null }));
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/bank-import/candidates")) return Promise.resolve({ ok: true, json: async () => sources });
    if (url.includes("include_closed=true")) return Promise.resolve({ ok: true, json: async () => [] });
    if (url.includes("external_account=OLD")) return new Promise((resolve) => { resolveOld = resolve; });
    if (url.includes("external_account=CURRENT")) return Promise.resolve({ ok: true, json: async () => [] });
    throw new Error(url);
  }));
  render(<AccountingBankImport org="1" accounts={[
    { id: 99, code: "999", title: "Не fallback", cash: true, category: "asset", required_dimensions: [] },
    { id: 62, code: "62", title: "Расчёты", cash: false, category: "asset", required_dimensions: [] },
  ]} policyId={3} date="2026-09-05" onDate={vi.fn()} onPosted={vi.fn()} />);
  const choose = await screen.findAllByRole("button", { name: "Выбрать" });
  fireEvent.click(choose[0]);
  fireEvent.click(choose[1]);
  await screen.findByText("Для строки нужна ровно одна действующая привязка банковского счёта.");
  await act(async () => { resolveOld?.({ ok: true, json: async () => [{ ledger_account_id: 99, dimensions: {} }] }); });
  expect(screen.getByLabelText("Счёт банка импорта")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Рассчитать проводки" })).toBeDisabled();
});
