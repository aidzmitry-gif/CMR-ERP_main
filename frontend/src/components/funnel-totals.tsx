import { formatMoney } from "@/lib/format";
import type { FunnelData } from "@/lib/funnel";

export function FunnelTotals({
  data,
  fmt = formatMoney,
}: {
  data: FunnelData;
  fmt?: (value: number) => string;
}) {
  const items = [
    { label: "Сделок в работе", value: String(data.activeCount) },
    { label: "Сумма в работе", value: fmt(data.activeSum) },
    { label: "Выиграно сделок", value: String(data.wonCount) },
    { label: "Сумма выигранных", value: fmt(data.wonSum) },
    { label: "Проиграно сделок", value: String(data.lostCount) },
    { label: "Конверсия (win rate)", value: `${data.conversion.toFixed(1)}%` },
  ];

  return (
    <div className="mt-4 rounded-xl bg-surface p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold text-ink">Итоги по воронке</h3>
        <span className="text-xs text-muted">По всем сделкам</span>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {items.map((t) => (
          <div key={t.label}>
            <div className="text-xs text-muted">{t.label}</div>
            <div className="mt-1 text-2xl font-bold text-ink">{t.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
