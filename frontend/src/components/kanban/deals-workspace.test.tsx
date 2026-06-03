import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({
  createDeal: vi.fn(),
  getKpis: vi.fn().mockResolvedValue([]),
  logActivity: vi.fn().mockResolvedValue(true),
  updateDealStage: vi.fn().mockResolvedValue(true),
  fetchChats: vi.fn().mockResolvedValue([]),
  lookupCounterparty: vi.fn().mockResolvedValue(null),
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
    count: 1,
    sum: 100,
    deals: [
      { id: "1", number: "CRM-1", company: "ООО Доска", description: "Поставка", amount: 100, priority: "Средний", owner: "И" },
    ],
  },
  { id: "won", title: "Закрыто: Успешно", color: "#000", count: 0, sum: 0, deals: [] },
];

beforeEach(() => vi.clearAllMocks());

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

  it("фильтр по приоритету скрывает несоответствующие сделки", () => {
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /Фильтры/ }));
    fireEvent.click(screen.getByRole("button", { name: "Высокий" }));
    expect(screen.queryByText("ООО Доска")).toBeNull(); // сделка «Средний» отфильтрована
  });

  it("отметка KPI вызывает logActivity и перечитывает показатели", async () => {
    const kpis = [
      { id: "calls", label: "Звонки", value: 1, target: 40, percent: 3, icon: "phone" as const, tone: "blue" as const },
    ];
    mock(api.getKpis).mockResolvedValue(kpis);
    render(<DealsWorkspace initialStages={stages} initialKpis={kpis} />);
    fireEvent.click(screen.getByTitle("Отметить (+1)"));
    await waitFor(() => expect(api.logActivity).toHaveBeenCalledWith("calls"));
    expect(api.getKpis).toHaveBeenCalled();
  });

  it("смена периода перечитывает KPI", async () => {
    mock(api.getKpis).mockResolvedValue([]);
    render(<DealsWorkspace initialStages={stages} initialKpis={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Месяц" }));
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
});
