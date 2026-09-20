import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { FinanceLedgerGroup } from "./finance-ledger-group";

const organizations = [{ id: 1, name: "Первая компания", unp: "111111111" }, { id: 2, name: "Вторая компания", unp: "222222222" }];
const response = (body: unknown, ok = true, status = 200) => ({ ok, status, json: async () => body });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/accounting/organizations") return response(organizations);
    const query = new URL(`https://test${url}`);
    if (url.includes("/organizations/1/reports")) return response({ organization_id: 1, from: query.searchParams.get("start"), to: query.searchParams.get("end"), status: "preliminary", pending_documents: 2, review_items: [{ code: "open", count: 1, message: "Период открыт" }], pnl: { profit: "12.34" }, cashflow: { closing: "50.00" }, balance: { equity: "40.00", difference: "0.00" } });
    if (url.includes("/organizations/2/reports")) return response({ detail: "Нет доступа к отчёту второй компании" }, false, 403);
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("показывает доступные книги, частичную ошибку и не подменяет её нулём", async () => {
  render(<FinanceLedgerGroup />);
  expect(await screen.findByText("Первая компания · 111111111")).toBeInTheDocument();
  expect(screen.getByText("12.34 BYN")).toBeInTheDocument();
  const total = screen.getByText("Сумма отдельных результатов — не консолидация:").parentElement;
  expect(total).not.toBeNull();
  expect(total).toHaveTextContent("12.34 BYN");
  expect(screen.getByText("50.00 BYN")).toBeInTheDocument();
  expect(screen.getByText(/Нет доступа к отчёту второй компании/)).toBeInTheDocument();
  expect(screen.getByText(/Отчёты с ошибкой: 1; они не заменены нулями/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Открыть отчёт; выберите Первая компания" })).toHaveAttribute("href", "/erp/accounting");
});

it("явно помечает сумму отдельных результатов как не-консолидацию", async () => {
  render(<FinanceLedgerGroup />);
  await waitFor(() => expect(screen.getByText(/Сумма отдельных результатов — не консолидация:/)).toBeInTheDocument());
  expect(screen.getByText(/Внутригрупповые исключения, консолидированная прибыль и налоговая отчётность не рассчитаны/)).toBeInTheDocument();
});
