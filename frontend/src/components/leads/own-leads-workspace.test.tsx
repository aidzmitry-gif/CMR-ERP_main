import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Lead } from "@/lib/types";
import { OwnLeadEditor, OwnLeadsWorkspace } from "./own-leads-workspace";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("./leads-load", () => ({ loadLeadsClient: vi.fn().mockResolvedValue({ state: "ok", leads: [] }) }));
const lead = { id: 4, company: "Owned buyer", source: "phone", name: "Buyer", status: "routed",
  assignedTo: "Owner", ownerId: 901, crmClientId: 1 } as Lead;
const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
const clients = [1, 2].map((id) => ({ id, name: `Buyer ${id}`, source: "crm", unp: null, is_active: true, deal_id: null }));

beforeEach(() => { vi.restoreAllMocks(); });

it("uses canonical server prices after PUT and rejects malformed confirmation", async () => {
  let malformed = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => url.includes("/items")
    ? json(init?.method === "PUT" ? malformed ? {} : [{ sku_id: 1, qty: "1.00", price: "1.01" }] : [{ sku_id: 1, qty: 1, price: 1 }])
    : json([{ id: 1, code: "SKU", title: "Part" }])));
  const updated = vi.fn(); render(<OwnLeadEditor lead={lead} onUpdated={updated} />);
  const price = await screen.findByLabelText("Цена 1");
  fireEvent.change(price, { target: { value: "1.005" } });
  fireEvent.click(screen.getByText("Сохранить позиции"));
  await waitFor(() => expect(price).toHaveValue(1.01));
  expect(screen.getByText("Конвертировать в сделку")).toBeEnabled();
  malformed = true;
  fireEvent.change(price, { target: { value: "2" } });
  fireEvent.click(screen.getByText("Сохранить позиции"));
  await screen.findByRole("alert");
  expect(screen.getByText("Конвертировать в сделку")).toBeDisabled();
  expect(updated).toHaveBeenCalledTimes(1);
});

it.each([0, 409, 503])("refreshes persisted lead after ambiguous route outcome %s", async (status) => {
  const updated = vi.fn(); const routed = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!url.endsWith("/route")) return json([]);
    routed(); if (!status) throw new Error("Lost reply");
    return new Response(JSON.stringify({ detail: "Route outcome uncertain" }), { status });
  }));
  const view = render(<OwnLeadEditor lead={{ ...lead, status: "qualified" }} onUpdated={updated} />);
  await waitFor(() => expect(screen.getByLabelText("Следующий шаг")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Следующий шаг"), { target: { value: "Call" } });
  fireEvent.change(screen.getByLabelText("Срок"), { target: { value: "2026-09-20T10:00" } });
  fireEvent.click(screen.getByText("Назначить себе"));
  await waitFor(() => expect(updated).toHaveBeenCalledTimes(1));
  view.rerender(<OwnLeadEditor lead={lead} onUpdated={updated} />);
  expect(screen.getByText("Конвертировать в сделку")).toBeEnabled();
  expect(routed).toHaveBeenCalledTimes(1);
});

it("ignores a late saved response after selecting another lead", async () => {
  let resolve!: (value: Response) => void;
  const pending = new Promise<Response>((done) => { resolve = done; });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => init?.method === "PUT" ? pending : url.includes("/items")
    ? json([{ sku_id: 1, qty: 1, price: url.includes("/4/") ? 1 : 3 }]) : json([])));
  const updated = vi.fn(); const view = render(<OwnLeadEditor lead={lead} onUpdated={updated} />);
  await screen.findByLabelText("Цена 1"); fireEvent.click(screen.getByText("Сохранить позиции"));
  view.rerender(<OwnLeadEditor lead={{ ...lead, id: 5 }} onUpdated={updated} />);
  await waitFor(() => expect(screen.getByLabelText("Цена 1")).toHaveValue(3));
  await act(async () => resolve(json([{ sku_id: 1, qty: 1, price: 99 }])));
  expect(screen.getByLabelText("Цена 1")).toHaveValue(3);
  expect(updated).not.toHaveBeenCalled();
});

it("keeps null price blank, allows explicit zero and blocks conversion of unsaved rows", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("/items") ? json([{ sku_id: 1, qty: 1, price: null }]) : json([{ id: 1, code: "SKU", title: "Part" }])));
  render(<OwnLeadEditor lead={lead} onUpdated={vi.fn()} />);
  const price = await screen.findByLabelText("Цена 1");
  expect(price).toHaveValue(null);
  expect(screen.getByText("Сохранить позиции")).toBeDisabled();
  expect(screen.getByText("Конвертировать в сделку")).toBeDisabled();
  fireEvent.change(price, { target: { value: "0" } });
  expect(screen.getByText("Сохранить позиции")).toBeEnabled();
  expect(screen.getByText("Конвертировать в сделку")).toBeDisabled();
});

it("does not issue legacy stats, channels or bulk requests for own workspace", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<OwnLeadsWorkspace initialLeads={[lead]} />);
  expect(screen.getByText("Мои лиды")).toBeInTheDocument();
  expect(screen.queryByText("Разобрать целевых")).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});

it("replays exactly the saved creation after a lost reply", async () => {
  const bodies: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/clients?")) return json({ rows: clients, total: 2 });
    if (url.includes("/contacts")) return json([]);
    if (url === "/api/leads") {
      bodies.push(String(init?.body));
      if (bodies.length === 1) throw new Error("Lost reply");
      return json({ id: 44 });
    }
    throw new Error(url);
  }));
  render(<OwnLeadsWorkspace initialLeads={[]} />);
  fireEvent.click(screen.getByText("Новый лид"));
  await screen.findByText("Buyer 1");
  fireEvent.change(screen.getByLabelText("CRM-клиент"), { target: { value: "1" } });
  await waitFor(() => expect(screen.getByText("Создать лид")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Обращение"), { target: { value: "Confirmed request" } });
  fireEvent.click(screen.getByText("Создать лид"));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Обращение")).toBeDisabled();
  fireEvent.click(screen.getByText("Повторить создание"));
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies[0]).toBe(bodies[1]);
  expect(JSON.parse(bodies[0]).crm_client_id).toBe(1);
  expect(JSON.parse(bodies[0]).request_key).toBeTruthy();
});

it("ignores late contacts from a previously selected client", async () => {
  let resolveOld!: (value: Response) => void;
  const old = new Promise<Response>((resolve) => { resolveOld = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/clients?")) return json({ rows: clients, total: 2 });
    if (url.includes("/clients/1/contacts")) return old;
    return json([{ id: 22, crm_client_id: 2, full_name: "Current contact", phone: null, email: null, is_primary: false }]);
  }));
  render(<OwnLeadsWorkspace initialLeads={[]} />);
  fireEvent.click(screen.getByText("Новый лид"));
  await screen.findByText("Buyer 1");
  fireEvent.change(screen.getByLabelText("CRM-клиент"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("CRM-клиент"), { target: { value: "2" } });
  await screen.findByText("Current contact");
  await act(async () => resolveOld(json([{ id: 11, crm_client_id: 1, full_name: "Stale contact", phone: null, email: null, is_primary: false }])));
  expect(screen.queryByText("Stale contact")).not.toBeInTheDocument();
});

it("keeps conversion retry available after transport failure without double clicks", async () => {
  let reject!: (error: Error) => void;
  const pending = new Promise<Response>((_, fail) => { reject = fail; });
  const converted = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!url.endsWith("/convert")) return json([]);
    converted(); return pending;
  }));
  const updated = vi.fn(); render(<OwnLeadEditor lead={lead} onUpdated={updated} />);
  await waitFor(() => expect(screen.getByText("Конвертировать в сделку")).toBeEnabled());
  fireEvent.click(screen.getByText("Конвертировать в сделку"));
  fireEvent.click(screen.getByText("Конвертировать в сделку"));
  expect(converted).toHaveBeenCalledTimes(1);
  await act(async () => reject(new Error("Lost reply")));
  expect(screen.getByText("Конвертировать в сделку")).toBeEnabled();
  expect(updated).not.toHaveBeenCalled();
});
