import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingSeoProjectView } from "./marketing-seo-project-view";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

// The actual fetch adapters and component compose here; only HTTP transport is replaced.
const project = {
  id: 5, external_project_id: "training-5", name: "Учебный SEO-проект", domain: "training.example",
  region: "Минск", keywordCount: 100, visibility: 20, taskCount: 3, lastCheck: null, status: "active",
};
let bodies: Record<string, unknown>;

beforeEach(() => {
  bodies = {
    "/api/marketing/seo/projects/5": { ...project },
    "/api/marketing/seo/projects/5/dashboard": {
      project: { ...project }, visibilityHistory: [], priorityTasks: [], quickWins: [], top10Count: 0, criticalTasks: 0,
    },
    "/api/marketing/seo/projects/5/tasks": [],
    "/api/marketing/seo/projects/5/deep-link": { url: "https://seo.training.example/projects/training-5" },
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!(url in bodies)) throw new Error("Unexpected test request");
    return { ok: true, status: 200, json: async () => bodies[url] };
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("SEO actual adapter/component contract", () => {
  it("недостающий счётчик проекта не становится подтверждённым нулём", async () => {
    bodies["/api/marketing/seo/projects/5"] = { ...project, keywordCount: undefined };
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-проект.");
    expect(screen.queryByRole("heading", { name: project.name })).not.toBeInTheDocument();
  });

  it("неполный дашборд показывает неизвестные показатели при доступном проекте", async () => {
    bodies["/api/marketing/seo/projects/5/dashboard"] = { project, visibilityHistory: [], priorityTasks: [], quickWins: [] };
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: project.name });
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить дашборд проекта.");
    for (const label of ["В ТОП-10", "Критические задачи"]) expect(screen.getByText(label).parentElement).toHaveTextContent("—");
  });

  it("повреждённая задача не отображается как новая задача среднего приоритета", async () => {
    bodies["/api/marketing/seo/projects/5/tasks"] = [{ id: 1, title: "Неизвестная задача" }];
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: project.name });
    fireEvent.click(screen.getByRole("button", { name: "SEO-задачи" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-задачи.");
    expect(screen.queryByText("Неизвестная задача")).not.toBeInTheDocument();
    expect(screen.queryByText("В проекте пока нет SEO-задач.")).not.toBeInTheDocument();
  });

  it("сохраняет настоящие нули из полного native дашборда", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: project.name });
    for (const label of ["В ТОП-10", "Критические задачи"]) expect(screen.getByText(label).parentElement).toHaveTextContent("0");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("подтверждённый пустой массив задач остаётся пустым списком", async () => {
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: project.name });
    fireEvent.click(screen.getByRole("button", { name: "SEO-задачи" }));
    expect(screen.getByText("В проекте пока нет SEO-задач.")).toBeInTheDocument();
  });

  it("не раскрывает содержимое ответа другой карточки", async () => {
    bodies["/api/marketing/seo/projects/5"] = { ...project, id: 9, name: "Чужой учебный проект" };
    render(<MarketingSeoProjectView projectId="5" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-проект.");
    expect(screen.queryByText("Чужой учебный проект")).not.toBeInTheDocument();
  });

  it("повреждённая история видимости не превращается в нулевой график", async () => {
    bodies["/api/marketing/seo/projects/5/dashboard"] = {
      project, visibilityHistory: [{ date: "2026-10-31" }], priorityTasks: [], quickWins: [], top10Count: 0, criticalTasks: 0,
    };
    render(<MarketingSeoProjectView projectId="5" />);
    await screen.findByRole("heading", { name: project.name });
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить дашборд проекта.");
    expect(screen.getByText("Данные о видимости недоступны.")).toBeInTheDocument();
  });
});
