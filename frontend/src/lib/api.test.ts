import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addContact,
  addDealItem,
  aiAssist,
  aiDraftReply,
  convertLead,
  createDeal,
  createDocument,
  createLead,
  decideApproval,
  fetchApprovals,
  fetchBoardStages,
  fetchChats,
  fetchContacts,
  fetchDealDetail,
  fetchDealItems,
  fetchDocuments,
  fetchEvents,
  fetchKpis,
  fetchLeads,
  fetchMessages,
  fetchSkus,
  getKpis,
  logActivity,
  lookupCounterparty,
  qualifyLead,
  requestApproval,
  routeLead,
  sendMessage,
  updateDeal,
  updateDealStage,
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
    stubFetch({}, true);
    expect(await createDocument("1", "invoice")).toBe(true);
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
