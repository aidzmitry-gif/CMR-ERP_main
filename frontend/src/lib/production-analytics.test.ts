import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type AnalyticsData,
  fetchAnalytics,
  fetchAnalyticsServer,
  fmtByn,
  fmtNh,
  fmtPct,
  kpiTone,
} from "@/lib/production-analytics";

function jsonResponse(data: unknown, ok = true): Response {
  return { ok, json: async () => data } as Response;
}

const SAMPLE: AnalyticsData = {
  vyrabotka_fact_nh: 100,
  vyrabotka_plan_nh: 120,
  efficiency_pct: 83.3,
  fpy_pct: 95,
  pass_rate_pct: 98,
  scrap_pct: 2,
  premium_fot_byn: 500,
  plan_fact_by_month: [{ month: 1, plan_nh: 10, fact_nh: 8 }],
  scrap_reasons: [{ reason: "брак литья", count: 3 }],
  team_contribution: [{ name: "Иванов", nh_output: 10, share_pct: 10 }],
  top_products: [{ product: "Аккумулятор", fact_nh: 20 }],
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("production-analytics", () => {
  describe("fmtNh", () => {
    it("0 → '0,0'", () => expect(fmtNh(0)).toBe("0,0"));
    it("1 → '1,0'", () => expect(fmtNh(1)).toBe("1,0"));
    it("176.5 → '176,5'", () => expect(fmtNh(176.5)).toBe("176,5"));
  });

  describe("fmtPct", () => {
    it("95.5 → '95,5%'", () => expect(fmtPct(95.5)).toBe("95,5%"));
    it("100 → '100,0%'", () => expect(fmtPct(100)).toBe("100,0%"));
    it("0 → '0,0%'", () => expect(fmtPct(0)).toBe("0,0%"));
  });

  describe("fmtByn", () => {
    it("форматирует 2 знака после запятой", () => {
      expect(fmtByn(1234.567)).toContain(",57");
    });
    it("включает 'р.'", () => {
      expect(fmtByn(100)).toContain("р.");
    });
    it("0 → '0,00 р.'", () => expect(fmtByn(0)).toBe("0,00 р."));
  });

  describe("kpiTone — high (чем больше тем лучше)", () => {
    it("≥80 → green", () => {
      expect(kpiTone("high", 80)).toBe("text-green-600");
      expect(kpiTone("high", 100)).toBe("text-green-600");
    });

    it("60..79 → amber", () => {
      expect(kpiTone("high", 60)).toBe("text-amber-600");
      expect(kpiTone("high", 79)).toBe("text-amber-600");
    });

    it("<60 → red", () => {
      expect(kpiTone("high", 59)).toBe("text-red-600");
      expect(kpiTone("high", 0)).toBe("text-red-600");
    });
  });

  describe("kpiTone — low (чем меньше тем лучше)", () => {
    it("≤5 → green", () => {
      expect(kpiTone("low", 0)).toBe("text-green-600");
      expect(kpiTone("low", 5)).toBe("text-green-600");
    });

    it("6..15 → amber", () => {
      expect(kpiTone("low", 6)).toBe("text-amber-600");
      expect(kpiTone("low", 15)).toBe("text-amber-600");
    });

    it(">15 → red", () => {
      expect(kpiTone("low", 16)).toBe("text-red-600");
      expect(kpiTone("low", 100)).toBe("text-red-600");
    });
  });
});

describe("fetchAnalyticsServer", () => {
  it("зовёт BASE/production/analytics с годом, no-store, без ролей", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SAMPLE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalyticsServer(2025);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/production/analytics?year=2025",
      { cache: "no-store", headers: undefined },
    );
    expect(result).toEqual(SAMPLE);
  });

  it("передаёт X-User-Roles, если роли переданы", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SAMPLE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalyticsServer(2024, "director,rop");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/production/analytics?year=2024",
      { cache: "no-store", headers: { "X-User-Roles": "director,rop" } },
    );
  });

  it("использует текущий год, если год не передан", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-18T00:00:00Z"));
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SAMPLE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalyticsServer();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/production/analytics?year=2026",
      { cache: "no-store", headers: undefined },
    );
    vi.useRealTimers();
  });

  it("возвращает null при ok:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));
    expect(await fetchAnalyticsServer(2025)).toBeNull();
  });

  it("возвращает null при исключении fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    expect(await fetchAnalyticsServer(2025)).toBeNull();
  });
});

describe("fetchAnalytics", () => {
  it("зовёт /api/production/analytics с годом и no-store, возвращает данные", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SAMPLE));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAnalytics(2023);

    expect(fetchMock).toHaveBeenCalledWith("/api/production/analytics?year=2023", {
      cache: "no-store",
    });
    expect(result).toEqual(SAMPLE);
  });

  it("использует текущий год, если год не передан", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-18T00:00:00Z"));
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SAMPLE));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAnalytics();

    expect(fetchMock).toHaveBeenCalledWith("/api/production/analytics?year=2026", {
      cache: "no-store",
    });
    vi.useRealTimers();
  });

  it("возвращает null при ok:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));
    expect(await fetchAnalytics(2025)).toBeNull();
  });

  it("возвращает null при исключении fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await fetchAnalytics(2025)).toBeNull();
  });
});
