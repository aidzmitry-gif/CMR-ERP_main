import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевой слой логистики; чистую доменную логику (quoteTariff/tariffWeightPrice)
// и форматирование (formatByn) берём из настоящей реализации — их поведение и проверяем
// через рендер калькулятора котировки.
vi.mock("@/lib/logistics-api", () => ({
  fetchZones: vi.fn(),
  fetchTariffs: vi.fn(),
  patchTariff: vi.fn(),
  seedZones: vi.fn(),
  seedTariffs: vi.fn(),
}));

import { LogisticsTariffs } from "@/components/erp/logistics-tariffs";
import * as api from "@/lib/logistics-api";
import type { CarrierTariff, Zone } from "@/lib/logistics-api";

type Mock = ReturnType<typeof vi.fn>;

const ZONES: Zone[] = [
  {
    id: 1,
    code: "minsk",
    name: "Минск и область",
    coverage: "город + пригород",
    cities: ["Минск"],
    sla_days_min: 1,
    sla_days_max: 2,
  },
  {
    id: 2,
    code: "regions",
    name: "Регионы РБ",
    coverage: "областные центры",
    cities: ["Брест", "Гомель"],
    sla_days_min: 2,
    sla_days_max: 4,
  },
];

function tariff(over: Partial<CarrierTariff> = {}): CarrierTariff {
  return {
    carrier_code: "CARGO",
    zone_code: "minsk",
    price_w5: 20,
    price_w10: 30,
    price_w30: 50,
    over30_per_kg: 2,
    pickup_fee: 5,
    cod_pct: 10,
    insurance_pct: 1,
    ...over,
  };
}

// CARGO: вес 8кг → вилка w10 (30) + забор 5 = котировка 35 (дешевле)
// FAST:  вес 8кг → вилка w10 (40) + забор 10 = котировка 50
const TARIFFS: CarrierTariff[] = [
  tariff({ carrier_code: "CARGO" }),
  tariff({
    carrier_code: "FAST",
    price_w5: 25,
    price_w10: 40,
    price_w30: 62, // ≠ котировке 60 (вес 8 + страховка), чтобы не совпадать в своей строке
    over30_per_kg: 3,
    pickup_fee: 10,
    cod_pct: 10,
    insurance_pct: 1,
  }),
];

beforeEach(() => {
  vi.clearAllMocks();
  (api.fetchZones as Mock).mockResolvedValue(ZONES);
  (api.fetchTariffs as Mock).mockResolvedValue(TARIFFS);
  (api.patchTariff as Mock).mockResolvedValue(tariff());
  (api.seedZones as Mock).mockResolvedValue(ZONES);
  (api.seedTariffs as Mock).mockResolvedValue(TARIFFS);
});

describe("LogisticsTariffs", () => {
  it("показывает индикатор загрузки, пока зоны не пришли", () => {
    (api.fetchZones as Mock).mockReturnValue(new Promise(() => {})); // навсегда pending
    render(<LogisticsTariffs />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
  });

  it("без зон показывает пустое состояние с кнопкой засева демо", async () => {
    (api.fetchZones as Mock).mockResolvedValue([]);
    render(<LogisticsTariffs />);
    expect(
      await screen.findByText("Зоны доставки и тарифы ещё не заданы."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Заполнить демо/ })).toBeInTheDocument();
  });

  it("рендерит зоны, тарифы и помечает самую дешёвую котировку пилюлей «дешевле»", async () => {
    render(<LogisticsTariffs />);

    // тарифы грузятся вторым эффектом после выбора зоны — ждём строку перевозчика
    await screen.findByText("CARGO");

    // зоны из справочника (первая выбрана по умолчанию → грузятся её тарифы)
    expect(screen.getByText("Минск и область")).toBeInTheDocument();
    expect(screen.getByText("Регионы РБ")).toBeInTheDocument();
    expect(screen.getByText(/SLA 1–2 дн/)).toBeInTheDocument();
    expect(screen.getByText("FAST")).toBeInTheDocument();

    // котировки при дефолтном весе 8 кг (проверяем в своих строках)
    const cargoRow = screen.getByText("CARGO").closest("tr") as HTMLElement;
    const fastRow = screen.getByText("FAST").closest("tr") as HTMLElement;
    expect(within(cargoRow).getByText("35 BYN")).toBeInTheDocument(); // w10 30 + забор 5
    expect(within(fastRow).getByText("50 BYN")).toBeInTheDocument(); // w10 40 + забор 10

    // пилюля «дешевле» одна и висит в строке CARGO
    expect(screen.getAllByText("дешевле")).toHaveLength(1);
    expect(within(cargoRow).getByText("дешевле")).toBeInTheDocument();
    expect(within(fastRow).queryByText("дешевле")).not.toBeInTheDocument();
  });

  it("клик по другой зоне перезагружает тарифы этой зоны", async () => {
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    // на маунте тарифы грузятся для первой зоны
    expect(api.fetchTariffs).toHaveBeenCalledWith("minsk");

    fireEvent.click(screen.getByText("Регионы РБ"));
    await waitFor(() => expect(api.fetchTariffs).toHaveBeenCalledWith("regions"));
  });

  it("изменение веса пересчитывает котировку по весовой вилке", async () => {
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    // вес 3 кг → вилка w5: CARGO 20 + забор 5 = 25, FAST 25 + забор 10 = 35
    const weightInput = screen.getAllByRole("spinbutton")[0];
    fireEvent.change(weightInput, { target: { value: "3" } });

    const cargoRow = () => screen.getByText("CARGO").closest("tr") as HTMLElement;
    const fastRow = () => screen.getByText("FAST").closest("tr") as HTMLElement;
    await waitFor(() => expect(within(cargoRow()).getByText("25 BYN")).toBeInTheDocument());
    expect(within(fastRow()).getByText("35 BYN")).toBeInTheDocument();
    // самой дешёвой теперь стала CARGO (25) — пилюля «дешевле» в её строке
    expect(within(cargoRow()).getByText("дешевле")).toBeInTheDocument();
  });

  it("ценность груза добавляет страховку к котировке", async () => {
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    // ценность 1000 при insurance_pct 1% = +10: CARGO 35 → 45
    const declaredInput = screen.getAllByRole("spinbutton")[1];
    fireEvent.change(declaredInput, { target: { value: "1000" } });

    const cargoRow = () => screen.getByText("CARGO").closest("tr") as HTMLElement;
    const fastRow = () => screen.getByText("FAST").closest("tr") as HTMLElement;
    await waitFor(() => expect(within(cargoRow()).getByText("45 BYN")).toBeInTheDocument()); // 35 + 10
    expect(within(fastRow()).getByText("60 BYN")).toBeInTheDocument(); // 50 + 10 (≠ price_w30 62)
  });

  it("наложенный платёж наценивает котировку на cod_pct", async () => {
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    // COD 10% от фрахта: CARGO 35 → 38.5
    fireEvent.click(screen.getByRole("checkbox"));
    expect(await screen.findByText("38,5 BYN")).toBeInTheDocument();
  });

  it("inline-правка тарифа вызывает patchTariff с распарсенным патчем и перечитывает тарифы", async () => {
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    const cargoRow = () => screen.getByText("CARGO").closest("tr") as HTMLElement;
    fireEvent.click(within(cargoRow()).getByRole("button", { name: "✏" }));

    // появились числовые поля правки (5 сборов) — меняем цену до 5 кг
    const editInput = within(cargoRow()).getAllByRole("spinbutton")[0];
    fireEvent.change(editInput, { target: { value: "22" } });

    fireEvent.click(within(cargoRow()).getByRole("button", { name: "✓" }));

    await waitFor(() =>
      expect(api.patchTariff).toHaveBeenCalledWith(
        "CARGO",
        "minsk",
        expect.objectContaining({ price_w5: 22 }),
      ),
    );
    // после успешного сохранения тарифы перечитываются заново
    await waitFor(() => expect((api.fetchTariffs as Mock).mock.calls.length).toBeGreaterThan(1));
  });

  it("сбой сохранения тарифа показывает ошибку, а не молчит", async () => {
    (api.patchTariff as Mock).mockResolvedValue(null); // бэкенд отдал ошибку/недоступен
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    const cargoRow = () => screen.getByText("CARGO").closest("tr") as HTMLElement;
    fireEvent.click(within(cargoRow()).getByRole("button", { name: "✏" }));
    fireEvent.click(within(cargoRow()).getByRole("button", { name: "✓" }));

    expect(await screen.findByText("Не удалось сохранить тариф.")).toBeInTheDocument();
    // строка осталась в режиме правки (кнопка отмены на месте)
    expect(within(cargoRow()).getByRole("button", { name: "✕" })).toBeInTheDocument();
  });

  it("отмена правки возвращает форматированные значения без patchTariff", async () => {
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    const cargoRow = () => screen.getByText("CARGO").closest("tr") as HTMLElement;
    fireEvent.click(within(cargoRow()).getByRole("button", { name: "✏" }));
    expect(within(cargoRow()).getAllByRole("spinbutton").length).toBeGreaterThan(0);

    fireEvent.click(within(cargoRow()).getByRole("button", { name: "✕" }));

    // вернулись к чтению: карандаш снова доступен, patchTariff не звался
    expect(within(cargoRow()).getByRole("button", { name: "✏" })).toBeInTheDocument();
    expect(api.patchTariff).not.toHaveBeenCalled();
  });

  it("«Обновить демо» засевает зоны и тарифы", async () => {
    render(<LogisticsTariffs />);
    await screen.findByText("CARGO");

    fireEvent.click(screen.getByRole("button", { name: "Обновить демо" }));

    await waitFor(() => expect(api.seedZones).toHaveBeenCalled());
    expect(api.seedTariffs).toHaveBeenCalled();
  });
});
