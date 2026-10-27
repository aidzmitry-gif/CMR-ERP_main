import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OwnerPage from "./page";
import { fetchOwnerDashboard } from "@/lib/api";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("@/components/owner-ai-insight", () => ({ OwnerAiInsight: () => null }));
vi.mock("@/lib/role-server", () => ({ currentRole: async () => "director", currentAccessToken: async () => "test" }));
vi.mock("@/lib/api", () => ({ fetchOwnerDashboard: vi.fn() }));

const metrics = { approvals_pending: 2, events_count: 4, audit_count: 5, counterparties: 6, skus: 0, modules: [], widgets: [] };
const stages = [
  { id: "work", title: "В работе", count: 3, sum: 100, color: "black", deals: [] },
  { id: "won", title: "Выиграно", count: 7, sum: 200, color: "green", deals: [] },
  { id: "lost", title: "Проиграно", count: 11, sum: 900, color: "red", deals: [] },
];
beforeEach(() => vi.mocked(fetchOwnerDashboard).mockReset());
const metric = (name: string) => within(screen.getByText(name).parentElement!.parentElement!);

describe("панель директора", () => {
  it("закрытые проигранные сделки не увеличивают работающий портфель, отсутствие плана не равно 0%", async () => {
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({ metrics, stages, kpis: [] });
    render(await OwnerPage());
    expect(metric("Сделок в работе").getByText("3")).toBeInTheDocument();
    expect(metric("Сумма в работе").getByText(/100/)).toBeInTheDocument();
    expect(metric("Среднее выполнение KPI с планом").getByText("Нет данных")).toBeInTheDocument();
  });
  it("среднее считает только показатели с заданным положительным планом", async () => {
    const kpi = { id: "k", label: "KPI", value: 1, target: 10, percent: 40, icon: "ruble" as const, tone: "blue" as const };
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({ metrics, stages, kpis: [kpi, { ...kpi, id: "noplan", target: 0, percent: 100 }] });
    render(await OwnerPage());
    expect(metric("Среднее выполнение KPI с планом").getByText("40%")).toBeInTheDocument();
  });
});
