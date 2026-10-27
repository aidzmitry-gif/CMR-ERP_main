import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingStatutoryRequirements } from "./accounting-statutory-requirements";

afterEach(() => vi.unstubAllGlobals());
const ok = (value: unknown) => ({ ok: true, status: 200, json: async () => value });
const fail = (status: number) => ({ ok: false, status, json: async () => ({}) });
const form = (overrides = {}) => ({ requirement_id: 1, organization_id: 7, kind: "form", code: "PAYROLL-FORM", title: "Synthetic form", effective_from: "2026-10-01", revision: 1, source_reference: "Synthetic verified source", evidence: "Synthetic documented evidence", form_version: "1.0", electronic_format_version: "xml-1.0", rate_value: null, rate_unit: null, rate_basis: null, request_key: "00000000-0000-4000-8000-000000000001", digest: "a".repeat(64), actor: "tester", ...overrides });
function deferred() { let resolve!: (value: unknown) => void; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }

function fillCommon() {
  fireEvent.change(screen.getByLabelText("Код требования"), { target: { value: "PAYROLL-FORM" } });
  fireEvent.change(screen.getByLabelText("Наименование требования"), { target: { value: "Synthetic form" } });
  fireEvent.change(screen.getByLabelText("Первичный источник требования"), { target: { value: "Synthetic verified source" } });
  fireEvent.change(screen.getByLabelText("Основание требования"), { target: { value: "Synthetic documented evidence" } });
}

it("does not request without organization/period and uses the scoped period endpoint", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const view = render(<AccountingStatutoryRequirements org="" month="" disabled={false} />);
  expect(fetch).not.toHaveBeenCalled();
  fetch.mockResolvedValue(ok([])); view.rerender(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} />);
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  expect(fetch.mock.calls[0][0]).toBe("/api/accounting/organizations/7/periods/2026-10/statutory-requirements");
});

it("sends mutually exclusive form/rate bodies without implicit values", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(ok([])).mockResolvedValueOnce(ok(form())).mockResolvedValueOnce(ok(form({ requirement_id: 2, kind: "rate", code: "SOCIAL-RATE", title: "Synthetic rate", form_version: null, electronic_format_version: null, rate_value: "0", rate_unit: "percent", rate_basis: "Synthetic verified basis", request_key: "00000000-0000-4000-8000-000000000002" })));
  vi.stubGlobal("fetch", fetch); vi.stubGlobal("crypto", { randomUUID: vi.fn().mockReturnValueOnce("00000000-0000-4000-8000-000000000001").mockReturnValueOnce("00000000-0000-4000-8000-000000000002") });
  render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} />); await screen.findByText("Для выбранного юрлица и периода записей нет.");
  fillCommon(); fireEvent.change(screen.getByLabelText("Версия формы"), { target: { value: "1.0" } }); fireEvent.change(screen.getByLabelText("Версия электронного формата"), { target: { value: "xml-1.0" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить версию требования" })); await screen.findByText("Версия 1 сохранена.");
  const first = JSON.parse(fetch.mock.calls[1][1].body); expect(first).toMatchObject({ kind: "form", effective_from: "2026-10-01", rate_value: null, rate_unit: null, rate_basis: null });
  fireEvent.click(screen.getByRole("button", { name: "Ставка" })); fillCommon(); fireEvent.change(screen.getByLabelText("Код требования"), { target: { value: "SOCIAL-RATE" } }); fireEvent.change(screen.getByLabelText("Наименование требования"), { target: { value: "Synthetic rate" } }); fireEvent.change(screen.getByLabelText("Значение ставки"), { target: { value: "0.0" } }); fireEvent.change(screen.getByLabelText("Единица ставки"), { target: { value: "percent" } }); fireEvent.change(screen.getByLabelText("База ставки"), { target: { value: "Synthetic verified basis" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить версию требования" })); await screen.findByText("Версия 1 сохранена.");
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  const second = JSON.parse(fetch.mock.calls[2][1].body); expect(second).toMatchObject({ kind: "rate", form_version: null, electronic_format_version: null, rate_value: "0.0" });
});

it("rejects foreign response and retries exactly the frozen request body", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(ok([form({ organization_id: 8 })])); vi.stubGlobal("fetch", fetch);
  const rejected = render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} />); expect(await screen.findByRole("alert")).toHaveTextContent("другое юрлицо"); rejected.unmount();

  fetch.mockReset(); fetch.mockResolvedValueOnce(ok([])).mockResolvedValueOnce(fail(503)).mockResolvedValueOnce(ok(form())); vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" });
  render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} />); await screen.findByText("Для выбранного юрлица и периода записей нет."); fillCommon(); fireEvent.change(screen.getByLabelText("Версия формы"), { target: { value: "1.0" } }); fireEvent.change(screen.getByLabelText("Версия электронного формата"), { target: { value: "xml-1.0" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить версию требования" })); await screen.findByText("Запрос сохранён; повторите его без изменения полей."); fireEvent.click(screen.getByRole("button", { name: "Повторить сохранённый запрос" })); await screen.findByText("Версия 1 сохранена.");
  const posts = fetch.mock.calls.filter(([, init]) => init?.method === "POST"); expect(posts).toHaveLength(2); expect(posts[0][1].body).toBe(posts[1][1].body);
});

it("rejects a mismatched saved response and clears retry after known 403", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(ok([])).mockResolvedValueOnce(ok(form({ code: "OTHER" }))); vi.stubGlobal("fetch", fetch); vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" });
  const view = render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} />); await screen.findByText("Для выбранного юрлица и периода записей нет."); fillCommon(); fireEvent.change(screen.getByLabelText("Версия формы"), { target: { value: "1.0" } }); fireEvent.change(screen.getByLabelText("Версия электронного формата"), { target: { value: "xml-1.0" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить версию требования" })); expect(await screen.findByRole("alert")).toHaveTextContent("Результат не подтверждён");
  view.unmount(); fetch.mockReset(); fetch.mockResolvedValueOnce(ok([])).mockResolvedValueOnce(fail(403)); render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} />); await screen.findByText("Для выбранного юрлица и периода записей нет."); fillCommon(); fireEvent.change(screen.getByLabelText("Версия формы"), { target: { value: "1.0" } }); fireEvent.change(screen.getByLabelText("Версия электронного формата"), { target: { value: "xml-1.0" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить версию требования" })); expect(await screen.findByRole("alert")).toHaveTextContent("403:"); expect(screen.getByRole("button", { name: "Сохранить версию требования" })).toBeEnabled();
});

it("replaces the active row when a later revision has the same kind and code", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(ok([form()])).mockResolvedValueOnce(ok(form({ requirement_id: 2, revision: 2 }))); vi.stubGlobal("fetch", fetch); vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" });
  render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} />); await screen.findByText("Форма: PAYROLL-FORM · версия 1"); fillCommon(); fireEvent.change(screen.getByLabelText("Версия формы"), { target: { value: "1.0" } }); fireEvent.change(screen.getByLabelText("Версия электронного формата"), { target: { value: "xml-1.0" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить версию требования" })); await screen.findByText("Форма: PAYROLL-FORM · версия 2"); expect(screen.queryByText("Форма: PAYROLL-FORM · версия 1")).not.toBeInTheDocument();
});

it("locks parent while save is unresolved and ignores stale organization completion", async () => {
  const oldList = deferred(), busy = vi.fn(), fetch = vi.fn().mockReturnValueOnce(oldList.promise).mockResolvedValueOnce(ok([])); vi.stubGlobal("fetch", fetch); vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000001" });
  const view = render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} onBusyChange={busy} />); view.rerender(<AccountingStatutoryRequirements org="8" month="2026-10" disabled={false} onBusyChange={busy} />); await act(async () => oldList.resolve(ok([form()]))); await screen.findByText("Для выбранного юрлица и периода записей нет."); expect(screen.queryByText(/PAYROLL-FORM/)).not.toBeInTheDocument();
  view.unmount(); const post = deferred(); fetch.mockReset(); fetch.mockResolvedValueOnce(ok([])).mockReturnValueOnce(post.promise); render(<AccountingStatutoryRequirements org="7" month="2026-10" disabled={false} onBusyChange={busy} />); await screen.findByText("Для выбранного юрлица и периода записей нет."); fillCommon(); fireEvent.change(screen.getByLabelText("Версия формы"), { target: { value: "1.0" } }); fireEvent.change(screen.getByLabelText("Версия электронного формата"), { target: { value: "xml-1.0" } }); const submit = screen.getByRole("button", { name: "Сохранить версию требования" }); act(() => { fireEvent.click(submit); fireEvent.click(submit); }); await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2)); await waitFor(() => expect(busy).toHaveBeenCalledWith(true)); expect(screen.getByLabelText("Код требования")).toBeDisabled(); await act(async () => { post.resolve(ok(form())); await Promise.resolve(); }); await waitFor(() => expect(busy).toHaveBeenLastCalledWith(false));
});
