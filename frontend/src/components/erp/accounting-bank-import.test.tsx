import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingBankImport } from "./accounting-bank-import";

afterEach(() => vi.unstubAllGlobals());

it("binds an imported bank source, previews it, and confirms the same package", async () => {
  let bound = false;
  const candidate = {
    source_snapshot: {
      transaction_id: 7, ext_id: "BANK-7", occurred_on: "2026-09-05", amount: "75.00", currency: "BYN",
      payer_unp: null, payer_name: "Buyer", purpose: "Advance", account_code: "main", match_status: "unmatched",
    },
    source_digest: "a".repeat(64), binding_status: "unbound", imported: false, entry_id: null,
  };
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/bank-import/candidates")) return Promise.resolve({ ok: true, json: async () => [{ ...candidate, binding_status: bound ? "own" : "unbound" }] });
    if (url.endsWith("/source-bindings")) { bound = true; return Promise.resolve({ ok: true, json: async () => ({ id: 2 }) }); }
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
    { code: "51", title: "Банк", cash: true, category: "asset", required_dimensions: [] },
    { code: "62", title: "Покупатели", cash: false, category: "asset", required_dimensions: ["counterparty", "contract"] },
  ]} policyId={3} date="2026-09-05" onDate={vi.fn()} onPosted={posted} />);

  fireEvent.click(await screen.findByRole("button", { name: "Привязать" }));
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/source-bindings"))).toBe(true);
  fireEvent.click(await screen.findByRole("button", { name: "Выбрать" }));
  fireEvent.change(screen.getByLabelText("Расчёты: counterparty"), { target: { value: "CP-7" } });
  fireEvent.change(screen.getByLabelText("Расчёты: contract"), { target: { value: "CONTRACT-7" } });
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать проводки" }));
  expect(await screen.findByText("contract: CONTRACT-7")).toBeVisible();
  fireEvent.click(await screen.findByRole("button", { name: "Подтвердить импорт" }));
  expect(await screen.findByRole("status")).toHaveTextContent("BANK-7");
  expect(posted).toHaveBeenCalledOnce();
  const previewCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/bank-import/preview"));
  const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/bank-import/confirm"));
  expect(JSON.parse(String(previewCall?.[1]?.body)).source_digest).toBe("a".repeat(64));
  expect(JSON.parse(String(previewCall?.[1]?.body)).settlement_dimensions).toEqual({ counterparty: "CP-7", contract: "CONTRACT-7" });
  expect(JSON.parse(String(confirmCall?.[1]?.body)).settlement_dimensions).toEqual({ counterparty: "CP-7", contract: "CONTRACT-7" });
  expect(JSON.parse(String(confirmCall?.[1]?.body)).digest).toBe("c".repeat(64));
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
