import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingOutputVat } from "./accounting-output-vat";
import { AccountingOutputVatRegister } from "./accounting-output-vat-register";

afterEach(() => vi.unstubAllGlobals());
const digest = "a".repeat(64);
const row = { entry_id: 42, line_id: 8, entry_digest: digest, posting_date: "2026-09-10", side: "debit", amount: "20.01", currency: "BYN", source: "sale:7", source_version: 2, operation: "inventory_sale", opening: false, correction_of: null, account_code: "90.2", account_title: "Output VAT", dimensions: { vat_rate: "20", vat_basis: "Sale invoice", counterparty: "Buyer" }, review_issues: [], registered: false, tax_treatment: "not_assessed" };
const ok = (body: unknown) => ({ ok: true, json: async () => body });

it("loads output VAT candidates and keeps the entry trace", async () => {
  const onEntry = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async () => ok({ organization_id: 1, status: "review_worksheet", statutory_certified: false, vat_treatment_verified: false, totals: { debit: "20.01", credit: "0.00", opening_debit: "0.00", opening_credit: "0.00" }, rows_needing_metadata_review: 0, rows_needing_register_review: 1, rows: [row] })));
  render(<AccountingOutputVat org="1" start="2026-09-01" end="2026-09-30" onEntry={onEntry} />);
  fireEvent.click(await screen.findByRole("button", { name: "Операция № 42 · sale:7" }));
  expect(onEntry).toHaveBeenCalledWith(42);
  expect(screen.getByText("20.01 BYN")).toBeInTheDocument();
  expect(screen.getByText(/Без записи в реестре: 1/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Записать в реестр исходящего НДС" })).toBeInTheDocument();
});

it("requires explicit output VAT treatment before saving the evidence row", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith("/preview")) return ok({ organization_id: 1, source: { entry_id: 42, line_id: 8 }, status: "reviewed_output_vat", register_available: true, statutory_certified: false, vat_treatment_verified: false, digest });
    if (url.endsWith("/production-overhead-access")) return ok({ organization_id: 1, principal: "tester", can_confirm: true });
    if (url.endsWith("/confirm")) return ok({ organization_id: 1, entry_id: 42, line_id: 8, digest, statutory_certified: false, vat_treatment_verified: false });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingOutputVatRegister org="1" start="2026-09-01" row={row} onRegistered={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Записать в реестр исходящего НДС" }));
  fireEvent.change(screen.getByLabelText("Документ исходящего НДС"), { target: { value: "SALE-7" } });
  fireEvent.change(screen.getByLabelText("Налоговое обращение"), { target: { value: "standard" } });
  fireEvent.change(screen.getByLabelText("Основание налогового обращения"), { target: { value: "Ставка проверена по счёту и первичному документу" } });
  fireEvent.change(screen.getByLabelText("Подтверждение регистрации исходящего НДС"), { target: { value: "Счёт, накладная и основание сверены бухгалтером" } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить пакет" }));
  expect(await screen.findByText(/Пакет aaaaaaaaaaaa/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить запись реестра" }));
  expect(await screen.findByText(/Запись реестра сохранена/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/confirm")).length).toBe(1);
});
