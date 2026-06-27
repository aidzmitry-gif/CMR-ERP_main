"use client";

import clsx from "clsx";
import { AlertTriangle, ClipboardCheck, Boxes, PackageCheck, RefreshCw, Scale, Truck } from "lucide-react";
import Link from "next/link";

import { SourceTag } from "@/components/source-tag";
import { formatByn, formatNumber } from "@/lib/format";
import type { Dashboard } from "@/lib/wms-warehouse";

function Card({
  href, icon, label, value, tone, sub, source,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: string;
  sub?: string;
  source?: boolean;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-line bg-surface px-4 py-3.5 transition-colors hover:border-accent"
    >
      <div className="flex items-center gap-2 text-muted">
        {icon}
        <span className="text-xs font-medium">{label}</span>
      </div>
      <div className={clsx("mt-1.5 text-2xl font-bold tabular-nums", tone ?? "text-ink")}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-faint">{sub}</div>}
      {source && <div className="mt-1"><SourceTag entity="Остаток" source="1c" /></div>}
    </Link>
  );
}

export function WmsDashboard({ initial }: { initial: Dashboard }) {
  const d = initial;
  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">
          Сводка склада. Метрики со <SourceTag entity="" source="1c" /> считаются против зеркала 1С
          (истина остатка); WMS дублирует движения.
        </p>
        <Link href="/erp/wms/operations" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken">
          Воронка операций →
        </Link>
      </div>

      {!d.gateway && (
        <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          Источник 1С не подключён — метрики сверки и дефицита недоступны.
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Card href="/erp/wms/receipts" icon={<PackageCheck size={15} />} label="Приёмки в очереди QC"
              value={formatNumber(d.receipts_pending_qc)} tone={d.receipts_pending_qc ? "text-amber-600" : undefined} />
        <Card href="/erp/wms/tasks" icon={<ClipboardCheck size={15} />} label="Размещение (put-away)"
              value={formatNumber(d.tasks_putaway_open)} sub="открытых задач" />
        <Card href="/erp/wms/tasks" icon={<Truck size={15} />} label="Подбор (pick)"
              value={formatNumber(d.tasks_pick_open)} sub="открытых задач" />
        <Card href="/erp/wms/inventory" icon={<Boxes size={15} />} label="Инвентаризации"
              value={formatNumber(d.inventories_open)} sub="открытых" />
        <Card href="/erp/wms/alerts" icon={<AlertTriangle size={15} />} label="Дефицит (low-stock)"
              value={formatNumber(d.alerts_count)} tone={d.alerts_count ? "text-red-600" : undefined} source />
        <Card href="/erp/wms/reconciliation" icon={<Scale size={15} />} label="Расхождение с 1С"
              value={formatByn(d.recon_total_diff_value)} tone={d.recon_total_diff_value ? "text-red-600" : undefined}
              sub={`макс ${formatByn(d.recon_max_diff_value)}`} source />
        <Card href="/erp/wms/movements" icon={<RefreshCw size={15} />} label="Приход сегодня"
              value={formatNumber(d.movements_today_in)} tone="text-green-600" />
        <Card href="/erp/wms/movements" icon={<RefreshCw size={15} />} label="Расход сегодня"
              value={formatNumber(d.movements_today_out)} tone="text-red-600" />
      </div>
    </div>
  );
}
