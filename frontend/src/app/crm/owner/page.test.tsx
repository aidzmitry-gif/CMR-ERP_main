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
const available = <T,>(data: T) => ({ status: "ok" as const, data });
beforeEach(() => vi.mocked(fetchOwnerDashboard).mockReset());
const metric = (name: string) => within(screen.getByText(name).parentElement!.parentElement!);

describe("панель директора", () => {
  it("закрытые проигранные сделки не увеличивают работающий портфель, отсутствие плана не равно 0%", async () => {
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({ metrics: available(metrics), stages: available(stages), kpis: available([]) });
    render(await OwnerPage());
    expect(metric("Сделок в работе").getByText("3")).toBeInTheDocument();
    expect(metric("Сумма в работе").getByText("100 BYN")).toBeInTheDocument();
    expect(metric("Среднее выполнение KPI с планом").getByText("Нет данных")).toBeInTheDocument();
  });
  it("среднее считает только показатели с заданным положительным планом", async () => {
    const kpi = { id: "k", label: "KPI", value: 1, target: 10, percent: 40, icon: "ruble" as const, tone: "blue" as const };
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({
      metrics: available(metrics), stages: available(stages),
      kpis: available([kpi, { ...kpi, id: "noplan", target: 0, percent: 100 }]),
    });
    render(await OwnerPage());
    expect(metric("Среднее выполнение KPI с планом").getByText("40%")).toBeInTheDocument();
  });

  it("не превращает запрет доступа к источникам в нулевые показатели", async () => {
    const denied = { status: "auth" as const };
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({ metrics: denied, stages: denied, kpis: denied });
    render(await OwnerPage());
    expect(metric("Сделок в работе").getByText("Нет доступа")).toBeInTheDocument();
    expect(metric("Сумма в работе").getByText("Нет доступа")).toBeInTheDocument();
    expect(metric("Согласований ждут").getByText("Нет доступа")).toBeInTheDocument();
    expect(metric("Среднее выполнение KPI с планом").getByText("Нет доступа")).toBeInTheDocument();
    expect(screen.getByText("Нет доступа к воронке продаж.")).toBeInTheDocument();
  });

  it("не показывает fallback-значения для недоступных источников", async () => {
    const unavailable = { status: "unavailable" as const };
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({
      metrics: available(metrics), stages: unavailable, kpis: unavailable,
    });
    render(await OwnerPage());
    expect(metric("Сделок в работе").getByText("Нет данных")).toBeInTheDocument();
    expect(metric("Сумма в работе").getByText("Нет данных")).toBeInTheDocument();
    expect(metric("Согласований ждут").getByText("2")).toBeInTheDocument();
    expect(metric("Среднее выполнение KPI с планом").getByText("Нет данных")).toBeInTheDocument();
    expect(screen.getByText("Воронка продаж временно недоступна.")).toBeInTheDocument();
    expect(screen.getByText("Показатели KPI временно недоступны.")).toBeInTheDocument();
  });

  it("сохраняет успешные метрики и KPI при ошибке воронки", async () => {
    const kpi = { id: "k", label: "KPI", value: 1, target: 10, percent: 40, icon: "ruble" as const, tone: "blue" as const };
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({
      metrics: available(metrics), stages: { status: "unavailable" }, kpis: available([kpi]),
    });
    render(await OwnerPage());
    expect(metric("Согласований ждут").getByText("2")).toBeInTheDocument();
    expect(metric("Среднее выполнение KPI с планом").getByText("40%")).toBeInTheDocument();
    expect(metric("Сделок в работе").getByText("Нет данных")).toBeInTheDocument();
  });

  it("сохраняет воронку при некорректных метриках", async () => {
    const { fetchOwnerDashboard: fetchOwnerDashboardActual } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => url.includes("/system/owner")
        ? {
            approvals_pending: "2", approvals_total: 3, audit_count: 4, events_count: 5,
            counterparties: 6, skus: 7, modules: ["sales"], widgets: [{ key: "sales", title: "Sales" }],
          }
        : url.includes("/sales/board")
          ? { stages }
          : [{ key: "calls", title: "Звонки", target: 10, actual: 4, percent: 40, unit: "count", icon: "phone", tone: "blue" }],
    }));
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(fetchOwnerDashboard).mockImplementation(fetchOwnerDashboardActual);

    try {
      render(await OwnerPage());
      expect(metric("Сделок в работе").getByText("3")).toBeInTheDocument();
      expect(metric("Среднее выполнение KPI с планом").getByText("40%")).toBeInTheDocument();
      expect(screen.getByText("Метрики владельца временно недоступны.")).toBeInTheDocument();
      for (const label of ["Согласований ждут", "Событий в шине", "Записей аудита", "Контрагентов"]) {
        expect(metric(label).getByText("Нет данных")).toBeInTheDocument();
        expect(metric(label).queryByText("0")).not.toBeInTheDocument();
      }
    } finally {
      vi.unstubAllGlobals();
      vi.mocked(fetchOwnerDashboard).mockReset();
    }
  });

  it("считает успешный пустой список воронки нулём, не ошибкой загрузки", async () => {
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({
      metrics: available(metrics), stages: available([]), kpis: available([]),
    });
    render(await OwnerPage());
    expect(metric("Сделок в работе").getByText("0")).toBeInTheDocument();
    expect(metric("Выиграно сделок").getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Стадий пока нет.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("форматирует сумму владельца в BYN и исключает закрытые стадии из портфеля", async () => {
    vi.mocked(fetchOwnerDashboard).mockResolvedValue({
      metrics: available(metrics), stages: available(stages), kpis: available([]),
    });
    render(await OwnerPage());
    expect(metric("Сумма в работе").getByText("100 BYN")).toBeInTheDocument();
    expect(within(screen.getByText("В работе").parentElement!.parentElement!).getByText("3 · 100 BYN")).toBeInTheDocument();
    expect(screen.queryByText(/₽/)).not.toBeInTheDocument();
  });
});
