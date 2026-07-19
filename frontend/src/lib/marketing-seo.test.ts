import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_SUMMARY,
  fetchSeoAttention,
  fetchSeoDashboard,
  fetchSeoDeepLink,
  fetchSeoProject,
  fetchSeoProjectDashboard,
  fetchSeoProjects,
  fetchSeoProjectsSummary,
  fetchSeoTasks,
  formatSeoDate,
  normalizeSeoProject,
} from "@/lib/marketing-seo";

afterEach(() => vi.restoreAllMocks());

function mockFetch(impl: (...args: unknown[]) => Promise<unknown>) {
  global.fetch = vi.fn(impl) as unknown as typeof fetch;
}

describe("normalizeSeoProject", () => {
  it("маппит camelCase поля как есть", () => {
    const raw = {
      id: 1,
      externalProjectId: "ext-1",
      name: "Проект А",
      domain: "a.by",
      region: "RU",
      keywordCount: 120,
      visibility: 45.5,
      taskCount: 7,
      lastCheck: "2026-07-10",
      status: "active",
    };
    expect(normalizeSeoProject(raw)).toEqual({
      id: 1,
      externalProjectId: "ext-1",
      name: "Проект А",
      domain: "a.by",
      region: "RU",
      keywordCount: 120,
      visibility: 45.5,
      taskCount: 7,
      lastCheck: "2026-07-10",
      status: "active",
    });
  });

  it("маппит snake_case fallback-поля", () => {
    const raw = {
      id: "2",
      external_project_id: "ext-2",
      name: "Проект Б",
      domain: "b.by",
      region: "BY",
      keyword_count: 30,
      visibility: 10,
      task_count: 3,
      last_check: null,
      status: "paused",
    };
    expect(normalizeSeoProject(raw)).toEqual({
      id: 2,
      externalProjectId: "ext-2",
      name: "Проект Б",
      domain: "b.by",
      region: "BY",
      keywordCount: 30,
      visibility: 10,
      taskCount: 3,
      lastCheck: null,
      status: "paused",
    });
  });

  it("дефолты для пустого объекта", () => {
    expect(normalizeSeoProject({})).toEqual({
      id: NaN,
      externalProjectId: "",
      name: "",
      domain: "",
      region: "",
      keywordCount: 0,
      visibility: 0,
      taskCount: 0,
      lastCheck: null,
      status: "active",
    });
  });
});

describe("formatSeoDate", () => {
  it("форматирует ISO-дату в русский формат", () => {
    expect(formatSeoDate("2026-07-15")).toBe("15 июл. 2026 г.");
  });

  it("null/undefined → прочерк", () => {
    expect(formatSeoDate(null)).toBe("—");
    expect(formatSeoDate(undefined)).toBe("—");
  });

  it("невалидная дата → прочерк", () => {
    expect(formatSeoDate("not-a-date")).toBe("—");
  });
});

describe("fetchSeoProjects", () => {
  it("зовёт правильный URL и маппит список", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => [{ id: 1, name: "П1", keyword_count: 5 }],
    }));
    mockFetch(f);
    const result = await fetchSeoProjects();
    expect(f).toHaveBeenCalledWith("/api/marketing/seo/projects", { cache: "no-store" });
    expect(result).toEqual([
      {
        id: 1,
        externalProjectId: "",
        name: "П1",
        domain: "",
        region: "",
        keywordCount: 5,
        visibility: 0,
        taskCount: 0,
        lastCheck: null,
        status: "active",
      },
    ]);
  });

  it("при HTTP-ошибке бросает исключение", async () => {
    mockFetch(async () => ({ ok: false }));
    await expect(fetchSeoProjects()).rejects.toThrow("fetch projects failed");
  });
});

describe("fetchSeoProjectsSummary", () => {
  it("зовёт правильный URL и маппит summary", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => ({ total_projects: 4, activeProjects: 3, total_keywords: 200, totalTasks: 10 }),
    }));
    mockFetch(f);
    const result = await fetchSeoProjectsSummary();
    expect(f).toHaveBeenCalledWith("/api/marketing/seo/projects/summary", { cache: "no-store" });
    expect(result).toEqual({ totalProjects: 4, activeProjects: 3, totalKeywords: 200, totalTasks: 10 });
  });

  it("при HTTP-ошибке бросает исключение", async () => {
    mockFetch(async () => ({ ok: false }));
    await expect(fetchSeoProjectsSummary()).rejects.toThrow("fetch summary failed");
  });
});

describe("fetchSeoProject", () => {
  it("зовёт URL с id и маппит проект", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ id: 7, name: "Проект-7" }) }));
    mockFetch(f);
    const result = await fetchSeoProject(7);
    expect(f).toHaveBeenCalledWith("/api/marketing/seo/projects/7", { cache: "no-store" });
    expect(result?.id).toBe(7);
    expect(result?.name).toBe("Проект-7");
  });

  it("404 → null", async () => {
    mockFetch(async () => ({ ok: false, status: 404 }));
    expect(await fetchSeoProject(1)).toBeNull();
  });

  it("прочая HTTP-ошибка → исключение", async () => {
    mockFetch(async () => ({ ok: false, status: 500 }));
    await expect(fetchSeoProject(1)).rejects.toThrow("fetch project failed");
  });
});

describe("fetchSeoProjectDashboard", () => {
  it("зовёт URL дашборда и маппит все части (camelCase)", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        project: { id: 1, name: "П1" },
        visibilityHistory: [{ date: "2026-07-01", visibility: 30 }],
        priorityTasks: [{ id: 9, title: "Задача" }],
        quickWins: [{ keyword: "насос", frequency: 100 }],
        top10Count: 5,
        criticalTasks: 2,
      }),
    }));
    mockFetch(f);
    const result = await fetchSeoProjectDashboard(1);
    expect(f).toHaveBeenCalledWith("/api/marketing/seo/projects/1/dashboard", { cache: "no-store" });
    expect(result.project.id).toBe(1);
    expect(result.visibilityHistory).toEqual([{ date: "2026-07-01", visibility: 30 }]);
    expect(result.priorityTasks).toEqual([
      {
        id: 9,
        externalTaskId: "",
        title: "Задача",
        type: "",
        priority: "medium",
        status: "new",
        url: "",
        clusterName: "",
        assignedTo: "",
      },
    ]);
    expect(result.quickWins).toEqual([{ keyword: "насос", frequency: 100 }]);
    expect(result.top10Count).toBe(5);
    expect(result.criticalTasks).toBe(2);
  });

  it("маппит snake_case fallback-поля и пустые массивы по умолчанию", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        top10_count: 3,
        critical_tasks: 1,
      }),
    }));
    mockFetch(f);
    const result = await fetchSeoProjectDashboard("2");
    expect(result.visibilityHistory).toEqual([]);
    expect(result.priorityTasks).toEqual([]);
    expect(result.quickWins).toEqual([]);
    expect(result.top10Count).toBe(3);
    expect(result.criticalTasks).toBe(1);
    expect(result.project.id).toBeNaN();
  });

  it("при HTTP-ошибке бросает исключение", async () => {
    mockFetch(async () => ({ ok: false }));
    await expect(fetchSeoProjectDashboard(1)).rejects.toThrow("fetch dashboard failed");
  });
});

describe("fetchSeoTasks", () => {
  it("зовёт URL задач и маппит список", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => [{ id: 3, title: "Т1", cluster_name: "Кластер" }],
    }));
    mockFetch(f);
    const result = await fetchSeoTasks(4);
    expect(f).toHaveBeenCalledWith("/api/marketing/seo/projects/4/tasks", { cache: "no-store" });
    expect(result[0].clusterName).toBe("Кластер");
  });

  it("при HTTP-ошибке бросает исключение", async () => {
    mockFetch(async () => ({ ok: false }));
    await expect(fetchSeoTasks(1)).rejects.toThrow("fetch tasks failed");
  });
});

describe("fetchSeoDeepLink", () => {
  it("зовёт правильный URL и возвращает url", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ url: "https://ahrefs.com/x" }) }));
    mockFetch(f);
    const result = await fetchSeoDeepLink(5);
    expect(f).toHaveBeenCalledWith("/api/marketing/seo/projects/5/deep-link", { cache: "no-store" });
    expect(result).toBe("https://ahrefs.com/x");
  });

  it("ответ без url → null", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({}) }));
    expect(await fetchSeoDeepLink(1)).toBeNull();
  });

  it("при HTTP-ошибке → null (не бросает)", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSeoDeepLink(1)).toBeNull();
  });
});

describe("fetchSeoAttention", () => {
  it("зовёт правильный URL и маппит элементы", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => [
        { kind: "task", project_id: 1, project_name: "П1", title: "Т", priority: "high", url: "/x" },
      ],
    }));
    mockFetch(f);
    const result = await fetchSeoAttention();
    expect(f).toHaveBeenCalledWith("/api/marketing/seo/attention", { cache: "no-store" });
    expect(result).toEqual([
      { kind: "task", projectId: 1, projectName: "П1", title: "Т", priority: "high", url: "/x" },
    ]);
  });

  it("при HTTP-ошибке → [] (не бросает)", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSeoAttention()).toEqual([]);
  });
});

describe("fetchSeoDashboard", () => {
  it("happy-path: оба запроса успешны, возвращает projects+summary как есть", async () => {
    const f = vi.fn(async (url: unknown) => {
      if (String(url).endsWith("/summary")) {
        return { ok: true, json: async () => ({ totalProjects: 2, activeProjects: 1, totalKeywords: 50, totalTasks: 5 }) };
      }
      return { ok: true, json: async () => [{ id: 1, keyword_count: 10, task_count: 2, status: "active" }] };
    });
    mockFetch(f);
    const result = await fetchSeoDashboard();
    expect(result.summary).toEqual({ totalProjects: 2, activeProjects: 1, totalKeywords: 50, totalTasks: 5 });
    expect(result.projects).toHaveLength(1);
  });

  it("если summary упал — считает сводку локально по projects", async () => {
    const f = vi.fn(async (url: unknown) => {
      if (String(url).endsWith("/summary")) {
        return { ok: false };
      }
      return {
        ok: true,
        json: async () => [
          { id: 1, keyword_count: 10, task_count: 2, status: "active" },
          { id: 2, keyword_count: 5, task_count: 1, status: "paused" },
        ],
      };
    });
    mockFetch(f);
    const result = await fetchSeoDashboard();
    expect(result.summary).toEqual({
      totalProjects: 2,
      activeProjects: 1,
      totalKeywords: 15,
      totalTasks: 3,
    });
    expect(result.projects).toHaveLength(2);
  });
});

describe("EMPTY_SUMMARY", () => {
  it("нулевая сводка", () => {
    expect(EMPTY_SUMMARY).toEqual({
      totalProjects: 0,
      activeProjects: 0,
      totalKeywords: 0,
      totalTasks: 0,
    });
  });
});
