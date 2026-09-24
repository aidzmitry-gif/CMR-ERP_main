
function milestones(target: string) {
  const stages = ["collection", "payment", "production", "to_cn_warehouse", "to_minsk", "customs"]; const durations = [28, 7, 14, 7, 20, 7]; let day = new Date(target);
  const result = stages.map((stage, seq) => ({ stage, title: stage, seq, duration_days: durations[seq], planned_date: "", actual_date: null }));
  for (const m of [...result].reverse()) { m.planned_date = day.toISOString().slice(0, 10); day = new Date(day.getTime() - m.duration_days * 86400000); } return { milestones: result, start_date: day.toISOString().slice(0, 10) };
}
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { ProcurementMachineEditor } from "./procurement-machine-editor";
import { commandHash, emptyLine, type EditCommand } from "@/lib/procurement-machine";
const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
const storage = vi.hoisted(() => ({ rows: new Map<string, unknown>(), tail: Promise.resolve(), fail: false }));
vi.mock("@/lib/procurement-editor-journal", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/procurement-editor-journal")>();
  return { ...actual, editorJournal: actual.createJournal({ change(key, update) {
    const next = storage.tail.then(() => {
      if (storage.fail) throw new Error("storage unavailable");
      const value = update(structuredClone(storage.rows.get(key) ?? null) as import("@/lib/procurement-editor-journal").Attempt | null);
      if (value) storage.rows.set(key, structuredClone(value)); return structuredClone(value);
    }); storage.tail = next.then(() => {}, () => {}); return next;
  } }) };
});
const pending = () => [...storage.rows.values()].filter(x => (x as { state: string }).state === "pending");
const serverReceipts = new Map<string, unknown>();
let f: ReturnType<typeof vi.fn>;
let principal: string; let manage: boolean; let status: string; let freight: string;
let lines: { id: number; sku_code: string; qty: string; goods_value_byn: string; weight: string; volume: string }[];
let mode: string; let date: string | null;
const ok = (body: unknown) => ({ ok: true, status: (body as { action?: string })?.action === "add_line" ? 201 : 200, json: async () => body });
const plan = (org: number) => ({ organization_id: org, order_id: 7, principal, transport_method_code: "truck", target_arrival_date: date, start_date: null, total_days: 83, ...(date ? milestones(date) : { milestones: [], start_date: null }), customer_requirements_status: "unverified", at_risk: null, required_by: null, required_arrival: null, slack_days: null, at_risk_deals: [], schedule_start_in_past: null });
const writes = () => f.mock.calls.filter(([, init]) => init?.method);
beforeEach(() => {
  navigation.push.mockClear();
  storage.rows.clear(); storage.tail = Promise.resolve(); storage.fail = false; serverReceipts.clear(); sessionStorage.clear(); principal = "alice"; manage = true; status = "draft"; freight = "100.00"; mode = "ok"; date = null;
  lines = [{ id: 11, ...emptyLine(), sku_code: "AKB-190", qty: "2.00", goods_value_byn: "900.00", weight: "50.000", volume: "3.0000" }];
  f = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("receipt-organizations")) return ok([{ id: 1, name: "A", unp: "1" }, { id: 2, name: "B", unp: "2" }]);
    const org = Number(url.match(/organizations\/(\d+)/)?.[1] ?? (init?.headers as Record<string, string>)?.["X-Expected-Organization"] ?? 1);
    if (url.endsWith("request-plan-context")) return ok({ organization_id: org, principal, can_manage: manage });
    if (url.includes("/sku-options?q=")) return ok({ organization_id: org, items: [{ id: 71, code: "AKB-190", title: "Аккумулятор", unit: "шт" }, { id: 99, code: "NEW", title: "Новый товар", unit: "шт" }], truncated: false });
    if (url.includes("/edit-history?after_id=")) return ok({ organization_id: org, order_id: 7, number: org === 1 ? "ZAK-7" : "B-7", items: [], next_after_id: null });
    if (init?.method) {
      const c = JSON.parse(String(init.body)) as EditCommand;
      const common = { version: 1, organization_id: org, principal, request_key: c.request_key, command_hash: await commandHash(c), order_id: 7, action: c.action };
      let result = serverReceipts.get(c.request_key);
      if (mode === "reject") return { ok: false, status: 409, json: async () => ({ detail: "conflict" }) };
      if (!result && url.endsWith("/reconcile")) { result = { ...common, outcome: "rejected", code: "command_abandoned", no_business_write: true }; serverReceipts.set(c.request_key, result); }
      if (!result) {
        if (mode === "lost") throw new Error("lost response");
        const body = c.payload; let effect: unknown;
        if (c.action === "add_line") { const row = { id: 12, sku_code: body.sku_code, qty: body.qty, goods_value_byn: body.goods_value_byn, weight: body.weight, volume: body.volume } as typeof lines[number]; lines.push(row); effect = { line: row }; }
        else if (c.action === "delete_line") { effect = { line: lines.find(x => x.id === body.line_id) }; lines = lines.filter(x => x.id !== body.line_id); }
        else if (c.action === "header") { effect = { before: { freight_byn: freight }, after: body }; freight = String(body.freight_byn); }
        else if (c.action === "plan") { date = String(body.target_arrival_date); effect = plan(org); }
        else { effect = { from: status, to: body.status, received_at: null, event_ids: status === body.status ? [] : [1] }; status = String(body.status); }
        result = { ...common, outcome: "applied", ownership_id: 9, effect }; serverReceipts.set(c.request_key, result);
      }
      if (mode === "lost-after") throw new Error("lost after commit");
      return { ok: (result as { outcome: string }).outcome === "applied", status: (result as { outcome: string }).outcome === "applied" ? 200 : 409, json: async () => result };
    }
    if (url.includes("?after_line_id=")) return ok({ organization_id: org, id: 7, number: org === 1 ? "ZAK-7" : "B-7", supplier: "Shenzhen Co", status, eta_date: "2026-08-01", freight_byn: freight, lines: [...lines], next_after_line_id: null });
    if (url.endsWith("landed-preview")) return mode === "no-preview" ? { ok: false, status: 503 } : ok({ organization_id: org, order_id: 7, freight_byn: freight, lines: [{ sku_code: "AKB-190", goods_byn: "900.00", allocated_byn: "50.00", landed_total_byn: "950.00", unit_landed_cost_byn: "475.00" }], total_goods_byn: "900.00", total_landed_byn: "950.00" });
    if (url.endsWith("/plan")) return ok(plan(org));
    throw new Error(`Unexpected URL ${url}`);
  }); vi.stubGlobal("fetch", f);
});
afterEach(() => vi.unstubAllGlobals());
async function ready() { render(<ProcurementMachineEditor orderId={7} suggestedOrg="1" />); await screen.findByText("Состав заказа ZAK-7"); await waitFor(() => expect(screen.getByRole("button", { name: "Проверить состав" })).toBeEnabled()); }
async function selectNewSku() { await screen.findByRole("option", { name: "NEW · Новый товар · шт" }); fireEvent.change(screen.getByLabelText("Номенклатура из справочника"), { target: { value: "99" } }); }
it("renders header, status and backend preview through scoped reads", async () => { await ready(); expect(screen.getByText(/Shenzhen Co/)).toHaveTextContent("Черновик"); expect(screen.getByText(/Shenzhen Co/)).toHaveTextContent("ETA 2026-08-01"); expect(screen.getByText("475")).toBeInTheDocument(); expect(screen.getByText("Итого landed: 950.00 BYN")).toBeInTheDocument(); });
it("shows saved order changes with actor and server time", async () => {
  const original = f.getMockImplementation()!;
  f.mockImplementation((url: string, init?: RequestInit) => url.includes("/edit-history?after_id=")
    ? Promise.resolve(ok({ organization_id: 1, order_id: 7, number: "ZAK-7", items: [{ id: 31, changed_at: "2026-09-24T12:00:00Z", changed_by: "tester", action: "header", changes: [{ field: "freight_byn", before: "100.00", after: "120.00" }] }], next_after_id: null }))
    : original(url, init));
  await ready();
  expect(screen.getByRole("region", { name: "История изменений заказа" })).toHaveTextContent("2026-09-24T12:00:00Z · tester");
  expect(screen.getByText("Фрахт, BYN: 100.00 → 120.00")).toBeInTheDocument();
});
it("separates expected, client-bound and free quantities without calling them physical stock", async () => {
  const original = f.getMockImplementation()!;
  f.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith("expected-reservations/order/7")) return Promise.resolve(ok({ organization_id: 1, order_id: 7, lines: [{ pending_conversion_count: 0, order_line_id: 11, sku_code: "AKB-190", ordered: "20.00", accepted: "0.00", warehouse_accepted: "0.00", physical_convertible: "0.00", expected: "20.00", converted: "0.00", convertible: "0.00", expected_reserved: "12.00", free_expected: "8.00", uncovered: "0.00", reservations: [] }] }));
    if (url.endsWith("orders/7/deal-demands")) return Promise.resolve(ok({ organization_id: 1, order_id: 7, lines: [{ order_line_id: 11, sku_code: "AKB-190", ordered: "20.00", client_ordered: "12.00", free_for_client: "12.00", candidates: [{ demand_id: 31, deal_id: 41, deal_item_id: 51, sku_code: "AKB-190", qty: "12.00", free_qty: "12.00", document_id: 61 }], allocations: [] }] }));
    if (url.endsWith("demands/31/allocations") && init?.method === "POST") { const command = JSON.parse(String(init.body)); return Promise.resolve(ok({ id: 31, organization_id: 1, deal_id: 41, deal_item_id: 51, sku_id: 71, sku_code: "AKB-190", qty: "12.00", ordered_qty: "8.00", free_qty: "4.00", document_id: 61, request_key: "demand-key", allocations: [{ id: 91, order_id: 7, order_line_id: 11, qty: "8.00" }], replayed: false, allocation_request_key: command.request_key, allocation: { id: 91, demand_id: 31, order_id: 7, order_line_id: 11, sku_code: "AKB-190", qty: "8.00" } })); }
    return original(url, init);
  });
  await ready();
  expect(screen.getByLabelText("Предварительный резерв AKB-190")).toHaveTextContent("Ожидается 20.00 · клиентам 12.00 · свободно 8.00");
  expect(screen.getByText(/товар ещё не на складе и физический остаток или резерв не изменяются/)).toBeInTheDocument();
  expect(screen.getByText("сделка №41 · счёт ID 61: 12.00 шт.")).toBeInTheDocument();
  const reserve = screen.getByRole("button", { name: "Закрепить ожидаемые 8.00" }); expect(reserve).toBeEnabled(); fireEvent.click(reserve);
  await waitFor(() => expect(f.mock.calls.find(([url]) => String(url).endsWith("demands/31/allocations"))?.[1]?.body).toContain('"qty":"8.00"'));
});
it("does not fetch an order without explicit organization", async () => { render(<ProcurementMachineEditor orderId={7} />); await screen.findByRole("option", { name: "A · 1" }); expect(f.mock.calls.map(([url]) => url)).toEqual(["/api/procurement/receipt-organizations"]); });
it("empty lines show the original add hint", async () => { lines = []; await ready(); expect(screen.getByText(/Позиций нет/)).toBeInTheDocument(); });
it("missing preview shows a dash and an error, never zero cost", async () => { mode = "no-preview"; await ready(); expect(screen.getByText("—")).toBeInTheDocument(); expect(screen.getByRole("alert")).toHaveTextContent("503"); expect(screen.queryByText(/Итого landed/)).not.toBeInTheDocument(); });
it("validates empty SKU before posting", async () => { await ready(); fireEvent.click(screen.getByRole("button", { name: "Добавить позицию" })); expect(screen.getByRole("alert")).toHaveTextContent("Выберите номенклатуру"); expect(writes()).toHaveLength(0); });
it("adds a line with exact decimals and displays the refreshed row", async () => {
  await ready(); await selectNewSku(); fireEvent.change(screen.getByLabelText("Стоимость товара"), { target: { value: "1234567.89" } }); fireEvent.click(screen.getByRole("button", { name: "Добавить позицию" }));
  await screen.findByText("NEW"); expect(JSON.parse(String(writes()[0][1].body)).payload).toMatchObject({ sku_id: 99, sku_code: "NEW", sku_title: "Новый товар", sku_unit: "шт", goods_value_byn: "1234567.89", qty: "1.00" });
});
it("generic409 shows the reason but cannot close the pending journal", async () => { await ready(); mode = "reject"; await selectNewSku(); fireEvent.click(screen.getByRole("button", { name: "Добавить позицию" })); await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("409")); expect(pending()).toHaveLength(1); });
it("deletes the selected line and refreshes the composition", async () => { await ready(); fireEvent.click(screen.getByRole("button", { name: "Удалить позицию" })); await screen.findByText(/Позиций нет/); expect(JSON.parse(String(writes()[0][1].body))).toMatchObject({ action: "delete_line", payload: { line_id: 11 } }); });
it("rejects negative freight and restores previous text", async () => { await ready(); const input = screen.getByLabelText("Фрахт партии, BYN"); fireEvent.change(input, { target: { value: "-5" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить фрахт" })); expect(screen.getByRole("alert")).toHaveTextContent("неотрицательным"); expect(input).toHaveValue("100.00"); expect(writes()).toHaveLength(0); });
it("saves valid freight only on an explicit action", async () => { await ready(); const input = screen.getByLabelText("Фрахт партии, BYN"); fireEvent.blur(input); expect(writes()).toHaveLength(0); fireEvent.change(input, { target: { value: "200.13" } }); fireEvent.click(screen.getByRole("button", { name: "Сохранить фрахт" })); await screen.findByText("Изменение сохранено. Серверная квитанция подтверждена."); expect(JSON.parse(String(writes()[0][1].body)).payload).toEqual({ freight_byn: "200.13" }); });
it("saves and closes only after the server confirms a changed order", async () => {
  await ready(); fireEvent.change(screen.getByLabelText("Фрахт партии, BYN"), { target: { value: "200.13" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/erp/procurement/orders?org=1"));
  expect(JSON.parse(String(writes()[0][1].body)).payload).toEqual({ freight_byn: "200.13" });
});
it("retains unsaved fields and stays open when a later change fails", async () => {
  const original = f.getMockImplementation()!;
  f.mockImplementation((url: string, init?: RequestInit) => init?.method && JSON.parse(String(init.body)).action === "header"
    ? Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: "conflict" }) })
    : original(url, init));
  await ready(); await selectNewSku();
  fireEvent.change(screen.getByLabelText("Фрахт партии, BYN"), { target: { value: "200.13" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("409"));
  expect(screen.getByLabelText("Фрахт партии, BYN")).toHaveValue("200.13");
  expect(screen.getByText("NEW")).toBeInTheDocument();
  expect(writes()).toHaveLength(2);
  expect(navigation.push).not.toHaveBeenCalled();
});
it("keeps the editor open when the save result is unknown", async () => {
  await ready(); mode = "lost-after"; fireEvent.change(screen.getByLabelText("Фрахт партии, BYN"), { target: { value: "200.13" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await screen.findByText(/Исход команды не подтверждён сервером/);
  expect(navigation.push).not.toHaveBeenCalled(); expect(screen.getByLabelText("Фрахт партии, BYN")).toHaveValue("200.13");
});
it("does not close with an incomplete new position", async () => {
  await ready(); fireEvent.change(screen.getByLabelText("Количество"), { target: { value: "3.00" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Выберите номенклатуру");
  expect(navigation.push).not.toHaveBeenCalled(); expect(writes()).toHaveLength(0);
});
it.each(["received", "cancelled"])("terminal %s composition stays uneditable", async terminal => { status = terminal; await ready(); expect(screen.getByRole("button", { name: "Добавить позицию" })).toBeDisabled(); expect(screen.getByLabelText("Фрахт партии, BYN")).toBeDisabled(); expect(screen.getByRole("button", { name: "Удалить позицию" })).toBeDisabled(); });
it("reader sees own order and cannot write", async () => { manage = false; await ready(); expect(screen.getByRole("button", { name: "Добавить позицию" })).toBeDisabled(); expect(screen.getByRole("button", { name: "Пересчитать план" })).toBeDisabled(); expect(writes()).toHaveLength(0); });
it("chief can change lifecycle status and plan with an explicit date", async () => {
  await ready(); fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await waitFor(() => expect(screen.getByText(/Shenzhen Co/)).toHaveTextContent("Заказан")); await waitFor(() => expect(screen.getByRole("button", { name: "Пересчитать план" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Пересчитать план" })); expect(screen.getByRole("alert")).toHaveTextContent("Укажите дату"); expect(writes()).toHaveLength(1);
  fireEvent.change(screen.getByLabelText("В Минске до"), { target: { value: "2026-12-01" } }); fireEvent.click(screen.getByRole("button", { name: "Пересчитать план" })); await waitFor(() => expect(writes()).toHaveLength(2)); expect(JSON.parse(String(writes()[1][1].body)).payload).toEqual({ transport_method_code: "truck", target_arrival_date: "2026-12-01" }); expect(screen.getByText("Клиентские сроки и штрафы не проверены.")).toBeInTheDocument();
});
it("principal change before send blocks the command and clears old data", async () => { await ready(); principal = "bob"; fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Пользователь изменился")); expect(writes()).toHaveLength(0); expect(screen.queryByText("Состав заказа ZAK-7")).not.toBeInTheDocument(); });
it("lost response remains unknown across reload and is never automatically resent", async () => {
  const view = render(<ProcurementMachineEditor orderId={7} suggestedOrg="1" />); await waitFor(() => expect(screen.getByRole("button", { name: "Изменить статус" })).toBeEnabled()); mode = "lost";
  fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await screen.findByText(/Исход команды не подтверждён сервером/); expect(writes()).toHaveLength(1); expect(pending()).toHaveLength(1);
  view.unmount(); mode = "ok"; await ready(); expect(screen.getByRole("button", { name: "Добавить позицию" })).toBeDisabled(); expect(writes()).toHaveLength(1);
});
it("late org A response cannot overwrite org B", async () => {
  let release!: (v: unknown) => void; const original = f.getMockImplementation()!; f.mockImplementation((url: string, init?: RequestInit) => url.includes("organizations/1/orders/7?") ? new Promise(r => { release = r; }) : original(url, init));
  render(<ProcurementMachineEditor orderId={7} suggestedOrg="1" />); await waitFor(() => expect(release).toBeTypeOf("function")); fireEvent.change(screen.getByLabelText("Юрлицо заказа"), { target: { value: "2" } }); await screen.findByText("Состав заказа B-7");
  await act(async () => { release(ok({ organization_id: 1, id: 7, number: "ZAK-7", supplier: "S", status: "draft", eta_date: null, freight_byn: "1.00", lines: [], next_after_line_id: null })); }); expect(screen.queryByText("Состав заказа ZAK-7")).not.toBeInTheDocument();
});
it("storage failure prevents dispatch", async () => { await ready(); storage.fail = true; fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("storage unavailable")); expect(writes()).toHaveLength(0); });

it("known saved write followed by failed refresh is not reported as an undo", async () => {
  await ready(); const original = f.getMockImplementation()!;
  let written = false;
  f.mockImplementation(async (url: string, init?: RequestInit) => { if (written && url.includes("?after_line_id=")) return { ok: false, status: 503 }; const response = await original(url, init); if (init?.method) written = true; return response; });
  fireEvent.click(screen.getByRole("button", { name: "Изменить статус" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Квитанция сохранена, но состав не обновлён"));
  expect(pending()).toHaveLength(0); expect(writes()).toHaveLength(1);
});
it("principal change after an accepted write keeps journal and hides the old order", async () => {
  await ready(); const original = f.getMockImplementation()!;
  f.mockImplementation(async (url: string, init?: RequestInit) => { const response = await original(url, init); if (init?.method) principal = "bob"; return response; });
  fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await screen.findByText(/Исход команды не подтверждён сервером/);
  expect(screen.queryByText("Состав заказа ZAK-7")).not.toBeInTheDocument(); expect(pending()).toHaveLength(1); expect(writes()).toHaveLength(1);
});
it("grant loss after displayed detail clears data and prevents a command", async () => {
  await ready(); manage = false; fireEvent.click(screen.getByRole("button", { name: "Изменить статус" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("нужны права")); expect(writes()).toHaveLength(0); expect(screen.getByRole("button", { name: "Добавить позицию" })).toBeDisabled();
});
it("reading old composition cannot resolve an unknown write or enable another command", async () => {
  await ready(); mode = "lost"; fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await screen.findByText(/Исход команды не подтверждён сервером/); mode = "ok";
  const journal = JSON.stringify(pending());
  fireEvent.click(screen.getByRole("button", { name: "Проверить состав" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Проверить состав" })).toBeEnabled());
  expect(screen.queryByRole("button", { name: /Результат проверен/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Добавить позицию" })).toBeDisabled();
  expect(JSON.stringify(pending())).toBe(journal); expect(writes()).toHaveLength(1);
});
it("double submit is blocked while the command is pending", async () => {
  await ready(); let release!: (v: unknown) => void; const original = f.getMockImplementation()!;
  f.mockImplementation((url: string, init?: RequestInit) => init?.method ? new Promise(r => { release = r; }) : original(url, init));
  const button = screen.getByRole("button", { name: "Изменить статус" }); fireEvent.click(button); fireEvent.click(button); await waitFor(() => expect(writes()).toHaveLength(1));
  await act(async () => { release(await original(String(writes()[0][0]), writes()[0][1])); }); expect(writes()).toHaveLength(1);
});

it("lost applied command recovers the exact UUID without duplicating a line", async () => {
  await ready(); mode = "lost-after"; await selectNewSku(); fireEvent.click(screen.getByRole("button", { name: "Добавить позицию" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Повторить сохранённую команду" })).toBeEnabled()); const first = writes()[0][1].body; mode = "ok";
  fireEvent.click(screen.getByRole("button", { name: "Повторить сохранённую команду" })); await screen.findByText("NEW"); expect(writes()[1][1].body).toBe(first); expect(lines.filter(x => x.sku_code === "NEW")).toHaveLength(1); expect(pending()).toHaveLength(0);
});
it("reconcile tombstone restores editor only after explicit preparation and blocks late original", async () => {
  await ready(); mode = "lost"; fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await waitFor(() => expect(screen.getByRole("button", { name: "Сверить и закрыть неисполненную" })).toBeEnabled()); const originalBody = String(writes()[0][1].body); mode = "ok";
  fireEvent.click(screen.getByRole("button", { name: "Сверить и закрыть неисполненную" })); await screen.findByRole("button", { name: "Подготовить новую попытку" }); expect(writes()[1][1].body).toBe(originalBody); expect(screen.getByRole("button", { name: "Изменить статус" })).toBeDisabled();
  const late = await f(String(writes()[0][0]), writes()[0][1]); expect(late.status).toBe(409); expect(status).toBe("draft");
  await waitFor(() => expect(screen.getByRole("button", { name: "Подготовить новую попытку" })).toBeEnabled()); fireEvent.click(screen.getByRole("button", { name: "Подготовить новую попытку" })); fireEvent.click(screen.getByRole("button", { name: "Изменить статус" })); await waitFor(() => expect(status).toBe("ordered")); expect(JSON.parse(String(writes().at(-1)![1].body)).request_key).not.toBe(JSON.parse(originalBody).request_key);
});
it("legacy nonUUID attempt is not migrated or unlocked by a GET", async () => {
  sessionStorage.setItem("procurement-editor/1/7", JSON.stringify({ action: "add_line", body: { sku_code: "OLD" } })); await ready();
  expect(screen.getByText(/Старая попытка без UUID остаётся/)).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Добавить позицию" })).toBeDisabled(); expect(screen.queryByRole("button", { name: "Сверить и закрыть неисполненную" })).not.toBeInTheDocument(); expect(writes()).toHaveLength(0); expect(storage.rows.size).toBe(0);
});
