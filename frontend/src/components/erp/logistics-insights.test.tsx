import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Компонент клиентский: единственная зависимость данных — @/lib/logistics-api (все фетчи
// graceful, отдают null/[]). Мокаем её, чтобы дёргать ветки состояний детерминированно.
// formatByn (@/lib/format) и мелкие UI-примитивы (logistics-ui) — реальные (чистые, лёгкие).
vi.mock("@/lib/logistics-api", () => ({
  fetchCostInsights: vi.fn(),
  seedZones: vi.fn(),
  seedTariffs: vi.fn(),
  seedAudit: vi.fn(),
  seedRfq: vi.fn(),
  awardRfq: vi.fn(),
}));

import { LogisticsInsights } from "@/components/erp/logistics-insights";
import * as api from "@/lib/logistics-api";
import type { CostInsights } from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

function makeInsights(over: Partial<CostInsights> = {}): CostInsights {
  return {
    reference_weight_kg: 30,
    potential_savings: 812,
    best_savings_zone: "Z1",
    tender_savings_total: 445,
    audit_to_recover: 137,
    import_freight_total: 9600,
    import_freight_avg: 3200,
    import_freight_count: 3,
    zones: [
      {
        zone_code: "Z1",
        zone_name: "Минск",
        carriers: 4,
        cheapest_carrier: "DELINE",
        cheapest_carrier_name: "Деловые Линии",
        cheapest_total: 55,
        avg_total: 70,
        max_total: 92,
        spread_pct: 24,
      },
      {
        zone_code: "Z2",
        zone_name: "Брест",
        carriers: 3,
        cheapest_carrier: "SDEK",
        cheapest_carrier_name: "СДЭК",
        cheapest_total: 61,
        avg_total: 64,
        max_total: 68,
        spread_pct: 5,
      },
    ],
    tenders: [
      {
        rfq_number: "RFQ-77",
        route: "Минск → Гомель",
        carrier: "Деловые Линии",
        baseline: 500,
        awarded: 380,
        saved: 120,
        saved_pct: 24,
      },
    ],
    recommendations: ["Переключить зону Z1 на самого дешёвого перевозчика"],
    ...over,
  };
}

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

// formatByn использует ru-RU NumberFormat → неразрывные пробелы в разрядах ("9 600").
// testing-library нормализует пробелы в DOM, но не в строке-матчере → приводим обе стороны.
const norm = (s: string) => s.replace(/\s/g, " ");
const byn = (v: number) => norm(formatByn(v));

beforeEach(() => {
  vi.clearAllMocks();
  asMock(api.fetchCostInsights).mockResolvedValue(makeInsights());
});

describe("LogisticsInsights", () => {
  it("показывает индикатор загрузки, пока не пришли данные", () => {
    asMock(api.fetchCostInsights).mockReturnValue(new Promise(() => {})); // не резолвится
    render(<LogisticsInsights />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
  });

  it("null от API (backend недоступен) → честное сообщение об ошибке, а не пустая аналитика", async () => {
    asMock(api.fetchCostInsights).mockResolvedValue(null);
    render(<LogisticsInsights />);
    expect(await screen.findByText(/Не удалось загрузить аналитику экономии/)).toBeInTheDocument();
    // это НЕ пустое состояние с засевом — кнопки засева тут быть не должно
    expect(screen.queryByRole("button", { name: /Заполнить демо/ })).not.toBeInTheDocument();
  });

  it("пустой список зон → пустое состояние с кнопкой засева демо-данных", async () => {
    asMock(api.fetchCostInsights).mockResolvedValue(makeInsights({ zones: [] }));
    render(<LogisticsInsights />);
    expect(
      await screen.findByText(/Нет данных для аналитики стоимости/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Заполнить демо-данными/ })).toBeInTheDocument();
  });

  it("рендерит KPI-плитки с суммами в BYN и строки зон с самым дешёвым перевозчиком", async () => {
    render(<LogisticsInsights />);
    // KPI: потенциал/торг/аудит/фрахт — суммы форматируются formatByn
    expect(await screen.findByText(formatByn(812))).toBeInTheDocument();
    expect(screen.getByText(formatByn(445))).toBeInTheDocument();
    expect(screen.getByText(formatByn(137))).toBeInTheDocument();
    expect(screen.getByText(byn(9600))).toBeInTheDocument(); // разряды: неразрывный пробел

    // строки зон: имя дешёвого перевозчика и его цена
    // «Деловые Линии» встречается и в зоне, и в тендерах → берём все
    expect(screen.getAllByText("Деловые Линии").length).toBeGreaterThan(0);
    expect(screen.getByText("СДЭК")).toBeInTheDocument(); // только в строке зоны Z2
    expect(screen.getByText(formatByn(55))).toBeInTheDocument();

    // разброс пилюлей: 24% и 5% (toFixed(0))
    expect(screen.getByText("24%")).toBeInTheDocument();
    expect(screen.getByText("5%")).toBeInTheDocument();

    // рекомендация выведена
    expect(screen.getByText(/Переключить зону Z1/)).toBeInTheDocument();
  });

  it("плитка «К возврату (аудит)» краснеет при долге и зеленеет при нуле", async () => {
    // долг > 0 → tone red
    const { unmount } = render(<LogisticsInsights />);
    const debtLabel = await screen.findByText("К возврату (аудит)");
    const debtValue = debtLabel.parentElement?.querySelector("div.text-red-600");
    expect(debtValue).not.toBeNull();
    expect(debtValue).toHaveTextContent(formatByn(137));
    unmount();

    // ноль → tone emerald (не красный)
    asMock(api.fetchCostInsights).mockResolvedValue(makeInsights({ audit_to_recover: 0 }));
    render(<LogisticsInsights />);
    const zeroLabel = await screen.findByText("К возврату (аудит)");
    expect(zeroLabel.parentElement?.querySelector("div.text-red-600")).toBeNull();
    expect(zeroLabel.parentElement?.querySelector("div.text-emerald-600")).not.toBeNull();
  });

  it("переключение эталонного веса перезапрашивает аналитику под новый вес", async () => {
    render(<LogisticsInsights />);
    await screen.findByText("СДЭК"); // данные пришли
    expect(api.fetchCostInsights).toHaveBeenCalledWith(30); // маунт: дефолт 30 кг

    fireEvent.click(screen.getByRole("button", { name: "5 кг" }));

    await waitFor(() => expect(api.fetchCostInsights).toHaveBeenCalledWith(5));
  });

  it("«Обновить демо» из пустого состояния засевает данные, заключает демо-тендер и показывает аналитику", async () => {
    // сначала пусто → показ EmptyState с засевом
    asMock(api.fetchCostInsights).mockResolvedValueOnce(makeInsights({ zones: [] }));
    asMock(api.seedRfq).mockResolvedValue({ id: 51 });
    asMock(api.awardRfq).mockResolvedValue({});
    // после засева load(weight) снова тянет аналитику — теперь с данными
    asMock(api.fetchCostInsights).mockResolvedValue(makeInsights());

    render(<LogisticsInsights />);
    const seedBtn = await screen.findByRole("button", { name: /Заполнить демо-данными/ });
    fireEvent.click(seedBtn);

    await waitFor(() => expect(api.seedZones).toHaveBeenCalled());
    expect(api.seedTariffs).toHaveBeenCalled();
    expect(api.seedAudit).toHaveBeenCalled();
    expect(api.seedRfq).toHaveBeenCalled();
    // seedRfq вернул тендер → его заключаем (awardRfq по id), появляется экономия торга
    expect(api.awardRfq).toHaveBeenCalledWith(51);

    // после засева таблица зон отрисована
    expect(await screen.findByText("СДЭК")).toBeInTheDocument();
  });

  it("рендерит таблицу экономии по заключённым тендерам", async () => {
    render(<LogisticsInsights />);
    expect(await screen.findByText("Экономия по заключённым тендерам")).toBeInTheDocument();
    const table = screen.getByText("RFQ-77").closest("table") as HTMLElement;
    expect(within(table).getByText("Минск → Гомель")).toBeInTheDocument();
    // сэкономлено + процент в одной ячейке
    expect(within(table).getByText(formatByn(120))).toBeInTheDocument();
    expect(within(table).getByText(/\(24%\)/)).toBeInTheDocument();
  });

  it("без заключённых тендеров блок экономии торга не рендерится", async () => {
    asMock(api.fetchCostInsights).mockResolvedValue(makeInsights({ tenders: [] }));
    render(<LogisticsInsights />);
    await screen.findByText("Деловые Линии"); // данные пришли
    expect(screen.queryByText("Экономия по заключённым тендерам")).not.toBeInTheDocument();
  });
});
