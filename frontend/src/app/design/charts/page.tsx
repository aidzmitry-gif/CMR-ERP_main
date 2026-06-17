import { Card, CardHeader, CardBody, Badge } from "@/components/ui";

/**
 * ДЕМО: как будут выглядеть графики для анализа в нашем стиле (Stripe/Notion).
 * Нарисованы на чистом SVG/CSS на токенах — БЕЗ chart-библиотеки (выбор recharts/tremor
 * сделаем при встройке в продукт). Цель — показать вид и палитру. Открыть: /design/charts
 */

// ── палитра графиков (из токенов) ──
const C = {
  money: "#0F9D58",
  accent: "#635BFF",
  teal: "#0E9384",
  amber: "#F59E0B",
  red: "#DC2626",
  line: "#ECECF0",
  faint: "#9BA0A8",
};

// данные (демо, BYN)
const revenue = [
  { m: "Янв", rev: 180, margin: 42 },
  { m: "Фев", rev: 210, margin: 51 },
  { m: "Мар", rev: 195, margin: 47 },
  { m: "Апр", rev: 240, margin: 63 },
  { m: "Май", rev: 228, margin: 58 },
  { m: "Июн", rev: 280, margin: 74 },
];
const team = [
  { name: "Анна А.", plan: 92 },
  { name: "Дмитрий Д.", plan: 74 },
  { name: "Мария М.", plan: 61 },
  { name: "Сергей С.", plan: 48 },
];
const funnel = [
  { stage: "Квалификация", v: 68, tone: C.accent },
  { stage: "Коммерч. предл.", v: 38, tone: C.accent },
  { stage: "Согласование", v: 14, tone: C.red },
  { stage: "Договор", v: 9, tone: C.teal },
  { stage: "Закрыто", v: 6, tone: C.money },
];
const profit = [
  { label: "АКБ", v: 52, tone: C.money },
  { label: "Доставка", v: 18, tone: C.teal },
  { label: "Услуги", v: 20, tone: C.accent },
  { label: "Прочее", v: 10, tone: C.amber },
];

export default function ChartsDemoPage() {
  return (
    <main className="mx-auto max-w-[1160px] space-y-4 p-6">
      <header>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">Демо · графики для анализа</p>
        <h1 className="mt-1 text-xl font-bold tracking-tight">Как будут выглядеть графики</h1>
        <p className="mt-1 text-sm text-muted">
          В стиле Stripe/Notion на наших токенах. Деньги/маржа — зелёным (приоритет №1). Нарисовано на SVG для
          показа вида; в продукте — на chart-библиотеке (recharts/tremor).
        </p>
      </header>

      {/* KPI со спарклайнами */}
      <div className="grid gap-4 sm:grid-cols-3">
        <SparkKpi label="Выручка · июнь" value="280 000 BYN" delta="+22%" up data={revenue.map((d) => d.rev)} color={C.accent} />
        <SparkKpi label="Маржа · июнь" value="+74 000 BYN" delta="+18%" up data={revenue.map((d) => d.margin)} color={C.money} />
        <SparkKpi label="Срыв сроков" value="12%" delta="+3 пп" data={[8, 9, 7, 11, 10, 12]} color={C.red} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Линия + площадь: выручка и маржа */}
        <Card>
          <CardHeader>
            Динамика выручки и маржи
            <span className="ml-auto flex gap-3 text-[11px]">
              <Legend color={C.accent} label="Выручка" />
              <Legend color={C.money} label="Маржа" />
            </span>
          </CardHeader>
          <CardBody>
            <LineAreaChart data={revenue} />
          </CardBody>
        </Card>

        {/* Бары: план/факт по менеджерам */}
        <Card>
          <CardHeader>% плана по менеджерам<span className="ml-auto text-[11px] text-muted">июнь</span></CardHeader>
          <CardBody>
            <div className="space-y-3 pt-1">
              {team.map((t) => {
                const tone = t.plan >= 85 ? C.money : t.plan >= 60 ? C.amber : C.red;
                return (
                  <div key={t.name}>
                    <div className="flex items-center justify-between text-sm">
                      <span>{t.name}</span>
                      <span className="font-semibold tabular-nums" style={{ color: tone }}>{t.plan}%</span>
                    </div>
                    <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-[#EEEEF1]">
                      <div className="h-full rounded-full transition-all" style={{ width: `${t.plan}%`, background: tone }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardBody>
        </Card>

        {/* Горизонтальная воронка */}
        <Card>
          <CardHeader>Воронка — сколько на этапах</CardHeader>
          <CardBody>
            <div className="space-y-2.5 pt-1">
              {funnel.map((f) => (
                <div key={f.stage} className="flex items-center gap-3">
                  <span className="w-32 flex-shrink-0 text-[13px] text-muted">{f.stage}</span>
                  <div className="h-7 flex-1 overflow-hidden rounded-lg bg-[#F4F4F7]">
                    <div
                      className="flex h-full items-center justify-end rounded-lg pr-2 text-[11px] font-bold text-white tabular-nums"
                      style={{ width: `${(f.v / funnel[0].v) * 100}%`, background: f.tone }}
                    >
                      {f.v}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

        {/* Донат: структура прибыли */}
        <Card>
          <CardHeader>Структура прибыли по позициям</CardHeader>
          <CardBody>
            <div className="flex items-center gap-6">
              <DonutChart data={profit} />
              <div className="space-y-2">
                {profit.map((p) => (
                  <div key={p.label} className="flex items-center gap-2 text-sm">
                    <span className="size-2.5 rounded-full" style={{ background: p.tone }} />
                    <span className="text-muted">{p.label}</span>
                    <span className="ml-auto font-semibold tabular-nums">{p.v}%</span>
                  </div>
                ))}
              </div>
            </div>
          </CardBody>
        </Card>
      </div>
    </main>
  );
}

// ── KPI со спарклайном ──
function SparkKpi({ label, value, delta, up, data, color }: { label: string; value: string; delta: string; up?: boolean; data: number[]; color: string }) {
  const max = Math.max(...data), min = Math.min(...data);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * 100},${28 - ((v - min) / (max - min || 1)) * 24}`).join(" ");
  return (
    <Card className="p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">{label}</div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <span className="text-lg font-bold tabular-nums tracking-tight">{value}</span>
        <svg viewBox="0 0 100 30" className="h-8 w-24" preserveAspectRatio="none">
          <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
        </svg>
      </div>
      <div className="mt-1 text-[11px] font-semibold tabular-nums" style={{ color: up ? C.money : C.red }}>
        {up ? "▲" : "▼"} {delta}
      </div>
    </Card>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-muted">
      <span className="size-2 rounded-full" style={{ background: color }} /> {label}
    </span>
  );
}

// ── Линия + площадь (выручка + маржа) ──
function LineAreaChart({ data }: { data: { m: string; rev: number; margin: number }[] }) {
  const W = 480, H = 180, P = 28;
  const max = Math.max(...data.map((d) => d.rev)) * 1.1;
  const x = (i: number) => P + (i / (data.length - 1)) * (W - P * 2);
  const y = (v: number) => H - P - (v / max) * (H - P * 2);
  const path = (key: "rev" | "margin") => data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d[key])}`).join(" ");
  const area = `${path("rev")} L${x(data.length - 1)},${H - P} L${x(0)},${H - P} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      <defs>
        <linearGradient id="rev-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.accent} stopOpacity="0.18" />
          <stop offset="100%" stopColor={C.accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* сетка */}
      {[0, 0.5, 1].map((g) => (
        <line key={g} x1={P} x2={W - P} y1={P + g * (H - P * 2)} y2={P + g * (H - P * 2)} stroke={C.line} strokeWidth="1" />
      ))}
      <path d={area} fill="url(#rev-fill)" />
      <path d={path("rev")} fill="none" stroke={C.accent} strokeWidth="2.5" />
      <path d={path("margin")} fill="none" stroke={C.money} strokeWidth="2.5" />
      {data.map((d, i) => (
        <g key={d.m}>
          <circle cx={x(i)} cy={y(d.rev)} r="3" fill="#fff" stroke={C.accent} strokeWidth="2" />
          <circle cx={x(i)} cy={y(d.margin)} r="3" fill="#fff" stroke={C.money} strokeWidth="2" />
          <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="10" fill={C.faint}>{d.m}</text>
        </g>
      ))}
    </svg>
  );
}

// ── Донат ──
function DonutChart({ data }: { data: { label: string; v: number; tone: string }[] }) {
  const total = data.reduce((s, d) => s + d.v, 0);
  const R = 52, SW = 18, C0 = 2 * Math.PI * R;
  let acc = 0;
  return (
    <svg viewBox="0 0 130 130" className="size-[130px] flex-shrink-0 -rotate-90">
      <circle cx="65" cy="65" r={R} fill="none" stroke="#EEEEF1" strokeWidth={SW} />
      {data.map((d) => {
        const len = (d.v / total) * C0;
        const seg = (
          <circle
            key={d.label}
            cx="65" cy="65" r={R} fill="none" stroke={d.tone} strokeWidth={SW}
            strokeDasharray={`${len} ${C0 - len}`} strokeDashoffset={-acc}
          />
        );
        acc += len;
        return seg;
      })}
    </svg>
  );
}
