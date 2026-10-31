import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingSeoView } from "./marketing-seo-view";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

// Exercise the actual HTTP adapters and view together; only the transport is synthetic.
const root = "/api/marketing/seo/projects";
const attentionUrl = "/api/marketing/seo/attention";
const project = {
  id: 5, external_project_id: "training-5", name: "Учебный SEO-проект", domain: "training.example",
  region: "Минск", keyword_count: 11, visibility: 20, task_count: 3, last_check: null, status: "active",
};
const summary = { total_projects: 7, active_projects: 4, total_keywords: 123, total_tasks: 9 };
let bodies: Record<string, unknown>;
let failures: Record<string, number | "network">;
let calls: string[];

function metric(label: string) {
  return screen.getByText(label).closest("div")!.parentElement as HTMLElement;
}

beforeEach(() => {
  bodies = { [root]: [{ ...project }], [`${root}/summary`]: { ...summary }, [attentionUrl]: [] };
  failures = {};
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
    calls.push(url);
    expect(options).toEqual({ cache: "no-store" });
    if (!(url in bodies)) throw new Error(`Unexpected URL: ${url}`);
    if (failures[url] === "network") throw new Error("private network details");
    const status = typeof failures[url] === "number" ? failures[url] : 200;
    return new Response(JSON.stringify(bodies[url]), { status });
  }));
});

afterEach(() => vi.unstubAllGlobals());

describe("SEO overview native wire contract", () => {
  it.each([
    ["active", "Активен"], ["paused", "Пауза"], ["archived", "Архив"], ["external_pending", "external_pending"],
  ])("показывает статус %s без ложного перевода", async (status, label) => {
    bodies[root] = [{ ...project, status }];
    render(<MarketingSeoView />);
    await screen.findByRole("link", { name: project.name });
    const row = screen.getByRole("row", { name: new RegExp(project.name) });
    expect(within(row).getByText(label)).toBeInTheDocument();
    if (status !== "archived") expect(within(row).queryByText("Архив")).not.toBeInTheDocument();
    expect(calls).toHaveLength(3);
  });

  it.each(["HTTP 500", "network", "malformed"])("сбой сводки %s сохраняет проекты, неизвестные метрики и явное восстановление", async (kind) => {
    if (kind === "malformed") bodies[`${root}/summary`] = {};
    else failures[`${root}/summary`] = kind === "network" ? "network" : 500;
    render(<MarketingSeoView />);
    expect(await screen.findByRole("link", { name: project.name })).toHaveAttribute("href", "/erp/marketing/seo/projects/5");
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить сводку SEO");
    for (const label of ["Всего проектов", "Активных проектов", "Ключей в мониторинге", "SEO-задач"]) {
      expect(within(metric(label)).getByText("—")).toBeInTheDocument();
    }
    expect(screen.queryByText("Данные проектов недоступны.")).not.toBeInTheDocument();
    expect(screen.queryByText(/private network details/)).not.toBeInTheDocument();
    expect(calls).toHaveLength(3);
    delete failures[`${root}/summary`];
    bodies[`${root}/summary`] = { ...summary };
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
    expect(screen.queryByRole("link", { name: project.name })).not.toBeInTheDocument();
    await screen.findByRole("link", { name: project.name });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(within(metric("Всего проектов")).getByText("7")).toBeInTheDocument();
    expect(calls).toHaveLength(6);
    for (const url of [root, `${root}/summary`, attentionUrl]) expect(calls.filter((call) => call === url)).toHaveLength(2);
  });

  it.each([
    [root, 401], [root, 403], [`${root}/summary`, 401], [`${root}/summary`, 403], [attentionUrl, 401], [attentionUrl, 403],
  ] as const)("отказ %s HTTP %s закрывает все данные без повтора", async (url, status) => {
    failures[url] = status;
    if (url === attentionUrl) failures[`${root}/summary`] = 500;
    render(<MarketingSeoView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-проекты");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(within(metric("Всего проектов")).getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/Нет привязанных SEO-проектов/)).not.toBeInTheDocument();
    expect(calls).toHaveLength(3);
  });

  it("ошибка списка проектов не выдаёт успешную сводку за доступный реестр", async () => {
    failures[root] = 500;
    render(<MarketingSeoView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить SEO-проекты");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(within(metric("Всего проектов")).getByText("—")).toBeInTheDocument();
    expect(calls).toHaveLength(3);
  });

  it("подтверждённо пустой реестр и нулевая сводка остаются настоящими нулями", async () => {
    bodies[root] = [];
    bodies[`${root}/summary`] = { total_projects: 0, active_projects: 0, total_keywords: 0, total_tasks: 0 };
    render(<MarketingSeoView />);
    await screen.findByText(/Нет привязанных SEO-проектов/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    for (const label of ["Всего проектов", "Активных проектов", "Ключей в мониторинге", "SEO-задач"]) {
      expect(within(metric(label)).getByText("0")).toBeInTheDocument();
    }
    expect(calls).toHaveLength(3);
  });
});
