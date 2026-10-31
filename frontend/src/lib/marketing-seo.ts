export type SeoProjectStatus = string;

export interface SeoProject {
  id: number;
  externalProjectId: string;
  name: string;
  domain: string;
  region: string;
  keywordCount: number;
  visibility: number;
  taskCount: number;
  lastCheck: string | null;
  status: SeoProjectStatus;
}

export interface SeoProjectsSummary {
  totalProjects: number;
  activeProjects: number;
  totalKeywords: number;
  totalTasks: number;
}

export interface SeoTask {
  id: number;
  externalTaskId: string;
  title: string;
  type: string;
  priority: string;
  status: string;
  url: string;
  clusterName: string;
  assignedTo: string;
}

export interface SeoVisibilityPoint {
  date: string;
  visibility: number;
}

export interface SeoQuickWin {
  keyword?: string | null;
  frequency?: number | null;
  potential?: string | null;
  url?: string | null;
}

export interface SeoDashboard {
  project: SeoProject;
  visibilityHistory: SeoVisibilityPoint[];
  priorityTasks: SeoTask[];
  quickWins: SeoQuickWin[];
  top10Count: number;
  criticalTasks: number;
}

export interface SeoAttentionItem {
  kind: string;
  projectId: number;
  projectName: string;
  title: string;
  priority: string;
  url: string;
}

const EMPTY_SUMMARY: SeoProjectsSummary = {
  totalProjects: 0,
  activeProjects: 0,
  totalKeywords: 0,
  totalTasks: 0,
};

function pick<T>(raw: Record<string, unknown>, camel: string, snake: string): T {
  return (raw[camel] !== undefined ? raw[camel] : raw[snake]) as T;
}

function wireRecord(value: unknown, kind: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`Invalid SEO ${kind} response`);
  return value as Record<string, unknown>;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isNonnegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function projectRequestId(value: string | number): number {
  const id = Number(value);
  if ((typeof value === "string" && !/^\d+$/.test(value)) || !isCount(id) || id === 0) {
    throw new Error("Invalid SEO project id");
  }
  return id;
}

export function normalizeSeoProject(value: unknown): SeoProject {
  const raw = wireRecord(value, "project");
  const project = {
    id: raw.id,
    externalProjectId: pick<unknown>(raw, "externalProjectId", "external_project_id"),
    name: raw.name, domain: raw.domain, region: raw.region,
    keywordCount: pick<unknown>(raw, "keywordCount", "keyword_count"),
    visibility: raw.visibility,
    taskCount: pick<unknown>(raw, "taskCount", "task_count"),
    lastCheck: pick<unknown>(raw, "lastCheck", "last_check"),
    status: raw.status,
  };
  if (!isCount(project.id) || project.id === 0 || !isCount(project.keywordCount)
    || !isCount(project.taskCount) || !isNonnegativeNumber(project.visibility)
    || ![project.externalProjectId, project.name, project.domain, project.region, project.status]
      .every((field) => typeof field === "string")
    || (project.lastCheck !== null && (typeof project.lastCheck !== "string" || !Number.isFinite(Date.parse(project.lastCheck))))) {
    throw new Error("Invalid SEO project response");
  }
  return project as SeoProject;
}

function normalizeTask(value: unknown): SeoTask {
  const raw = wireRecord(value, "task");
  const task = {
    id: raw.id,
    externalTaskId: pick<unknown>(raw, "externalTaskId", "external_task_id"),
    title: raw.title, type: raw.type, priority: raw.priority, status: raw.status, url: raw.url,
    clusterName: pick<unknown>(raw, "clusterName", "cluster_name"),
    assignedTo: pick<unknown>(raw, "assignedTo", "assigned_to"),
  };
  if (!isCount(task.id) || task.id === 0
    || ![task.externalTaskId, task.title, task.type, task.priority, task.status, task.url, task.clusterName, task.assignedTo]
      .every((field) => typeof field === "string")) throw new Error("Invalid SEO task response");
  return task as SeoTask;
}

function normalizeTasks(raw: unknown): SeoTask[] {
  if (!Array.isArray(raw)) throw new Error("Invalid SEO tasks response");
  const tasks = raw.map(normalizeTask);
  if (new Set(tasks.map((task) => task.id)).size !== tasks.length) throw new Error("Invalid SEO tasks response");
  return tasks;
}

function normalizeSummary(raw: unknown): SeoProjectsSummary {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid SEO summary response");
  const row = raw as Record<string, unknown>;
  const counts = [
    pick<unknown>(row, "totalProjects", "total_projects"),
    pick<unknown>(row, "activeProjects", "active_projects"),
    pick<unknown>(row, "totalKeywords", "total_keywords"),
    pick<unknown>(row, "totalTasks", "total_tasks"),
  ];
  if (!counts.every(isCount)) {
    throw new Error("Invalid SEO summary response");
  }
  const [totalProjects, activeProjects, totalKeywords, totalTasks] = counts as number[];
  return {
    totalProjects,
    activeProjects,
    totalKeywords,
    totalTasks,
  };
}

export function formatSeoDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export async function fetchSeoProjects(): Promise<SeoProject[]> {
  const res = await fetch("/api/marketing/seo/projects", { cache: "no-store" });
  if (!res.ok) throw Object.assign(new Error("fetch projects failed"), { status: res.status });
  const data: unknown = await res.json();
  if (!Array.isArray(data)) throw new Error("Invalid SEO projects response");
  const projects = data.map(normalizeSeoProject);
  if (new Set(projects.map((project) => project.id)).size !== projects.length) throw new Error("Invalid SEO projects response");
  return projects;
}

export async function fetchSeoProjectsSummary(): Promise<SeoProjectsSummary> {
  const res = await fetch("/api/marketing/seo/projects/summary", { cache: "no-store" });
  if (!res.ok) throw Object.assign(new Error("fetch summary failed"), { status: res.status });
  return normalizeSummary((await res.json()) as Record<string, unknown>);
}

export async function fetchSeoProject(id: string | number): Promise<SeoProject | null> {
  const projectId = projectRequestId(id);
  const res = await fetch(`/api/marketing/seo/projects/${projectId}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw Object.assign(new Error("fetch project failed"), { status: res.status });
  const project = normalizeSeoProject(await res.json());
  if (project.id !== projectId) throw new Error("Invalid SEO project response");
  return project;
}

export async function fetchSeoProjectDashboard(id: string | number): Promise<SeoDashboard> {
  const projectId = projectRequestId(id);
  const res = await fetch(`/api/marketing/seo/projects/${projectId}/dashboard`, { cache: "no-store" });
  if (!res.ok) throw Object.assign(new Error("fetch dashboard failed"), { status: res.status });
  const raw = wireRecord(await res.json(), "dashboard");
  const project = normalizeSeoProject(raw.project);
  const history = pick<unknown>(raw, "visibilityHistory", "visibility_history");
  const quickWins = pick<unknown>(raw, "quickWins", "quick_wins");
  const top10Count = pick<unknown>(raw, "top10Count", "top10_count");
  const criticalTasks = pick<unknown>(raw, "criticalTasks", "critical_tasks");
  if (project.id !== projectId || !isCount(top10Count) || !isCount(criticalTasks)
    || !Array.isArray(history) || !Array.isArray(quickWins)) throw new Error("Invalid SEO dashboard response");
  const visibilityHistory = history.map((value) => {
    const point = wireRecord(value, "visibility");
    if (typeof point.date !== "string" || !Number.isFinite(Date.parse(point.date)) || !isNonnegativeNumber(point.visibility)) {
      throw new Error("Invalid SEO visibility response");
    }
    return { date: point.date, visibility: point.visibility };
  });
  const checkedQuickWins = quickWins.map((value) => {
    const row = wireRecord(value, "quick-win");
    if (![row.keyword, row.potential, row.url].every((field) => field === undefined || field === null || typeof field === "string")
      || (row.frequency !== undefined && row.frequency !== null && !isNonnegativeNumber(row.frequency))) {
      throw new Error("Invalid SEO quick-win response");
    }
    return row as SeoQuickWin;
  });
  return {
    project, visibilityHistory,
    priorityTasks: normalizeTasks(pick<unknown>(raw, "priorityTasks", "priority_tasks")),
    quickWins: checkedQuickWins, top10Count, criticalTasks,
  };
}

export async function fetchSeoTasks(id: string | number): Promise<SeoTask[]> {
  const projectId = projectRequestId(id);
  const res = await fetch(`/api/marketing/seo/projects/${projectId}/tasks`, { cache: "no-store" });
  if (!res.ok) throw Object.assign(new Error("fetch tasks failed"), { status: res.status });
  return normalizeTasks(await res.json());
}

export async function fetchSeoDeepLink(id: string | number): Promise<string | null> {
  const projectId = projectRequestId(id);
  const res = await fetch(`/api/marketing/seo/projects/${projectId}/deep-link`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw Object.assign(new Error("fetch deep-link failed"), { status: res.status });
  const data: unknown = await res.json();
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid SEO deep-link response");
  const url = (data as { url?: unknown }).url;
  if (url === undefined || url === null || url === "") return null;
  if (typeof url !== "string") throw new Error("Invalid SEO deep-link response");
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") return url;
  } catch { /* Treat malformed integration data as unavailable, without exposing it. */ }
  throw new Error("Invalid SEO deep-link response");
}

export async function fetchSeoAttention(): Promise<SeoAttentionItem[]> {
  const res = await fetch("/api/marketing/seo/attention", { cache: "no-store" });
  if (!res.ok) throw Object.assign(new Error("fetch attention failed"), { status: res.status });
  const data: unknown = await res.json();
  if (!Array.isArray(data)) throw new Error("Invalid SEO attention response");
  return data.map((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid SEO attention response");
    const raw = value as Record<string, unknown>;
    const projectId = pick<unknown>(raw, "projectId", "project_id");
    const projectName = pick<unknown>(raw, "projectName", "project_name");
    const kind = raw.kind ?? "task";
    const url = raw.url ?? "";
    if (typeof projectId !== "number" || !Number.isSafeInteger(projectId) || projectId <= 0
      || typeof projectName !== "string" || typeof raw.title !== "string" || typeof raw.priority !== "string"
      || typeof kind !== "string" || typeof url !== "string") throw new Error("Invalid SEO attention response");
    return { kind, projectId, projectName, title: raw.title, priority: raw.priority, url };
  });
}

export async function fetchSeoDashboard(): Promise<{
  projects: SeoProject[];
  summary: SeoProjectsSummary | null;
}> {
  const [projects, summary] = await Promise.allSettled([
    fetchSeoProjects(),
    fetchSeoProjectsSummary(),
  ]);
  if (summary.status === "rejected" && summary.reason && typeof summary.reason === "object"
    && (summary.reason.status === 401 || summary.reason.status === 403)) throw summary.reason;
  if (projects.status === "rejected") throw projects.reason;
  return { projects: projects.value, summary: summary.status === "fulfilled" ? summary.value : null };
}

export { EMPTY_SUMMARY };
