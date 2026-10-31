"use client";



import clsx from "clsx";

import { ArrowLeft, BarChart3, ExternalLink, Layers, ListTodo, Search } from "lucide-react";

import Link from "next/link";

import { useEffect, useMemo, useState } from "react";



import { formatNumber } from "@/lib/format";

import {

  fetchSeoDeepLink,

  fetchSeoProject,

  fetchSeoProjectDashboard,

  fetchSeoTasks,

  formatSeoDate,

  type SeoDashboard,

  type SeoProject,

  type SeoTask,

} from "@/lib/marketing-seo";



type TabKey = "dashboard" | "tasks";



const PROJECT_TABS: { key: TabKey; label: string; icon: typeof BarChart3 }[] = [

  { key: "dashboard", label: "Дашборд", icon: BarChart3 },

  { key: "tasks", label: "SEO-задачи", icon: ListTodo },

];



function VisibilityChart({ points }: { points: { date: string; visibility: number }[] }) {

  const max = useMemo(() => Math.max(...points.map((p) => p.visibility), 1), [points]);

  if (points.length === 0) {

    return <p className="text-sm text-muted">Нет данных о видимости — выполните sync из SEO-платформы.</p>;

  }

  return (

    <div className="flex h-32 items-end justify-center gap-2">

      {points.map((p) => (

        <div key={p.date} className="group flex h-full min-w-0 max-w-12 flex-1 flex-col items-center justify-end gap-1">

          <div

            className="w-full rounded-t bg-accent/80 transition-colors group-hover:bg-accent"

            style={{ height: `${Math.max(4, (p.visibility / max) * 100)}%` }}

            title={`${p.date}: ${p.visibility}%`}

          />

          <span className="hidden text-[9px] text-faint sm:block">

            {p.date.slice(5)}

          </span>

        </div>

      ))}

    </div>

  );

}



const TASK_TYPES: Record<string, string> = {
  on_page: "Оптимизация страниц",
  tech: "Техническое SEO",
  content: "Контент",
};

const TASK_PRIORITIES: Record<string, string> = {
  critical: "Критический",
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
};

const TASK_STATUSES: Record<string, string> = {
  new: "Новая",
  in_progress: "В работе",
};

function taskLabel(value: string, labels: Record<string, string>): string {
  return Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : value || "—";
}

function PriorityBadge({ priority }: { priority: string }) {

  const tone =

    priority === "critical"

      ? "bg-red-50 text-red-700"

      : priority === "high"

        ? "bg-amber-50 text-amber-800"

        : "bg-sunken text-muted";

  return <span className={clsx("rounded-full px-2 py-0.5 text-xs font-medium", tone)}>{taskLabel(priority, TASK_PRIORITIES)}</span>;

}



export function MarketingSeoProjectView({ projectId }: { projectId: string }) {

  const [tab, setTab] = useState<TabKey>("dashboard");
  const [revision, setRevision] = useState(0);
  const key = `${projectId}:${revision}`;
  const [loaded, setLoaded] = useState<{
    key: string;
    project: SeoProject | null;
    dashboard: SeoDashboard | null;
    tasks: SeoTask[] | null;
    deepLink: string | null;
    error: string | null;
    notFound: boolean;
    linkFailed: boolean;
  } | null>(null);
  const state = loaded?.key === key ? loaded : null;
  const loading = state === null;
  const project = state?.project ?? null;
  const dashboard = state?.dashboard ?? null;
  const tasks = state?.tasks ?? [];
  const deepLink = state?.deepLink ?? null;
  const error = state?.error ?? null;
  const notFound = state?.notFound ?? false;

  useEffect(() => {
    let active = true;
    const empty = { key, project: null, dashboard: null, tasks: null, deepLink: null,
      error: null, notFound: false, linkFailed: false };
    void (async () => {
      // Defer even invalid route handling so a changed key hides old content immediately.
      await Promise.resolve();
      const requestedId = Number(projectId);
      if (!/^\d+$/.test(projectId) || !Number.isSafeInteger(requestedId) || requestedId <= 0) {
        if (active) setLoaded({ ...empty, notFound: true });
        return;
      }
      try {
        const results = await Promise.allSettled([
          fetchSeoProject(projectId), fetchSeoProjectDashboard(projectId),
          fetchSeoTasks(projectId), fetchSeoDeepLink(projectId),
        ] as const);
        if (!active) return;
        const statuses = results.flatMap((result) => result.status === "rejected"
          ? [(result.reason as { status?: number } | null)?.status] : []);
        if (statuses.includes(401) || statuses.includes(403)) {
          setLoaded({ ...empty, error: statuses.includes(401)
            ? "Сессия истекла. Войдите в систему." : "Нет доступа к SEO-проекту." });
          return;
        }
        const [projectResult, dashboardResult, tasksResult, linkResult] = results;
        if (projectResult.status === "rejected") {
          setLoaded({ ...empty, error: "Не удалось загрузить SEO-проект. Повторите попытку." });
          return;
        }
        if (projectResult.value === null) {
          setLoaded({ ...empty, notFound: true });
          return;
        }
        if (!projectResult.value || projectResult.value.id !== requestedId) {
          setLoaded({ ...empty, error: "Не удалось загрузить SEO-проект. Повторите попытку." });
          return;
        }
        setLoaded({
          ...empty, project: projectResult.value,
          dashboard: dashboardResult.status === "fulfilled"
            && dashboardResult.value?.project?.id === requestedId ? dashboardResult.value : null,
          tasks: tasksResult.status === "fulfilled" && Array.isArray(tasksResult.value) ? tasksResult.value : null,
          deepLink: linkResult.status === "fulfilled" ? linkResult.value : null,
          linkFailed: linkResult.status === "rejected",
        });
      } catch {
        if (active) setLoaded({ ...empty, error: "Не удалось загрузить SEO-проект. Повторите попытку." });
      }
    })();
    return () => { active = false; };
  }, [projectId, key]);

  if (loading) {

    return (

      <main className="flex-1 overflow-auto p-6">

        <p className="text-sm text-muted">Загрузка проекта…</p>

      </main>

    );

  }



  if (notFound || error || !project) {

    return (

      <main className="flex-1 overflow-auto p-6">

        <Link

          href="/erp/marketing/seo"

          className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink"

        >

          <ArrowLeft size={14} />

          Все проекты

        </Link>

        <p role={error ? "alert" : undefined} className="mt-6 text-sm text-muted">{error ?? "SEO-проект не найден."}</p>
        <button type="button" onClick={() => setRevision((value) => value + 1)}
          className="mt-4 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink">
          Повторить
        </button>

      </main>

    );

  }



  const visibility = dashboard?.visibilityHistory ?? [];

  const quickWins = dashboard?.quickWins ?? [];

  const priorityTasks = dashboard?.priorityTasks ?? [];



  return (

    <main className="flex-1 overflow-auto p-6">

      <Link

        href="/erp/marketing/seo"

        className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink"

      >

        <ArrowLeft size={14} />

        Все проекты

      </Link>



      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">

        <div>

          <h1 className="text-xl font-bold text-ink">{project.name}</h1>

          <p className="mt-1 text-sm text-muted">

            {project.domain || "—"} · {project.region || "—"} · проверка{" "}

            {formatSeoDate(project.lastCheck)}

          </p>

          {project.externalProjectId && (

            <p className="mt-1 text-xs text-faint">SEO ID: {project.externalProjectId}</p>

          )}

        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setRevision((value) => value + 1)}
            className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-sunken/50">
            Обновить
          </button>

          {deepLink && (
            <a

              href={deepLink}

              target="_blank"

              rel="noopener noreferrer"

              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-accent-ink hover:bg-sunken/50"

            >

              <ExternalLink size={14} />

              Открыть в SEO

            </a>
          )}

          <span

            className={clsx(

              "rounded-full px-2.5 py-1 text-xs font-medium",

              project.status === "active"

                ? "bg-emerald-50 text-emerald-700"

                : "bg-sunken text-muted",

            )}

          >

            {project.status === "active"

              ? "Активен"

              : project.status === "paused"

                ? "Пауза"

                : project.status === "archived" ? "Архив" : project.status || "—"}

          </span>

        </div>

      </div>



      <div className="mt-5 flex flex-wrap items-center gap-1 border-b border-line">

        {PROJECT_TABS.map((t) => (

          <button

            key={t.key}

            type="button"

            onClick={() => setTab(t.key)}

            className={clsx(

              "relative flex items-center gap-1.5 px-3 py-2 text-sm transition-colors",

              tab === t.key ? "font-semibold text-accent-ink" : "text-muted hover:text-ink",

            )}

          >

            <t.icon size={14} />

            {t.label}

            {tab === t.key && (

              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-accent" />

            )}

          </button>

        ))}

        <span

          title="Раздел в разработке"

          className="flex cursor-default items-center gap-1.5 px-3 py-2 text-sm text-faint"

        >

          <Search size={14} />

          Ключевые запросы

          <span className="text-[9px] uppercase">скоро</span>

        </span>

        <span

          title="Раздел в разработке"

          className="flex cursor-default items-center gap-1.5 px-3 py-2 text-sm text-faint"

        >

          <Layers size={14} />

          Кластеры

          <span className="text-[9px] uppercase">скоро</span>

        </span>

      </div>



      {state?.linkFailed && <p role="alert" className="mt-4 text-sm text-muted">Не удалось загрузить ссылку SEO.</p>}
      {tab === "dashboard" && !dashboard && <p role="alert" className="mt-4 text-sm text-muted">Не удалось загрузить дашборд проекта.</p>}

      {tab === "dashboard" ? (

        <>

          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <div className="text-sm text-muted">Ключей в мониторинге</div>

              <div className="mt-2 text-2xl font-bold tabular-nums text-ink">

                {formatNumber(project.keywordCount)}

              </div>

            </div>

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <div className="text-sm text-muted">Видимость</div>

              <div className="mt-2 text-2xl font-bold tabular-nums text-ink">

                {project.visibility}%

              </div>

            </div>

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <div className="text-sm text-muted">В ТОП-10</div>

              <div className="mt-2 text-2xl font-bold tabular-nums text-ink">

                {dashboard ? formatNumber(dashboard.top10Count) : "—"}

              </div>

            </div>

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <div className="text-sm text-muted">Критические задачи</div>

              <div className="mt-2 text-2xl font-bold tabular-nums text-ink">

                {dashboard ? formatNumber(dashboard.criticalTasks) : "—"}

              </div>

            </div>

          </div>



          <div className="mt-6 grid gap-4 lg:grid-cols-2">

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <h2 className="text-sm font-semibold text-ink">Динамика видимости</h2>

              <div className="mt-4">

                {dashboard ? <VisibilityChart points={visibility} /> : <p className="text-sm text-muted">Данные о видимости недоступны.</p>}

              </div>

            </div>

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <h2 className="text-sm font-semibold text-ink">Быстрые победы</h2>

              {!dashboard ? <p className="mt-3 text-sm text-muted">Данные о быстрых победах недоступны.</p> : quickWins.length === 0 ? (

                <p className="mt-3 text-sm text-muted">В последнем снимке нет быстрых побед.</p>

              ) : (

                <ul className="mt-3 space-y-2">

                  {quickWins.slice(0, 6).map((qw, i) => (

                    <li key={i} className="text-sm">

                      <span className="font-medium text-ink">{qw.keyword ?? "—"}</span>

                      {qw.potential ? (

                        <span className="text-muted"> · {qw.potential}</span>

                      ) : null}

                    </li>

                  ))}

                </ul>

              )}

            </div>

          </div>



          {priorityTasks.length > 0 ? (

            <div className="mt-6 rounded-2xl border border-line bg-surface p-5 shadow-card">

              <h2 className="text-sm font-semibold text-ink">Приоритетные задачи</h2>

              <ul className="mt-3 divide-y divide-line">

                {priorityTasks.map((task) => (

                  <li key={task.id} className="flex items-start justify-between gap-3 py-2.5">

                    <div>

                      <div className="font-medium text-ink">{task.title}</div>

                      {task.clusterName ? (

                        <div className="text-xs text-muted">{task.clusterName}</div>

                      ) : null}

                    </div>

                    <PriorityBadge priority={task.priority} />

                  </li>

                ))}

              </ul>

            </div>

          ) : null}

        </>

      ) : (

        <div role="region" aria-label="SEO-задачи проекта" tabIndex={0} className="mt-5 overflow-x-auto rounded-2xl border border-line bg-surface shadow-card">

          {state?.tasks === null ? (
            <p role="alert" className="px-4 py-8 text-center text-sm text-muted">Не удалось загрузить SEO-задачи. Повторите попытку.</p>
          ) : tasks.length === 0 ? (

            <div className="px-4 py-8 text-center text-sm text-muted">

              В проекте пока нет SEO-задач.

            </div>

          ) : (

            <table className="w-full text-sm">

              <thead>

                <tr className="border-b border-line bg-sunken/50 text-left text-xs text-muted">

                  <th className="px-4 py-3 font-medium">Задача</th>

                  <th className="px-4 py-3 font-medium">Тип</th>

                  <th className="px-4 py-3 font-medium">Приоритет</th>

                  <th className="px-4 py-3 font-medium">Статус</th>

                </tr>

              </thead>

              <tbody>

                {tasks.map((task) => (

                  <tr key={task.id} className="border-b border-line last:border-0">

                    <td className="px-4 py-3">

                      <div className="font-medium text-ink">{task.title}</div>

                      {task.url ? (

                        <div className="truncate text-xs text-muted">{task.url}</div>

                      ) : null}

                    </td>

                    <td className="px-4 py-3 text-muted">{taskLabel(task.type, TASK_TYPES)}</td>

                    <td className="px-4 py-3">

                      <PriorityBadge priority={task.priority} />

                    </td>

                    <td className="px-4 py-3 text-muted">{taskLabel(task.status, TASK_STATUSES)}</td>

                  </tr>

                ))}

              </tbody>

            </table>

          )}

        </div>

      )}

    </main>

  );

}

