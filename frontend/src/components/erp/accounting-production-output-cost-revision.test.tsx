import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionOutputCostRevision } from "./accounting-production-output-cost-revision";

afterEach(() => { vi.unstubAllGlobals(); globalThis.localStorage?.clear(); });

it("does not send a confirm command when the current principal lacks confirmation access", async () => {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes("production-overhead-access")) return { ok: true, json: async () => ({ organization_id: 1, principal: "viewer", can_confirm: false }) };
    if (url.includes("transfer-status")) return { ok: true, json: async () => ({ organization_id: 1, month: "2026-10", order_id: 7, entry_id: 42 }) };
    if (url.includes("revision-preview")) return { ok: true, json: async () => ({ organization_id: 1, month: "2026-10", original_entry_id: 42, posting_date: "2026-10-31", request_evidence: "Late WIP", basis_digest: "a".repeat(64), source: { candidate_transfer_byn: "120.00" }, destinations: [], posting_document: null, final_cost_certified: false }) };
    throw Error(`Unexpected request: ${url} ${options?.method ?? "GET"}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingProductionOutputCostRevision org="1" month="2026-10" disabled={false} />);
  await screen.findByText("Пользователь: viewer");
  fireEvent.change(screen.getByPlaceholderText("№ наряда"), { target: { value: "7" } });
  fireEvent.change(screen.getByPlaceholderText("Основание"), { target: { value: "Late WIP" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти выпуск" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Подготовить корректировку" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Подготовить корректировку" }));
  await screen.findByText("Источник: 120.00 BYN");
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить корректировку" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Нет права");
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("revision-confirm"))).toBe(false);
});

it("ignores a delayed response from the previous organization and unlocks the new context", async () => {
  let finishOld!: (value: unknown) => void;
  const fetcher = vi.fn((url: string) => {
    if (url.includes("production-overhead-access")) {
      const organization_id = url.includes("/organizations/1/") ? 1 : 2;
      return Promise.resolve({ ok: true, json: async () => ({ organization_id, principal: `user-${organization_id}`, can_confirm: true }) });
    }
    if (url.includes("/organizations/1/") && url.includes("transfer-status")) {
      return new Promise((resolve) => { finishOld = resolve; });
    }
    if (url.includes("/organizations/2/") && url.includes("transfer-status")) {
      return Promise.resolve({ ok: true, json: async () => ({ organization_id: 2, month: "2026-10", order_id: 8, entry_id: 88 }) });
    }
    throw Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AccountingProductionOutputCostRevision org="1" month="2026-10" disabled={false} />);
  await screen.findByText("Пользователь: user-1");
  fireEvent.change(screen.getByLabelText("Номер наряда"), { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти выпуск" }));
  await waitFor(() => expect(finishOld).toBeTypeOf("function"));
  view.rerender(<AccountingProductionOutputCostRevision org="2" month="2026-10" disabled={false} />);
  await screen.findByText("Пользователь: user-2");
  fireEvent.change(screen.getByLabelText("Номер наряда"), { target: { value: "8" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти выпуск" }));
  expect(await screen.findByRole("button", { name: "Подготовить корректировку" })).toBeEnabled();
  finishOld({ ok: true, json: async () => ({ organization_id: 1, month: "2026-10", order_id: 7, entry_id: 42 }) });
  await waitFor(() => expect(screen.getByLabelText("Номер наряда")).toHaveValue("8"));
});

it("retries the same saved UUID after remount when confirmation outcome was unknown", async () => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key), clear: () => values.clear() });
  vi.stubGlobal("crypto", { randomUUID: () => "550e8400-e29b-41d4-a716-446655440000" });
  let confirms = 0;
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes("production-overhead-access")) return { ok: true, json: async () => ({ organization_id: 1, principal: "chief", can_confirm: true }) };
    if (url.includes("transfer-status")) return { ok: true, json: async () => ({ organization_id: 1, month: "2026-10", order_id: 7, entry_id: 42 }) };
    if (url.includes("revision-preview")) return { ok: true, json: async () => ({ organization_id: 1, month: "2026-10", original_entry_id: 42, posting_date: "2026-10-31", request_evidence: "Late WIP", basis_digest: "a".repeat(64), source: { candidate_transfer_byn: "120.00" }, destinations: [], posting_document: null, final_cost_certified: false }) };
    if (url.includes("revision-confirm")) {
      confirms += 1;
      if (confirms === 1) return { ok: false, status: 500, json: async () => ({ detail: "timeout" }) };
      const command = JSON.parse(String(options?.body));
      return { ok: true, status: 201, json: async () => ({ organization_id: 1, month: "2026-10", actor: "chief", original_entry_id: 42, request_key: command.request_key, basis_digest: command.basis_digest, revision_id: 4, entry_id: null, sequence: 1, posted: true, final_cost_certified: false }) };
    }
    throw Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const props = { org: "1", month: "2026-10", disabled: false };
  const view = render(<AccountingProductionOutputCostRevision {...props} />);
  await screen.findByText("Пользователь: chief");
  fireEvent.change(screen.getByLabelText("Номер наряда"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Основание корректировки"), { target: { value: "Late WIP" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти выпуск" }));
  expect(await screen.findByRole("button", { name: "Подготовить корректировку" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Подготовить корректировку" }));
  await screen.findByText("Источник: 120.00 BYN");
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить корректировку" }));
  await screen.findByRole("alert");
  view.unmount();
  render(<AccountingProductionOutputCostRevision {...props} />);
  expect(await screen.findByRole("button", { name: "Повторить тот же запрос" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить тот же запрос" }));
  expect(await screen.findByRole("status")).toHaveTextContent("новой проводки не создано");
  const bodies = fetcher.mock.calls.filter(([url]) => String(url).includes("revision-confirm")).map(([, options]) => String((options as RequestInit).body));
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toBe(bodies[1]);
});

it("does not send another principal's restored command", async () => {
  const values = new Map<string, string>();
  const pending = { org: "1", month: "2026-10", principal: "chief", command: { original_entry_id: 42, posting_date: "2026-10-31", request_evidence: "Late WIP", request_key: "550e8400-e29b-41d4-a716-446655440000", basis_digest: "a".repeat(64) } };
  values.set("production-output-cost-revision:[\"1\",\"2026-10\",\"chief\"]", JSON.stringify(pending));
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key), clear: () => values.clear() });
  let calls = 0;
  const fetcher = vi.fn(async (url: string) => {
    if (!url.includes("production-overhead-access")) throw Error(`Unexpected request: ${url}`);
    calls += 1;
    return { ok: true, json: async () => ({ organization_id: 1, principal: calls === 1 ? "chief" : "accountant", can_confirm: true }) };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingProductionOutputCostRevision org="1" month="2026-10" disabled={false} />);
  expect(await screen.findByRole("button", { name: "Повторить тот же запрос" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить тот же запрос" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Пользователь изменился");
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("revision-confirm"))).toBe(false);
  expect(values.size).toBe(1);
});

it("does not save or post a command when access resolves after the organization changes", async () => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key), clear: () => values.clear() });
  vi.stubGlobal("crypto", { randomUUID: () => "550e8400-e29b-41d4-a716-446655440000" });
  let accessCalls = 0;
  let finishConfirmAccess!: (value: unknown) => void;
  const fetcher = vi.fn((url: string) => {
    if (url.includes("production-overhead-access")) {
      accessCalls += 1;
      if (accessCalls === 3) return new Promise((resolve) => { finishConfirmAccess = resolve; });
      const organization_id = url.includes("/organizations/2/") ? 2 : 1;
      return Promise.resolve({ ok: true, json: async () => ({ organization_id, principal: "chief", can_confirm: true }) });
    }
    if (url.includes("transfer-status")) return Promise.resolve({ ok: true, json: async () => ({ organization_id: 1, month: "2026-10", order_id: 7, entry_id: 42 }) });
    if (url.includes("revision-preview")) return Promise.resolve({ ok: true, json: async () => ({ organization_id: 1, month: "2026-10", original_entry_id: 42, posting_date: "2026-10-31", request_evidence: "Late WIP", basis_digest: "a".repeat(64), source: { candidate_transfer_byn: "120.00" }, destinations: [], posting_document: null, final_cost_certified: false }) });
    throw Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AccountingProductionOutputCostRevision org="1" month="2026-10" disabled={false} />);
  await screen.findByText("Пользователь: chief");
  fireEvent.change(screen.getByLabelText("Номер наряда"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Основание корректировки"), { target: { value: "Late WIP" } });
  fireEvent.click(screen.getByRole("button", { name: "Найти выпуск" }));
  await screen.findByRole("button", { name: "Подготовить корректировку" });
  fireEvent.click(screen.getByRole("button", { name: "Подготовить корректировку" }));
  await screen.findByText("Источник: 120.00 BYN");
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить корректировку" }));
  await waitFor(() => expect(finishConfirmAccess).toBeTypeOf("function"));
  view.rerender(<AccountingProductionOutputCostRevision org="2" month="2026-10" disabled={false} />);
  await screen.findByText("Пользователь: chief");
  await act(async () => { finishConfirmAccess({ ok: true, json: async () => ({ organization_id: 1, principal: "chief", can_confirm: true }) }); });
  await waitFor(() => expect(values.size).toBe(0));
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("revision-confirm"))).toBe(false);
});

it("refuses a retry when the saved command changed in another tab", async () => {
  const command = { original_entry_id: 42, posting_date: "2026-10-31", request_evidence: "Late WIP", request_key: "550e8400-e29b-41d4-a716-446655440000", basis_digest: "a".repeat(64) };
  const key = 'production-output-cost-revision:["1","2026-10","chief"]';
  const values = new Map([[key, JSON.stringify({ org: "1", month: "2026-10", principal: "chief", command })]]);
  vi.stubGlobal("localStorage", { getItem: (item: string) => values.get(item) ?? null, setItem: (item: string, value: string) => values.set(item, value), removeItem: (item: string) => values.delete(item), clear: () => values.clear() });
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => ({ organization_id: 1, principal: "chief", can_confirm: true }) }));
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingProductionOutputCostRevision org="1" month="2026-10" disabled={false} />);
  const retry = await screen.findByRole("button", { name: "Повторить тот же запрос" });
  values.set(key, JSON.stringify({ org: "1", month: "2026-10", principal: "chief", command: { ...command, request_key: "550e8400-e29b-41d4-a716-446655440001" } }));
  fireEvent.click(retry);
  expect(await screen.findByRole("alert")).toHaveTextContent("изменился в другой вкладке");
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("revision-confirm"))).toBe(false);
});

it.each([
  ["Output cost basis changed; preview again", false],
  ["Accounting principal changed; review the command again", true],
])("preserves pending unless 409 is a definite stale basis: %s", async (detail, retained) => {
  const command = {original_entry_id:42,posting_date:"2026-10-31",request_evidence:"Late WIP",
    request_key:"550e8400-e29b-41d4-a716-446655440000",basis_digest:"a".repeat(64)};
  const pending = {org:"1",month:"2026-10",principal:"chief",command};
  const storageKey = 'production-output-cost-revision:["1","2026-10","chief"]';
  const values = new Map([[storageKey,JSON.stringify(pending)]]);
  vi.stubGlobal("localStorage",{getItem:(key:string)=>values.get(key)??null,
    setItem:(key:string,value:string)=>values.set(key,value),removeItem:(key:string)=>values.delete(key),clear:()=>values.clear()});
  vi.stubGlobal("fetch",vi.fn(async (url:string)=>url.includes("production-overhead-access")
    ? {ok:true,json:async()=>({organization_id:1,principal:"chief",can_confirm:true})}
    : {ok:false,status:409,json:async()=>({detail})}));
  render(<AccountingProductionOutputCostRevision org="1" month="2026-10" disabled={false}/>);
  fireEvent.click(await screen.findByRole("button",{name:"Повторить тот же запрос"}));
  await screen.findByRole("alert");
  expect(values.has(storageKey)).toBe(retained);
  expect(Boolean(screen.queryByRole("button",{name:"Повторить тот же запрос"}))).toBe(retained);
});
