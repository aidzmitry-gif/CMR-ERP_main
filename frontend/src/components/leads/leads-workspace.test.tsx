import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom; API модуля — мок (компонент тестируем изолированно)
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
// next/navigation.useRouter — нужен для router.push в двойном клике по лиду (drawer-pattern).
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({
  createLead: vi.fn(),
  qualifyLead: vi.fn(),
  routeLead: vi.fn(),
  convertLead: vi.fn(),
  // call-popup использует createDealTask для постановки задачи из звонка
  createDealTask: vi.fn().mockResolvedValue(true),
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

  it("конвертация распределённого лида показывает ссылку на сделку", async () => {
    (api.convertLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      lead_id: 1,
      deal_id: 42,
      number: "CRM-LEAD-1",
      status: "converted",
    });
    render(
      <LeadsWorkspace
        initialLeads={[{ ...lead, status: "routed", assignedTo: "Иванов И.И.", funnel: "new" }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "В сделку" }));
    await waitFor(() => expect(api.convertLead).toHaveBeenCalledWith(1));
    const link = await screen.findByRole("link", { name: /Открыть сделку/ });
    expect(link).toHaveAttribute("href", "/crm/deals/42");
  });

  it("приём лида через форму добавляет его в инбокс", async () => {
    (api.createLead as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...lead,
      id: 99,
      company: "ООО Новый Лид",
    });
    render(<LeadsWorkspace initialLeads={[]} />);
    fireEvent.click(screen.getByRole("button", { name: /Принять лид/ }));
    const form = screen.getByText("Принять лид", { selector: "h3" }).closest("form") as HTMLElement;
    fireEvent.change(within(form).getByPlaceholderText("ООО ..."), {
      target: { value: "ООО Новый Лид" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Принять" }));
    await waitFor(() => expect(api.createLead).toHaveBeenCalled());
    expect((await screen.findAllByText("ООО Новый Лид")).length).toBeGreaterThan(0);
  });

  it("без лидов показывает подсказку выбрать лид", () => {
    render(<LeadsWorkspace initialLeads={[]} />);
    expect(screen.getByText(/Выберите лид/)).toBeInTheDocument();
  });

  it("отображает статусы «В сделке» и «Отклонён»", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          { ...lead, id: 2, status: "converted", dealId: 5 },
          { ...lead, id: 3, status: "rejected" },
        ]}
      />,
    );
    expect(screen.getAllByText("В сделке").length).toBeGreaterThan(0);
    expect(screen.getByText("Отклонён")).toBeInTheDocument();
    // выбран первый (конвертированный) → в панели ссылка на сделку
    expect(screen.getByRole("link", { name: /Открыть сделку/ })).toHaveAttribute("href", "/crm/deals/5");
  });

  it("панель показывает контакты, нецелевой вердикт, распределение и AI-обоснование", () => {
    render(
      <LeadsWorkspace
        initialLeads={[
          {
            ...lead,
            id: 4,
            name: "Пётр",
            company: "ООО Полный",
            phone: "+375290000000",
            email: "p@x.by",
            status: "routed",
            score: 30,
            qualification: "non-target",
            reason: "мало данных",
            assignedTo: "Сидоров С.С.",
            funnel: "regular",
            aiRationale: "AI-пояснение по лиду",
          },
        ]}
      />,
    );
    expect(screen.getByText("+375290000000")).toBeInTheDocument();
    expect(screen.getByText("p@x.by")).toBeInTheDocument();
    expect(screen.getAllByText(/нецелевой/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Сидоров С\.С\./)).toBeInTheDocument();
    expect(screen.getByText("AI-пояснение по лиду")).toBeInTheDocument();
    expect(screen.getByText(/Постоянные/)).toBeInTheDocument(); // воронка regular
  });
});
