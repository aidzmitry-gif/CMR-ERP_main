import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionLaborCost } from "./accounting-production-labor-cost";

afterEach(() => vi.unstubAllGlobals());

const prepared = { organization_id: 1, month: "2026-10", policy_id: 2, source_digest: "a".repeat(64), digest: "b".repeat(64),
  status: "reviewed_verified_payroll", posting_available: true, posted: false, final_cost_certified: false,
  posting_document: { lines: [{ account: "20", side: "debit", amount: "100.00" }, { account: "70", side: "credit", amount: "100.00" }] } };

it("prepares a verified labor import and keeps it provisional", async () => {
  const request = vi.fn(async () => Response.json(prepared));
  vi.stubGlobal("fetch", request);
  render(<AccountingProductionLaborCost org="1" month="2026-10" policyId="2" disabled={false} />);
  fireEvent.change(screen.getByLabelText("Digest ведомости"), { target: { value: "a".repeat(64) } });
  fireEvent.change(screen.getByLabelText("Проверил начисления"), { target: { value: "chief" } });
  fireEvent.change(screen.getByLabelText("Основание ведомости"), { target: { value: "Проверенная ведомость за период" } });
  fireEvent.change(screen.getByLabelText("Сотрудник труда 1"), { target: { value: "E-1" } });
  fireEvent.change(screen.getByLabelText("Наряд труда 1"), { target: { value: "42" } });
  fireEvent.change(screen.getByLabelText("Аналитика труда 1"), { target: { value: "ORDER-42" } });
  fireEvent.change(screen.getByLabelText("Подразделение труда 1"), { target: { value: "SHOP" } });
  fireEvent.change(screen.getByLabelText("Сумма труда 1"), { target: { value: "100.00" } });
  fireEvent.change(screen.getByLabelText("Основание строки труда 1"), { target: { value: "Табель и расчёт" } });
  fireEvent.click(screen.getByText("Проверить импорт труда"));
  await screen.findByText(/Источник подтверждён/);
  expect(String(request.mock.calls[0][0])).toContain("production-labor-import-preview");
  expect(screen.getByText(/Финальная себестоимость/)).toBeInTheDocument();
});

it("rejects a labor preview from another organization", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...prepared, organization_id: 9 })));
  render(<AccountingProductionLaborCost org="1" month="2026-10" policyId="2" disabled={false} />);
  fireEvent.change(screen.getByLabelText("Digest ведомости"), { target: { value: "a".repeat(64) } });
  fireEvent.change(screen.getByLabelText("Проверил начисления"), { target: { value: "chief" } });
  fireEvent.change(screen.getByLabelText("Основание ведомости"), { target: { value: "Проверенная ведомость за период" } });
  fireEvent.change(screen.getByLabelText("Сотрудник труда 1"), { target: { value: "E-1" } });
  fireEvent.change(screen.getByLabelText("Наряд труда 1"), { target: { value: "42" } });
  fireEvent.change(screen.getByLabelText("Аналитика труда 1"), { target: { value: "ORDER-42" } });
  fireEvent.change(screen.getByLabelText("Подразделение труда 1"), { target: { value: "SHOP" } });
  fireEvent.change(screen.getByLabelText("Сумма труда 1"), { target: { value: "100.00" } });
  fireEvent.change(screen.getByLabelText("Основание строки труда 1"), { target: { value: "Табель и расчёт" } });
  fireEvent.click(screen.getByText("Проверить импорт труда"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("не соответствует"));
});
