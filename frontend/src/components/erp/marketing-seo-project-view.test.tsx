import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom (компонент тестируем изолированно от роутера).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Мокаем ТОЛЬКО сетевые фетчеры модуля; чистые хелперы (formatSeoDate) — настоящие.
vi.mock("@/lib/marketing-seo", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/marketing-seo")>();
  return {
    ...actual,
    fetchSeoProject: vi.fn(),
    fetchSeoProjectDashboard: vi.fn(),
    fetchSeoTasks: vi.fn(),
    fetchSeoDeepLink: vi.fn(),
  };
});

import { MarketingSeoProjectView } from "@/components/erp/marketing-seo-project-view";
import * as seo from "@/lib/marketing-seo";
import type { SeoDashboard, SeoProject, SeoTask } from "@/lib/marketing-seo";

const project: SeoProject = {
  id: 5,
  externalProjectId: "EXT-777",
  name: "microchips.by",
  domain: "microchips.by",
  region: "Минск",
  keywordCount: 128,
  visibility: 63,
  taskCount: 9,
  lastCheck: "2026-07-01T00:00:00",
  status: "active",
};

const dashboard: SeoDashboard = {
  project,
  visibilityHistory: [
    { date: "2026-06-01", visibility: 40 },
    { date: "2026-07-01", visibility: 63 },
  ],
  priorityTasks: [
    { ...blankTask(), id: 11, title: "Переписать title главной", priority: "critical", clusterName: "Главная" },
  ],
  quickWins: [{ keyword: "акб минск", potential: "ТОП-5 близко" }],
  top10Count: 12,
  criticalTasks: 4,
};

function blankTask(): SeoTask {
  return {
    id: 0,
    externalTaskId: "",
    title: "",
    type: "",
    priority: "medium",
    status: "new",
    url: "",
    clusterName: "",
    assignedTo: "",
  };
}

const fetchProject = seo.fetchSeoProject as ReturnType<typeof vi.fn>;
const fetchDashboard = seo.fetchSeoProjectDashboard as ReturnType<typeof vi.fn>;
const fetchTasks = seo.fetchSeoTasks as ReturnType<typeof vi.fn>;
const fetchDeepLink = seo.fetchSeoDeepLink as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  // Разумный дефолт «всё загрузилось»; отдельные тесты переопределяют по надобности.
  fetchProject.mockResolvedValue(project);
  fetchDashboard.mockResolvedValue(dashboard);
  fetchTasks.mockResolvedValue([]);
  fetchDeepLink.mockResolvedValue(null);
});

describe("MarketingSeoProjectView", () => {
  it("держит индикатор загрузки, пока проект не пришёл", () => {
    fetchProject.mockReturnValue(new Promise(() => {})); // никогда не резолвится
    render(<MarketingSeoProjectView projectId="5" />);
    expect(screen.getByText("Загрузка проекта…")).toBeInTheDocument();
    // до загрузки заголовка проекта ещё нет
    expect(screen.queryByRole("heading", { name: "microchips.by" })).not.toBeInTheDocument();
  });

  it("показывает «проект не найден», когда fetchSeoProject вернул null", async () => {
    fetchProject.mockResolvedValue(null);
    render(<MarketingSeoProjectView projectId="404" />);
    expect(await screen.findByText("SEO-проект не найден.")).toBeInTheDocument();
    // дашборд не рендерится — плиток KPI нет
    expect(screen.queryByText("Ключей в мониторинге")).not.toBeInTheDocument();
  });

  it("рендерит шапку и KPI-плитки из проекта и дашборда", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("heading", { name: "microchips.by" })).toBeInTheDocument();
    // видимость — из project.visibility, а НЕ из чего попало
    expect(screen.getByText("63%")).toBeInTheDocument();
    // ключи в мониторинге — formatNumber(project.keywordCount)
    expect(screen.getByText("128")).toBeInTheDocument();
    // ТОП-10 и критические задачи — из дашборда (12 и 4), не из project.taskCount (9)
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    // приоритетная задача из дашборда показана
    expect(screen.getByText("Переписать title главной")).toBeInTheDocument();
  });

  it("критические задачи падают на project.taskCount, когда дашборд не загрузился", async () => {
    fetchDashboard.mockResolvedValue(null);
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    // dashboard=null → criticalTasks берётся из project.taskCount (9)
    const tile = screen.getByText("Критические задачи").closest("div")?.parentElement;
    expect(tile).toHaveTextContent("9");
    // и quick wins показывает пустую подсказку
    expect(screen.getByText("Нет quick wins в последнем снимке.")).toBeInTheDocument();
  });

  it("статус «active» отображается как «Активен»", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByText("Активен")).toBeInTheDocument();
  });

  it("статус «paused» отображается как «Пауза»", async () => {
    fetchProject.mockResolvedValue({ ...project, status: "paused" });
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByText("Пауза")).toBeInTheDocument();
    expect(screen.queryByText("Активен")).not.toBeInTheDocument();
  });

  it("кнопка «Открыть в SEO» появляется при наличии deep-link и ведёт на него", async () => {
    fetchDeepLink.mockResolvedValue("https://seo.example/project/777");
    render(<MarketingSeoProjectView projectId="5" />);
    const link = await screen.findByRole("link", { name: /Открыть в SEO/ });
    expect(link).toHaveAttribute("href", "https://seo.example/project/777");
  });

  it("без deep-link кнопки «Открыть в SEO» нет", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    expect(screen.queryByRole("link", { name: /Открыть в SEO/ })).not.toBeInTheDocument();
  });

  it("переключение на вкладку «SEO-задачи» с пустым списком показывает подсказку про sync", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    // на дашборде плитки видны
    expect(screen.getByText("Ключей в мониторинге")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /SEO-задачи/ }));

    expect(
      screen.getByText(/Задачи не синхронизированы\. Запустите sync в SEO-платформе\./),
    ).toBeInTheDocument();
    // ушли с дашборда — KPI-плиток больше нет
    expect(screen.queryByText("Ключей в мониторинге")).not.toBeInTheDocument();
  });

  it("вкладка «SEO-задачи» с данными рендерит строки таблицы", async () => {
    fetchTasks.mockResolvedValue([
      { ...blankTask(), id: 21, title: "Ускорить LCP", type: "tech", priority: "high", status: "in_progress" },
      { ...blankTask(), id: 22, title: "Закрыть 404", type: "content", priority: "medium", status: "new" },
    ]);
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });

    fireEvent.click(screen.getByRole("button", { name: /SEO-задачи/ }));

    expect(await screen.findByText("Ускорить LCP")).toBeInTheDocument();
    expect(screen.getByText("Закрыть 404")).toBeInTheDocument();
    expect(screen.getByText("in_progress")).toBeInTheDocument();
    // подсказки про пустоту нет
    expect(screen.queryByText(/Задачи не синхронизированы/)).not.toBeInTheDocument();
  });

  it("быстрые победы из дашборда показывают ключ и потенциал", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    expect(screen.getByText("акб минск")).toBeInTheDocument();
    expect(screen.getByText(/ТОП-5 близко/)).toBeInTheDocument();
  });

  it("перезапрашивает данные при смене projectId", async () => {
    const { rerender } = render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    expect(fetchProject).toHaveBeenCalledWith("5");

    fetchProject.mockResolvedValue({ ...project, id: 8, name: "battery.by" });
    rerender(<MarketingSeoProjectView projectId="8" />);

    await waitFor(() => expect(fetchProject).toHaveBeenCalledWith("8"));
    expect(await screen.findByRole("heading", { name: "battery.by" })).toBeInTheDocument();
  });
});
