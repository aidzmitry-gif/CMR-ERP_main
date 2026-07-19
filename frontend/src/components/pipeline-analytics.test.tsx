import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Воронки — из @/lib/api (мок). Остальные данные компонент тянет глобальным fetch,
// который мы маршрутизируем по URL ниже (fetch не мокается через @/lib/api).
vi.mock("@/lib/api", () => ({
  fetchFunnels: vi.fn(),
}));

import { PipelineAnalytics } from "@/components/pipeline-analytics";
import * as api from "@/lib/api";

// Плитка по подписи: возвращает контейнер плитки для проверки суммы (formatByn кладёт
// неразрывный пробел-разделитель → точный getByText хрупок; toHaveTextContent нормализует).
function tileByLabel(label: string): HTMLElement {
  return screen.getByText(label).parentElement as HTMLElement;
}

// ── фикстуры (перезаписываются в отдельных тестах) ────────────────────────────
const ANALYTICS_OK = {
  funnel: "new_clients",
  stages: [
    { id: "s1", title: "Новый", color: "#3b82f6", count: 10, sum: 50000, weighted: 20000, avg_age_days: 3, next_conv_pct: 60 },
    { id: "s2", title: "Переговоры", color: "#f59e0b", count: 6, sum: 30000, weighted: 15000, avg_age_days: 5, next_conv_pct: null },
    { id: "s3", title: "Выиграно", color: "#10b981", count: 4, sum: 20000, weighted: 20000, avg_age_days: null, next_conv_pct: null },
  ],
  forecast_weighted: 55000,
  avg_cycle_days: 12,
  won_count: 4,
};

const ANALYTICS_EMPTY = { ...ANALYTICS_OK, stages: ANALYTICS_OK.stages.map((s) => ({ ...s, count: 0 })) };

const MARGIN_OK = {
  funnel: "new_clients", owner: null,
  revenue_weighted: 40000, gross_weighted: 12000, margin_pct_blended: 30,
  deals_priced: 8, deals_total: 10, reason: null,
};

const MARGIN_NO_GROSS = {
  funnel: "new_clients", owner: null,
  revenue_weighted: 40000, gross_weighted: null, margin_pct_blended: null,
  deals_priced: 0, deals_total: 10, reason: "Себестоимость закупок не подключена — тест",
};

const METRICS_OK = {
  funnel: "new_clients", date_from: "2026-06-01", date_to: "2026-06-30",
  stages: [
    { id: "s1", title: "Новый", color: "#3b82f6", entered_count: 20, conv_next_pct: 50, avg_time_days: 2, completed_count: 10 },
    { id: "s2", title: "Переговоры", color: "#f59e0b", entered_count: 10, conv_next_pct: null, avg_time_days: 4, completed_count: 5 },
    { id: "s3", title: "Выиграно", color: "#10b981", entered_count: 5, conv_next_pct: null, avg_time_days: null, completed_count: 5 },
  ],
};

// ── настраиваемое состояние маршрутизатора fetch ──────────────────────────────
let analytics: { ok: boolean; data: unknown };
let margin: { ok: boolean; data: unknown };
let metrics: { ok: boolean; data: unknown };
let users: { full_name: string; role: string }[];
let dealOwners: { owner?: string }[];

function resp(ok: boolean, data: unknown) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: async () => data });
}

function routeFetch(input: RequestInfo | URL) {
  const url = String(input);
  if (url.includes("/system/users")) return resp(true, { users });
  if (url.includes("/pipeline/analytics")) return resp(analytics.ok, analytics.data);
  if (url.includes("/pipeline/margin-forecast")) return resp(margin.ok, margin.data);
  if (url.includes("/pipeline/stage-metrics")) return resp(metrics.ok, metrics.data);
  if (url.includes("stuck_days")) return resp(true, [{ funnel: "new_clients" }, { funnel: "new_clients" }]);
  if (url.includes("/sales/deals")) return resp(true, dealOwners);
  return resp(true, {});
}

beforeEach(() => {
  vi.clearAllMocks();
  analytics = { ok: true, data: ANALYTICS_OK };
  margin = { ok: true, data: MARGIN_OK };
  metrics = { ok: true, data: METRICS_OK };
  users = [];
  dealOwners = [];
  (api.fetchFunnels as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  global.fetch = vi.fn(routeFetch) as unknown as typeof fetch;
});

describe("PipelineAnalytics", () => {
  it("рендерит фильтры и после загрузки — плитки, стадии и суммы воронки", async () => {
    render(<PipelineAnalytics />);

    // фильтры на месте сразу
    expect(screen.getByText("Воронка")).toBeInTheDocument();
    expect(screen.getByText("Продавец")).toBeInTheDocument();

    // плитки верхнего ряда после загрузки
    expect(await screen.findByText("Взвеш. прогноз")).toBeInTheDocument();
    expect(tileByLabel("Взвеш. прогноз")).toHaveTextContent(/55\s*000\s*BYN/); // forecast_weighted
    expect(screen.getByText("12 дн")).toBeInTheDocument(); // средний цикл won
    expect(screen.getByText("Средний цикл won")).toBeInTheDocument();

    // «Висяки» — из stuck_days=14 (2 записи в фикстуре)
    expect(screen.getByText("Висяки (≥14 дн)")).toBeInTheDocument();

    // стадии воронки отрисованы с русскими подписями (встречаются и в блоке метрик)
    expect(screen.getAllByText("Новый").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Переговоры").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Выиграно").length).toBeGreaterThan(0);
    // склонение «10 сделок» на первой стадии
    expect(screen.getByText("10 сделок")).toBeInTheDocument();
  });

  it("honest-empty: воронка без сделок показывает подсказку вместо графиков", async () => {
    analytics = { ok: true, data: ANALYTICS_EMPTY };
    render(<PipelineAnalytics />);

    expect(await screen.findByText(/нет сделок — аналитика пуста/)).toBeInTheDocument();
    // плиток прогноза при пустой воронке нет
    expect(screen.queryByText("Взвеш. прогноз")).not.toBeInTheDocument();
  });

  it("ошибка загрузки аналитики показывает сообщение и «Повторить»; ретрай грузит данные", async () => {
    analytics = { ok: false, data: {} };
    render(<PipelineAnalytics />);

    expect(await screen.findByText("Не удалось загрузить аналитику.")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Повторить" });

    // чиним ответ и жмём «Повторить» → появляются плитки
    analytics = { ok: true, data: ANALYTICS_OK };
    fireEvent.click(retry);

    expect(await screen.findByText("Взвеш. прогноз")).toBeInTheDocument();
    expect(tileByLabel("Взвеш. прогноз")).toHaveTextContent(/55\s*000\s*BYN/);
  });

  it("маржа воронки без валовой прибыли показывает honest-баннер с причиной", async () => {
    margin = { ok: true, data: MARGIN_NO_GROSS };
    render(<PipelineAnalytics />);

    expect(await screen.findByText("Маржа воронки")).toBeInTheDocument();
    // выручка показана, а вал. прибыль/маржа — прочерк
    expect(tileByLabel("Выручка взвеш.")).toHaveTextContent(/40\s*000\s*BYN/);
    expect(screen.getByText(/Себестоимость закупок не подключена — тест/)).toBeInTheDocument();
    expect(screen.getByText(/оценка по 0 из 10 сделкам/)).toBeInTheDocument();
  });

  it("график этапов: конверсия 50% показана, а пустая стадия — «нет данных»", async () => {
    render(<PipelineAnalytics />);

    expect(await screen.findByText("Конверсия и время на этапах")).toBeInTheDocument();
    expect(screen.getByText("2026-06-01 — 2026-06-30")).toBeInTheDocument();
    // конверсия первой стадии = 50% (из stage-metrics, не из воронки)
    expect(screen.getByText("50%")).toBeInTheDocument();
    // стадии без данных конверсии/времени → honest «нет данных» (несколько мест)
    expect(screen.getAllByText("нет данных").length).toBeGreaterThan(0);
  });

  it("переключение периода на «Неделя» перезапрашивает stage-metrics с period=week", async () => {
    render(<PipelineAnalytics />);
    await screen.findByText("Конверсия и время на этапах");

    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));

    await waitFor(() => {
      const calls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes("stage-metrics") && u.includes("period=week"))).toBe(true);
    });
  });

  it("режим «Все» без настроенных воронок — honest-empty про пустую аналитику", async () => {
    render(<PipelineAnalytics />);
    await screen.findByText("Взвеш. прогноз");

    // переключаем select воронки на «Все» (funnels пусты в фикстуре)
    fireEvent.change(screen.getByDisplayValue("new_clients"), { target: { value: "all" } });

    expect(await screen.findByText(/Воронки не настроены — аналитика пуста/)).toBeInTheDocument();
  });

  it("фильтр «Продавец» наполняется реальными owner-ами действующих сотрудников", async () => {
    users = [
      { full_name: "Иванов Иван Иванович", role: "sales" },
      { full_name: "Сидоров Сидор", role: "sales_head" },
      { full_name: "Чужой Человек", role: "warehouse" }, // не продавец — отсечь
    ];
    dealOwners = [
      { owner: "Иванов И.И." }, // совпадает по фамилии с активным продавцом
      { owner: "Заявки" }, // артефакт — не должен попасть в список
    ];
    render(<PipelineAnalytics />);

    // опция продавца появляется после двухшаговой подгрузки (users → deals)
    expect(await screen.findByRole("option", { name: "Иванов И.И." })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Заявки" })).not.toBeInTheDocument();
  });
});
