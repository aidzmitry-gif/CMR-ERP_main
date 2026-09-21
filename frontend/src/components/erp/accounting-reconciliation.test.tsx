import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

it("persists a scoped immutable queue for mismatches with the responsible owner", async () => {
  const candidate = { status: "differences", cutover_ready: false, eligibility_blockers: ["numeric_differences"], left: { from: "2026-09-01", to: "2026-09-30", sha256: "left", status: "closed_periods", pending_documents: 0 }, right: { sha256: "right", status: "closed_periods", pending_documents: 0 }, differences: [{ account: "001", currency: "USD", off_balance: false, dimensions: { sku: "A" }, presence: "both", fields: { debit: { left: "1.00", right: "2.00", right_minus_left: "1.00" } } }] };
  const queued = { organization_id: 7, issue_id: 18, request_key: "00000000-0000-4000-8000-000000000018", period_from: "2026-09-01", period_to: "2026-09-30", left_digest: "left", right_digest: "right", difference_count: 1, eligibility_blockers: ["numeric_differences"], responsible: "accountant:stock", evidence: "Расхождение передано по складскому источнику", requires_fresh_comparison: true, accepted_by_accountant: false, cutover_ready: false };
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => candidate }).mockResolvedValueOnce({ ok: true, json: async () => queued });
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("crypto", { randomUUID: () => queued.request_key });
  render(<AccountingReconciliation org="7" />);
  selectFiles();
  fireEvent.click(screen.getByText("Сравнить ОСВ"));
  await screen.findByText(/Строк с расхождениями: 1/);
  fireEvent.change(screen.getByLabelText("Ответственный за исправление"), { target: { value: queued.responsible } });
  fireEvent.change(screen.getByLabelText("Основание постановки в очередь"), { target: { value: "Расхождение передано по складскому источнику" } });
  fireEvent.click(screen.getByText("Сохранить очередь сверки"));
  expect(await screen.findByText(/Очередь №18 сохранена/)).toBeInTheDocument();
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ left_base64: "77u/QQ==", right_base64: "77u/QQ==", request_key: queued.request_key, responsible: queued.responsible, evidence: "Расхождение передано по складскому источнику" });
  expect(screen.getByText(/нужна новая сверка/)).toBeInTheDocument();
});

it("freezes an uncertain queue write and repeats exactly the same command", async () => {
  const candidate = { status: "differences", cutover_ready: false, eligibility_blockers: ["numeric_differences"], left: { from: "2026-09-01", to: "2026-09-30", sha256: "left", status: "closed_periods" }, right: { sha256: "right", status: "closed_periods" }, differences: [{ account: "001", currency: "BYN", off_balance: false, dimensions: {}, presence: "both", fields: { debit: { left: "1.00", right: "2.00", right_minus_left: "1.00" } } }] };
  const queued = { organization_id: 7, issue_id: 19, request_key: "00000000-0000-4000-8000-000000000019", period_from: "2026-09-01", period_to: "2026-09-30", left_digest: "left", right_digest: "right", difference_count: 1, eligibility_blockers: ["numeric_differences"], responsible: "accountant:stock", evidence: "Расхождение передано по складскому источнику", requires_fresh_comparison: true, accepted_by_accountant: false, cutover_ready: false };
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => candidate }).mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce({ ok: true, json: async () => queued });
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("crypto", { randomUUID: () => queued.request_key });
  render(<AccountingReconciliation org="7" />);
  selectFiles();
  fireEvent.click(screen.getByText("Сравнить ОСВ"));
  await screen.findByText(/Строк с расхождениями: 1/);
  fireEvent.change(screen.getByLabelText("Ответственный за исправление"), { target: { value: queued.responsible } });
  fireEvent.change(screen.getByLabelText("Основание постановки в очередь"), { target: { value: "Расхождение передано по складскому источнику" } });
  fireEvent.click(screen.getByText("Сохранить очередь сверки"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Результат сохранения очереди неизвестен");
  expect(screen.getByLabelText("Левая ОСВ")).toBeDisabled();
  expect(screen.getByLabelText("Ответственный за исправление")).toBeDisabled();
  fireEvent.click(screen.getByText("Повторить сохранение той же очереди"));
  expect(await screen.findByText(/Очередь №19 сохранена/)).toBeInTheDocument();
  expect(fetcher.mock.calls[1][1].body).toBe(fetcher.mock.calls[2][1].body);
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

it("keeps source files and evidence locked until acceptance finishes", async () => {
  const candidate = { status: "no_numeric_differences", cutover_ready: true, left: { from: "2026-09-01", to: "2026-09-30", sha256: "left", status: "closed_periods" }, right: { sha256: "right", status: "closed_periods" }, differences: [] };
  let finish!: (response: unknown) => void;
  const pending = new Promise(resolve => { finish = resolve; });
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => candidate }).mockReturnValueOnce(pending);
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" });
  render(<AccountingReconciliation org="7" />);
  selectFiles();
  fireEvent.click(screen.getByText("Сравнить ОСВ"));
  await screen.findByText(/ОСВ совпадают/);
  fireEvent.change(screen.getByLabelText("Основание принятия сверки"), { target: { value: "Проверено бухгалтером" } });
  fireEvent.click(screen.getByText("Принять протокол бухгалтером"));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(screen.getByLabelText("Левая ОСВ")).toBeDisabled();
  expect(screen.getByLabelText("Правая ОСВ")).toBeDisabled();
  expect(screen.getByText("Сравнить ОСВ")).toBeDisabled();
  expect(screen.getByLabelText("Основание принятия сверки")).toBeDisabled();
  await act(async () => finish({ ok: false, json: async () => ({ detail: "Temporary failure" }) }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Temporary failure");
  expect(screen.getByLabelText("Левая ОСВ")).toBeEnabled();
  expect(screen.getByLabelText("Основание принятия сверки")).toHaveValue("Проверено бухгалтером");
});
