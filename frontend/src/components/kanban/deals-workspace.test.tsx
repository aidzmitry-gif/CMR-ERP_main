import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
// next/navigation: useRouter — для прокидывания router.push в double-click → /crm/deals/[id];
// replace — hoisted-спай (переключатель «Чья доска» пишет ?owner= через router.replace).
// useSearchParams — фильтры читаются из URL (FiltersMenu в шапке); mockSearchParams per-test.
let mockSearchParams = new URLSearchParams();
const routerReplace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: routerReplace, prefetch: vi.fn() }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/crm/deals",
}));
vi.mock("@/lib/api", () => ({
  createDeal: vi.fn(),
  getKpis: vi.fn().mockResolvedValue([]),
  logActivity: vi.fn().mockResolvedValue(true),
  updateDealStage: vi.fn().mockResolvedValue(true),
  updateDeal: vi.fn().mockResolvedValue(true),
  createDealTask: vi.fn().mockResolvedValue(true),
  fetchChats: vi.fn().mockResolvedValue([]),
  lookupCounterparty: vi.fn().mockResolvedValue(null),
  loseDeal: vi.fn().mockResolvedValue(true),
  fetchLossReasons: vi.fn().mockResolvedValue([]),
  fetchPlans: vi.fn().mockResolvedValue([]),
  fetchLeadManagers: vi.fn().mockResolvedValue([]),
}));
// @dnd-kit не работает в jsdom — мокаем DndContext, чтобы вызвать обработчики drag.
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({
    children,
    onDragStart,
    onDragEnd,
  }: {
    children: React.ReactNode;
    onDragStart: (e: { active: { id: string } }) => void;
    onDragEnd: (e: { active: { id: string }; over: { id: string } | null }) => void;
  }) => (
    <div>
      <button data-testid="dnd-start" onClick={() => onDragStart({ active: { id: "1" } })} />
      <button data-testid="dnd-end" onClick={() => onDragEnd({ active: { id: "1" }, over: { id: "won" } })} />
      <button data-testid="dnd-end-lost" onClick={() => onDragEnd({ active: { id: "1" }, over: { id: "lost" } })} />
      <button data-testid="dnd-end-null" onClick={() => onDragEnd({ active: { id: "1" }, over: null })} />
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

import { DealsWorkspace } from "@/components/kanban/deals-workspace";
import * as api from "@/lib/api";
import type { Stage } from "@/lib/types";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const stages: Stage[] = [
  {
    id: "new",
    title: "Новая заявка",
    color: "#000",
    count: 2,
    sum: 300,
    deals: [
      // без nextStep/todo → маркер «нет шага» + фильтр ?attn=no_step
      { id: "1", number: "CRM-1", company: "ООО Доска", description: "Поставка", amount: 100, priority: "Средний", owner: "И" },
      // шаг в прошлом → чип «Просрочено» + фильтр ?attn=overdue
      { id: "2", number: "CRM-2", company: "ООО Просрочка", description: "Опт", amount: 200, priority: "Средний", owner: "Петров", nextStep: "Позвонить", nextStepAt: "2020-01-01T10:00:00" },
    ],
  },
  { id: "won", title: "Закрыто: Успешно", color: "#000", count: 0, sum: 0, deals: [] },
  { id: "lost", title: "Закрыто: Отказ", color: "#EF4444", count: 0, sum: 0, deals: [] },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockSearchParams = new URLSearchParams();
});

describe("DealsWorkspace (канбан)", () => {
  it("рендерит колонки стадий и карточку сделки", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    expect(screen.getByText("Новая заявка")).toBeInTheDocument();
    expect(screen.getByText("Закрыто: Успешно")).toBeInTheDocument();
    expect(screen.getByText("ООО Доска")).toBeInTheDocument();
  });

  it("поиск фильтрует карточки по контрагенту", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.change(screen.getByPlaceholderText("Поиск сделок..."), {
      target: { value: "несуществующий" },
    });
    expect(screen.queryByText("ООО Доска")).toBeNull();
  });

  it("кнопка «Создать сделку» открывает модалку", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /Создать сделку/ }));
    expect(screen.getByText("Новая сделка")).toBeInTheDocument();
  });

  it("переключение в режим списка показывает таблицу сделок", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTitle("Список"));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("CRM-1")).toBeInTheDocument();
  });

  it("фильтр по приоритету (?priority= из шапки FiltersMenu) скрывает несоответствующие сделки", () => {
    mockSearchParams = new URLSearchParams({ priority: "Высокий" });
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    expect(screen.queryByText("ООО Доска")).toBeNull(); // сделка «Средний» отфильтрована
  });

  it("отметка KPI вызывает logActivity и перечитывает показатели", async () => {
    // id должен совпадать с одним из PRIMARY_CELLS — иначе KPI уходит во вторичный
    // ряд «Ещё N» (скрыт по умолчанию) и кнопка «Отметить» не видна без раскрытия.
    const kpis = [
      { id: "calls_all", label: "Звонки", value: 1, target: 40, percent: 3, icon: "phone" as const, tone: "blue" as const },
    ];
    mock(api.getKpis).mockResolvedValue(kpis);
    render(<DealsWorkspace initialStages={stages} initialKpis={kpis} />);
    fireEvent.click(screen.getByTitle("Отметить (+1)"));
    await waitFor(() => expect(api.logActivity).toHaveBeenCalledWith("calls_all"));
    expect(api.getKpis).toHaveBeenCalled();
  });

  it("смена периода (выпадающий список) перечитывает KPI", async () => {
    mock(api.getKpis).mockResolvedValue([]);
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Период" }), {
      target: { value: "month" },
    });
    await waitFor(() => expect(api.getKpis).toHaveBeenCalledWith("month"));
  });

  it("drag&drop переносит сделку и сохраняет стадию", async () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTestId("dnd-start")); // handleDragStart → activeDeal
    fireEvent.click(screen.getByTestId("dnd-end")); // handleDragEnd → перенос + сохранение
    await waitFor(() => expect(api.updateDealStage).toHaveBeenCalledWith("1", "won"));
  });

  it("drag без цели не сохраняет стадию", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTestId("dnd-end-null")); // over=null → ранний выход
    expect(api.updateDealStage).not.toHaveBeenCalled();
  });

  // --- Сделки 2.0 ---

  it("тулбар содержит фильтр «Висяки» (SALES-43)", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    expect(screen.getByRole("button", { name: /Висяки/ })).toBeInTheDocument();
  });

  it("шапка рабочей колонки показывает взвешенную сумму (SALES-44)", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    // сделка amount=100 в стадии new (дефолт 10%) → взвешенно 10 ₽
    expect(screen.getByText(/взвешенно:/)).toBeInTheDocument();
  });

  it("перетаскивание в «отказ» открывает модалку причины, не двигая сделку (SALES-40)", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTestId("dnd-end-lost"));
    expect(screen.getByText("Закрыть сделку в отказ")).toBeInTheDocument();
    expect(api.updateDealStage).not.toHaveBeenCalled(); // отказ не сохраняет стадию напрямую
  });

  it("подтверждение отказа закрывает модалку, проставляет причину и зовёт loseDeal (SALES-40)", async () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTestId("dnd-end-lost"));
    fireEvent.change(screen.getByLabelText("Причина отказа"), { target: { value: "price" } });
    fireEvent.click(screen.getByRole("button", { name: "Закрыть в отказ" }));
    await waitFor(() => expect(api.loseDeal).toHaveBeenCalledWith("1", "price", undefined));
    expect(screen.queryByText("Закрыть сделку в отказ")).toBeNull(); // модалка закрылась
    expect(screen.getByText(/Причина: Дорого/)).toBeInTheDocument(); // плашка причины на карточке
  });

  // --- Слайс 3: «Все вместе» (мульти-воронки, П5 ТЗ) ---

  it("«Все вместе»: рендерит секцию на каждую воронку с заголовком и её колонками", () => {
    const tenderStages: Stage[] = [
      {
        id: "tn_announced",
        title: "Объявлен",
        color: "#3B82F6",
        count: 1,
        sum: 500,
        deals: [
          { id: "9", number: "T-1", company: "Госзакупки РБ", description: "Тендер", amount: 500, priority: "Средний", owner: "И" },
        ],
      },
    ];
    render(
      <DealsWorkspace
        initialStages={stages}
        initialKpis={[]}
        combinedStages={[
          { code: "new_clients", title: "Новые клиенты", stages },
          { code: "tenders", title: "Тендеры", stages: tenderStages },
        ]}
      />,
    );
    expect(screen.getByText("Новые клиенты")).toBeInTheDocument();
    expect(screen.getByText("Тендеры")).toBeInTheDocument();
    // колонки обеих воронок на странице разом (не переключение, а стек)
    expect(screen.getByText("Новая заявка")).toBeInTheDocument();
    expect(screen.getByText("Объявлен")).toBeInTheDocument();
    expect(screen.getByText("Госзакупки РБ")).toBeInTheDocument();
    // переключатель вида/группировки виден и в комбинированном режиме (эталон
    // sales-board-mockup.html держит его всегда — «По датам»/«Список» выходят из стопки
    // секций в плоский срез, см. deals-workspace.tsx).
    expect(screen.getByTitle("Список")).toBeInTheDocument();
  });

  it("«Все вместе» + «Список»: сплющивает сделки ВСЕХ секций в таблицу (не только первой)", () => {
    const tenderStages: Stage[] = [
      {
        id: "tn_announced",
        title: "Объявлен",
        color: "#3B82F6",
        count: 1,
        sum: 500,
        deals: [
          { id: "9", number: "T-1", company: "Госзакупки РБ", description: "Тендер", amount: 500, priority: "Средний", owner: "И" },
        ],
      },
    ];
    render(
      <DealsWorkspace
        initialStages={stages}
        initialKpis={[]}
        combinedStages={[
          { code: "new_clients", title: "Новые клиенты", stages },
          { code: "tenders", title: "Тендеры", stages: tenderStages },
        ]}
      />,
    );
    fireEvent.click(screen.getByTitle("Список"));
    // сделка из ПЕРВОЙ секции (stages, тоже переданной как initialStages)
    expect(screen.getByText("ООО Доска")).toBeInTheDocument();
    // сделка из ВТОРОЙ секции (tenderStages) — раньше flatDeals читал только initialStages
    // и терял сделки остальных воронок «Все вместе»
    expect(screen.getByText("Госзакупки РБ")).toBeInTheDocument();
  });

  // --- П4 (слайс 4): группировка «По датам действий» ---

  it("группа «По датам действий» показывает сделку в бакете «Без даты» (нет next_step_at)", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTitle("По датам действий"));
    expect(screen.getByText("Без даты")).toBeInTheDocument();
    // «Просрочено» встречается и как заголовок бакета, и как чип на карточке CRM-2
    expect(screen.getAllByText("Просрочено").length).toBeGreaterThan(0);
    expect(screen.getByText("ООО Доска")).toBeInTheDocument(); // карточка всё ещё видна
    // Стадийные колонки скрыты в режиме дат.
    expect(screen.queryByText("Новая заявка")).toBeNull();
  });

  it("переключатель группировки скрыт в режиме списка", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTitle("Список"));
    expect(screen.queryByTitle("По датам действий")).toBeNull();
  });

  it("возврат к «По стадиям» восстанавливает канбан-колонки", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByTitle("По датам действий"));
    fireEvent.click(screen.getByTitle("По стадиям"));
    expect(screen.getByText("Новая заявка")).toBeInTheDocument();
    expect(screen.queryByText("Без даты")).toBeNull();
  });

  it("чип «На сегодня» фильтрует по дате действия; повторный клик снимает фильтр", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    // у сделки нет next_step_at → бакет «Без даты» → «На сегодня» её скрывает
    fireEvent.click(screen.getByRole("button", { name: /На сегодня/ }));
    expect(screen.queryByText("ООО Доска")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /На сегодня/ })); // повторный клик — снять
    expect(screen.getByText("ООО Доска")).toBeInTheDocument();
  });

  it("фильтры действуют и в «Все вместе»: поиск скрывает карточки секций", () => {
    render(
      <DealsWorkspace
        initialStages={stages}
        initialKpis={[]}
        combinedStages={[{ code: "new_clients", title: "Новые клиенты", stages }]}
      />,
    );
    expect(screen.getByText("ООО Доска")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Поиск сделок..."), {
      target: { value: "несуществующий" },
    });
    expect(screen.queryByText("ООО Доска")).toBeNull();
  });

  // --- Слайс 2: фильтры «Ответственный»/«Внимание», чипы срочности, кап карточек ---

  it("?owner= фильтрует по ответственному", () => {
    mockSearchParams = new URLSearchParams({ owner: "Петров" });
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    expect(screen.queryByText("ООО Доска")).toBeNull();
    expect(screen.getByText("ООО Просрочка")).toBeInTheDocument();
  });

  it("?attn=no_step оставляет только сделки без следующего шага", () => {
    mockSearchParams = new URLSearchParams({ attn: "no_step" });
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    expect(screen.getByText("ООО Доска")).toBeInTheDocument();
    expect(screen.queryByText("ООО Просрочка")).toBeNull();
  });

  it("?attn=overdue оставляет только просроченные (считается после тика now)", async () => {
    mockSearchParams = new URLSearchParams({ attn: "overdue" });
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    await waitFor(() => expect(screen.getByText("ООО Просрочка")).toBeInTheDocument());
    expect(screen.queryByText("ООО Доска")).toBeNull();
  });

  it("сделка с шагом в прошлом получает чип «Просрочено», без шага — маркер «нет шага»", async () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    expect(screen.getByText("нет шага")).toBeInTheDocument(); // CRM-1 — не зависит от now
    await waitFor(() => expect(screen.getByText("Просрочено")).toBeInTheDocument()); // CRM-2
  });

  it("колонка рендерит максимум 50 карточек; «Показать ещё» раскрывает остальные", () => {
    const many: Stage[] = [
      {
        id: "new",
        title: "Новая заявка",
        color: "#000",
        count: 60,
        sum: 60,
        deals: Array.from({ length: 60 }, (_, i) => ({
          id: `d${i}`,
          number: `CRM-${i}`,
          company: `Компания ${i}`,
          description: "",
          amount: 1,
          priority: "Средний" as const,
          owner: "И",
        })),
      },
    ];
    render(<DealsWorkspace initialStages={many} initialKpis={[]} />);
    expect(screen.getAllByTestId(/^deal-card-/)).toHaveLength(50);
    fireEvent.click(screen.getByRole("button", { name: "Показать ещё 10 (из 60)" }));
    expect(screen.getAllByTestId(/^deal-card-/)).toHaveLength(60);
    expect(screen.queryByRole("button", { name: /Показать ещё/ })).toBeNull();
  });

  it("demoData показывает плашку «демо-данные»; без него плашки нет", () => {
    const { unmount } = render(
      <DealsWorkspace initialStages={stages} initialKpis={[]} demoData />,
    );
    expect(screen.getByText(/Демо-данные: backend недоступен/)).toBeInTheDocument();
    unmount();
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    expect(screen.queryByText(/Демо-данные: backend недоступен/)).toBeNull();
  });

  // --- Слайс 3 + FIX-2 ---

  const condStage: Stage = {
    id: "cond_lost",
    title: "Условный отказ",
    color: "#F97316",
    count: 1,
    sum: 100,
    deals: [
      { id: "c1", number: "CRM-9", company: "ООО Спячка", description: "", amount: 100, priority: "Средний", owner: "И", stageChangedAt: "2020-01-01T00:00:00" },
    ],
  };

  it("FIX-2: cond_lost не «висяк» ни на доске, ни в списке, ни в «Все вместе» — но с чипом «реанимировать»", async () => {
    const { unmount } = render(<DealsWorkspace initialStages={[condStage]} initialKpis={[]} />);
    // now тикает после маунта: появляется «реанимировать · N дн», а «застряло»/«висяк» — нет
    await waitFor(() =>
      expect(screen.getByText(/реанимировать · \d+ дн/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/застряло:/)).toBeNull();
    fireEvent.click(screen.getByTitle("Список"));
    expect(screen.getByText(/· \d+ дн/)).toBeInTheDocument(); // дни в списке есть
    expect(screen.queryByText(/дн · висяк/)).toBeNull(); // пометки «висяк» нет
    unmount();
    // «Все вместе»: combinedCardExtras считает так же, как cardExtras (единый isStuck)
    render(
      <DealsWorkspace
        initialStages={[condStage]}
        initialKpis={[]}
        combinedStages={[{ code: "new_clients", title: "Новые клиенты", stages: [condStage] }]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText(/реанимировать · \d+ дн/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/застряло:/)).toBeNull();
  });

  it("?attn=revive оставляет только условные отказы старше порога", async () => {
    mockSearchParams = new URLSearchParams({ attn: "revive" });
    render(<DealsWorkspace initialStages={[...stages, condStage]} initialKpis={[]} />);
    await waitFor(() => expect(screen.getByText("ООО Спячка")).toBeInTheDocument());
    expect(screen.queryByText("ООО Доска")).toBeNull();
    expect(screen.queryByText("ООО Просрочка")).toBeNull();
  });

  it("переключатель «Чья доска» ставит ?owner= через router.replace (та же ручка, что FiltersMenu)", async () => {
    mock(api.fetchLeadManagers).mockResolvedValue([
      { name: "Петров П.П.", regions: [], products: [], load: 1 },
    ]);
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Петров П.П." }));
    expect(routerReplace).toHaveBeenCalledWith(
      `/crm/deals?${new URLSearchParams({ owner: "Петров П.П." }).toString()}`,
    );
    // «👥 Все» сбрасывает параметр
    fireEvent.click(screen.getByRole("button", { name: "👥 Все" }));
    expect(routerReplace).toHaveBeenLastCalledWith("/crm/deals?");
  });
});
