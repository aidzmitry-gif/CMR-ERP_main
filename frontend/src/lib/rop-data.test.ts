import { describe, expect, it } from "vitest";

import {
  aging,
  attention,
  cashKpis,
  capacity,
  focus,
  forecast,
  funnel,
  lossQueue,
  managerDso,
  overviewKpis,
  paceMeters,
  planActions,
  team,
  velocity,
} from "@/lib/rop-data";

describe("rop-data — целостность витрины РОП", () => {
  it("содержит непустые данные для каждого слоя управленческого дашборда", () => {
    expect(overviewKpis).toHaveLength(6);
    expect(forecast.parts.reduce((sum, part) => sum + part.amount, 0)).toBe(298000);
    expect(funnel.at(-1)?.stage).toBe("Закрыто: успешно");
    expect(attention.some((deal) => deal.action)).toBe(true);
    expect(team.reduce((sum, manager) => sum + manager.calls, 0)).toBe(154);
    expect(lossQueue.some((item) => item.selected)).toBe(true);
    expect(capacity.length).toBeGreaterThan(0);
    expect(planActions.every((action) => action.who && action.text)).toBe(true);
    expect(paceMeters.length).toBeGreaterThan(0);
    expect(Object.keys(velocity)).toContain("cells");
    expect(cashKpis.length).toBeGreaterThan(0);
    expect(aging.reduce((sum, bucket) => sum + bucket.amount, 0)).toBeGreaterThan(0);
    expect(managerDso.every((manager) => manager.dso.includes("дн"))).toBe(true);
    expect(focus.length).toBeGreaterThan(0);
  });
});
