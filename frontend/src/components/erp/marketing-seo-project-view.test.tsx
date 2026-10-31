import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("не выдаёт общее число задач за критические при недоступном дашборде", async () => {
    fetchDashboard.mockResolvedValue(null);
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    const tile = screen.getByText("Критические задачи").closest("div")?.parentElement;
    expect(tile).toHaveTextContent("—");
    expect(tile).not.toHaveTextContent("9");
    expect(screen.getByText("Данные о быстрых победах недоступны.")).toBeInTheDocument();
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

  it("показывает подтверждённый пустой список задач без предположений о синхронизации", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    // на дашборде плитки видны
    expect(screen.getByText("Ключей в мониторинге")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /SEO-задачи/ }));

    expect(
      screen.getByText("В проекте пока нет SEO-задач."),
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
    expect(screen.getByText("В работе")).toBeInTheDocument();
    expect(screen.getByText("Новая")).toBeInTheDocument();
    expect(screen.getByText("Техническое SEO")).toBeInTheDocument();
    expect(screen.getByText("Контент")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument();
    expect(screen.getByText("Средний")).toBeInTheDocument();
    // подсказки про пустоту нет
    expect(screen.queryByText(/Задачи не синхронизированы/)).not.toBeInTheDocument();
  });

  it("переводит известные коды SEO, сохраняя неизвестные значения интеграции", async () => {
    fetchDashboard.mockResolvedValue({ ...dashboard, quickWins: [] });
    fetchTasks.mockResolvedValue([
      { ...blankTask(), id: 23, title: "Проверить страницу", type: "on_page", priority: "critical" },
      { ...blankTask(), id: 24, title: "Внешняя задача", type: "custom_type", priority: "custom_priority", status: "custom_status" },
      { ...blankTask(), id: 25, title: "Задача без кодов", type: "", priority: "", status: "" },
    ]);
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    expect(screen.getByText("Критический")).toBeInTheDocument();
    expect(screen.getByText("В последнем снимке нет быстрых побед.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /SEO-задачи/ }));
    expect(await screen.findByText("Оптимизация страниц")).toBeInTheDocument();
    for (const value of ["custom_type", "custom_priority", "custom_status"]) {
      expect(screen.getByText(value)).toBeInTheDocument();
    }
    expect(screen.getAllByText("—")).toHaveLength(3);
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


describe("SEO detail truthful failure states", () => {
  const httpError = (status: number) => Object.assign(new Error("private backend body"), { status });

  it("отличает сбой проекта от подтверждённого 404", async () => {
    fetchProject.mockRejectedValue(httpError(500));
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-проект.");
    expect(screen.queryByText("SEO-проект не найден.")).not.toBeInTheDocument();
    expect(screen.queryByText("private backend body")).not.toBeInTheDocument();
  });

  it("сбой дашборда оставляет проект и неизвестные показатели вместо нулей", async () => {
    fetchDashboard.mockRejectedValue(httpError(500));
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить дашборд проекта.");
    for (const label of ["В ТОП-10", "Критические задачи"]) {
      expect(screen.getByText(label).parentElement).toHaveTextContent("—");
    }
    expect(screen.getByText("Данные о видимости недоступны.")).toBeInTheDocument();
    expect(screen.queryByText("В последнем снимке нет быстрых побед.")).not.toBeInTheDocument();
  });

  it("сбой списка задач не становится подтверждённым пустым списком", async () => {
    fetchTasks.mockRejectedValue(httpError(500));
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    fireEvent.click(screen.getByRole("button", { name: /SEO-задачи/ }));
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-задачи.");
    expect(screen.queryByText(/Задачи не синхронизированы|В проекте пока нет SEO-задач/)).not.toBeInTheDocument();
  });

  it.each([
    ["project", fetchProject], ["dashboard", fetchDashboard], ["tasks", fetchTasks], ["link", fetchDeepLink],
  ])("отказ 403 в %s закрывает карточку целиком", async (_name, fetcher) => {
    fetcher.mockRejectedValue(httpError(403));
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа к SEO-проекту.");
    expect(screen.queryByRole("heading", { name: "microchips.by" })).not.toBeInTheDocument();
    expect(screen.queryByText("Ключей в мониторинге")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Открыть в SEO/ })).not.toBeInTheDocument();
  });

  it("истёкшую сессию не обозначает отсутствующим проектом", async () => {
    fetchTasks.mockRejectedValue(httpError(401));
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Сессия истекла. Войдите в систему.");
    expect(screen.queryByRole("heading", { name: "microchips.by" })).not.toBeInTheDocument();
  });

  it("сбой внешней ссылки не скрывает доступный проект", async () => {
    fetchDeepLink.mockRejectedValue(httpError(500));
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("heading", { name: "microchips.by" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить ссылку SEO.");
  });

  it("восстанавливает дашборд только по явному обновлению, без скрытого повтора", async () => {
    fetchDashboard.mockRejectedValueOnce(httpError(500)).mockResolvedValue(dashboard);
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    expect(fetchDashboard).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(await screen.findByText("12")).toBeInTheDocument();
    for (const fetcher of [fetchProject, fetchDashboard, fetchTasks, fetchDeepLink]) expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("не показывает старую карточку в первый рендер нового projectId", async () => {
    const view = render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    fetchProject.mockReturnValue(new Promise(() => {}));
    view.rerender(<MarketingSeoProjectView projectId="8" />);
    expect(screen.queryByRole("heading", { name: "microchips.by" })).not.toBeInTheDocument();
    expect(screen.getByText("Загрузка проекта…")).toBeInTheDocument();
  });

  it("запоздалый ответ старого проекта не заменяет новый", async () => {
    let completeOld!: (value: SeoProject) => void;
    fetchProject.mockReturnValueOnce(new Promise<SeoProject>((resolve) => { completeOld = resolve; }));
    const view = render(<MarketingSeoProjectView projectId="5" />);
    const next = { ...project, id: 8, name: "Другой учебный проект" };
    fetchProject.mockResolvedValue(next);
    fetchDashboard.mockResolvedValue({ ...dashboard, project: next });
    view.rerender(<MarketingSeoProjectView projectId="8" />);
    await screen.findByRole("heading", { name: next.name });
    await act(async () => completeOld(project));
    expect(screen.getByRole("heading", { name: next.name })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "microchips.by" })).not.toBeInTheDocument();
  });

  it("не принимает ответ другой карточки за запрошенный проект", async () => {
    fetchProject.mockResolvedValue({ ...project, id: 8 });
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-проект.");
    expect(screen.queryByRole("heading", { name: "microchips.by" })).not.toBeInTheDocument();
  });

  it("чужой дашборд не подмешивает показатели в доступный проект", async () => {
    fetchDashboard.mockResolvedValue({ ...dashboard, project: { ...project, id: 8 } });
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить дашборд проекта.");
    expect(screen.getByText("В ТОП-10").parentElement).toHaveTextContent("—");
  });

  it("показывает подтверждённые нулевые показатели дашборда", async () => {
    fetchDashboard.mockResolvedValue({ ...dashboard, top10Count: 0, criticalTasks: 0 });
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: "microchips.by" });
    for (const label of ["В ТОП-10", "Критические задачи"]) expect(screen.getByText(label).parentElement).toHaveTextContent("0");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("неизвестный статус не превращает проект в архивный", async () => {
    fetchProject.mockResolvedValue({ ...project, status: "pending_external" });
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByText("pending_external")).toBeInTheDocument();
    expect(screen.queryByText("Архив")).not.toBeInTheDocument();
  });
});
