import { FUNNEL_TOTALS } from "@/lib/mock-data";

export function FunnelTotals() {
  return (
    <div className="mt-4 rounded-xl bg-white p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold text-ink">Итоги по воронке</h3>
        <span className="text-xs text-muted">01.05.2024 – 31.05.2024</span>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {FUNNEL_TOTALS.map((t) => (
          <div key={t.id}>
            <div className="text-xs text-muted">{t.label}</div>
            <div className="mt-1 text-2xl font-bold text-ink">{t.value}</div>
            <div className="mt-1 text-xs font-medium text-emerald-600">{t.delta}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
