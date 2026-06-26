import { FileText, Phone, PhoneCall, Plus, RussianRuble, Snowflake } from "lucide-react";
import { formatMoney } from "@/lib/format";
import type { Kpi, KpiIcon, KpiTone } from "@/lib/types";

type IconCmp = React.ComponentType<{ size?: number }>;

const ICONS: Record<KpiIcon, IconCmp> = {
  "phone-key": PhoneCall,
  phone: Phone,
  ruble: RussianRuble,
  snow: Snowflake,
  doc: FileText,
};

const TONES: Record<KpiTone, { chip: string; bar: string }> = {
  blue: { chip: "bg-blue-50 text-blue-600", bar: "bg-blue-500" },
  indigo: { chip: "bg-indigo-50 text-indigo-600", bar: "bg-indigo-500" },
  green: { chip: "bg-emerald-50 text-emerald-600", bar: "bg-emerald-500" },
  cyan: { chip: "bg-cyan-50 text-cyan-600", bar: "bg-cyan-500" },
  slate: { chip: "bg-sunken text-muted", bar: "bg-line-strong" },
};

/** Светофор выполнения (Сделки 2.0): ≥100% — зелёный, ≥70% — янтарь, иначе красный. */
function perfTone(pct: number): { bar: string; text: string } {
  if (pct >= 100) return { bar: "bg-emerald-500", text: "text-emerald-600" };
  if (pct >= 70) return { bar: "bg-amber-500", text: "text-amber-600" };
  return { bar: "bg-red-500", text: "text-red-600" };
}

export function KpiCard({
  kpi,
  onLog,
  fmt = formatMoney,
}: {
  kpi: Kpi;
  onLog?: () => void;
  fmt?: (value: number) => string;
}) {
  const Icon = ICONS[kpi.icon];
  const tone = TONES[kpi.tone];
  const perf = perfTone(kpi.percent);
  const value = kpi.money ? fmt(kpi.value) : kpi.value;
  const target = kpi.money ? fmt(kpi.target) : kpi.target;

  return (
    <div className="rounded-xl bg-surface p-4 shadow-card">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${tone.chip}`}>
            <Icon size={16} />
          </span>
          <span className="text-xs leading-tight text-muted">{kpi.label}</span>
        </div>
        {onLog && !kpi.money && (
          <button
            onClick={onLog}
            title="Отметить (+1)"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-faint hover:bg-sunken hover:text-accent-ink"
          >
            <Plus size={15} />
          </button>
        )}
      </div>
      <div className="mt-3 text-lg font-semibold text-ink">
        {value} <span className="text-sm font-normal text-muted">/ {target}</span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-sunken">
        <div className={`h-full rounded-full ${perf.bar}`} style={{ width: `${Math.min(kpi.percent, 100)}%` }} />
      </div>
      <div className={`mt-1.5 flex items-center gap-1 text-xs ${perf.text}`}>
        <span className="text-[9px] leading-none">●</span>
        {kpi.percent}% выполнено
      </div>
    </div>
  );
}
