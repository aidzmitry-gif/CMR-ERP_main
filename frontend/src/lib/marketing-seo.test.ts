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


function wireProject(overrides: Record<string, unknown> = {}) {
  return { id: 1, external_project_id: "", name: "Учебный проект", domain: "", region: "",
    keyword_count: 0, visibility: 0, task_count: 0, last_check: null, status: "active", ...overrides };
}
function wireTask(overrides: Record<string, unknown> = {}) {
  return { id: 1, external_task_id: "", title: "Учебная задача", type: "", priority: "medium",
    status: "new", url: "", cluster_name: "", assigned_to: "", ...overrides };
}
function wireDashboard(overrides: Record<string, unknown> = {}) {
  return { project: wireProject(), visibilityHistory: [], priorityTasks: [], quickWins: [],
    top10Count: 0, criticalTasks: 0, ...overrides };
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
      id: 2,
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

  it("отклоняет пустой объект вместо выдуманных нулей и активного статуса", () => {
    expect(() => normalizeSeoProject({})).toThrow("Invalid SEO project response");
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
      json: async () => [wireProject({ id: 1, name: "П1", keyword_count: 5 })],
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
    const f = vi.fn(async () => ({ ok: true, json: async () => (wireProject({ id: 7, name: "Проект-7" })) }));
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
        project: wireProject({ id: 1, name: "П1" }),
        visibilityHistory: [{ date: "2026-07-01", visibility: 30 }],
        priorityTasks: [wireTask({ id: 9, title: "Задача" })],
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

  it("маппит полный native snake_case ответ и подтверждённо пустые массивы", async () => {
    const f = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        project: wireProject({ id: 2 }), visibility_history: [], priority_tasks: [], quick_wins: [],
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
    expect(result.project.id).toBe(2);
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
      json: async () => [wireTask({ id: 3, title: "Т1", cluster_name: "Кластер" })],
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

  it("при HTTP-ошибке не скрывает недоступность ссылки", async () => {
    mockFetch(async () => ({ ok: false }));
    await expect(fetchSeoDeepLink(1)).rejects.toThrow("fetch deep-link failed");
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

  it("не подменяет HTTP 500 подтверждённым отсутствием задач", async () => {
    mockFetch(async () => ({ ok: false, status: 500 }));
    await expect(fetchSeoAttention()).rejects.toThrow("fetch attention failed");
  });

  it.each([401, 403])("отказ HTTP %s не превращается в пустой список и не читает тело", async (status) => {
    const body = vi.fn(async () => ({ detail: "private refusal" }));
    mockFetch(async () => ({ ok: false, status, json: body }));
    await expect(fetchSeoAttention()).rejects.toMatchObject({ message: "fetch attention failed", status });
    expect(body).not.toHaveBeenCalled();
  });

  it("при подтверждённом пустом ответе возвращает пустой список", async () => {
    mockFetch(async () => ({ ok: true, json: async () => [] }));
    expect(await fetchSeoAttention()).toEqual([]);
  });

  it.each([{ response: {} }, { response: [{ project_id: 0, project_name: "П1", title: "Т", priority: "high" }] }])(
    "отклоняет повреждённые данные задач без выдуманной ссылки на проект",
    async ({ response }) => {
      mockFetch(async () => ({ ok: true, json: async () => response }));
      await expect(fetchSeoAttention()).rejects.toThrow("Invalid SEO attention response");
    },
  );
});

describe("fetchSeoDashboard", () => {
  it("happy-path: оба запроса успешны, возвращает projects+summary как есть", async () => {
    const f = vi.fn(async (url: unknown) => {
      if (String(url).endsWith("/summary")) {
        return { ok: true, json: async () => ({ totalProjects: 2, activeProjects: 1, totalKeywords: 50, totalTasks: 5 }) };
      }
      return { ok: true, json: async () => [wireProject({ id: 1, keyword_count: 10, task_count: 2, status: "active" })] };
    });
    mockFetch(f);
    const result = await fetchSeoDashboard();
    expect(result.summary).toEqual({ totalProjects: 2, activeProjects: 1, totalKeywords: 50, totalTasks: 5 });
    expect(result.projects).toHaveLength(1);
  });

  it("при сбое summary не выдаёт локальную сумму за серверную и не повторяет projects", async () => {
    const f = vi.fn(async (url: unknown) => {
      if (String(url).endsWith("/summary")) {
        return { ok: false };
      }
      return {
        ok: true,
        json: async () => [
          wireProject({ id: 1, keyword_count: 10, task_count: 2, status: "active" }),
          wireProject({ id: 2, keyword_count: 5, task_count: 1, status: "paused" }),
        ],
      };
    });
    mockFetch(f);
    await expect(fetchSeoDashboard()).rejects.toThrow("fetch summary failed");
    expect(f).toHaveBeenCalledTimes(2);
  });

  it.each([401, 403])("не повторяет отказ projects HTTP %s и не показывает данные повторного запроса", async (status) => {
    let projectsCalls = 0;
    const f = vi.fn(async (url: unknown) => {
      if (String(url).endsWith("/summary")) return { ok: true, json: async () => ({ totalProjects: 1, activeProjects: 1, totalKeywords: 10, totalTasks: 2 }) };
      projectsCalls++;
      return projectsCalls === 1
        ? { ok: false, status }
        : { ok: true, json: async () => [wireProject({ id: 1, name: "Поздний проект", keyword_count: 10, task_count: 2 })] };
    });
    mockFetch(f);
    await expect(fetchSeoDashboard()).rejects.toThrow("fetch projects failed");
    expect(projectsCalls).toBe(1);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("не превращает отсутствующие счётчики сводки в подтверждённые нули", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({}) }));
    await expect(fetchSeoProjectsSummary()).rejects.toThrow("Invalid SEO summary response");
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


describe("SEO detail HTTP status contract", () => {
  it.each([
    ["project", fetchSeoProject], ["dashboard", fetchSeoProjectDashboard], ["tasks", fetchSeoTasks], ["deep-link", fetchSeoDeepLink],
  ])("сохраняет статус отказа доступа для %s", async (_name, load) => {
    mockFetch(async () => ({ ok: false, status: 403 }));
    await expect(load(5)).rejects.toMatchObject({ status: 403 });
  });

  it.each(["javascript:alert(1)", "/projects/5", "data:text/html,test"])("не принимает %s за адрес внешней SEO-платформы", async (url) => {
    mockFetch(async () => ({ ok: true, json: async () => ({ url }) }));
    await expect(fetchSeoDeepLink(5)).rejects.toThrow("Invalid SEO deep-link response");
  });

  it("не передаёт объект вместо URL в ссылку", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ url: { href: "https://seo.example" } }) }));
    await expect(fetchSeoDeepLink(5)).rejects.toThrow("Invalid SEO deep-link response");
  });
});


describe("SEO native wire validation", () => {
  it.each([
    ["missing keyword count", { keyword_count: undefined }], ["null count", { keyword_count: null }],
    ["numeric text", { keyword_count: "0" }], ["NaN tasks", { task_count: NaN }],
    ["zero id", { id: 0 }], ["unsafe id", { id: Number.MAX_SAFE_INTEGER + 1 }], ["text id", { id: "1" }],
    ["object name", { name: {} }], ["missing status", { status: undefined }], ["null region", { region: null }],
    ["invalid date type", { last_check: 42 }], ["invalid date", { last_check: "not-a-date" }],
    ["infinite visibility", { visibility: Infinity }], ["negative visibility", { visibility: -1 }],
  ])("отклоняет проект: %s", (_name, changes) => {
    expect(() => normalizeSeoProject(wireProject(changes))).toThrow("Invalid SEO project response");
  });

  it("сохраняет настоящие нули, null даты и неизвестный код статуса", () => {
    expect(normalizeSeoProject(wireProject({ status: "external_pending" }))).toMatchObject({
      id: 1, keywordCount: 0, taskCount: 0, visibility: 0, lastCheck: null, status: "external_pending",
    });
  });

  it.each([
    ["missing status", { status: undefined }], ["null priority", { priority: null }],
    ["object title", { title: {} }], ["zero id", { id: 0 }], ["text id", { id: "1" }],
    ["object URL", { url: { href: "https://training.example" } }],
  ])("не выдаёт повреждённую задачу за новую/среднюю: %s", async (_name, changes) => {
    mockFetch(async () => ({ ok: true, json: async () => [wireTask(changes)] }));
    await expect(fetchSeoTasks(1)).rejects.toThrow("Invalid SEO task response");
  });

  it("неизвестные коды задачи остаются значениями интеграции", async () => {
    mockFetch(async () => ({ ok: true, json: async () => [wireTask({ priority: "external_priority", status: "external_status" })] }));
    expect(await fetchSeoTasks(1)).toMatchObject([{ priority: "external_priority", status: "external_status" }]);
  });

  it.each([
    ["missing TOP10", { top10Count: undefined }], ["null critical count", { criticalTasks: null }],
    ["missing history", { visibilityHistory: undefined }],
    ["bad history point", { visibilityHistory: [{ date: "2026-10-31", visibility: null }] }],
    ["bad history date", { visibilityHistory: [{ date: {}, visibility: 5 }] }],
    ["quickwin object as list", { quickWins: {} }],
    ["quickwin object keyword", { quickWins: [{ keyword: {} }] }],
    ["quickwin object potential", { quickWins: [{ potential: {} }] }],
    ["different project", { project: wireProject({ id: 2 }) }],
    ["missing project", { project: undefined }],
    ["malformed priority task", { priorityTasks: [{}] }],
  ])("не превращает повреждённый дашборд в достоверные значения: %s", async (_name, changes) => {
    mockFetch(async () => ({ ok: true, json: async () => wireDashboard(changes) }));
    await expect(fetchSeoProjectDashboard(1)).rejects.toThrow();
  });

  it("сохраняет optional null внутри непрозрачных native quick-wins", async () => {
    mockFetch(async () => ({ ok: true, json: async () => wireDashboard({ quickWins: [{ keyword: null, potential: null, frequency: null }] }) }));
    expect((await fetchSeoProjectDashboard(1)).quickWins).toEqual([{ keyword: null, potential: null, frequency: null }]);
  });

  it("отклоняет повторяющиеся идентификаторы проектов", async () => {
    mockFetch(async () => ({ ok: true, json: async () => [wireProject(), wireProject()] }));
    await expect(fetchSeoProjects()).rejects.toThrow("Invalid SEO projects response");
  });

  it("отклоняет повторяющиеся идентификаторы задач", async () => {
    mockFetch(async () => ({ ok: true, json: async () => [wireTask(), wireTask()] }));
    await expect(fetchSeoTasks(1)).rejects.toThrow("Invalid SEO tasks response");
  });

  it("не принимает другой проект по успешному HTTP-ответу карточки", async () => {
    mockFetch(async () => ({ ok: true, json: async () => wireProject({ id: 2 }) }));
    await expect(fetchSeoProject(1)).rejects.toThrow("Invalid SEO project response");
  });

  it.each([-1, 0, "../other", "2.5", "NaN", Number.MAX_SAFE_INTEGER + 1])("не отправляет некорректный ID %s в API", async (id) => {
    const f = vi.fn(async () => ({ ok: true, json: async () => wireProject() }));
    mockFetch(f);
    for (const load of [fetchSeoProject, fetchSeoProjectDashboard, fetchSeoTasks, fetchSeoDeepLink]) {
      await expect(load(id)).rejects.toThrow("Invalid SEO project id");
    }
    expect(f).not.toHaveBeenCalled();
  });
});
