import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingRepairs } from "./accounting-repairs";

afterEach(() => vi.unstubAllGlobals());
const sourceDigest = "b".repeat(64);
const postingDigest = "c".repeat(64);
const ok = (body: unknown) => ({ ok: true, json: async () => body });

function fillRequired() {
  fireEvent.change(screen.getByLabelText("Заявка ремонта"), { target: { value: "42" } });
  fireEvent.change(screen.getByLabelText("Digest источника ремонта"), { target: { value: sourceDigest } });
  fireEvent.change(screen.getByLabelText("Серийный номер ремонта"), { target: { value: "SN-100" } });
  fireEvent.change(screen.getByLabelText("Код владельца изделия"), { target: { value: "customer-7" } });
  fireEvent.change(screen.getByLabelText("Контрагент ремонта"), { target: { value: "customer-7" } });
  fireEvent.change(screen.getByLabelText("Стоимость услуги ремонта"), { target: { value: "150.00" } });
  fireEvent.change(screen.getByLabelText("Стоимость собственных материалов ремонта"), { target: { value: "50.00" } });
  fireEvent.change(screen.getByLabelText("Основание ремонта"), { target: { value: "Акт ремонта и подтверждение владельца" } });
}

it("previews a paid repair and displays the financial result", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes("/repairs?")) return ok({ organization_id: 1, rows: [] });
    if (url.endsWith("/repair-preview")) return ok({ organization_id: 1, status: "reviewed_repair", posting_available: true, digest: postingDigest, financial_result: { service_amount_byn: "150.00", cost_amount_byn: "50.00", gross_result_byn: "100.00", customer_material_lines: [] } });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingRepairs org="1" month="2026-10" policyId="3" onEntry={vi.fn()} />);
  expect(await screen.findByText("Проведённых ремонтов за период нет.")).toBeInTheDocument();
  fillRequired();
  fireEvent.click(screen.getByRole("button", { name: "Проверить ремонт" }));
  expect(await screen.findByText(/Результат: выручка 150.00 BYN/)).toBeInTheDocument();
});

it("sends customer material as zero-valued evidence", async () => {
  let previewBody: Record<string, unknown> | undefined;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/repairs?")) return ok({ organization_id: 1, rows: [] });
    if (url.endsWith("/repair-preview")) { previewBody = JSON.parse(String(init?.body)); return ok({ organization_id: 1, status: "reviewed_repair", posting_available: true, digest: postingDigest, financial_result: { service_amount_byn: "150.00", cost_amount_byn: "0.00", gross_result_byn: "150.00", customer_material_lines: ["customer-material"] } }); }
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingRepairs org="1" month="2026-10" policyId="3" onEntry={vi.fn()} />);
  await screen.findByText("Проведённых ремонтов за период нет.");
  fillRequired();
  fireEvent.click(screen.getByRole("checkbox", { name: "Материал клиента" }));
  fireEvent.click(screen.getByRole("button", { name: "Проверить ремонт" }));
  await screen.findByText(/затраты 0.00 BYN/);
  const lines = previewBody?.lines as Array<Record<string, unknown>>;
  expect(lines[0].amount_byn).toBe("0.00");
  expect(lines[0].credit_account).toBeUndefined();
});

it("sends multiple owned and customer cost lines with stable identities", async () => {
  let previewBody: Record<string, unknown> | undefined;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/repairs?")) return ok({ organization_id: 1, rows: [] });
    if (url.endsWith("/repair-preview")) { previewBody = JSON.parse(String(init?.body)); return ok({ organization_id: 1, status: "reviewed_repair", posting_available: true, digest: postingDigest, financial_result: { service_amount_byn: "150.00", cost_amount_byn: "75.00", gross_result_byn: "75.00", customer_material_lines: ["customer-material-2"] } }); }
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingRepairs org="1" month="2026-10" policyId="3" onEntry={vi.fn()} />);
  await screen.findByText("Проведённых ремонтов за период нет.");
  fillRequired();
  fireEvent.click(screen.getByRole("button", { name: "Добавить строку затрат" }));
  fireEvent.change(screen.getByLabelText("Тип затрат ремонта 2"), { target: { value: "labor" } });
  fireEvent.change(screen.getByLabelText("Описание затрат ремонта 2"), { target: { value: "Работа мастера" } });
  fireEvent.change(screen.getByLabelText("Стоимость строки ремонта 2"), { target: { value: "25.00" } });
  fireEvent.change(screen.getByLabelText("Основание строки ремонта 2"), { target: { value: "Табель и акт выполненных работ" } });
  fireEvent.click(screen.getByRole("button", { name: "Добавить строку затрат" }));
  fireEvent.change(screen.getByLabelText("Принадлежность строки ремонта 3"), { target: { value: "customer" } });
  fireEvent.change(screen.getByLabelText("Основание строки ремонта 3"), { target: { value: "Акт передачи детали клиента" } });
  fireEvent.click(screen.getByRole("button", { name: "Проверить ремонт" }));
  await screen.findByText(/затраты 75.00 BYN/);
  const lines = previewBody?.lines as Array<Record<string, unknown>>;
  expect(lines).toHaveLength(3);
  expect(lines.map(line => line.source_line_id)).toEqual(["repair-cost-1", "repair-cost-2", "customer-material-3"]);
  expect(lines[1].kind).toBe("labor");
  expect(lines[2].amount_byn).toBe("0.00");
  expect(lines[2].debit_account).toBeUndefined();
});
