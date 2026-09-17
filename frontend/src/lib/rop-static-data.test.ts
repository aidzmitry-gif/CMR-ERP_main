import { describe, expect, it } from "vitest";

import {
  activityFunnel,
  activityKpis,
  activityNorms,
  activityRules,
  managerActivity,
  managerActivityTotal,
  staleDeals,
} from "@/lib/rop-activity-data";
import {
  ageBuckets,
  managerAging,
  managerAgingTotal,
  stageAging,
  stageKpis,
  stageSla,
  stuckDeals,
} from "@/lib/rop-stages-data";

describe("статические данные РОП", () => {
  it("активность согласована по итогам команды и воронки", () => {
    expect(activityKpis).toHaveLength(6);
    expect(activityNorms.every((item) => item.fact <= item.norm)).toBe(true);
    expect(activityFunnel.at(-1)).toMatchObject({ label: "Закрыто: успешно", count: 6 });
    expect(managerActivity.reduce((sum, item) => sum + item.calls, 0)).toBe(managerActivityTotal.calls);
    expect(managerActivity.reduce((sum, item) => sum + item.meetings, 0)).toBe(managerActivityTotal.meetings);
    expect(staleDeals).toHaveLength(4);
    expect(activityRules).toHaveLength(5);
  });

  it("старение этапов имеет непротиворечивые суммы и SLA", () => {
    expect(stageKpis).toHaveLength(6);
    expect(stageAging.reduce((sum, item) => sum + item.count, 0)).toBe(129);
    expect(ageBuckets.reduce((sum, item) => sum + item.count, 0)).toBe(129);
    expect(managerAging.reduce((sum, item) => sum + item.count, 0)).toBe(managerAgingTotal.count);
    expect(stuckDeals).toHaveLength(5);
    expect(stageSla).toHaveLength(5);
    expect(stageAging.filter((item) => item.over).map((item) => item.stage)).toEqual([
      "Согласование",
      "Договор",
    ]);
  });
});
