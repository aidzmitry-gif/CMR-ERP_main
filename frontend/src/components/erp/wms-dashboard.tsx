"use client";

import clsx from "clsx";
import { AlertTriangle, Banknote, ClipboardCheck, Boxes, Coins, PackageCheck, RefreshCw, Scale, Truck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { InstanceOrganizationGate } from "@/components/instance-organization-gate";
import { formatByn, formatNumber } from "@/lib/format";
import { fetchDashboard, type Dashboard } from "@/lib/wms-warehouse";

function Card({ href, icon, label, value, tone, sub }: {
  href?: string; icon: React.ReactNode; label: string; value: string; tone?: string; sub?: string;
}) {
  const className = "rounded-xl border border-line bg-surface px-4 py-3.5 " + (href ? "hover:border-accent" : "");
  const body = <>
    <div className="flex items-center gap-2 text-muted">{icon}<span className="text-xs font-medium">{label}</span></div>
    <div className={clsx("mt-1.5 text-2xl font-bold tabular-nums", tone ?? "text-ink")}>{value}</div>
    {sub && <div className="mt-0.5 text-[11px] text-faint">{sub}</div>}
  </>;
  return href ? <Link href={href} className={className}>{body}</Link>
    : <section aria-label={label} className={className}>{body}</section>;
}

export function ScopedWmsDashboard() {
  return <InstanceOrganizationGate>{organization => <CompanyDashboard key={organization.id} organizationId={organization.id} />}</InstanceOrganizationGate>;
}

function CompanyDashboard({ organizationId }: { organizationId: number }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ loading: boolean; data: Dashboard | null }>({ loading: true, data: null });
  useEffect(() => {
    const controller = new AbortController();
    void fetchDashboard(organizationId, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ loading: false, data });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ loading: false, data: null });
    });
    return () => controller.abort();
  }, [organizationId, attempt]);
  if (state.loading) return <p role="status" className="p-6">Загрузка сводки компании…</p>;
  return <WmsDashboard initial={state.data} onRetry={() => {
    setState({ loading: true, data: null }); setAttempt(value => value + 1);
  }} />;
}

/** Presentation also supports known zero; synthetic presentation is not source qualification. */
export function WmsDashboard({ initial, onRetry }: { initial: Dashboard | null; onRetry?: () => void }) {
  if (!initial) return <div className="flex-1 overflow-auto p-6">
    <p role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-700">
      Не удалось загрузить сводку склада. Остатки, дефицит и задачи неизвестны.
    </p>
    <button type="button" onClick={onRetry ?? (() => window.location.reload())} className="mt-3 rounded-lg border border-line px-3 py-2 text-sm">Повторить загрузку</button>
  </div>;
  const d = initial;
  const reportDate = d.report_date.split("-").reverse().join(".");
  return <div className="flex-1 overflow-auto p-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted">Сводка подтверждённых документов компании в ERP.</p>
      <Link href="/erp/wms/operations" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-muted">История операций →</Link>
    </div>
    {d.valuation_unavailable_reason && <p role="status" className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-700">
      Оценка, дефицит и сверка с 1С неизвестны: источник не подтверждает принадлежность данных компании.
      {!d.gateway && " Шлюз 1С не настроен."}
    </p>}
    <p className="mt-3 text-sm text-muted">Записи движений за {reportDate} (по журналу ERP). Это число строк журнала; количества товаров с разными единицами не складываются.</p>
    <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card href="/erp/wms/receipts" icon={<PackageCheck size={15} />} label="Приёмки в очереди QC" value={formatNumber(d.receipts_pending_qc)} />
      <Card href="/erp/wms/tasks" icon={<ClipboardCheck size={15} />} label="Размещение (put-away)" value={formatNumber(d.tasks_putaway_open)} sub="открытых задач" />
      <Card href="/erp/wms/tasks" icon={<Truck size={15} />} label="Подбор (pick)" value={formatNumber(d.tasks_pick_open)} sub="открытых задач" />
      <Card href="/erp/wms/inventory" icon={<Boxes size={15} />} label="Инвентаризации" value={formatNumber(d.inventories_open)} sub="открытых" />
      <Card icon={<AlertTriangle size={15} />} label="Дефицит (low-stock)" value={d.alerts_count === null ? "—" : formatNumber(d.alerts_count)} sub={d.alerts_count === null ? "нет подтверждённого источника компании" : undefined} />
      <Card icon={<Banknote size={15} />} label="Дефицит в деньгах" value={d.alerts_deficit_value === null ? "—" : formatByn(d.alerts_deficit_value)} sub={d.alerts_deficit_value === null ? "нет подтверждённой оценки" : undefined} />
      <Card icon={<Coins size={15} />} label="Стоимость остатка" value={d.inventory_value === null ? "—" : formatByn(d.inventory_value)} sub={d.inventory_value === null ? "нет подтверждённой себестоимости" : undefined} />
      <Card icon={<Scale size={15} />} label="Расхождение с 1С" value={d.recon_total_diff_value === null ? "—" : formatByn(d.recon_total_diff_value)} sub={d.recon_max_diff_value === null ? "сверка компании не выполнена" : "макс " + formatByn(d.recon_max_diff_value)} />
      <Card href="/erp/wms/movements" icon={<RefreshCw size={15} />} label="Записей прихода за дату" value={formatNumber(d.movement_rows_today_in)} tone="text-green-600" />
      <Card href="/erp/wms/movements" icon={<RefreshCw size={15} />} label="Записей расхода за дату" value={formatNumber(d.movement_rows_today_out)} tone="text-red-600" />
    </div>
  </div>;
}
