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

    <div className="flex h-32 items-end gap-1">

      {points.map((p) => (

        <div key={p.date} className="group flex flex-1 flex-col items-center gap-1">

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



function PriorityBadge({ priority }: { priority: string }) {

  const tone =

    priority === "critical"

      ? "bg-red-50 text-red-700"

      : priority === "high"

        ? "bg-amber-50 text-amber-800"

        : "bg-sunken text-muted";

  return <span className={clsx("rounded-full px-2 py-0.5 text-xs font-medium", tone)}>{priority}</span>;

}



export function MarketingSeoProjectView({ projectId }: { projectId: string }) {

  const [project, setProject] = useState<SeoProject | null>(null);

  const [dashboard, setDashboard] = useState<SeoDashboard | null>(null);

  const [tasks, setTasks] = useState<SeoTask[]>([]);

  const [deepLink, setDeepLink] = useState<string | null>(null);

  const [tab, setTab] = useState<TabKey>("dashboard");

  const [loading, setLoading] = useState(true);

  const [notFound, setNotFound] = useState(false);



  useEffect(() => {

    let cancelled = false;

    setLoading(true);

    setNotFound(false);

    void Promise.all([

      fetchSeoProject(projectId),

      fetchSeoProjectDashboard(projectId).catch(() => null),

      fetchSeoTasks(projectId).catch(() => []),

      fetchSeoDeepLink(projectId),

    ])

      .then(([proj, dash, taskList, link]) => {

        if (cancelled) return;

        if (!proj) {

          setNotFound(true);

          return;

        }

        setProject(proj);

        setDashboard(dash);

        setTasks(taskList);

        setDeepLink(link);

      })

      .catch(() => {

        if (!cancelled) setNotFound(true);

      })

      .finally(() => {

        if (!cancelled) setLoading(false);

      });

    return () => {

      cancelled = true;

    };

  }, [projectId]);



  if (loading) {

    return (

      <main className="flex-1 overflow-auto p-6">

        <p className="text-sm text-muted">Загрузка проекта…</p>

      </main>

    );

  }



  if (notFound || !project) {

    return (

      <main className="flex-1 overflow-auto p-6">

        <Link

          href="/erp/marketing/seo"

          className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink"

        >

          <ArrowLeft size={14} />

          Все проекты

        </Link>

        <p className="mt-6 text-sm text-muted">SEO-проект не найден.</p>

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

                : "Архив"}

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

                {formatNumber(dashboard?.top10Count ?? 0)}

              </div>

            </div>

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <div className="text-sm text-muted">Критические задачи</div>

              <div className="mt-2 text-2xl font-bold tabular-nums text-ink">

                {formatNumber(dashboard?.criticalTasks ?? project.taskCount)}

              </div>

            </div>

          </div>



          <div className="mt-6 grid gap-4 lg:grid-cols-2">

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <h2 className="text-sm font-semibold text-ink">Динамика видимости</h2>

              <div className="mt-4">

                <VisibilityChart points={visibility} />

              </div>

            </div>

            <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">

              <h2 className="text-sm font-semibold text-ink">Быстрые победы</h2>

              {quickWins.length === 0 ? (

                <p className="mt-3 text-sm text-muted">Нет quick wins в последнем снимке.</p>

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

        <div className="mt-5 overflow-hidden rounded-2xl border border-line bg-surface shadow-card">

          {tasks.length === 0 ? (

            <div className="px-4 py-8 text-center text-sm text-muted">

              Задачи не синхронизированы. Запустите sync в SEO-платформе.

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

                    <td className="px-4 py-3 text-muted">{task.type || "—"}</td>

                    <td className="px-4 py-3">

                      <PriorityBadge priority={task.priority} />

                    </td>

                    <td className="px-4 py-3 text-muted">{task.status}</td>

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

