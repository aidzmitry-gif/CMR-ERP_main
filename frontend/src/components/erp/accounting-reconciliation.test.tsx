import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingReconciliation } from "./accounting-reconciliation";

afterEach(() => vi.unstubAllGlobals());
const file = () => ({ name: "osv.csv", size: 4, arrayBuffer: async () => new Uint8Array([239, 187, 191, 65]).buffer });
function selectFiles() {
  fireEvent.change(screen.getByLabelText("Левая ОСВ"), { target: { files: [file()] } });
  fireEvent.change(screen.getByLabelText("Правая ОСВ"), { target: { files: [file()] } });
}

it("sends exact bytes only on comparison and displays missing rows separately", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ status: "differences", left: { from: "2026-09-01", to: "2026-09-30", sha256: "left", status: "preliminary" }, right: { sha256: "right", status: "closed_periods" }, differences: [{ account: "001", currency: "USD", off_balance: true, dimensions: {}, presence: "left_only", fields: { debit: { left: "9007199254740993.01", right: null, right_minus_left: null } } }] }) }));
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingReconciliation org="7" />);
  selectFiles();
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Сравнить ОСВ"));
  expect(await screen.findByText(/Строк с расхождениями: 1/)).toBeInTheDocument();
  expect(screen.getByText(/справа нет строки; разница не рассчитывается/)).toBeInTheDocument();
  expect(fetcher.mock.calls[0]).toEqual(["/api/accounting/organizations/7/reconciliation", expect.objectContaining({ body: JSON.stringify({ left_base64: "77u/QQ==", right_base64: "77u/QQ==" }) })]);
  fireEvent.change(screen.getByLabelText("Левая ОСВ"), { target: { files: [] } });
  expect(screen.queryByText(/Строк с расхождениями/)).not.toBeInTheDocument();
});

it("shows validation failures without a successful protocol", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => ({ detail: "Invalid CSV" }) })));
  render(<AccountingReconciliation org="7" />);
  selectFiles();
  fireEvent.click(screen.getByText("Сравнить ОСВ"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid CSV");
  expect(screen.queryByText("Скачать протокол JSON")).not.toBeInTheDocument();
});

it("offers one idempotent accountant acceptance for a closed complete match", async () => {
  const candidate = { status: "no_numeric_differences", cutover_ready: true, accepted_by_accountant: false, eligibility_blockers: [], left: { from: "2026-09-01", to: "2026-09-30", sha256: "left", status: "closed_periods", pending_documents: 0 }, right: { sha256: "right", status: "closed_periods", pending_documents: 0 }, differences: [] };
  const receipt = { organization_id: 7, request_key: "00000000-0000-4000-8000-000000000001", accepted_by_accountant: true, cutover_ready: true, receipt_id: 12 };
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => candidate })
    .mockResolvedValueOnce({ ok: true, json: async () => receipt });
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("crypto", { randomUUID: () => receipt.request_key });
  render(<AccountingReconciliation org="7" />);
  selectFiles();
  fireEvent.click(screen.getByText("Сравнить ОСВ"));
  expect(await screen.findByText(/ОСВ совпадают/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Основание принятия сверки"), { target: { value: "Проверено главным бухгалтером по протоколу" } });
  fireEvent.click(screen.getByText("Принять протокол бухгалтером"));
  expect(await screen.findByText(/Протокол принят бухгалтером/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetcher.mock.calls[1][1].body).request_key).toBe(receipt.request_key);
});
