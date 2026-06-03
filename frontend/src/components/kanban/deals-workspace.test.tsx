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
});
