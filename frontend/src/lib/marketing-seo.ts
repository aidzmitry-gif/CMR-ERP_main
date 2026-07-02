export type SeoProjectStatus = "active" | "paused" | "archived";

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
  keyword?: string;
  frequency?: number;
  potential?: string;
  url?: string;
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
  return (raw[camel] ?? raw[snake]) as T;
}

export function normalizeSeoProject(raw: Record<string, unknown>): SeoProject {
  return {
    id: Number(raw.id),
    externalProjectId: String(pick(raw, "externalProjectId", "external_project_id") ?? ""),
    name: String(raw.name ?? ""),
    domain: String(raw.domain ?? ""),
    region: String(raw.region ?? ""),
    keywordCount: Number(pick(raw, "keywordCount", "keyword_count") ?? 0),
    visibility: Number(raw.visibility ?? 0),
    taskCount: Number(pick(raw, "taskCount", "task_count") ?? 0),
    lastCheck: (pick<string | null>(raw, "lastCheck", "last_check") ?? null) as string | null,
    status: (String(raw.status ?? "active") as SeoProjectStatus),
  };
}

function normalizeTask(raw: Record<string, unknown>): SeoTask {
  return {
    id: Number(raw.id),
    externalTaskId: String(pick(raw, "externalTaskId", "external_task_id") ?? ""),
    title: String(raw.title ?? ""),
    type: String(raw.type ?? ""),
    priority: String(raw.priority ?? "medium"),
    status: String(raw.status ?? "new"),
    url: String(raw.url ?? ""),
    clusterName: String(pick(raw, "clusterName", "cluster_name") ?? ""),
    assignedTo: String(pick(raw, "assignedTo", "assigned_to") ?? ""),
  };
}

function normalizeSummary(raw: Record<string, unknown>): SeoProjectsSummary {
  return {
    totalProjects: Number(pick(raw, "totalProjects", "total_projects") ?? 0),
    activeProjects: Number(pick(raw, "activeProjects", "active_projects") ?? 0),
    totalKeywords: Number(pick(raw, "totalKeywords", "total_keywords") ?? 0),
    totalTasks: Number(pick(raw, "totalTasks", "total_tasks") ?? 0),
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
  if (!res.ok) throw new Error("fetch projects failed");
  const data = (await res.json()) as Record<string, unknown>[];
  return data.map(normalizeSeoProject);
}

export async function fetchSeoProjectsSummary(): Promise<SeoProjectsSummary> {
  const res = await fetch("/api/marketing/seo/projects/summary", { cache: "no-store" });
  if (!res.ok) throw new Error("fetch summary failed");
  return normalizeSummary((await res.json()) as Record<string, unknown>);
}

export async function fetchSeoProject(id: string | number): Promise<SeoProject | null> {
  const res = await fetch(`/api/marketing/seo/projects/${id}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("fetch project failed");
  return normalizeSeoProject((await res.json()) as Record<string, unknown>);
}

export async function fetchSeoProjectDashboard(id: string | number): Promise<SeoDashboard> {
  const res = await fetch(`/api/marketing/seo/projects/${id}/dashboard`, { cache: "no-store" });
  if (!res.ok) throw new Error("fetch dashboard failed");
  const raw = (await res.json()) as Record<string, unknown>;
  return {
    project: normalizeSeoProject((raw.project as Record<string, unknown>) ?? {}),
    visibilityHistory: ((raw.visibilityHistory ?? raw.visibility_history) as Record<string, unknown>[] ?? []).map(
      (p) => ({
        date: String(p.date ?? ""),
        visibility: Number(p.visibility ?? 0),
      }),
    ),
    priorityTasks: ((raw.priorityTasks ?? raw.priority_tasks) as Record<string, unknown>[] ?? []).map(normalizeTask),
    quickWins: ((raw.quickWins ?? raw.quick_wins) as SeoQuickWin[]) ?? [],
    top10Count: Number(pick(raw, "top10Count", "top10_count") ?? 0),
    criticalTasks: Number(pick(raw, "criticalTasks", "critical_tasks") ?? 0),
  };
}

export async function fetchSeoTasks(id: string | number): Promise<SeoTask[]> {
  const res = await fetch(`/api/marketing/seo/projects/${id}/tasks`, { cache: "no-store" });
  if (!res.ok) throw new Error("fetch tasks failed");
  const data = (await res.json()) as Record<string, unknown>[];
  return data.map(normalizeTask);
}

export async function fetchSeoDeepLink(id: string | number): Promise<string | null> {
  const res = await fetch(`/api/marketing/seo/projects/${id}/deep-link`, { cache: "no-store" });
  if (!res.ok) return null;
  const data = (await res.json()) as { url?: string };
  return data.url ?? null;
}

export async function fetchSeoAttention(): Promise<SeoAttentionItem[]> {
  const res = await fetch("/api/marketing/seo/attention", { cache: "no-store" });
  if (!res.ok) return [];
  const data = (await res.json()) as Record<string, unknown>[];
  return data.map((raw) => ({
    kind: String(raw.kind ?? "task"),
    projectId: Number(pick(raw, "projectId", "project_id") ?? 0),
    projectName: String(pick(raw, "projectName", "project_name") ?? ""),
    title: String(raw.title ?? ""),
    priority: String(raw.priority ?? ""),
    url: String(raw.url ?? ""),
  }));
}

export async function fetchSeoDashboard(): Promise<{
  projects: SeoProject[];
  summary: SeoProjectsSummary;
}> {
  try {
    const [projects, summary] = await Promise.all([
      fetchSeoProjects(),
      fetchSeoProjectsSummary(),
    ]);
    return { projects, summary };
  } catch {
    const projects = await fetchSeoProjects();
    return {
      projects,
      summary: {
        totalProjects: projects.length,
        activeProjects: projects.filter((p) => p.status === "active").length,
        totalKeywords: projects.reduce((n, p) => n + p.keywordCount, 0),
        totalTasks: projects.reduce((n, p) => n + p.taskCount, 0),
      },
    };
  }
}

export { EMPTY_SUMMARY };
