import { afterEach, describe, expect, it, vi } from "vitest";

import { decidePlanComment, getKpisForOwner, reopenPlan } from "@/lib/planning-api";

afterEach(() => vi.unstubAllGlobals());

describe("planning-api", () => {
  it("переоткрывает план с причиной и без неё", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await expect(reopenPlan(7, "  Исправить прогноз  ")).resolves.toBe(true);
    await expect(reopenPlan(8)).resolves.toBe(true);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/sales/plans/7/reopen", expect.objectContaining({ body: JSON.stringify({ reason: "  Исправить прогноз  " }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/sales/plans/8/reopen", expect.objectContaining({ body: "{}" }));
  });

  it("решает план и нормализует пустой комментарий", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await expect(decidePlanComment(9, true, "  ")).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/plans/9/decide", expect.objectContaining({ body: JSON.stringify({ approved: true, comment: undefined }) }));
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(decidePlanComment(9, false, "no")).resolves.toBe(false);
    await expect(reopenPlan(9)).resolves.toBe(false);
  });

  it("маппит KPI владельца и возвращает пустой список при ответе с ошибкой", async () => {
    const kpis = [{ key: "revenue", title: "Выручка", target: 100, actual: 80, percent: 80, unit: "money", icon: "₽", tone: "green" }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => kpis }));
    await expect(getKpisForOwner("2026-09", 12)).resolves.toEqual([
      { id: "revenue", label: "Выручка", value: 80, target: 100, percent: 80, money: true, icon: "₽", tone: "green" },
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    await expect(getKpisForOwner("2026-09", 12)).resolves.toEqual([]);
  });
});
