import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createDecision,
  decisionLabel,
  fetchDecisions,
  fetchDecisionsServer,
  fetchStats,
  fetchStatsServer,
  formatPassRate,
  REWORK_REASONS,
} from "@/lib/production-otk";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const qcRecord = {
  id: 5,
  order_code: "PRO-5",
  product: "Аккумулятор LiFePO4",
  decision: "accept" as const,
  reason: "",
  inspector: "Петров",
};

const qcStats = { accepted: 10, rework: 2, scrap: 1, total: 13, pass_rate: 76.9 };

describe("production-otk", () => {
  it("decisionLabel: подписи решений", () => {
    expect(decisionLabel("accept")).toBe("Принять");
    expect(decisionLabel("rework")).toBe("Доработка");
    expect(decisionLabel("scrap")).toBe("Брак");
  });

  it("decisionLabel: возвращает исходное значение для неизвестного решения", () => {
    expect(decisionLabel("unknown" as never)).toBe("unknown");
  });

  it("formatPassRate: проценты с запятой", () => {
    expect(formatPassRate(96)).toBe("96%");
    expect(formatPassRate(95.5)).toBe("95,5%");
    expect(formatPassRate(0)).toBe("0%");
  });

  it("REWORK_REASONS: непустой преднабор причин", () => {
    expect(REWORK_REASONS.length).toBeGreaterThan(0);
    expect(REWORK_REASONS).toContain("Пайка БМС · непропай / перемычка");
  });
});

describe("fetchDecisionsServer", () => {
  it("зовёт backend URL напрямую с no-store и без заголовков ролей", async () => {
    const fn = stubFetch([qcRecord]);
    const result = await fetchDecisionsServer();
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/production/qc/decisions", {
      cache: "no-store",
      headers: undefined,
    });
    expect(result).toEqual([qcRecord]);
  });

  it("передаёт роли в заголовке X-User-Roles", async () => {
    const fn = stubFetch([qcRecord]);
    await fetchDecisionsServer("sales,rop");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/production/qc/decisions", {
      cache: "no-store",
      headers: { "X-User-Roles": "sales,rop" },
    });
  });

  it("возвращает пустой массив при !ok", async () => {
    stubFetch(null, false);
    expect(await fetchDecisionsServer()).toEqual([]);
  });

  it("возвращает пустой массив при исключении fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    expect(await fetchDecisionsServer()).toEqual([]);
  });
});

describe("fetchStatsServer", () => {
  it("зовёт backend URL напрямую и маппит статистику", async () => {
    const fn = stubFetch(qcStats);
    const result = await fetchStatsServer("owner");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/production/qc/stats", {
      cache: "no-store",
      headers: { "X-User-Roles": "owner" },
    });
    expect(result).toEqual(qcStats);
  });

  it("возвращает EMPTY_STATS при !ok", async () => {
    stubFetch(null, false);
    expect(await fetchStatsServer()).toEqual({
      accepted: 0,
      rework: 0,
      scrap: 0,
      total: 0,
      pass_rate: 0,
    });
  });

  it("возвращает EMPTY_STATS при исключении fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    expect(await fetchStatsServer()).toEqual({
      accepted: 0,
      rework: 0,
      scrap: 0,
      total: 0,
      pass_rate: 0,
    });
  });
});

describe("fetchDecisions (client)", () => {
  it("зовёт относительный /api маршрут", async () => {
    const fn = stubFetch([qcRecord]);
    const result = await fetchDecisions();
    expect(fn).toHaveBeenCalledWith("/api/production/qc/decisions", { cache: "no-store" });
    expect(result).toEqual([qcRecord]);
  });

  it("возвращает пустой массив при !ok", async () => {
    stubFetch(null, false);
    expect(await fetchDecisions()).toEqual([]);
  });

  it("возвращает пустой массив при исключении fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    expect(await fetchDecisions()).toEqual([]);
  });
});

describe("fetchStats (client)", () => {
  it("зовёт относительный /api маршрут и маппит статистику", async () => {
    const fn = stubFetch(qcStats);
    const result = await fetchStats();
    expect(fn).toHaveBeenCalledWith("/api/production/qc/stats", { cache: "no-store" });
    expect(result).toEqual(qcStats);
  });

  it("возвращает EMPTY_STATS при !ok", async () => {
    stubFetch(null, false);
    expect(await fetchStats()).toEqual({
      accepted: 0,
      rework: 0,
      scrap: 0,
      total: 0,
      pass_rate: 0,
    });
  });
});

describe("createDecision", () => {
  it("шлёт POST с JSON-телом и Content-Type", async () => {
    const fn = stubFetch(qcRecord);
    const input = {
      decision: "rework" as const,
      order_code: "PRO-5",
      product: "Аккумулятор",
      reason: "Пайка БМС",
      inspector: "Петров",
    };
    const result = await createDecision(input);
    expect(fn).toHaveBeenCalledWith("/api/production/qc/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    expect(result).toEqual(qcRecord);
  });

  it("возвращает null при !ok", async () => {
    stubFetch(null, false);
    expect(await createDecision({ decision: "scrap" })).toBeNull();
  });

  it("возвращает null при исключении fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    expect(await createDecision({ decision: "accept" })).toBeNull();
  });
});
