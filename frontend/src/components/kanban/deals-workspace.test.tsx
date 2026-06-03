import { fireEvent, render, screen } from "@testing-library/react";
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
import type { Stage } from "@/lib/types";

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
});
