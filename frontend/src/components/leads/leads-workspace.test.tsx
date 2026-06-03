import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom; API модуля — мок (компонент тестируем изолированно)
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({
  createLead: vi.fn(),
  qualifyLead: vi.fn(),
  routeLead: vi.fn(),
  convertLead: vi.fn(),
}));

import { LeadsWorkspace } from "@/components/leads/leads-workspace";
import * as api from "@/lib/api";
import type { Lead } from "@/lib/types";

const lead: Lead = {
  id: 1,
  source: "site",
  name: "Иван",
  company: "ООО Тест",
  region: "Минск",
  product: "лист",
  message: "Нужен лист 5 мм",
  status: "new",
  score: 0,
  qualification: "",
  reason: "",
  assignedTo: "",
  funnel: "",
};

beforeEach(() => vi.clearAllMocks());

describe("LeadsWorkspace", () => {
  it("рендерит инбокс лидов и счётчик новых", () => {
    render(<LeadsWorkspace initialLeads={[lead]} />);
    expect(screen.getByText("Приём лидов")).toBeInTheDocument();
    expect(screen.getByText(/Новых: 1 из 1/)).toBeInTheDocument();
    expect(screen.getAllByText("ООО Тест").length).toBeGreaterThan(0);
  });

  it("квалификация обновляет балл, вердикт и показывает AI-обоснование", async () => {
    (api.qualifyLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "qualified",
      score: 85,
      qualification: "target",
      reason: "есть телефон, указан продукт",
      ai_rationale: "AI-обоснование квалификации",
      model: "qwen",
    });
    render(<LeadsWorkspace initialLeads={[lead]} />);

    // первый лид выбран по умолчанию → действие доступно в правой панели
    fireEvent.click(screen.getByRole("button", { name: "Квалифицировать" }));

    await waitFor(() => expect(api.qualifyLead).toHaveBeenCalledWith(1));
    expect(await screen.findByText("AI-обоснование квалификации")).toBeInTheDocument();
    expect(screen.getAllByText(/85 · целевой/).length).toBeGreaterThan(0);
  });

  it("распределение показывает назначенного менеджера и воронку", async () => {
    (api.routeLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 1,
      status: "routed",
      assigned_to: "Иванов И.И.",
      funnel: "new",
    });
    render(<LeadsWorkspace initialLeads={[{ ...lead, status: "qualified", score: 70, qualification: "target" }]} />);

    fireEvent.click(screen.getByRole("button", { name: "Распределить" }));

    await waitFor(() => expect(api.routeLead).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/Иванов И\.И\./)).toBeInTheDocument();
    expect(screen.getByText(/Новые клиенты/)).toBeInTheDocument();
  });

  it("кнопка «Принять лид» открывает форму приёма", () => {
    render(<LeadsWorkspace initialLeads={[]} />);
    expect(screen.getByText(/Лидов пока нет/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Принять лид/ }));
    const dialog = screen.getByText("Принять лид", { selector: "h3" }).closest("form");
    expect(dialog).not.toBeNull();
    expect(within(dialog as HTMLElement).getByPlaceholderText("ООО ...")).toBeInTheDocument();
  });
});
