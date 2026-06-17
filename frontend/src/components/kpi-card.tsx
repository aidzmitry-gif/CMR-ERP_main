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

export function KpiCard({ kpi, onLog }: { kpi: Kpi; onLog?: () => void }) {
  const Icon = ICONS[kpi.icon];
  const tone = TONES[kpi.tone];
  const value = kpi.money ? formatMoney(kpi.value) : kpi.value;
  const target = kpi.money ? formatMoney(kpi.target) : kpi.target;

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
        <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${kpi.percent}%` }} />
      </div>
      <div className="mt-1.5 text-xs text-muted">{kpi.percent}% выполнено</div>
    </div>
  );
}
