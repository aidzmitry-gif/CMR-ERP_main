"use client";

import type { FieldProvenance } from "@/lib/reference-data";
import { formatAuditDate, sourceMeta } from "@/lib/spravochniki-card";

// Тон бейджа источника → пары классов (стандартная палитра Tailwind; в тёмной теме
// светлые фоны слегка приглушаются глобально — как у существующего бейджа «Активен»).
export const TONE_CLASS: Record<string, string> = {
  egr: "bg-emerald-50 text-emerald-700",
  erp: "bg-violet-50 text-violet-700",
  manual: "bg-sunken text-muted",
  onec: "bg-blue-50 text-blue-700",
  bitrix: "bg-amber-50 text-amber-700",
};

/** Бейдж происхождения поля (M2): иконка + источник, дата — нативным title-tooltip. */
export function ProvenanceBadge({ prov }: { prov: FieldProvenance | undefined }) {
  if (!prov) return null;
  const meta = sourceMeta(prov.source);
  const date = prov.at ? formatAuditDate(prov.at) : null;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${TONE_CLASS[meta.tone]}`}
      title={`Источник: ${meta.label}${date ? ` · ${date}` : ""}`}
    >
      <span aria-hidden>{meta.icon}</span>
      {meta.label}
    </span>
  );
}

/** Поле «подпись + значение в плашке» с бейджем источника справа от подписи. */
export function Field({
  label,
  value,
  prov,
  mono = false,
  className = "",
}: {
  label: string;
  value: React.ReactNode;
  prov?: FieldProvenance;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-muted">{label}</p>
        <ProvenanceBadge prov={prov} />
      </div>
      <div className={`mt-1 rounded-xl bg-sunken px-3 py-2 text-sm text-ink ${mono ? "font-mono" : ""}`}>
        {value}
      </div>
    </div>
  );
}
