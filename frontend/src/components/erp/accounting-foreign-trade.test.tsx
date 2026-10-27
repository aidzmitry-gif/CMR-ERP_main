import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingForeignTrade } from "./accounting-foreign-trade";

afterEach(() => vi.unstubAllGlobals());

const digest = "a".repeat(64);
const row = {
  entry_id: 42, line_id: 8, source: "procurement:import:7", source_version: 1,
  operation: "inventory_purchase", posting_date: "2026-09-10", document_date: "2026-09-10",
  operation_date: "2026-09-10", side: "debit", amount: "120.00", currency: "BYN",
  original_amount: null, rate: null, rate_scale: null, rate_date: null, rate_source: null,
  account_code: "41", account_title: "Товары", dimensions: {}, review_issues: [],
  trade_mode: "not_assessed", register_id: null, registered: false, entry_digest: digest,
};
const worksheet = { rows: [row], rows_needing_metadata_review: 0, rows_needing_register_review: 1, statutory_certified: false, trade_treatment_verified: false };
const ok = (body: unknown) => ({ ok: true, json: async () => body });

it("loads trade candidates and keeps the source entry link", async () => {
  const onEntry = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => ok(worksheet)));
  render(<AccountingForeignTrade org="1" start="2026-09-01" end="2026-09-30" onEntry={onEntry} />);
  fireEvent.click(await screen.findByRole("button", { name: "Операция № 42 · procurement:import:7" }));
  expect(onEntry).toHaveBeenCalledWith(42);
  expect(screen.getByText(/Без записи доказательств: 1/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Записать доказательства ВЭД" })).toBeInTheDocument();
});

it("previews and confirms one explicit EAEU evidence package", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/foreign-trade-lines?start=2026-09-01&end=2026-09-30")) return ok(worksheet);
    if (url.endsWith("/foreign-trade-register/preview")) return ok({ organization_id: 1, source: { entry_id: 42, line_id: 8, account_code: "41" }, status: "reviewed_foreign_trade", register_available: true, statutory_certified: false, trade_treatment_verified: false, digest });
    if (url.endsWith("/production-overhead-access")) return ok({ organization_id: 1, principal: "tester", can_confirm: true });
    if (url.endsWith("/foreign-trade-register/confirm")) return ok({ organization_id: 1, entry_id: 42, line_id: 8, digest, statutory_certified: false, trade_treatment_verified: false });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingForeignTrade org="1" start="2026-09-01" end="2026-09-30" onEntry={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Записать доказательства ВЭД" }));
  fireEvent.change(screen.getByLabelText("Страна партнёра ВЭД"), { target: { value: "KZ" } });
  fireEvent.change(screen.getByLabelText("Договор ВЭД"), { target: { value: "EAEU-1" } });
  fireEvent.change(screen.getByLabelText("Документ ВЭД"), { target: { value: "INV-1" } });
  fireEvent.change(screen.getByLabelText("Документ ЕАЭС"), { target: { value: "EAEU-DOC-1" } });
  fireEvent.change(screen.getByLabelText("Доказательства ВЭД"), { target: { value: "Документы проверены бухгалтером" } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить пакет ВЭД" }));
  expect(await screen.findByText(/Пакет aaaaaaaaaaaa/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить запись ВЭД" }));
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/foreign-trade-register/confirm")).length).toBe(1));
  expect(screen.getByText(/Запись ВЭД сохранена/)).toBeInTheDocument();
});
