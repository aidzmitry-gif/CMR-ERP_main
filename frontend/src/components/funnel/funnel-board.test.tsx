import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FunnelStage } from "@/lib/types";

vi.mock("@/lib/funnel-api", () => ({
  fetchFunnelBoard: vi.fn(),
  createFunnelCard: vi.fn().mockResolvedValue(true),
  moveFunnelCard: vi.fn().mockResolvedValue(true),
}));
// @dnd-kit не работает в jsdom — мокаем DndContext, чтобы вызвать обработчики drag.
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({
    children,
    onDragStart,
    onDragEnd,
  }: {
    children: React.ReactNode;
    onDragStart: (e: { active: { id: number } }) => void;
    onDragEnd: (e: { active: { id: number }; over: { id: string } | null }) => void;
  }) => (
    <div>
      <button data-testid="dnd-start" onClick={() => onDragStart({ active: { id: 1 } })} />
      <button data-testid="dnd-end" onClick={() => onDragEnd({ active: { id: 1 }, over: { id: "qc" } })} />
      <button data-testid="dnd-end-null" onClick={() => onDragEnd({ active: { id: 1 }, over: null })} />
      {children}
    </div>
  ),
  DragOverlay: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PointerSensor: class {},
  useSensor: () => ({}),
  useSensors: () => [],
  useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: () => {}, isDragging: false }),
  useDroppable: () => ({ setNodeRef: () => {}, isOver: false }),
}));

import { FunnelBoard } from "@/components/funnel/funnel-board";
import * as funnelApi from "@/lib/funnel-api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const stages: FunnelStage[] = [
  {
    id: "need",
    title: "Потребность",
    color: "#000",
    count: 1,
    sum: 1000,
    cards: [
      {
        id: 1,
        code: "ЗАК-1",
        title: "AGM аккумулятор",
        subtitle: "Shenzhen SunPower",
        flag: "",
        amount: 1000,
        priority: "Высокий",
        status_tag: "",
        owner: "Иванов И.И.",
        date: "08.06",
        progress: null,
        next_step: "",
        insight: "Спрос +34% за 30 дней",
        tags: ["500 шт"],
      },
    ],
  },
  { id: "qc", title: "Приёмка / QC", color: "#000", count: 0, sum: 0, cards: [] },
];

const props = {
  title: "Закупки",
  boardPath: "/procurement/board",
  createPath: "/procurement/requests",
  patchPath: "/procurement/requests",
  fields: [{ key: "supplier", label: "Поставщик" }],
};

beforeEach(() => {
  vi.clearAllMocks();
  mock(funnelApi.fetchFunnelBoard).mockResolvedValue(stages);
});

describe("FunnelBoard", () => {
  it("загружает и рендерит стадии и карточку", async () => {
    render(<FunnelBoard {...props} />);
    expect(await screen.findByText("AGM аккумулятор")).toBeInTheDocument();
    expect(screen.getByText("Потребность")).toBeInTheDocument();
    expect(screen.getByText("Приёмка / QC")).toBeInTheDocument();
    expect(screen.getByText("Shenzhen SunPower")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument();
    expect(screen.getByText("500 шт")).toBeInTheDocument();
  });

  it("поиск фильтрует карточки", async () => {
    render(<FunnelBoard {...props} />);
    await screen.findByText("AGM аккумулятор");
    fireEvent.change(screen.getByPlaceholderText("Поиск..."), { target: { value: "несуществующий" } });
    expect(screen.queryByText("AGM аккумулятор")).toBeNull();
  });

  it("кнопка «Добавить» открывает форму и создаёт карточку", async () => {
    render(<FunnelBoard {...props} />);
    await screen.findByText("AGM аккумулятор");
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(screen.getByText("Поставщик")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Сохранить/ }));
    await waitFor(() =>
      expect(funnelApi.createFunnelCard).toHaveBeenCalledWith("/procurement/requests", expect.any(Object)),
    );
  });

  it("drag&drop меняет стадию карточки", async () => {
    render(<FunnelBoard {...props} />);
    await screen.findByText("AGM аккумулятор");
    fireEvent.click(screen.getByTestId("dnd-start"));
    fireEvent.click(screen.getByTestId("dnd-end"));
    await waitFor(() =>
      expect(funnelApi.moveFunnelCard).toHaveBeenCalledWith("/procurement/requests", 1, "qc"),
    );
  });

  it("drag без цели не сохраняет", async () => {
    render(<FunnelBoard {...props} />);
    await screen.findByText("AGM аккумулятор");
    fireEvent.click(screen.getByTestId("dnd-end-null"));
    expect(funnelApi.moveFunnelCard).not.toHaveBeenCalled();
  });

  it("итоги по воронке отображаются (с суммами при showSum)", async () => {
    render(<FunnelBoard {...props} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("Итоги по воронке")).toBeInTheDocument();
    expect(screen.getByText("Сумма в работе")).toBeInTheDocument();
  });

  it("showSum=false скрывает денежные итоги", async () => {
    render(<FunnelBoard {...props} showSum={false} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.queryByText("Сумма в работе")).toBeNull();
  });

  it("рендерит верхние KPI-плитки «План/Факт»", async () => {
    const kpis = [
      { label: "Заявки в работе", value: "32", target: "40", note: "80% от плана", percent: 80, tone: "blue" as const },
    ];
    render(<FunnelBoard {...props} kpis={kpis} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("Заявки в работе")).toBeInTheDocument();
    expect(screen.getByText("80% от плана")).toBeInTheDocument();
  });

  it("рендерит правую панель с лентой", async () => {
    const panel = {
      title: "AI-агенты и поставщики",
      items: [{ title: "Orchestrator", text: "план готов", tone: "ai" as const, badge: 3 }],
    };
    render(<FunnelBoard {...props} panel={panel} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("AI-агенты и поставщики")).toBeInTheDocument();
    expect(screen.getByText("Orchestrator")).toBeInTheDocument();
  });

  it("показывает статус-бар и итоги с дельтами из конфига", async () => {
    const summary = [{ label: "Закупок в работе", value: "142", delta: "+9%" }];
    render(<FunnelBoard {...props} statusNote="AI ведёт 18 закупок" summary={summary} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("AI ведёт 18 закупок")).toBeInTheDocument();
    expect(screen.getByText("Закупок в работе")).toBeInTheDocument();
    expect(screen.getByText("+9%")).toBeInTheDocument();
  });

  it("показывает AI-строку карточки, аватар и кастомную кнопку создания", async () => {
    render(<FunnelBoard {...props} createLabel="Создать закупку" />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("Спрос +34% за 30 дней")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Создать закупку/ })).toBeInTheDocument();
    expect(screen.getByText("ИИ")).toBeInTheDocument(); // аватар-инициалы ответственного
  });

  it("карточка с прогрессом показывает % готовности", async () => {
    mock(funnelApi.fetchFunnelBoard).mockResolvedValue([
      {
        id: "assembly",
        title: "В производстве",
        color: "#000",
        count: 1,
        sum: 0,
        cards: [
          {
            id: 2,
            code: "ПЗ-2",
            title: "Инвертор",
            subtitle: "",
            flag: "",
            amount: null,
            priority: "Средний",
            status_tag: "Линия 1",
            owner: "Мастер",
            date: "06.06",
            progress: 55,
            next_step: "Сборка BMS",
            insight: "",
            tags: [],
          },
        ],
      },
    ]);
    render(<FunnelBoard {...props} showSum={false} />);
    expect(await screen.findByText("Инвертор")).toBeInTheDocument();
    expect(screen.getByText("55% готовности")).toBeInTheDocument();
    expect(screen.getByText("Линия 1")).toBeInTheDocument();
    expect(screen.getByText(/Сборка BMS/)).toBeInTheDocument();
  });

  it("клик по карточке открывает drawer с маршрутом этапов", async () => {
    render(<FunnelBoard {...props} />);
    fireEvent.click(await screen.findByText("AGM аккумулятор"));
    expect(screen.getByText("Маршрут / этапы")).toBeInTheDocument();
    expect(screen.getByText(/Детали ·/)).toBeInTheDocument();
  });

  it("drawer показывает BOM и загрузку оборудования (производство)", async () => {
    const extras = {
      bom: [{ name: "BMS 16S", need: 120, stock: 84 }],
      equipment: [{ name: "Тест-стенд", load: 46 }],
    };
    render(<FunnelBoard {...props} detailExtras={extras} />);
    fireEvent.click(await screen.findByText("AGM аккумулятор"));
    expect(screen.getByText("Обеспеченность материалами (BOM)")).toBeInTheDocument();
    expect(screen.getByText("BMS 16S")).toBeInTheDocument();
    expect(screen.getByText("Загрузка оборудования")).toBeInTheDocument();
  });

  it("показывает флаг поставщика на карточке (закупки)", async () => {
    mock(funnelApi.fetchFunnelBoard).mockResolvedValue([
      {
        id: "need",
        title: "Потребность",
        color: "#000",
        count: 1,
        sum: 0,
        cards: [
          {
            id: 9,
            code: "ЗАК-9",
            title: "Панели",
            subtitle: "Shenzhen SunPower",
            flag: "🇨🇳",
            amount: 0,
            priority: "",
            status_tag: "",
            owner: "",
            date: "",
            progress: null,
            next_step: "",
            insight: "",
            tags: [],
          },
        ],
      },
    ]);
    render(<FunnelBoard {...props} showChannels />);
    await screen.findByText("Панели");
    expect(screen.getByText("🇨🇳")).toBeInTheDocument();
  });

  it("показывает конверсию воронки и лидерборд (HR)", async () => {
    const leaderboard = [{ name: "Соколова А.", meta: "5 закрыто", value: "92%" }];
    render(<FunnelBoard {...props} conversion leaderboard={leaderboard} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("Конверсия по воронке")).toBeInTheDocument();
    expect(screen.getByText("Топ рекрутёры")).toBeInTheDocument();
    expect(screen.getByText("Соколова А.")).toBeInTheDocument();
  });

  it("рендерит state-чип, score, кнопку action и key-value details", async () => {
    mock(funnelApi.fetchFunnelBoard).mockResolvedValue([
      {
        id: "qc",
        title: "Контроль",
        color: "#000",
        count: 1,
        sum: 0,
        cards: [
          {
            id: 21,
            code: "ОП-21",
            title: "Партия",
            subtitle: "ООО Поставка",
            flag: "",
            amount: 0,
            priority: "",
            status_tag: "",
            owner: "",
            date: "",
            progress: null,
            next_step: "",
            insight: "",
            score: "Score 8.7",
            state: "В процессе",
            action: "Принять качество",
            details: [
              { k: "План", v: "24 поз." },
              { k: "Принято", v: "22 поз." },
            ],
            tags: [],
          },
        ],
      },
    ]);
    render(<FunnelBoard {...props} />);
    await screen.findByText("Партия");
    expect(screen.getByText("В процессе")).toBeInTheDocument();
    expect(screen.getByText("Score 8.7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Принять качество" })).toBeInTheDocument();
    expect(screen.getByText("План")).toBeInTheDocument();
    expect(screen.getByText("22 поз.")).toBeInTheDocument();
  });

  it("рендерит пилюли Фокус/Приоритет, мини-иконки и табы доски", async () => {
    render(<FunnelBoard {...props} showFocusPills showActions boardTabs={["Все курсы", "Обязательные"]} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("Фокус")).toBeInTheDocument();
    expect(screen.getByText("Приоритет")).toBeInTheDocument();
    expect(screen.getByText("Все курсы")).toBeInTheDocument();
  });

  it("рендерит под-вкладки правой панели", async () => {
    const panel = { title: "AI-агенты", tabs: ["Лента", "Поставщики", "Задачи"], items: [{ title: "X", text: "y" }] };
    render(<FunnelBoard {...props} panel={panel} />);
    await screen.findByText("AGM аккумулятор");
    expect(screen.getByText("Поставщики")).toBeInTheDocument();
    expect(screen.getByText("Задачи")).toBeInTheDocument();
  });

  it("drawer: операции План/Факт и прогноз риска", async () => {
    const extras = {
      operations: [{ name: "Сварка шин", plan: "05.06", fact: "05.06", status: "ok" as const }],
      risk: { percent: 64, notes: ["Дефицит BMS"] },
    };
    render(<FunnelBoard {...props} detailExtras={extras} />);
    fireEvent.click(await screen.findByText("AGM аккумулятор"));
    expect(screen.getByText("План / Факт по операциям")).toBeInTheDocument();
    expect(screen.getByText("Сварка шин")).toBeInTheDocument();
    expect(screen.getByText("Прогноз риска")).toBeInTheDocument();
    expect(screen.getByText("64%")).toBeInTheDocument();
  });
});
