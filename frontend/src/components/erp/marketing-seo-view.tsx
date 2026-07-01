"use client";

import clsx from "clsx";
import {
  BarChart3,
  FolderKanban,
  Globe,
  Layers,
  ListTodo,
  Plus,
  RefreshCw,
  Search,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { formatNumber } from "@/lib/format";
import {
  EMPTY_SUMMARY,
  fetchSeoAttention,
  fetchSeoDashboard,
  type SeoAttentionItem,
  type SeoProject,
  type SeoProjectsSummary,
} from "@/lib/marketing-seo";

function MetricCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">
      <div className="flex items-center gap-2 text-sm text-muted">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-2 text-2xl font-bold tabular-nums text-ink">{value}</div>
    </div>
  );
}

function QuickLinkCard({
  label,
  description,
  icon,
  href,
  soon,
}: {
  label: string;
  description: string;
  icon: React.ReactNode;
  href?: string;
  soon?: boolean;
}) {
  const body = (
    <>
      <div className="flex items-center gap-2 text-muted">
        {icon}
        <span className="text-sm font-medium text-ink">{label}</span>
        {soon && <span className="text-[10px] font-semibold uppercase text-faint">скоро</span>}
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-muted">{description}</p>
    </>
  );

  if (href && !soon) {
    return (
      <Link
        href={href}
        className="rounded-xl border border-line bg-surface px-4 py-3.5 transition-colors hover:border-accent"
      >
        {body}
      </Link>
    );
  }

  return (
    <div
      className={clsx(
        "rounded-xl border border-line bg-surface px-4 py-3.5",
        soon && "opacity-75",
      )}
      title={soon ? "Раздел в разработке" : undefined}
    >
      {body}
    </div>
  );
}

function StatusBadge({ status }: { status: SeoProject["status"] }) {
  const active = status === "active";
  const label = status === "active" ? "Активен" : status === "paused" ? "Пауза" : "Архив";
  return (
    <span
      className={clsx(
        "inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
        active ? "bg-emerald-50 text-emerald-700" : "bg-sunken text-muted",
      )}
    >
      {label}
    </span>
  );
}

export function MarketingSeoView() {
  const [projects, setProjects] = useState<SeoProject[]>([]);
  const [summary, setSummary] = useState<SeoProjectsSummary>(EMPTY_SUMMARY);
  const [attention, setAttention] = useState<SeoAttentionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const [data, attn] = await Promise.all([fetchSeoDashboard(), fetchSeoAttention()]);
      setProjects(data.projects);
      setSummary(data.summary);
      setAttention(attn);
    } catch {
      setError(true);
      setProjects([]);
      setSummary(EMPTY_SUMMARY);
      setAttention([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Globe size={22} className="text-accent-ink" />
            <h1 className="text-xl font-bold text-ink">SEO / GEO Growth Platform</h1>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Органический трафик и гео-присутствие для B2B-каталога: мониторинг позиций,
            кластеризация запросов, SEO-задачи и связка с маркетинговыми кампаниями CRM.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-sunken/50 disabled:opacity-50"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : undefined} />
            Обновить
          </button>
          <button
            type="button"
            disabled
            title="Раздел в разработке"
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-faint"
          >
            <Plus size={16} />
            Создать проект
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          Не удалось загрузить SEO-проекты. Проверьте backend и попробуйте обновить.
        </div>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Всего проектов"
          value={loading ? "…" : summary.totalProjects}
          icon={<FolderKanban size={15} />}
        />
        <MetricCard label="Активных проектов" value={loading ? "…" : summary.activeProjects} />
        <MetricCard
          label="Ключей в мониторинге"
          value={loading ? "…" : formatNumber(summary.totalKeywords)}
          icon={<Search size={15} />}
        />
        <MetricCard
          label="SEO-задач"
          value={loading ? "…" : formatNumber(summary.totalTasks)}
          icon={<ListTodo size={15} />}
        />
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-ink">Разделы платформы</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <QuickLinkCard
            label="Дашборд"
            description="Видимость, динамика позиций и быстрые победы по проекту."
            icon={<BarChart3 size={15} />}
            href={projects[0] ? `/erp/marketing/seo/projects/${projects[0].id}` : undefined}
            soon={projects.length === 0}
          />
          <QuickLinkCard
            label="Ключевые запросы"
            description="Частотность, позиции в Яндексе и Google, приоритеты."
            icon={<Search size={15} />}
            soon
          />
          <QuickLinkCard
            label="Кластеры"
            description="Группировка семантики и каннибализация посадочных."
            icon={<Layers size={15} />}
            soon
          />
          <QuickLinkCard
            label="SEO-задачи"
            description="Очередь работ: контент, техника, посадочные страницы."
            icon={<ListTodo size={15} />}
            soon
          />
        </div>
      </div>

      {attention.length > 0 && (
        <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50/60 p-5">
          <h2 className="text-sm font-semibold text-amber-900">Требует внимания</h2>
          <ul className="mt-3 space-y-2">
            {attention.slice(0, 5).map((item, i) => (
              <li key={`${item.projectId}-${i}`} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <Link
                  href={`/erp/marketing/seo/projects/${item.projectId}`}
                  className="font-medium text-amber-950 hover:underline"
                >
                  {item.projectName}: {item.title}
                </Link>
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                  {item.priority}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-8">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">Проекты</h2>
          <span className="flex items-center gap-1 text-xs text-faint">
            <TrendingUp size={12} />
            {loading ? "Загрузка…" : "Реестр CRM · синхронизация с SEO-платформой"}
          </span>
        </div>

        <div className="mt-3 overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
          {loading ? (
            <div className="px-4 py-8 text-center text-sm text-muted">Загрузка проектов…</div>
          ) : projects.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted">
              Нет привязанных SEO-проектов. Подключите SEO-сервис через webhook или{" "}
              <code className="text-xs">POST /marketing/seo/projects/link</code>.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line bg-sunken/50 text-left text-xs text-muted">
                  <th className="px-4 py-3 font-medium">Название</th>
                  <th className="px-4 py-3 font-medium">Домен</th>
                  <th className="px-4 py-3 font-medium">Регион</th>
                  <th className="px-4 py-3 font-medium text-right">Ключи</th>
                  <th className="px-4 py-3 font-medium text-right">Видимость</th>
                  <th className="px-4 py-3 font-medium text-right">Задачи</th>
                  <th className="px-4 py-3 font-medium">Статус</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id} className="border-b border-line last:border-0 hover:bg-sunken/30">
                    <td className="px-4 py-3">
                      <Link
                        href={`/erp/marketing/seo/projects/${p.id}`}
                        className="font-medium text-accent-ink hover:underline"
                      >
                        {p.name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-muted">{p.domain || "—"}</td>
                    <td className="px-4 py-3 text-muted">{p.region || "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{formatNumber(p.keywordCount)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{p.visibility}%</td>
                    <td className="px-4 py-3 text-right tabular-nums">{formatNumber(p.taskCount)}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={p.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </main>
  );
}
