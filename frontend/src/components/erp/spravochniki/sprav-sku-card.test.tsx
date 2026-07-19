import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Компонент тестируем изолированно: единственная сетевая зависимость — fetchSkuLandedInputs
// (грузит «Маржа-вход» в сайдбаре таба «Обзор»). Остальное — чистые пропсы/хелперы,
// поэтому мок точечный (importOriginal сохраняет changedFields/provenanceCounts и т.п.).
vi.mock("@/lib/reference-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reference-data")>();
  return { ...actual, fetchSkuLandedInputs: vi.fn() };
});

import { SpravSkuCard } from "@/components/erp/spravochniki/sprav-sku-card";
import * as ref from "@/lib/reference-data";
import type { SkuCard, SkuLandedInputs } from "@/lib/reference-data";

const landedReady: SkuLandedInputs = {
  sku_code: "SKU-1",
  weight_kg: 5,
  volume_m3: 0.1,
  unit: "шт",
  country: "Беларусь",
  effective_tnved: { code: "8501", source: "own", group_code: null },
  duty_pct: 5,
  vat_code: "НДС20",
  vat_rate: 20,
  provenance: {
    weight: "own",
    volume: "own",
    unit: "own",
    country: "own",
    tnved: "own",
    vat: "tnved",
  },
};

// Полностью заполненная карточка (все «горячие» поля → полнота 100%, ветви данных активны).
const card: SkuCard = {
  code: "SKU-1",
  title: "Электродвигатель АИР 5 кВт",
  unit: "шт",
  category_id: 2,
  group_path: [
    { code: "g1", name: "Электрика" },
    { code: "g2", name: "Двигатели" },
  ],
  weight_kg: 5,
  volume_m3: 0.1,
  vat_code: "НДС20",
  tnved_code: "8501",
  effective_tnved: { code: "8501", source: "own", group_code: null, group_name: null },
  tnved_rates: {
    code: "8501",
    name: "Двигатели электрические",
    duty_rate: 5,
    vat_code: "НДС20",
    vat_rate: 20,
    excise: null,
    unit: null,
    as_of: "2026-01-01",
  },
  effective_unit: { value: "шт", source: "own", group_code: null, group_name: null },
  effective_country: { value: "Беларусь", source: "own", group_code: null, group_name: null },
  group_vat: { value: null, source: null, group_code: null, group_name: null, rate: null },
  effective_attrs: {
    Производитель: { value: "АкмеЗавод", source: "own", group_code: null, group_name: null },
  },
  shelf_life_days: 365,
  is_active: true,
  attributes: { Мощность: "5 кВт" },
  provenance: { title: { source: "1c", at: "2026-01-15" } },
  landed_cost: 500,
  sync: { origin: "1c", state: "synced", external_ref: "1c-42", last_synced_at: "2026-01-15T10:00:00" },
  stock: {
    rows: [
      { warehouse: "Основной склад", qty_available: 10, qty_reserved: 2, qty_forecast: 0, price: 500, cost: 400 },
    ],
    total_available: 10,
    total_reserved: 2,
    price: 500,
    cost: 400,
    updated_at: null,
  },
  batches: null,
  history: [],
};

function clone(over: Partial<SkuCard> = {}): SkuCard {
  return { ...card, ...over };
}

const mockedLanded = ref.fetchSkuLandedInputs as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  mockedLanded.mockResolvedValue(landedReady);
});

describe("SpravSkuCard", () => {
  it("рисует шапку: наименование, код, «Активна» и путь группы", () => {
    render(<SpravSkuCard card={card} />);
    expect(
      screen.getByRole("heading", { name: "Электродвигатель АИР 5 кВт" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Активна")).toBeInTheDocument();
    expect(screen.getByText("Электрика")).toBeInTheDocument();
    expect(screen.getByText("Двигатели")).toBeInTheDocument();
    // код-бейдж (mono) в шапке + поле «Код / артикул» → несколько совпадений
    expect(screen.getAllByText("SKU-1").length).toBeGreaterThan(0);
  });

  it("в архиве вместо «Активна» показывает «В архиве»", () => {
    render(<SpravSkuCard card={clone({ is_active: false })} />);
    expect(screen.getByText("В архиве")).toBeInTheDocument();
    expect(screen.queryByText("Активна")).not.toBeInTheDocument();
  });

  it("KPI-полоса: остаток с ед., landed cost в BYN и код ТН ВЭД", () => {
    render(<SpravSkuCard card={card} />);
    // остаток «10 шт» — в KPI-плитке и таблице склада может дублироваться
    const stockTile = screen.getByText("Остаток").closest("div")?.parentElement;
    expect(stockTile).toHaveTextContent("10");
    expect(stockTile).toHaveTextContent("резерв 2");
    // landed cost форматируется в BYN
    expect(screen.getAllByText("500 BYN").length).toBeGreaterThan(0);
    // ТН ВЭД / пошлина
    const tnvedTile = screen.getByText("ТН ВЭД / пошлина").closest("div")?.parentElement;
    expect(tnvedTile).toHaveTextContent("8501");
    expect(tnvedTile).toHaveTextContent("пошлина 5%");
  });

  it("полнота карточки со всеми «горячими» полями = 100%", () => {
    render(<SpravSkuCard card={card} />);
    expect(screen.getByText("Заполненность")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("«нет расчёта» landed cost, когда себестоимость партии отсутствует", () => {
    render(<SpravSkuCard card={clone({ landed_cost: null })} />);
    // KPI + сайдбар «Себестоимость партии» → минимум одно «нет расчёта»/«Нет расчёта»
    expect(screen.getByText("нет расчёта")).toBeInTheDocument();
    expect(screen.getByText("Нет расчёта")).toBeInTheDocument();
  });

  it("«Маржа-вход»: из loading переходит в ready и показывает пошлину и НДС по коду", async () => {
    render(<SpravSkuCard card={card} />);
    expect(await screen.findByText("Пошлина ТН ВЭД")).toBeInTheDocument();
    expect(screen.getByText("5%")).toBeInTheDocument(); // duty_pct
    expect(screen.getByText("20%")).toBeInTheDocument(); // vat_rate
    expect(ref.fetchSkuLandedInputs).toHaveBeenCalledWith("SKU-1");
  });

  it("«Маржа-вход»: висящий промис держит состояние загрузки", () => {
    mockedLanded.mockReturnValue(new Promise(() => {})); // никогда не резолвится
    render(<SpravSkuCard card={card} />);
    expect(screen.getByText("Загрузка входа маржи…")).toBeInTheDocument();
  });

  it("«Маржа-вход»: null от бэка → честная ошибка про доступ/данные, а не пустой блок", async () => {
    mockedLanded.mockResolvedValue(null);
    render(<SpravSkuCard card={card} />);
    expect(await screen.findByText(/Вход маржи недоступен/)).toBeInTheDocument();
  });

  it("«Маржа-вход»: нет кода ТН ВЭД → предупреждение о неполной марже", async () => {
    mockedLanded.mockResolvedValue({
      ...landedReady,
      effective_tnved: { code: null, source: null, group_code: null },
      duty_pct: null,
    });
    render(<SpravSkuCard card={card} />);
    expect(await screen.findByText(/Пошлина не определена/)).toBeInTheDocument();
  });

  it("таб «Характеристики»: рендерит JSONB-хвост параметром и значением", () => {
    render(<SpravSkuCard card={card} />);
    fireEvent.click(screen.getByRole("button", { name: "Характеристики" }));
    expect(screen.getByText("⚙️ Технические характеристики")).toBeInTheDocument();
    expect(screen.getByText("Мощность")).toBeInTheDocument();
    expect(screen.getByText("5 кВт")).toBeInTheDocument();
  });

  it("таб «Склад»: показывает строку остатка и метку истины 1С", () => {
    render(<SpravSkuCard card={card} />);
    fireEvent.click(screen.getByRole("button", { name: "Склад" }));
    expect(screen.getByText("🗄 Размещение и остатки")).toBeInTheDocument();
    // склад назван и в KPI-плитке «Где лежит», и в строке таблицы → несколько совпадений
    expect(screen.getAllByText("Основной склад").length).toBeGreaterThan(0);
    expect(screen.getByText("истина — 1С")).toBeInTheDocument();
  });

  it("таб «Склад» без остатков → честный EmptyState, а не нули", () => {
    render(<SpravSkuCard card={clone({ stock: null })} />);
    fireEvent.click(screen.getByRole("button", { name: "Склад" }));
    expect(screen.getByText("🗄 Размещение, остатки и движение")).toBeInTheDocument();
    expect(screen.getByText(/Остатков по этому товару в 1С нет/)).toBeInTheDocument();
  });

  it("таб «Закупка и партии» без партий → EmptyState (числа не выдумываем)", () => {
    render(<SpravSkuCard card={card} />); // batches: null
    fireEvent.click(screen.getByRole("button", { name: "Закупка и партии" }));
    expect(screen.getByText("🚚 Партии закупки и landed cost")).toBeInTheDocument();
  });

  it("таб «Цены и маржа»: себестоимость/цена в BYN и маржа +20%", () => {
    render(<SpravSkuCard card={card} />);
    fireEvent.click(screen.getByRole("button", { name: "Цены и маржа 🔒" }));
    expect(screen.getByText("Себестоимость (из 1С)")).toBeInTheDocument();
    expect(screen.getByText("400 BYN")).toBeInTheDocument(); // cost
    expect(screen.getAllByText("500 BYN").length).toBeGreaterThan(0); // price / landed
    // маржа = round((500-400)/500*100) = 20 → бейдж «+20%»
    expect(screen.getByText("+20%")).toBeInTheDocument();
  });

  it("таб «Цены и маржа» без цены/себеса → EmptyState вместо выдуманной маржи", () => {
    render(<SpravSkuCard card={clone({ stock: null })} />);
    fireEvent.click(screen.getByRole("button", { name: "Цены и маржа 🔒" }));
    expect(screen.getByText("💵 Цена и маржа")).toBeInTheDocument();
    expect(screen.getByText(/Цена и себестоимость по этому товару из 1С не пришли/)).toBeInTheDocument();
  });

  it("таб «История» без версий → EmptyState SCD2", () => {
    render(<SpravSkuCard card={card} />); // history: []
    fireEvent.click(screen.getByRole("button", { name: "История" }));
    expect(screen.getByText("🕘 История характеристик (SCD2)")).toBeInTheDocument();
  });

  it("таб «История» с версиями: первая версия помечается «первая версия»", () => {
    render(
      <SpravSkuCard
        card={clone({
          history: [
            {
              start_date: "2026-01-01",
              end_date: null,
              title: "Электродвигатель АИР 5 кВт",
              unit: "шт",
              category_id: 2,
              weight_kg: 5,
              volume_m3: 0.1,
              tnved_code: "8501",
              vat_code: "НДС20",
              shelf_life_days: 365,
              attributes: {},
            },
          ],
        })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "История" }));
    expect(screen.getByText("🕘 История характеристик")).toBeInTheDocument();
    expect(screen.getByText("текущая")).toBeInTheDocument();
    expect(screen.getByText("первая версия")).toBeInTheDocument();
  });
});
