import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ProcurementRequestPlan } from "@/components/erp/procurement-request-plan";

const organizations = [
  { id: 1, name: "Первая", unp: "111111111" },
  { id: 2, name: "Вторая", unp: "222222222" },
];
const json = (body: unknown) => ({ ok: true, json: async () => body });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/procurement/receipt-organizations") return json(organizations);
    const match = /organizations\/(\d+)\//.exec(url);
    const org = Number(match?.[1]);
    if (url.endsWith("request-plan-context")) return json({ organization_id: org, principal: "tester", can_manage: false });
    if (url.includes("owned-sources")) return json({ organization_id: org, items: [], next_after_id: null });
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("предвыбирает только доступное юрлицо после загрузки списка", async () => {
  render(<ProcurementRequestPlan suggestedOrg="2" />);
  await waitFor(() => expect(screen.getByLabelText("Юрлицо плана закупок")).toHaveValue("2"));
  expect(await screen.findByText("Доступен просмотр. Для изменения нужен главный бухгалтер этого юрлица с доступом к закупкам.")).toBeInTheDocument();
});

it.each(["0", "abc", "3", "2147483648"])("игнорирует недоступный или некорректный org %s", async (suggestedOrg) => {
  render(<ProcurementRequestPlan suggestedOrg={suggestedOrg} />);
  await screen.findByRole("option", { name: "Вторая · 222222222" });
  expect(screen.getByLabelText("Юрлицо плана закупок")).toHaveValue("");
  expect(screen.queryByText("Проверка доступа…")).toBeNull();
});
