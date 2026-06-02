import {
  CheckSquare,
  FileText,
  Gauge,
  Radio,
  Trophy,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { fetchOwnerDashboard } from "@/lib/api";
import { formatMoney } from "@/lib/format";

type IconCmp = React.ComponentType<{ size?: number }>;

function Metric({
  Icon,
  label,
  value,
  tone,
}: {
  Icon: IconCmp;
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-card">
      <div className="flex items-center gap-2 text-muted">
        <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${tone}`}>
          <Icon size={18} />
        </span>
        <span className="text-sm">{label}</span>
      </div>
      <div className="mt-3 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

export default async function OwnerPage() {
  const data = await fetchOwnerDashboard();
  if (!data) {
    return (
      <AppShell crumbs={["CRM", "Панель владельца"]}>
        <main className="flex-1 p-6 text-muted">Нет данных (бэкенд недоступен).</main>
      </AppShell>
    );
  }
  const { metrics, stages, kpis } = data;
  const active = stages.filter((s) => s.id !== "won");
  const activeCount = active.reduce((a, s) => a + s.count, 0);
  const activeSum = active.reduce((a, s) => a + s.sum, 0);
  const wonCount = stages.find((s) => s.id === "won")?.count ?? 0;
  const avgKpi = kpis.length
    ? Math.round(kpis.reduce((a, k) => a + k.percent, 0) / kpis.length)
    : 0;

  return (
    <AppShell crumbs={["CRM", "Панель владельца"]}>
      <main className="flex-1 overflow-auto p-6">
        <h1 className="text-xl font-bold text-ink">Панель владельца</h1>
        <p className="mt-1 text-sm text-muted">
          Здоровье бизнеса одним взглядом · AI Control Tower (без AI)
        </p>

        <div className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-4">
          <Metric Icon={Workflow} label="Сделок в работе" value={String(activeCount)} tone="bg-blue-50 text-brand-600" />
          <Metric Icon={Wallet} label="Сумма в работе" value={formatMoney(activeSum)} tone="bg-emerald-50 text-emerald-600" />
          <Metric Icon={Trophy} label="Выиграно сделок" value={String(wonCount)} tone="bg-amber-50 text-amber-600" />
          <Metric Icon={Gauge} label="Выполнение плана" value={`${avgKpi}%`} tone="bg-indigo-50 text-indigo-600" />
          <Metric Icon={CheckSquare} label="Согласований ждут" value={String(metrics.approvals_pending)} tone="bg-amber-50 text-amber-600" />
          <Metric Icon={Radio} label="Событий в шине" value={String(metrics.events_count)} tone="bg-cyan-50 text-cyan-600" />
          <Metric Icon={FileText} label="Записей аудита" value={String(metrics.audit_count)} tone="bg-slate-100 text-slate-600" />
          <Metric Icon={Users} label="Контрагентов" value={String(metrics.counterparties)} tone="bg-violet-50 text-violet-600" />
        </div>

        <section className="mt-6 rounded-2xl bg-white p-5 shadow-card">
          <h2 className="font-semibold text-ink">Воронка по стадиям</h2>
          <div className="mt-3 space-y-2">
            {stages.map((s) => (
              <div key={s.id} className="flex items-center gap-3">
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: s.color }} />
                <span className="w-44 shrink-0 text-sm text-ink">{s.title}</span>
                <span className="text-sm text-muted">
                  {s.count} · {formatMoney(s.sum)}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-4 grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl bg-white p-5 shadow-card">
            <h2 className="font-semibold text-ink">Подключённые модули</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {metrics.modules.map((m) => (
                <span key={m} className="rounded-lg bg-blue-50 px-3 py-1 text-sm font-medium text-brand-600">
                  {m}
                </span>
              ))}
            </div>
          </div>
          <div className="rounded-2xl bg-white p-5 shadow-card">
            <h2 className="font-semibold text-ink">Виджеты модулей</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {metrics.widgets.length === 0 && <span className="text-sm text-muted">Нет виджетов</span>}
              {metrics.widgets.map((w) => (
                <span key={w.key} className="rounded-lg bg-slate-100 px-3 py-1 text-sm text-slate-600">
                  {w.title}
                </span>
              ))}
            </div>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
