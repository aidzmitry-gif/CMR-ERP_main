import { describe, expect, it, vi } from "vitest";

import { loadLeadsClient, loadLeadsServer } from "@/components/leads/leads-load";

const apiLead = {
  id: 1,
  source: "site",
  name: "",
  company: "ООО Тест",
  phone: null,
  email: null,
  region: "Минск",
  product: "лист",
  message: "",
  status: "new",
  score: 0,
  qualification: "",
  reason: "",
  assigned_to: "",
  funnel: "",
  deal_id: null,
  reject_reason: "",
  next_step_at: null,
  next_step_note: "",
  created_at: "2026-07-17T10:00:00",
  first_action_at: null,
};

describe("leads-load", () => {
  it("preserves SSR own visibility and numeric identity with dev username", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify([{ ...apiLead, owner_id: 901, crm_client_id: 5, crm_contact_id: 9 }]), { headers: { "X-CRM-Visibility": "own" } }));
    vi.stubGlobal("fetch", fetcher);
    const result = await loadLeadsServer("sales_manager", undefined, "makarov");
    expect(result.visibility).toBe("own");
    expect(result.leads[0]).toMatchObject({ ownerId: 901, crmClientId: 5, crmContactId: 9 });
    expect(fetcher.mock.calls[0][1].headers["X-User"]).toBe("makarov");
    await loadLeadsServer("sales_manager", "token", "makarov");
    expect(fetcher.mock.calls[1][1].headers).toEqual({ "X-User-Roles": "sales_manager", Authorization: "Bearer token" });
  });
  it("loadLeadsClient → auth при 403, не пустой ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 403, json: async () => ({}) }),
    );
    const result = await loadLeadsClient();
    expect(result.state).toBe("auth");
    expect(result.leads).toEqual([]);
  });

  it("loadLeadsClient → ok с лидами при 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [apiLead] }),
    );
    const result = await loadLeadsClient();
    expect(result.state).toBe("ok");
    expect(result.leads[0]?.company).toBe("ООО Тест");
  });

  it("loadLeadsServer → auth при 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) }),
    );
    const result = await loadLeadsServer("sales_manager");
    expect(result.state).toBe("auth");
  });
});
