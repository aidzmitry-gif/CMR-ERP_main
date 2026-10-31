import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom (проверяем href навигации, а не роутер Next).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Мокаем ТОЛЬКО сетевые фетчи модуля; EMPTY_SUMMARY/типы/нормализаторы — настоящие
// (компонент импортирует EMPTY_SUMMARY отсюда же, поэтому importOriginal обязателен).
vi.mock("@/lib/marketing-seo", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/marketing-seo")>();
  return { ...actual, fetchSeoDashboard: vi.fn(), fetchSeoAttention: vi.fn() };
});

import { MarketingSeoView } from "@/components/erp/marketing-seo-view";
import * as seo from "@/lib/marketing-seo";
import type { SeoAttentionItem, SeoProject } from "@/lib/marketing-seo";

function project(over: Partial<SeoProject> = {}): SeoProject {
  return {
    id: 1,
    externalProjectId: "ext-1",
    name: "Каталог АКБ",
    domain: "akb.by",
    region: "Минск",
    keywordCount: 320,
    visibility: 42,
    taskCount: 8,
    lastCheck: null,
    status: "active",
    ...over,
  };
}

const mockedDashboard = seo.fetchSeoDashboard as ReturnType<typeof vi.fn>;
const mockedAttention = seo.fetchSeoAttention as ReturnType<typeof vi.fn>;

/** Значение метрики внутри карточки по её подписи (label и value — в одной карточке). */
function metricCardByLabel(label: string): HTMLElement {
  const labelEl = screen.getByText(label);
  // outer card = родитель flex-строки с иконкой+подписью
  return labelEl.closest("div")!.parentElement as HTMLElement;
}

beforeEach(() => {
  vi.resetAllMocks();
  // Дефолт: один активный проект, без «требует внимания». Тесты переопределяют по нужде.
  mockedDashboard.mockResolvedValue({
    projects: [project()],
    summary: { totalProjects: 1, activeProjects: 1, totalKeywords: 320, totalTasks: 8 },
  });
  mockedAttention.mockResolvedValue([]);
});

describe("MarketingSeoView", () => {
  it("сначала показывает состояние загрузки, затем данные проекта", async () => {
    render(<MarketingSeoView />);
    // до резолва промисов — таблица в состоянии загрузки, метрики-плейсхолдеры «…»
    expect(screen.getByText("Загрузка проектов…")).toBeInTheDocument();
    expect(screen.getAllByText("…").length).toBeGreaterThan(0);

    // после загрузки — строка проекта заменяет плейсхолдер
    expect(await screen.findByText("Каталог АКБ")).toBeInTheDocument();
    expect(screen.queryByText("Загрузка проектов…")).not.toBeInTheDocument();
    expect(mockedDashboard).toHaveBeenCalledTimes(1);
  });

  it("рендерит сводные метрики и таблицу проектов с ссылкой на дашборд проекта", async () => {
    mockedDashboard.mockResolvedValue({
      projects: [
        project({ id: 7, name: "Каталог АКБ", domain: "akb.by", visibility: 42, status: "active" }),
        project({ id: 9, name: "Гео Брест", domain: "", region: "", visibility: 15, status: "paused" }),
      ],
      summary: { totalProjects: 2, activeProjects: 1, totalKeywords: 320, totalTasks: 8 },
    });
    render(<MarketingSeoView />);

    await screen.findByText("Каталог АКБ");
    // сводка: totalProjects/activeProjects рендерятся сырым числом (не через formatNumber)
    expect(within(metricCardByLabel("Всего проектов")).getByText("2")).toBeInTheDocument();
    expect(within(metricCardByLabel("Активных проектов")).getByText("1")).toBeInTheDocument();

    // ссылка на дашборд конкретного проекта
    const link = screen.getByRole("link", { name: "Каталог АКБ" });
    expect(link).toHaveAttribute("href", "/erp/marketing/seo/projects/7");
    // видимость с суффиксом %
    expect(screen.getByText("42%")).toBeInTheDocument();
    // пустой домен/регион показываются прочерком
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // статусы: активен и пауза
    expect(screen.getByText("Активен")).toBeInTheDocument();
    expect(screen.getByText("Пауза")).toBeInTheDocument();
  });

  it("пустой список показывает подсказку подключить SEO-сервис и не даёт ссылок на проекты", async () => {
    mockedDashboard.mockResolvedValue({
      projects: [],
      summary: { totalProjects: 0, activeProjects: 0, totalKeywords: 0, totalTasks: 0 },
    });
    render(<MarketingSeoView />);

    expect(await screen.findByText(/Нет привязанных SEO-проектов/)).toBeInTheDocument();
    // Дашборд уже существует: без проекта показываем действительную причину недоступности.
    expect(screen.queryByRole("link", { name: /Дашборд/ })).not.toBeInTheDocument();
    expect(screen.getByText("Дашборд").closest("div")!.parentElement).toHaveAttribute("title", "Нет проектов");
    // и вообще ни одной ссылки на карточку проекта
    expect(
      screen.queryAllByRole("link").filter((a) => a.getAttribute("href")?.includes("/seo/projects/")),
    ).toHaveLength(0);
  });

  it("сбой загрузки показывает недоступность данных без ложных нулей и пустого списка", async () => {
    mockedDashboard.mockRejectedValue(new Error("backend down"));
    render(<MarketingSeoView />);

    expect(await screen.findByText(/Не удалось загрузить SEO-проекты/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-проекты");
    expect(screen.getByText("Данные проектов недоступны.")).toBeInTheDocument();
    expect(screen.queryByText(/Нет привязанных SEO-проектов/)).not.toBeInTheDocument();
    expect(screen.getByText("Дашборд").closest("div")!.parentElement).toHaveAttribute("title", "Недоступно");
    for (const label of ["Всего проектов", "Активных проектов", "Ключей в мониторинге", "SEO-задач"]) {
      expect(within(metricCardByLabel(label)).getByText("—")).toBeInTheDocument();
      expect(within(metricCardByLabel(label)).queryByText("0")).not.toBeInTheDocument();
    }
  });

  it("поздний успешный ответ не возвращает проекты после более нового отказа", async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof seo.fetchSeoDashboard>>) => void;
    const oldResponse = new Promise<Awaited<ReturnType<typeof seo.fetchSeoDashboard>>>((resolve) => { resolveOld = resolve; });
    mockedDashboard.mockReturnValueOnce(oldResponse).mockRejectedValueOnce(new Error("access denied"));
    render(<StrictMode><MarketingSeoView /></StrictMode>);
    await screen.findByText(/Не удалось загрузить SEO-проекты/);
    expect(mockedDashboard).toHaveBeenCalledTimes(2);
    await act(async () => resolveOld({
      projects: [project()],
      summary: { totalProjects: 1, activeProjects: 1, totalKeywords: 320, totalTasks: 8 },
    }));
    expect(screen.queryByRole("link", { name: "Каталог АКБ" })).not.toBeInTheDocument();
    expect(screen.getByText("Данные проектов недоступны.")).toBeInTheDocument();
    expect(within(metricCardByLabel("Всего проектов")).getByText("—")).toBeInTheDocument();
  });

  it("при обновлении сразу скрывает прежние ссылки и внимание, отказ не превращает их в нули", async () => {
    mockedAttention.mockResolvedValue([{ kind: "task", projectId: 1, projectName: "Каталог АКБ", title: "Проверить", priority: "high", url: "" }]);
    render(<MarketingSeoView />);
    await screen.findByRole("link", { name: "Каталог АКБ" });
    expect(screen.getByText("Требует внимания")).toBeInTheDocument();
    let rejectRefresh!: (error: Error) => void;
    mockedDashboard.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectRefresh = reject; }));
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByText("Требует внимания")).not.toBeInTheDocument();
    expect(within(metricCardByLabel("Всего проектов")).getByText("…")).toBeInTheDocument();
    await act(async () => rejectRefresh(new Error("private access detail")));
    expect(screen.getByText("Данные проектов недоступны.")).toBeInTheDocument();
    expect(screen.queryByText(/Нет привязанных SEO-проектов/)).not.toBeInTheDocument();
    expect(screen.queryByText(/private access detail/)).not.toBeInTheDocument();
    expect(within(metricCardByLabel("Всего проектов")).getByText("—")).toBeInTheDocument();
  });

  it("после ошибки повторная загрузка восстанавливает подтверждённые данные", async () => {
    mockedDashboard.mockRejectedValueOnce(new Error("offline"));
    render(<MarketingSeoView />);
    await screen.findByText(/Не удалось загрузить SEO-проекты/);
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
    expect(await screen.findByRole("link", { name: "Каталог АКБ" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(within(metricCardByLabel("Всего проектов")).getByText("1")).toBeInTheDocument();
  });

  it("секция «Требует внимания» рендерит не более 5 пунктов со ссылкой на проект", async () => {
    const attn: SeoAttentionItem[] = Array.from({ length: 6 }, (_, i) => ({
      kind: "task",
      projectId: 100 + i,
      projectName: `Проект ${i}`,
      title: `Задача ${i}`,
      priority: i === 0 ? "high" : "medium",
      url: "",
    }));
    mockedAttention.mockResolvedValue(attn);
    render(<MarketingSeoView />);

    expect(await screen.findByText("Требует внимания")).toBeInTheDocument();
    // slice(0,5): пятый пункт есть, шестой — нет
    expect(screen.getByText("Проект 4: Задача 4")).toBeInTheDocument();
    expect(screen.queryByText("Проект 5: Задача 5")).not.toBeInTheDocument();

    const link = screen.getByRole("link", { name: "Проект 0: Задача 0" });
    expect(link).toHaveAttribute("href", "/erp/marketing/seo/projects/100");
    expect(screen.getByText("Высокий")).toBeInTheDocument();
  });

  it("не выдумывает перевод неизвестного приоритета задачи", async () => {
    mockedAttention.mockResolvedValue([{ kind: "task", projectId: 1, projectName: "Каталог АКБ", title: "Проверить", priority: "external_review", url: "" }]);
    render(<MarketingSeoView />);
    expect(await screen.findByText("external_review")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Каталог АКБ: Проверить" })).toHaveAttribute("href", "/erp/marketing/seo/projects/1");
  });

  it("без пунктов внимания секция «Требует внимания» не рендерится", async () => {
    mockedAttention.mockResolvedValue([]);
    render(<MarketingSeoView />);
    await screen.findByText("Каталог АКБ");
    expect(screen.queryByText("Требует внимания")).not.toBeInTheDocument();
  });

  it("сбой списка внимания виден отдельно, подтверждённые проекты и метрики остаются доступны", async () => {
    mockedAttention.mockRejectedValue(new Error("private attention detail"));
    render(<MarketingSeoView />);
    expect(await screen.findByRole("link", { name: "Каталог АКБ" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить задачи, требующие внимания");
    expect(screen.queryByText(/Не удалось загрузить SEO-проекты/)).not.toBeInTheDocument();
    expect(screen.queryByText(/private attention detail/)).not.toBeInTheDocument();
    expect(within(metricCardByLabel("Всего проектов")).getByText("1")).toBeInTheDocument();
  });

  it("обновление после ошибки внимания показывает реальные задачи и убирает предупреждение", async () => {
    mockedAttention.mockRejectedValueOnce(new Error("offline"));
    render(<MarketingSeoView />);
    await screen.findByText(/Не удалось загрузить задачи, требующие внимания/);
    mockedAttention.mockResolvedValueOnce([{ kind: "task", projectId: 1, projectName: "Каталог АКБ", title: "Проверить", priority: "high", url: "" }]);
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
    expect(await screen.findByRole("link", { name: "Каталог АКБ: Проверить" })).toHaveAttribute("href", "/erp/marketing/seo/projects/1");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([401, 403])("отказ доступа внимания HTTP %s скрывает весь набор данных, включая успешный projects", async (status) => {
    mockedAttention.mockRejectedValue(Object.assign(new Error("private access detail"), { status }));
    render(<MarketingSeoView />);
    expect(await screen.findByText(/Не удалось загрузить SEO-проекты/)).toBeInTheDocument();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryByText("Требует внимания")).not.toBeInTheDocument();
    expect(screen.queryByText(/private access detail/)).not.toBeInTheDocument();
    expect(within(metricCardByLabel("Всего проектов")).getByText("—")).toBeInTheDocument();
  });

  it("кнопка «Обновить» перезагружает данные (повторный вызов фетчей)", async () => {
    render(<MarketingSeoView />);
    await screen.findByText("Каталог АКБ");
    expect(mockedDashboard).toHaveBeenCalledTimes(1);
    expect(mockedAttention).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    await waitFor(() => expect(mockedDashboard).toHaveBeenCalledTimes(2));
    expect(mockedAttention).toHaveBeenCalledTimes(2);
  });

  it("кнопка «Создать проект» отключена (раздел в разработке)", async () => {
    render(<MarketingSeoView />);
    await screen.findByText("Каталог АКБ");
    expect(screen.getByRole("button", { name: /Создать проект/ })).toBeDisabled();
  });
});
