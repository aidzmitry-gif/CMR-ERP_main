import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Компонент изолируем: мокаем только сетевой слой logistics-api (все фетчи).
// Чистые хелперы (vehicleFits из logistics-domain, formatNumber из format) и UI-примитивы
// (logistics-ui) НЕ мокаем — пусть считают/рендерят по-настоящему.
vi.mock("@/lib/logistics-api", () => ({
  fetchCarriers: vi.fn().mockResolvedValue([]),
  fetchVehicles: vi.fn().mockResolvedValue([]),
  fetchCargoCapabilities: vi.fn().mockResolvedValue([]),
  fetchEligible: vi.fn().mockResolvedValue([]),
  createCarrier: vi.fn().mockResolvedValue(null),
  seedCarriers: vi.fn().mockResolvedValue([]),
  seedFleet: vi.fn().mockResolvedValue(null),
}));

import { LogisticsFleet } from "@/components/erp/logistics-fleet";
import * as api from "@/lib/logistics-api";
import type { Carrier, Vehicle, CargoCapability, EligibleCarrier } from "@/lib/logistics-api";

const carrier: Carrier = {
  id: 1,
  name: "ООО Быстрый",
  code: "bystry",
  kind: "РБ",
  mode: "авто",
  on_time_pct: 95,
  avg_days: 3,
  shipments_count: 120,
  active: true,
};

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  // разумные дефолты после clearAllMocks (он стирает и реализации)
  mock(api.fetchCarriers).mockResolvedValue([]);
  mock(api.fetchVehicles).mockResolvedValue([]);
  mock(api.fetchCargoCapabilities).mockResolvedValue([]);
  mock(api.fetchEligible).mockResolvedValue([]);
  mock(api.createCarrier).mockResolvedValue(null);
  mock(api.seedCarriers).mockResolvedValue([]);
  mock(api.seedFleet).mockResolvedValue(null);
});

describe("LogisticsFleet", () => {
  it("показывает индикатор загрузки до ответа backend, затем таблицу перевозчиков", async () => {
    mock(api.fetchCarriers).mockResolvedValue([carrier]);
    render(<LogisticsFleet />);

    // до резолва промиса — состояние загрузки (loading=true)
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();

    // после ответа — реальный контент строки перевозчика
    expect(await screen.findByText("ООО Быстрый")).toBeInTheDocument();
    expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument();
  });

  it("пустой ответ показывает EmptyState, кнопка «Заполнить» зовёт seed и подгружает парк", async () => {
    // первый fetch (mount) — пусто → EmptyState; второй (после seed) — уже с перевозчиком
    mock(api.fetchCarriers).mockResolvedValueOnce([]).mockResolvedValue([carrier]);
    render(<LogisticsFleet />);

    expect(await screen.findByText("Перевозчики и парк ещё не заведены.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Заполнить демо-данными/ }));

    await waitFor(() => expect(api.seedCarriers).toHaveBeenCalledTimes(1));
    expect(api.seedFleet).toHaveBeenCalledTimes(1);
    // после засева таблица наполнилась (второй fetchCarriers)
    expect(await screen.findByText("ООО Быстрый")).toBeInTheDocument();
  });

  it("рендерит метрики перевозчика и статус: активный → «активен», выключенный → «выкл»", async () => {
    mock(api.fetchCarriers).mockResolvedValue([
      carrier,
      { ...carrier, id: 2, name: "ООО Медленный", code: "slow", kind: "РФ", mode: "ж/д", active: false },
    ]);
    render(<LogisticsFleet />);

    const row = (await screen.findByText("ООО Быстрый")).closest("tr") as HTMLElement;
    expect(within(row).getByText("РБ · авто")).toBeInTheDocument();
    expect(within(row).getByText("95%")).toBeInTheDocument();
    expect(within(row).getByText("3 дн")).toBeInTheDocument();
    expect(within(row).getByText("120")).toBeInTheDocument();
    expect(within(row).getByText("активен")).toBeInTheDocument();

    const row2 = screen.getByText("ООО Медленный").closest("tr") as HTMLElement;
    expect(within(row2).getByText("выкл")).toBeInTheDocument();
  });

  it("подбор перевозчика шлёт вес и температурный режим в fetchEligible и рендерит результат", async () => {
    mock(api.fetchCarriers).mockResolvedValue([carrier]);
    const eligible: EligibleCarrier[] = [
      { carrier_code: "cool", carrier: "ООО Холодок", vehicle_class: "Реф-фура", capacity_kg: 1500 },
    ];
    mock(api.fetchEligible).mockResolvedValue(eligible);
    render(<LogisticsFleet />);
    await screen.findByText("ООО Быстрый");

    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "800" } });
    fireEvent.click(screen.getByRole("checkbox")); // нужен холод (реф)
    fireEvent.click(screen.getByRole("button", { name: "Подобрать" }));

    await waitFor(() =>
      expect(api.fetchEligible).toHaveBeenCalledWith({ weight_kg: 800, needs_temp: true }),
    );
    // результат: "ООО Холодок · Реф-фура (1 500 кг)" — formatNumber считает по-настоящему
    expect(await screen.findByText(/Реф-фура/)).toBeInTheDocument();
    expect(screen.getByText(/1\s?500 кг/)).toBeInTheDocument();
  });

  it("подбор без подходящих перевозчиков показывает честную пустоту, а не молчит", async () => {
    mock(api.fetchCarriers).mockResolvedValue([carrier]);
    mock(api.fetchEligible).mockResolvedValue([]);
    render(<LogisticsFleet />);
    await screen.findByText("ООО Быстрый");

    fireEvent.click(screen.getByRole("button", { name: "Подобрать" }));

    expect(await screen.findByText("Подходящих перевозчиков не найдено.")).toBeInTheDocument();
  });

  it("клик по строке открывает парк; бейдж «под груз» — только у вмещающего ТС (vehicleFits)", async () => {
    mock(api.fetchCarriers).mockResolvedValue([carrier]);
    // вес по умолчанию 500: Фура (1000) вмещает, Газель (200) — нет
    const vehicles: Vehicle[] = [
      { vehicle_class: "Фура", capacity_kg: 1000, volume_m3: 82, temp_control: false, count: 4 },
      { vehicle_class: "Газель", capacity_kg: 200, volume_m3: 12, temp_control: false, count: 6 },
    ];
    const caps: CargoCapability[] = [
      { category: "Генеральный груз", adr: false, oversize: false, max_weight_kg: 20000, max_dim_cm: 600 },
    ];
    mock(api.fetchVehicles).mockResolvedValue(vehicles);
    mock(api.fetchCargoCapabilities).mockResolvedValue(caps);
    render(<LogisticsFleet />);

    fireEvent.click((await screen.findByText("ООО Быстрый")).closest("tr") as HTMLElement);

    await waitFor(() => expect(api.fetchVehicles).toHaveBeenCalledWith("bystry"));
    expect(await screen.findByText("Парк и допуски · bystry")).toBeInTheDocument();
    expect(screen.getByText(/Фура/)).toBeInTheDocument();
    expect(screen.getByText(/Газель/)).toBeInTheDocument();
    expect(screen.getByText("Генеральный груз")).toBeInTheDocument();
    // ровно один «под груз» — вмещает только Фура (Газель 200 < 500)
    expect(screen.getAllByText("под груз")).toHaveLength(1);
  });

  it("добавление перевозчика без названия блокируется валидацией, createCarrier не зовётся", async () => {
    mock(api.fetchCarriers).mockResolvedValue([carrier]);
    render(<LogisticsFleet />);
    await screen.findByText("ООО Быстрый");

    fireEvent.click(screen.getByRole("button", { name: "+ Добавить" }));
    // кнопка «Добавить» внутри формы (не тулбар-«+ Добавить»)
    fireEvent.click(screen.getByRole("button", { name: /^Добавить$/ }));

    expect(await screen.findByText("Название обязательно.")).toBeInTheDocument();
    expect(api.createCarrier).not.toHaveBeenCalled();
  });

  it("успешное добавление перевозчика отправляет форму в createCarrier и перезагружает список", async () => {
    const created: Carrier = { ...carrier, id: 9, name: "ООО Новый", code: "novy" };
    mock(api.fetchCarriers).mockResolvedValueOnce([carrier]).mockResolvedValue([carrier, created]);
    mock(api.createCarrier).mockResolvedValue(created);
    render(<LogisticsFleet />);
    await screen.findByText("ООО Быстрый");

    fireEvent.click(screen.getByRole("button", { name: "+ Добавить" }));
    fireEvent.change(screen.getByPlaceholderText("напр. ООО «Перевозкин»"), {
      target: { value: "ООО Новый" },
    });
    fireEvent.change(screen.getByPlaceholderText("напр. perevozkin"), { target: { value: "novy" } });
    fireEvent.click(screen.getByRole("button", { name: /^Добавить$/ }));

    await waitFor(() =>
      expect(api.createCarrier).toHaveBeenCalledWith(
        expect.objectContaining({ name: "ООО Новый", code: "novy", kind: "РБ", mode: "авто" }),
      ),
    );
    // список перезагрузился (второй fetchCarriers) — новый перевозчик в таблице
    expect(await screen.findByText("ООО Новый")).toBeInTheDocument();
  });
});
