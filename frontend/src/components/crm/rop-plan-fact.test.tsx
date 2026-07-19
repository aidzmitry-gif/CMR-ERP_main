import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RopPlanFact } from "@/components/crm/rop-plan-fact";

// Типы — локальные копии (компонент их не экспортирует); повторяют форму ответа бэка.
interface ManagerRow {
  name: string;
  plan_deals: number;
  fact_deals: number;
  plan_revenue: number;
  fact_revenue: number;
  conversion_pct: number;
}
interface PlanFactData {
  period: string;
  managers: ManagerRow[];
  demo_plans: boolean;
}

// Компонент ходит в бэкенд ЧЕРЕЗ глобальный fetch (не через @/lib/api) — мокаем его.
// Каждый it сам задаёт, что вернёт очередной вызов, через queueFetch().
type FetchResult =
  | { ok: true; json: unknown }
  | { ok: false; status: number }
  | "pending";

let fetchQueue: FetchResult[] = [];
let lastUrls: string[] = [];

function queueFetch(...results: FetchResult[]) {
  fetchQueue.push(...results);
}

function ruNum(n: number): string {
  // ru-RU разделяет разряды неразрывным пробелом; RTL нормализует его в обычный —
  // приводим ожидаемую строку к тому же виду, иначе точное совпадение не сработает.
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n).replace(/\s/g, " ");
}

function manager(over: Partial<ManagerRow> = {}): ManagerRow {
  return {
    name: "Иванов И.И.",
    plan_deals: 10,
    fact_deals: 10,
    plan_revenue: 100000,
    fact_revenue: 100000,
    conversion_pct: 42,
    ...over,
  };
}

function payload(over: Partial<PlanFactData> = {}): PlanFactData {
  return { period: "2026-07", managers: [manager()], demo_plans: false, ...over };
}

beforeEach(() => {
  fetchQueue = [];
  lastUrls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      lastUrls.push(url);
      const next = fetchQueue.shift();
      if (!next || next === "pending") return new Promise(() => {}); // висит → состояние загрузки
      if (next.ok === false) {
        return Promise.resolve({ ok: false, status: next.status });
      }
      return Promise.resolve({ ok: true, json: async () => next.json });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe("RopPlanFact", () => {
  it("на маунте показывает «Загрузка…», пока запрос не разрешён", () => {
    queueFetch("pending");
    render(<RopPlanFact defaultPeriod="2026-07" />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    // таблицы ещё нет
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("грузит период по умолчанию и рендерит строку менеджера с числами и BYN", async () => {
    queueFetch({
      ok: true,
      json: payload({
        managers: [
          manager({ name: "Петрова А.С.", plan_deals: 8, fact_deals: 6, plan_revenue: 90000, fact_revenue: 45000, conversion_pct: 37 }),
        ],
      }),
    });
    render(<RopPlanFact defaultPeriod="2026-07" />);

    // URL запроса содержит период по умолчанию
    await waitFor(() => expect(lastUrls[0]).toContain("period=2026-07"));

    expect(await screen.findByText("Петрова А.С.")).toBeInTheDocument();
    const row = screen.getByText("Петрова А.С.").closest("tr") as HTMLElement;
    // план/факт сделок и конверсия — по реальному тексту компонента
    expect(within(row).getByText("8")).toBeInTheDocument();
    expect(within(row).getByText("6")).toBeInTheDocument();
    expect(within(row).getByText("37%")).toBeInTheDocument();
    // выручка форматируется ru-RU и подписана BYN
    expect(within(row).getByText(`${ruNum(90000)} BYN`)).toBeInTheDocument();
    expect(within(row).getByText(`${ruNum(45000)} BYN`)).toBeInTheDocument();
    // «Загрузка…» ушла
    expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument();
  });

  it("бейдж % выполнения красит зелёным/жёлтым/красным по порогам 100/70", async () => {
    // Порог по СДЕЛКАМ: 100% (10/10) → emerald, 70% (7/10) → amber, 30% (3/10) → red.
    // Выручку задаём так, чтобы её % не совпадал с % сделок в той же строке
    // (иначе в строке два одинаковых бейджа и getByText неоднозначен).
    queueFetch({
      ok: true,
      json: payload({
        managers: [
          manager({ name: "Полный", plan_deals: 10, fact_deals: 10, plan_revenue: 100000, fact_revenue: 80000 }),
          manager({ name: "Средний", plan_deals: 10, fact_deals: 7, plan_revenue: 100000, fact_revenue: 100000 }),
          manager({ name: "Слабый", plan_deals: 10, fact_deals: 3, plan_revenue: 100000, fact_revenue: 100000 }),
        ],
      }),
    });
    render(<RopPlanFact defaultPeriod="2026-07" />);

    const full = (await screen.findByText("Полный")).closest("tr") as HTMLElement;
    const mid = screen.getByText("Средний").closest("tr") as HTMLElement;
    const weak = screen.getByText("Слабый").closest("tr") as HTMLElement;

    expect(within(full).getByText("100%").className).toMatch(/emerald/);
    expect(within(mid).getByText("70%").className).toMatch(/amber/);
    expect(within(weak).getByText("30%").className).toMatch(/red/);
  });

  it("делит на ноль безопасно: план 0 сделок → 0% и красный бейдж", async () => {
    queueFetch({
      ok: true,
      json: payload({ managers: [manager({ name: "Без плана", plan_deals: 0, fact_deals: 5 })] }),
    });
    render(<RopPlanFact defaultPeriod="2026-07" />);
    const row = (await screen.findByText("Без плана")).closest("tr") as HTMLElement;
    const badge = within(row).getByText("0%");
    expect(badge.className).toMatch(/red/);
  });

  it("пустой список менеджеров → сообщение «Нет данных за этот период»", async () => {
    queueFetch({ ok: true, json: payload({ managers: [] }) });
    render(<RopPlanFact defaultPeriod="2026-07" />);
    expect(await screen.findByText("Нет данных за этот период.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("HTTP-ошибка показывает текст ошибки, а не молчит и не рисует таблицу", async () => {
    queueFetch({ ok: false, status: 500 });
    render(<RopPlanFact defaultPeriod="2026-07" />);
    expect(await screen.findByText("HTTP 500")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument();
  });

  it("бейдж «демо-план» виден только когда demo_plans=true", async () => {
    queueFetch({ ok: true, json: payload({ demo_plans: true }) });
    const { unmount } = render(<RopPlanFact defaultPeriod="2026-07" />);
    expect(await screen.findByText("демо-план")).toBeInTheDocument();
    unmount();

    queueFetch({ ok: true, json: payload({ demo_plans: false }) });
    render(<RopPlanFact defaultPeriod="2026-07" />);
    await screen.findByText("Иванов И.И.");
    expect(screen.queryByText("демо-план")).not.toBeInTheDocument();
  });

  it("смена периода перезапрашивает данные с новым периодом и обновляет таблицу", async () => {
    queueFetch(
      { ok: true, json: payload({ managers: [manager({ name: "Июльский" })] }) },
      { ok: true, json: payload({ period: "2026-08", managers: [manager({ name: "Августовский" })] }) },
    );
    render(<RopPlanFact defaultPeriod="2026-07" />);
    expect(await screen.findByText("Июльский")).toBeInTheDocument();

    const monthInput = document.querySelector('input[type="month"]') as HTMLInputElement;
    expect(monthInput.value).toBe("2026-07");
    fireEvent.change(monthInput, { target: { value: "2026-08" } });

    // второй запрос ушёл с новым периодом
    await waitFor(() => expect(lastUrls.some((u) => u.includes("period=2026-08"))).toBe(true));
    expect(await screen.findByText("Августовский")).toBeInTheDocument();
    expect(screen.queryByText("Июльский")).not.toBeInTheDocument();
    expect(monthInput.value).toBe("2026-08");
  });
});
