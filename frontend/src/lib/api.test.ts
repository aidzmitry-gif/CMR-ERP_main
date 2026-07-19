import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addContact,
  addDealItem,
  aiAssist,
  aiDraftReply,
  callComment,
  callLinkDeal,
  callResult,
  commitLeadItemsToDeal,
  completeDealTask,
  convertLead,
  createDeal,
  createDealTask,
  createDocument,
  createPriceQuote,
  createStage,
  decideApproval,
  decideDocument,
  decidePlan,
  deleteDealItem,
  deleteLeadAttachment,
  deleteStage,
  expressBulkLeads,
  expressLead,
  fetchApprovals,
  fetchBoardResult,
  fetchBoardStages,
  fetchBranding,
  fetchCalls,
  fetchChats,
  fetchContacts,
  fetchDealDetail,
  fetchDealHandoff,
  fetchDealItems,
  fetchDealTasks,
  fetchDocuments,
  fetchEvents,
  fetchFunnels,
  fetchFunnelsServer,
  fetchKpis,
  fetchLastOrder,
  fetchLead,
  fetchLeadAttachments,
  fetchLeadHandoffStats,
  fetchLeadItems,
  fetchLeadManagers,
  fetchLeadPlan,
  fetchLeadSourceStats,
  fetchLeads,
  fetchLeadsClient,
  fetchLossReasons,
  fetchMessages,
  fetchOwnerDashboard,
  fetchOwnerInsight,
  fetchPlans,
  fetchSkus,
  fetchStock,
  getKpis,
  createLead,
  issueDocument,
  leadAttachmentDownloadUrl,
  LeadDuplicateError,
  linkLeadContact,
  localToNaiveUtc,
  logActivity,
  logLeadAttempt,
  loseDeal,
  lookupCounterparty,
  qualifyLead,
  rejectLead,
  requestApproval,
  routeLead,
  saveLeadItems,
  saveLeadPlan,
  sendMessage,
  setPrimaryContact,
  subscribeCalls,
  submitEmailLead,
  submitPlan,
  submitWebLead,
  triggerIncomingCall,
  updateBranding,
  updateDeal,
  updateDealItem,
  updateDealStage,
  updateStage,
  uploadLeadAttachment,
  upsertPlan,
} from "@/lib/api";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, json: async () => data }));
}

const apiDeal = {
  id: 9, number: "CRM-9", title: "Поставка", counterparty: "ООО Доска", amount: 500,
  priority: "Высокий", stage: "new", owner: "Иванов", next_step: "Звонок",
  deal_date: "12.05.2024", closed_date: null, focus: false, starred: true,
};

const apiLead = {
  id: 1, source: "site", name: "Иван", company: "ООО Тест", phone: null, email: null,
  region: "Минск", product: "лист", message: "m", status: "new", score: 0,
  qualification: "", reason: "", assigned_to: "", funnel: "", deal_id: null,
};

describe("api client — лиды", () => {
  it("fetchLeads маппит snake_case → camelCase", async () => {
    stubFetch([apiLead]);
    const [lead] = await fetchLeads();
    expect(lead.assignedTo).toBe("");
    expect(lead.dealId).toBeUndefined();
    expect(lead.region).toBe("Минск");
    expect(lead.status).toBe("new");
  });

  it("fetchLeads → [] при ошибке сети", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net down")));
    expect(await fetchLeads()).toEqual([]);
  });

  it("createLead маппит ответ или возвращает null при !ok", async () => {
    stubFetch({ ...apiLead, id: 7, company: "ООО Новый" });
    const created = await createLead({ source: "site", company: "ООО Новый" });
    expect(created?.id).toBe(7);
    expect(created?.company).toBe("ООО Новый");

    stubFetch({}, false);
    expect(await createLead({ source: "site" })).toBeNull();
  });

  it("qualifyLead возвращает балл, вердикт и AI-обоснование", async () => {
    stubFetch({
      id: 1, status: "qualified", score: 80, qualification: "target",
      reason: "есть телефон", ai_rationale: "обоснование", model: "qwen",
    });
    const res = await qualifyLead(1);
    expect(res?.qualification).toBe("target");
    expect(res?.score).toBe(80);
    expect(res?.ai_rationale).toBe("обоснование");
  });

  it("routeLead и convertLead возвращают результат сервера", async () => {
    stubFetch({ id: 1, status: "routed", assigned_to: "Иванов И.И.", funnel: "new" });
    expect((await routeLead(1))?.assigned_to).toBe("Иванов И.И.");

    stubFetch({ lead_id: 1, deal_id: 42, number: "CRM-LEAD-1", status: "converted" });
    expect((await convertLead(1))?.deal_id).toBe(42);
  });

  it("routeLead → null при ошибке HTTP", async () => {
    stubFetch({}, false);
    expect(await routeLead(1)).toBeNull();
  });
});

describe("api client — сделки/доска/KPI", () => {
  it("fetchBoardStages маппит стадии и сделки", async () => {
    stubFetch({ stages: [{ id: "new", title: "Новая", color: "#000", count: 1, sum: 500, deals: [apiDeal] }] });
    const stages = await fetchBoardStages();
    expect(stages[0].id).toBe("new");
    expect(stages[0].deals[0].company).toBe("ООО Доска");
    expect(stages[0].deals[0].starred).toBe(true);
  });

  it("fetchBoardStages → mock-fallback при ошибке", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect((await fetchBoardStages()).length).toBeGreaterThan(0);
  });

  it("fetchBoardResult честно помечает mock-fallback как demo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect((await fetchBoardResult()).demo).toBe(true);
    stubFetch({ stages: [] });
    expect((await fetchBoardResult()).demo).toBe(false);
  });

  it("fetchBoardResult не маскирует 403 демо-доской", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 403, ok: false }));
    const r = await fetchBoardResult();
    expect(r.demo).toBe(false);
    expect(r.authError).toBe(true);
    expect(r.stages).toEqual([]);
  });

  it("mapDeal переносит closed_date в closedDate (закрытая сделка)", async () => {
    stubFetch({
      stages: [
        { id: "won", title: "Закрыто", color: "#000", count: 1, sum: 100, deals: [{ ...apiDeal, deal_date: null, closed_date: "10.05.2024" }] },
      ],
    });
    const [won] = await fetchBoardStages();
    expect(won.deals[0].closedDate).toBe("10.05.2024");
    expect(won.deals[0].date).toBeUndefined();
  });

  it("fetchDealDetail маппит карточку с позициями", async () => {
    stubFetch({ ...apiDeal, items: [{ title: "Лист", last_price: 1500, min_price: 1450 }] });
    const detail = await fetchDealDetail("9");
    expect(detail.company).toBe("ООО Доска");
    expect(detail.items[0].title).toBe("Лист");
    expect(detail.items[0].minPrice).toBe(1450);
  });

  it("createDeal маппит ответ; null при !ok", async () => {
    stubFetch(apiDeal);
    expect((await createDeal({ number: "CRM-9", title: "t", counterparty: "c", amount: 1, priority: "Средний", stage: "new", owner: "" }))?.number).toBe("CRM-9");
    stubFetch({}, false);
    expect(await createDeal({ number: "x", title: "t", counterparty: "c", amount: 1, priority: "Средний", stage: "new", owner: "" })).toBeNull();
  });

  it("updateDealStage / updateDeal возвращают булев успех", async () => {
    stubFetch({}, true);
    expect(await updateDealStage("1", "won")).toBe(true);
    expect(await updateDeal("1", { focus: true })).toBe(true);
    stubFetch({}, false);
    expect(await updateDealStage("1", "won")).toBe(false);
  });

  it("fetchKpis/getKpis маппят показатели; logActivity — успех", async () => {
    const apiKpi = { key: "calls", title: "Звонки", target: 40, actual: 24, percent: 60, unit: "count", icon: "phone", tone: "blue" };
    stubFetch([apiKpi]);
    expect((await fetchKpis())[0].label).toBe("Звонки");
    stubFetch([apiKpi]);
    expect((await getKpis("day"))[0].percent).toBe(60);
    stubFetch({ ok: true });
    expect(await logActivity("calls")).toBe(true);
  });
});

describe("api client — документы/сообщения/согласования", () => {
  it("fetchDocuments / createDocument", async () => {
    stubFetch([{ id: 1, kind: "invoice", number: "СЧ-1", status: "posted", onec_ref: "1С-СЧ-1", amount: 5000 }]);
    expect((await fetchDocuments("1"))[0].onec_ref).toBe("1С-СЧ-1");
    stubFetch({ id: 2, kind: "invoice", number: "СЧ-2", status: "posted", onec_ref: null, amount: 5000, valid_until: null, reserve_status: "none" });
    expect((await createDocument("1", "invoice"))?.number).toBe("СЧ-2");
  });

  it("issueDocument: счёт даёт renderUrl, договор — только сообщение, null → ok=false", async () => {
    stubFetch({ id: 7, kind: "invoice", number: "СЧ-7", status: "posted", onec_ref: null, amount: 100, valid_until: null, reserve_status: "none" });
    const inv = await issueDocument("1", "invoice");
    expect(inv.ok).toBe(true);
    expect(inv.renderUrl).toBe("/api/sales/documents/7/render");
    expect(inv.message).toContain("СЧ-7");

    stubFetch({ id: 8, kind: "contract", number: "ДГ-8", status: "pending_approval", onec_ref: null, amount: 100, valid_until: null, reserve_status: "none" });
    const con = await issueDocument("1", "contract");
    expect(con.ok).toBe(true);
    expect(con.renderUrl).toBeUndefined(); // договор рендерится отдельно после согласования
    expect(con.message).toContain("согласование");

    stubFetch(null, false);
    const fail = await issueDocument("1", "invoice");
    expect(fail.ok).toBe(false);
    expect(fail.renderUrl).toBeUndefined();
  });

  it("fetchMessages / sendMessage / AI", async () => {
    stubFetch([{ id: 1, channel: "whatsapp", direction: "in", author: "Клиент", text: "Привет", created_at: "2026-06-02T14:00" }]);
    expect((await fetchMessages("1"))[0].text).toBe("Привет");
    stubFetch({}, true);
    expect(await sendMessage("1", "email", "hi")).toBe(true);
    stubFetch({ text: "Черновик", model: "qwen" });
    expect(await aiDraftReply("1")).toBe("Черновик");
    stubFetch({ kind: "summary", text: "Резюме", model: "qwen" });
    expect(await aiAssist("1", "summary")).toBe("Резюме");
    stubFetch(null, false);
    expect(await aiDraftReply("1")).toBeNull();
  });

  it("fetchApprovals / requestApproval / decideApproval", async () => {
    stubFetch([{ id: 1, kind: "deal.contract", entity_ref: "deal:1", subject: "s", route: "Юрист", status: "pending", requested_by: "М", decided_by: null }]);
    expect((await fetchApprovals({ status: "pending" }))[0].route).toBe("Юрист");
    stubFetch({}, true);
    expect(await requestApproval("1", "deal.contract")).toBe(true);
    expect(await decideApproval(1, true, "Юрист")).toBe(true);
  });

  it("контакты, номенклатура, реестр, события", async () => {
    stubFetch([{ id: 1, full_name: "Анна", phone: null, email: null, is_primary: true }]);
    expect((await fetchContacts("1"))[0].full_name).toBe("Анна");
    stubFetch({}, true);
    expect(await addContact("1", { full_name: "Борис" })).toBe(true);
    stubFetch([{ id: 1, code: "AKB-60", title: "АКБ", unit: "шт" }]);
    expect((await fetchSkus())[0].code).toBe("AKB-60");
    stubFetch([{ id: 1, sku_id: 1, code: "AKB-60", title: "АКБ", unit: "шт", qty: 2, last_price: null, min_price: null }]);
    expect((await fetchDealItems("1"))[0].qty).toBe(2);
    stubFetch({}, true);
    expect(await addDealItem("1", 1, 2)).toBe(true);
    stubFetch({ unp: "191234567", name: "ООО", address: "Минск", status: "Действующий" });
    expect((await lookupCounterparty("191234567"))?.name).toBe("ООО");
    stubFetch([{ id: 1, event_type: "sales.deal.created", created_at: "x", processed: false }]);
    expect((await fetchEvents())[0].event_type).toBe("sales.deal.created");
    stubFetch([]);
    expect(await fetchChats()).toEqual([]);
  });
});

describe("api client — прочие операции и fallback'и", () => {
  it("updateDealItem / deleteDealItem / setPrimaryContact / decideDocument", async () => {
    stubFetch({}, true);
    expect(await updateDealItem(1, 5)).toBe(true);
    expect(await deleteDealItem(1)).toBe(true);
    expect(await setPrimaryContact(1)).toBe(true);
    expect(await decideDocument(1, true, "Юрист")).toBe(true);
    stubFetch({}, false);
    expect(await deleteDealItem(1)).toBe(false);
  });

  it("fetchOwnerInsight: текст при успехе, null при ошибке", async () => {
    stubFetch({ text: "Инсайт", model: "qwen" });
    expect(await fetchOwnerInsight()).toBe("Инсайт");
    stubFetch({}, false);
    expect(await fetchOwnerInsight()).toBeNull();
  });

  it("fetchOwnerDashboard собирает метрики/воронку/KPI", async () => {
    stubFetch({ approvals_pending: 1, approvals_total: 2, modules: ["sales"], widgets: [] });
    const dash = await fetchOwnerDashboard();
    expect(dash?.metrics.approvals_pending).toBe(1);
  });

  it("fetchOwnerDashboard → null при ошибке", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect(await fetchOwnerDashboard()).toBeNull();
  });

  it("fallback'и при сетевой ошибке (mock-данные/пустые)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect((await fetchDealDetail("1")).number).toBeTruthy(); // mock-карточка
    expect((await fetchKpis()).length).toBeGreaterThan(0); // mock-KPI
    expect(await fetchDocuments("1")).toEqual([]);
    expect(await fetchMessages("1")).toEqual([]);
    expect(await fetchApprovals()).toEqual([]);
    expect(await fetchContacts("1")).toEqual([]);
    expect(await fetchEvents()).toEqual([]);
    expect(await fetchChats()).toEqual([]);
    expect(await routeLead(1)).toBeNull();
    expect(await convertLead(1)).toBeNull();
    expect(await fetchOwnerInsight()).toBeNull();
    expect(await createLead({ source: "site" })).toBeNull();
    expect(await qualifyLead(1)).toBeNull();
    expect(await aiDraftReply("1")).toBeNull();
    expect(await aiAssist("1", "summary")).toBeNull();
  });

  it("все мутаторы возвращают fallback при сетевой ошибке", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    const input = { number: "x", title: "t", counterparty: "c", amount: 1, priority: "Средний", stage: "new", owner: "" };
    expect(await createDeal(input)).toBeNull();
    expect(await updateDeal("1", {})).toBe(false);
    expect(await updateDealStage("1", "won")).toBe(false);
    expect(await logActivity("k")).toBe(false);
    expect(await addContact("1", { full_name: "x" })).toBe(false);
    expect(await setPrimaryContact(1)).toBe(false);
    expect(await addDealItem("1", 1, 1)).toBe(false);
    expect(await updateDealItem(1, 1)).toBe(false);
    expect(await deleteDealItem(1)).toBe(false);
    expect(await createDocument("1", "invoice")).toBeNull();
    expect(await decideDocument(1, true, "x")).toBe(false);
    expect(await sendMessage("1", "email", "x")).toBe(false);
    expect(await requestApproval("1", "deal.contract")).toBe(false);
    expect(await decideApproval(1, true, "x")).toBe(false);
    expect(await getKpis()).toEqual([]);
    expect(await fetchSkus()).toEqual([]);
    expect(await fetchDealItems("1")).toEqual([]);
    expect(await lookupCounterparty("191")).toBeNull();
  });
});

describe("api client — стадии/воронки/план", () => {
  it("createStage/updateStage/deleteStage шлют правильные URL и методы", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    const stageInput = {
      code: "new", title: "Новая", sort_order: 1, probability: 10,
      kind: "normal" as const, color: "#000", is_active: true, funnel: "main",
    };
    expect(await createStage(stageInput)).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/stages", expect.objectContaining({
      method: "POST",
      body: JSON.stringify(stageInput),
    }));

    expect(await updateStage("new won", { title: "Выиграна" })).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/sales/stages/new%20won",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "Выиграна" }) }),
    );

    fetchMock.mockResolvedValueOnce({ ok: true });
    expect(await deleteStage("won")).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/stages/won", { method: "DELETE" });
  });

  it("deleteStage возвращает detail на 409 (сделки в стадии)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "в стадии есть сделки" }),
    }));
    expect(await deleteStage("new")).toEqual({ ok: false, detail: "в стадии есть сделки" });
  });

  it("createStage/updateStage/deleteStage → false/detail-less при сетевой ошибке", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await createStage({ code: "x", title: "t", sort_order: 0, probability: 0, kind: "normal", color: "#000", is_active: true, funnel: "main" })).toBe(false);
    expect(await updateStage("x", {})).toBe(false);
    expect(await deleteStage("x")).toEqual({ ok: false });
  });

  it("fetchFunnels/fetchFunnelsServer читают список воронок", async () => {
    stubFetch([{ code: "main", title: "Основная", active_deals: 5 }]);
    expect((await fetchFunnels())[0].active_deals).toBe(5);
    stubFetch([{ code: "main", title: "Основная", active_deals: 5 }]);
    expect((await fetchFunnelsServer())[0].title).toBe("Основная");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchFunnels()).toEqual([]);
    expect(await fetchFunnelsServer()).toEqual([]);
  });

  it("fetchDealHandoff читает handoff-сводку; null при !ok/сбое", async () => {
    stubFetch({
      deal_id: 9, number: "CRM-9", counterparty: "ООО", amount: 500, owner: "Иванов",
      funnel: "main", items: [{ sku_code: "AKB-60", title: "АКБ", qty: 2 }],
      gross_profit: 120, handed_off_at: "2026-07-01T10:00",
    });
    const h = await fetchDealHandoff("9");
    expect(h?.gross_profit).toBe(120);
    expect(h?.items[0].qty).toBe(2);
    stubFetch({}, false);
    expect(await fetchDealHandoff("9")).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchDealHandoff("9")).toBeNull();
  });

  it("fetchPlans строит query-строку из фильтров и возвращает список; upsertPlan шлёт тело", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ id: 1, owner_id: 5, metric: "calls", period_type: "day", period_key: "2026-07-19", target: 10, status: "draft", approved_by: null, approved_at: null }],
    });
    vi.stubGlobal("fetch", fetchMock);
    const plans = await fetchPlans({ owner_id: 5, period_type: "day", period_key: "2026-07-19" });
    expect(plans[0].metric).toBe("calls");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sales/plans?owner_id=5&period_type=day&period_key=2026-07-19",
      expect.objectContaining({ cache: "no-store" }),
    );

    const input = { owner_id: 5, metric: "calls" as const, period_type: "day" as const, period_key: "2026-07-19", target: 20 };
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ...input, id: 2, status: "draft", approved_by: null, approved_at: null }) });
    const created = await upsertPlan(input);
    expect(created?.id).toBe(2);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/plans", expect.objectContaining({
      method: "POST",
      body: JSON.stringify(input),
    }));
  });

  it("fetchPlans/upsertPlan → []/null при ошибке", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchPlans({})).toEqual([]);
    expect(await upsertPlan({ owner_id: 1, metric: "calls", period_type: "day", period_key: "x", target: 1 })).toBeNull();
  });

  it("submitPlan/decidePlan шлют POST на верный URL с телом", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await submitPlan(7)).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/plans/7/submit", { method: "POST" });

    expect(await decidePlan(7, true, "ок")).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/plans/7/decide", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ approved: true, comment: "ок" }),
    }));

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await submitPlan(7)).toBe(false);
    expect(await decidePlan(7, false)).toBe(false);
  });
});

describe("api client — склад/цена/позиции/задачи/причины отказа", () => {
  it("fetchStock маппит остатки со всеми числовыми полями", async () => {
    stubFetch([{ sku_code: "AKB-60", warehouse: "Минск", qty_available: 10, qty_reserved: 2, qty_forecast: 5, price: 199.9, cost: 150 }]);
    const [row] = await fetchStock();
    expect(row.qty_available).toBe(10);
    expect(row.cost).toBe(150);
    stubFetch({}, false);
    expect(await fetchStock()).toEqual([]);
  });

  it("createPriceQuote шлёт корректное тело на /api/sales/prices", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await createPriceQuote("AKB-60", "ООО Ромашка", 199.9)).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/prices", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ sku_code: "AKB-60", counterparty: "ООО Ромашка", price: 199.9 }),
    }));
  });

  it("fetchLastOrder возвращает позиции повторного заказа; [] на !ok/сбой", async () => {
    stubFetch([{ id: 1, sku_id: 1, code: "AKB-60", title: "АКБ", unit: "шт", qty: 3, last_price: 100, min_price: 90 }]);
    expect((await fetchLastOrder("1"))[0].qty).toBe(3);
    stubFetch({}, false);
    expect(await fetchLastOrder("1")).toEqual([]);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchLastOrder("1")).toEqual([]);
  });

  it("fetchDealTasks/createDealTask/completeDealTask", async () => {
    stubFetch([{ id: 1, deal_id: 1, title: "Позвонить", kind: "call", assignee_id: null, due_at: null, status: "open", result: null, overdue: false }]);
    expect((await fetchDealTasks("1"))[0].title).toBe("Позвонить");

    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await createDealTask("1", { title: "Написать", kind: "email" })).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/deals/1/tasks", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ title: "Написать", kind: "email" }),
    }));

    expect(await completeDealTask(5, "Готово")).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/tasks/5", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ status: "done", result: "Готово" }),
    }));
  });

  it("fetchLossReasons/loseDeal", async () => {
    stubFetch([{ code: "price", title: "Дорого" }]);
    expect((await fetchLossReasons())[0].code).toBe("price");
    stubFetch({}, false);
    expect(await fetchLossReasons()).toEqual([]);

    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await loseDeal("1", "price", "слишком дорого")).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/deals/1/lose", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ reason_code: "price", comment: "слишком дорого" }),
    }));
  });
});

describe("api client — телефония", () => {
  it("fetchCalls строит query только из непустых параметров", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ id: 1, call_id: "c1", direction: "in", phone_e164: "+375291112233", owner: "Иванов", status: "ended", started_at: "2026-07-19T10:00" }],
    });
    vi.stubGlobal("fetch", fetchMock);
    const calls = await fetchCalls({ status: "ended", owner: "Иванов", date: "" });
    expect(calls[0].phone_e164).toBe("+375291112233");
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/calls?status=ended&owner=%D0%98%D0%B2%D0%B0%D0%BD%D0%BE%D0%B2", { cache: "no-store" });

    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [] });
    expect(await fetchCalls()).toEqual([]);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/calls", { cache: "no-store" });
  });

  it("fetchCalls → [] при ошибке", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchCalls()).toEqual([]);
  });

  it("callComment/callResult/callLinkDeal/triggerIncomingCall шлют POST с телом на верный путь", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await callComment(1, "заметка")).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/calls/1/comment", expect.objectContaining({
      method: "POST", body: JSON.stringify({ comment: "заметка" }),
    }));

    expect(await callResult(1, "answered")).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/calls/1/result", expect.objectContaining({
      body: JSON.stringify({ result: "answered" }),
    }));

    expect(await callLinkDeal(1, { deal_id: 9 })).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/calls/1/link-deal", expect.objectContaining({
      body: JSON.stringify({ deal_id: 9 }),
    }));

    expect(await triggerIncomingCall({ phone: "+375291112233" })).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/sales/telephony/incoming", expect.objectContaining({
      body: JSON.stringify({ phone: "+375291112233" }),
    }));

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await callComment(1, "x")).toBe(false);
  });

  it("subscribeCalls — no-op без EventSource (jsdom не предоставляет), не бросает", () => {
    const unsubscribe = subscribeCalls("Иванов", () => {});
    expect(typeof unsubscribe).toBe("function");
    expect(() => unsubscribe()).not.toThrow();
  });

  it("subscribeCalls строит URL с owner и без; onmessage парсит карточку", () => {
    const instances: { url: string; onmessage: ((e: { data: string }) => void) | null; close: () => void }[] = [];
    class FakeEventSource {
      onmessage: ((e: { data: string }) => void) | null = null;
      close = vi.fn();
      constructor(public url: string) {
        instances.push(this as unknown as typeof instances[number]);
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);

    const cards: { id: number }[] = [];
    const unsub = subscribeCalls("Иванов", (c) => cards.push(c as unknown as { id: number }));
    expect(instances[0].url).toBe("/api/sales/calls/stream?owner=%D0%98%D0%B2%D0%B0%D0%BD%D0%BE%D0%B2");
    instances[0].onmessage?.({ data: JSON.stringify({ id: 1 }) });
    expect(cards).toEqual([{ id: 1 }]);
    // «шум» потока (heartbeat/невалидный JSON) — не бросает и не добавляет карточку
    expect(() => instances[0].onmessage?.({ data: "not-json" })).not.toThrow();
    expect(cards).toHaveLength(1);
    unsub();
    expect(instances[0].close).toHaveBeenCalled();

    subscribeCalls(undefined, () => {});
    expect(instances[1].url).toBe("/api/sales/calls/stream");
  });
});

describe("api client — лиды: расширенный контракт", () => {
  it("localToNaiveUtc: конвертирует локальное время и чистит хвост Z", () => {
    expect(localToNaiveUtc("")).toBe("");
    expect(localToNaiveUtc("2026-07-20T10:00:00Z")).toBe("2026-07-20T10:00:00");
    expect(localToNaiveUtc("not-a-date")).toBe("not-a-date");
    const local = new Date(2026, 6, 20, 13, 0, 0); // 20 июля 2026, 13:00 локального времени рантайма
    expect(localToNaiveUtc("2026-07-20T13:00")).toBe(local.toISOString().slice(0, 19));
  });

  it("fetchLead: одиночный лид по id; null на !ok/сбой", async () => {
    stubFetch({ ...apiLead, id: 5, name: "Пётр" });
    expect((await fetchLead(5))?.name).toBe("Пётр");
    stubFetch({}, false);
    expect(await fetchLead(5)).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchLead(5)).toBeNull();
  });

  it("fetchLeadsClient: null (не []) на ошибке — чтобы не подменить живую доску пустотой", async () => {
    stubFetch([apiLead]);
    expect((await fetchLeadsClient())?.length).toBe(1);
    stubFetch({}, false);
    expect(await fetchLeadsClient()).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchLeadsClient()).toBeNull();
  });

  it("submitWebLead/submitEmailLead шлют POST с payload как есть", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await submitWebLead({ name: "Иван" })).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/integrations/web/lead", expect.objectContaining({
      body: JSON.stringify({ name: "Иван" }),
    }));
    expect(await submitEmailLead({ from: "a@b.by" })).toBe(true);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/integrations/email/inbound", expect.objectContaining({
      body: JSON.stringify({ from: "a@b.by" }),
    }));
  });

  it("createLead кидает LeadDuplicateError на 409 с duplicate_of", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 409,
      json: async () => ({ detail: { duplicate_of: 42 } }),
    }));
    await expect(createLead({ source: "site" })).rejects.toThrow(LeadDuplicateError);
    await expect(createLead({ source: "site" })).rejects.toMatchObject({ duplicateOf: 42 });
  });

  it("fetchLeadManagers", async () => {
    stubFetch([{ id: 1, name: "Иванов", region: "Минск", product: "лист", load: 3 } as unknown as Record<string, unknown>]);
    expect((await fetchLeadManagers()).length).toBe(1);
    stubFetch({}, false);
    expect(await fetchLeadManagers()).toEqual([]);
  });

  it("linkLeadContact: успех/ошибка-detail/сеть", async () => {
    stubFetch({ contact_id: 3, counterparty_id: 7, created: true, full_name: "Анна" });
    const ok = await linkLeadContact(1, { fullName: "Анна", counterpartyId: 7 });
    expect(ok).toEqual({ contactId: 3, counterpartyId: 7, created: true, fullName: "Анна" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "нет доступа" }) }));
    expect(await linkLeadContact(1, {})).toEqual({ error: "нет доступа" });

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await linkLeadContact(1, {})).toBeNull();
  });

  it("fetchLeadSourceStats маппит snake_case → camelCase с дефолтом pipeline", async () => {
    stubFetch([{
      source: "site", utm_campaign: "spring", total: 10, target: 6, converted: 3, rejected: 1,
      avg_score: 55.5, target_pct: 60, conversion_pct: 30, pipeline: 1200,
    }]);
    const [s] = await fetchLeadSourceStats(30);
    expect(s.utmCampaign).toBe("spring");
    expect(s.conversionPct).toBe(30);
    expect(s.pipeline).toBe(1200);
    stubFetch({}, false);
    expect(await fetchLeadSourceStats()).toEqual([]);
  });

  it("fetchLeadHandoffStats маппит и подставляет 0 для опциональных полей", async () => {
    stubFetch([{ manager: "Иванов", assigned: 5, converted: 2, pipeline: 900, conversion_pct: 40 }]);
    const [s] = await fetchLeadHandoffStats(7);
    expect(s.manager).toBe("Иванов");
    expect(s.pending).toBe(0);
    expect(s.pendingPipeline).toBe(0);
    expect(s.stale).toBe(0);
  });

  it("expressBulkLeads маппит skipped_non_target; null на !ok/сбой", async () => {
    stubFetch({ expressed: [1, 2], skipped_non_target: 3 });
    expect(await expressBulkLeads()).toEqual({ expressed: [1, 2], skippedNonTarget: 3 });
    stubFetch({}, false);
    expect(await expressBulkLeads()).toBeNull();
  });

  it("fetchLeadPlan/saveLeadPlan маппят план/факт", async () => {
    const apiPlan = {
      leads_target: 20, qualified_target: 10, converted_target: 5, reaction_target_min: 15,
      leads_fact: 8, qualified_fact: 4, converted_fact: 1, reaction_fact_min: 12,
    };
    stubFetch(apiPlan);
    const plan = await fetchLeadPlan();
    expect(plan?.leadsTarget).toBe(20);
    expect(plan?.reactionFactMin).toBe(12);
    stubFetch({}, false);
    expect(await fetchLeadPlan()).toBeNull();

    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => apiPlan });
    vi.stubGlobal("fetch", fetchMock);
    const saved = await saveLeadPlan({ leadsTarget: 20, qualifiedTarget: 10, convertedTarget: 5, reactionTargetMin: 15 });
    expect(saved?.leadsTarget).toBe(20);
    expect(fetchMock).toHaveBeenCalledWith("/api/leads/plan", expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ leads_target: 20, qualified_target: 10, converted_target: 5, reaction_target_min: 15 }),
    }));
  });

  it("logLeadAttempt: без callbackAt — просто POST; с callbackAt — тело с naive-UTC", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...apiLead, id: 1 }) });
    vi.stubGlobal("fetch", fetchMock);
    expect((await logLeadAttempt(1))?.id).toBe(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/leads/1/attempt", { method: "POST" });

    await logLeadAttempt(1, "2026-07-20T10:00:00Z");
    expect(fetchMock).toHaveBeenLastCalledWith("/api/leads/1/attempt", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ callback_at: "2026-07-20T10:00:00" }),
    }));

    stubFetch({}, false);
    expect(await logLeadAttempt(1)).toBeNull();
  });

  it("expressLead: успех/422-error/null", async () => {
    stubFetch({ ...apiLead, id: 1, status: "routed" });
    const res = await expressLead(1, { assignedTo: "Иванов" });
    expect(res && "id" in res ? res.id : undefined).toBe(1);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 422, ok: false, json: async () => ({ detail: "нецелевой балл" }) }));
    const err = await expressLead(1);
    expect(err).toEqual({ error: "нецелевой балл" });

    stubFetch({}, false);
    expect(await expressLead(1)).toBeNull();
  });

  it("rejectLead: с snoozeDays и без — верное тело", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 1, status: "rejected", reject_reason: "цена" }) });
    vi.stubGlobal("fetch", fetchMock);
    expect((await rejectLead(1, "цена"))?.reject_reason).toBe("цена");
    expect(fetchMock).toHaveBeenCalledWith("/api/leads/1/reject", expect.objectContaining({
      body: JSON.stringify({ reason: "цена" }),
    }));

    await rejectLead(1, "не сейчас", 30);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/leads/1/reject", expect.objectContaining({
      body: JSON.stringify({ reason: "не сейчас", snooze_days: 30 }),
    }));

    stubFetch({}, false);
    expect(await rejectLead(1, "цена")).toBeNull();
  });
});

describe("api client — корзина лида/вложения/бренд", () => {
  it("fetchLeadItems маппит позиции корзины", async () => {
    stubFetch([{ id: 1, lead_id: 1, sku_id: 2, sku_code: "AKB-60", name: "АКБ", qty: 3, price: 199.9, discount_pct: 5, created_at: "x" }]);
    const [item] = await fetchLeadItems(1);
    expect(item).toEqual({ skuId: 2, skuCode: "AKB-60", name: "АКБ", qty: 3, price: 199.9, discountPct: 5 });
    stubFetch({}, false);
    expect(await fetchLeadItems(1)).toEqual([]);
  });

  it("saveLeadItems шлёт PUT с массивом в snake_case", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    const items = [{ skuId: 2, skuCode: "AKB-60", name: "АКБ", qty: 3, price: 199.9, discountPct: 5 }];
    expect(await saveLeadItems(1, items)).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/leads/1/items", expect.objectContaining({
      method: "PUT",
      body: JSON.stringify([{ sku_id: 2, sku_code: "AKB-60", name: "АКБ", qty: 3, price: 199.9, discount_pct: 5 }]),
    }));
  });

  it("commitLeadItemsToDeal переносит позиции в сделку и котирует цену; считает ok/total", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    const items = [
      { skuId: 1, skuCode: "AKB-60", name: "АКБ", qty: 2, price: 100, discountPct: 0 },
      { skuId: 2, skuCode: "AKB-70", name: "АКБ70", qty: 0, price: 0, discountPct: 0 }, // price=0 → без котировки
    ];
    const res = await commitLeadItemsToDeal("9", "ООО Ромашка", items);
    expect(res).toEqual({ ok: 2, total: 2 });
  });

  it("commitLeadItemsToDeal — ok меньше total, если часть addDealItem провалилась", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) }) // addDealItem #1
      .mockResolvedValueOnce({ ok: false, json: async () => ({}) }) // addDealItem #2
      .mockResolvedValue({ ok: true, json: async () => ({}) }); // createPriceQuote calls
    vi.stubGlobal("fetch", fetchMock);
    const items = [
      { skuId: 1, skuCode: "A", name: "A", qty: 1, price: 10, discountPct: 0 },
      { skuId: 2, skuCode: "B", name: "B", qty: 1, price: 10, discountPct: 0 },
    ];
    const res = await commitLeadItemsToDeal("9", "ООО", items);
    expect(res).toEqual({ ok: 1, total: 2 });
  });

  it("fetchLeadAttachments маппит вложения", async () => {
    stubFetch([{ id: 1, lead_id: 5, filename: "скан.pdf", content_type: "application/pdf", size_bytes: 1024, source: "manual", created_at: "x" }]);
    const [att] = await fetchLeadAttachments(5);
    expect(att).toEqual({ id: 1, leadId: 5, filename: "скан.pdf", contentType: "application/pdf", sizeBytes: 1024, source: "manual", createdAt: "x" });
    stubFetch({}, false);
    expect(await fetchLeadAttachments(5)).toEqual([]);
  });

  it("uploadLeadAttachment читает файл как data-URI и шлёт JSON; маппит ответ", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 9, lead_id: 5, filename: "a.txt", content_type: "text/plain", size_bytes: 3, source: "manual", created_at: "x" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["abc"], "a.txt", { type: "text/plain" });
    const res = await uploadLeadAttachment(5, file);
    expect(res.attachment?.filename).toBe("a.txt");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/leads/5/attachments");
    const body = JSON.parse(init.body as string) as { filename: string; data_url: string; source: string };
    expect(body.filename).toBe("a.txt");
    expect(body.source).toBe("manual");
    expect(body.data_url.startsWith("data:")).toBe(true);
  });

  it("uploadLeadAttachment возвращает detail на !ok и общую ошибку на сбой", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: "слишком большой файл" }) }));
    const file = new File(["abc"], "a.txt", { type: "text/plain" });
    expect((await uploadLeadAttachment(5, file)).error).toBe("слишком большой файл");

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect((await uploadLeadAttachment(5, file)).error).toBe("Не удалось загрузить файл");
  });

  it("leadAttachmentDownloadUrl строит прямую ссылку", () => {
    expect(leadAttachmentDownloadUrl(5, 9)).toBe("/api/leads/5/attachments/9/download");
  });

  it("deleteLeadAttachment: true на 200 и на 404 (уже нет — цель достигнута); false на сбой", async () => {
    stubFetch({}, true);
    expect(await deleteLeadAttachment(5, 9)).toBe(true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    expect(await deleteLeadAttachment(5, 9)).toBe(true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    expect(await deleteLeadAttachment(5, 9)).toBe(false);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await deleteLeadAttachment(5, 9)).toBe(false);
  });

  it("fetchBranding/updateBranding", async () => {
    stubFetch({ logo_data_url: "data:image/png;base64,xyz" });
    expect(await fetchBranding()).toBe("data:image/png;base64,xyz");
    stubFetch({}, false);
    expect(await fetchBranding()).toBeNull();

    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await updateBranding("data:image/png;base64,new")).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/branding", expect.objectContaining({
      method: "PUT",
      body: JSON.stringify({ logo_data_url: "data:image/png;base64,new" }),
    }));
  });
});

describe("api client — convertLead поллит deal_id", () => {
  it("возвращает deal_id, как только он появляется у лида", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ lead_id: 1, status: "converted" }) }) // POST /convert
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...apiLead, deal_id: null }) }) // poll #1 — ещё нет
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...apiLead, deal_id: 77 }) }); // poll #2 — появился
    vi.stubGlobal("fetch", fetchMock);

    const promise = convertLead(1);
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(1000);
    const res = await promise;
    expect(res).toEqual({ lead_id: 1, status: "converted", deal_id: 77 });
    vi.useRealTimers();
  });

  it("возвращает undefined deal_id после исчерпания попыток", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ lead_id: 2, status: "converted" }) })
      .mockResolvedValue({ ok: true, json: async () => ({ ...apiLead, deal_id: null }) });
    vi.stubGlobal("fetch", fetchMock);

    const promise = convertLead(2);
    await vi.advanceTimersByTimeAsync(12000);
    const res = await promise;
    expect(res?.deal_id).toBeUndefined();
    vi.useRealTimers();
  });
});
