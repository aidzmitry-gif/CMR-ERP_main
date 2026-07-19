import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deletePosition,
  fetchPlan,
  fetchPlanServer,
  fmtNh,
  loadTone,
  putPlanCell,
  upsertPosition,
} from "@/lib/production-plan";
import type { PlanBoard } from "@/lib/production-plan";

function makeBoard(): PlanBoard {
  return {
    year: 2026,
    capacity_nh: 176,
    rows: [],
    totals: {
      month_nh: [],
      fact_nh: [],
      load_pct: [],
      year_nh: 0,
      plan_ytd: 0,
      fact_ytd: 0,
      peak_month: 0,
      low_month: 0,
    },
  };
}

function okResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => data } as Response;
}

function errResponse(status = 500) {
  return { ok: false, status, json: async () => ({}) } as Response;
}

describe("production-plan", () => {
  describe("loadTone", () => {
    it("≤69 → green", () => {
      expect(loadTone(0)).toContain("green");
      expect(loadTone(50)).toContain("green");
      expect(loadTone(69)).toContain("green");
    });

    it("70..100 → amber", () => {
      expect(loadTone(70)).toContain("amber");
      expect(loadTone(85)).toContain("amber");
      expect(loadTone(100)).toContain("amber");
    });

    it(">100 → red", () => {
      expect(loadTone(101)).toContain("red");
      expect(loadTone(150)).toContain("red");
    });
  });

  describe("fmtNh", () => {
    it("0 → '0,0'", () => {
      expect(fmtNh(0)).toBe("0,0");
    });

    it("1 → '1,0'", () => {
      expect(fmtNh(1)).toBe("1,0");
    });

    it("176.5 → '176,5'", () => {
      expect(fmtNh(176.5)).toBe("176,5");
    });

    it("0.25 → '0,3' (round)", () => {
      expect(fmtNh(0.25)).toBe("0,3");
    });

    it("704 → '704,0'", () => {
      expect(fmtNh(704)).toBe("704,0");
    });
  });

  describe("fetchPlanServer", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
      fetchMock.mockReset();
      vi.stubGlobal("fetch", fetchMock);
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("зовёт BACKEND_URL (дефолт 127.0.0.1:8000) с явным годом и ролями, парсит доску", async () => {
      const board = makeBoard();
      fetchMock.mockResolvedValueOnce(okResponse(board));

      const result = await fetchPlanServer(2027, "rop,worker");

      expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/production/plan?year=2027", {
        cache: "no-store",
        headers: { "X-User-Roles": "rop,worker" },
      });
      expect(result).toEqual(board);
    });

    it("без года подставляет текущий, без ролей — headers undefined", async () => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date(2026, 5, 1));
      fetchMock.mockResolvedValueOnce(okResponse(makeBoard()));

      await fetchPlanServer();

      expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/production/plan?year=2026", {
        cache: "no-store",
        headers: undefined,
      });
      vi.useRealTimers();
    });

    it("возвращает null при не-ok ответе", async () => {
      fetchMock.mockResolvedValueOnce(errResponse(404));
      expect(await fetchPlanServer(2026)).toBeNull();
    });

    it("возвращает null при исключении сети", async () => {
      fetchMock.mockRejectedValueOnce(new Error("network down"));
      expect(await fetchPlanServer(2026)).toBeNull();
    });
  });

  describe("fetchPlan", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
      fetchMock.mockReset();
      vi.stubGlobal("fetch", fetchMock);
    });

    afterEach(() => vi.unstubAllGlobals());

    it("зовёт прокси /api с годом", async () => {
      const board = makeBoard();
      fetchMock.mockResolvedValueOnce(okResponse(board));

      const result = await fetchPlan(2025);

      expect(fetchMock).toHaveBeenCalledWith("/api/production/plan?year=2025", {
        cache: "no-store",
      });
      expect(result).toEqual(board);
    });

    it("возвращает null при не-ok", async () => {
      fetchMock.mockResolvedValueOnce(errResponse());
      expect(await fetchPlan(2025)).toBeNull();
    });

    it("возвращает null при исключении", async () => {
      fetchMock.mockRejectedValueOnce(new Error("boom"));
      expect(await fetchPlan(2025)).toBeNull();
    });
  });

  describe("putPlanCell", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
      fetchMock.mockReset();
      vi.stubGlobal("fetch", fetchMock);
    });

    afterEach(() => vi.unstubAllGlobals());

    it("шлёт PUT с JSON-телом обновления и возвращает доску", async () => {
      const board = makeBoard();
      fetchMock.mockResolvedValueOnce(okResponse(board));
      const update = { year: 2026, product: "Корпус", month: 3, plan_qty: 15 };

      const result = await putPlanCell(update);

      expect(fetchMock).toHaveBeenCalledWith("/api/production/plan/cell", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      expect(result).toEqual(board);
    });

    it("возвращает null при ошибке сервера", async () => {
      fetchMock.mockResolvedValueOnce(errResponse(400));
      expect(
        await putPlanCell({ year: 2026, product: "X", month: 1, plan_qty: 1 }),
      ).toBeNull();
    });

    it("возвращает null при исключении сети", async () => {
      fetchMock.mockRejectedValueOnce(new Error("fail"));
      expect(
        await putPlanCell({ year: 2026, product: "X", month: 1, plan_qty: 1 }),
      ).toBeNull();
    });
  });

  describe("upsertPosition", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
      fetchMock.mockReset();
      vi.stubGlobal("fetch", fetchMock);
    });

    afterEach(() => vi.unstubAllGlobals());

    it("шлёт POST с 12 месяцами и возвращает доску", async () => {
      const board = makeBoard();
      fetchMock.mockResolvedValueOnce(okResponse(board));
      const data = { year: 2026, product: "Крышка", monthly: Array(12).fill(3) };

      const result = await upsertPosition(data);

      expect(fetchMock).toHaveBeenCalledWith("/api/production/plan/position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      expect(result).toEqual(board);
    });

    it("возвращает null при не-ok", async () => {
      fetchMock.mockResolvedValueOnce(errResponse(500));
      expect(
        await upsertPosition({ year: 2026, product: "X", monthly: Array(12).fill(0) }),
      ).toBeNull();
    });

    it("возвращает null при исключении", async () => {
      fetchMock.mockRejectedValueOnce(new Error("fail"));
      expect(
        await upsertPosition({ year: 2026, product: "X", monthly: Array(12).fill(0) }),
      ).toBeNull();
    });
  });

  describe("deletePosition", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
      fetchMock.mockReset();
      vi.stubGlobal("fetch", fetchMock);
    });

    afterEach(() => vi.unstubAllGlobals());

    it("кодирует product в query и шлёт DELETE, true при успехе", async () => {
      fetchMock.mockResolvedValueOnce(okResponse({}));

      const result = await deletePosition(2026, "Блок питания №1");

      expect(fetchMock).toHaveBeenCalledWith(
        "/api/production/plan/position?year=2026&product=%D0%91%D0%BB%D0%BE%D0%BA%20%D0%BF%D0%B8%D1%82%D0%B0%D0%BD%D0%B8%D1%8F%20%E2%84%961",
        { method: "DELETE" },
      );
      expect(result).toBe(true);
    });

    it("false при не-ok ответе", async () => {
      fetchMock.mockResolvedValueOnce(errResponse(404));
      expect(await deletePosition(2026, "X")).toBe(false);
    });

    it("false при исключении сети", async () => {
      fetchMock.mockRejectedValueOnce(new Error("fail"));
      expect(await deletePosition(2026, "X")).toBe(false);
    });
  });
});
