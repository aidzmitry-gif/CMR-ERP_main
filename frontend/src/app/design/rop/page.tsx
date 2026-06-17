import { Card, CardHeader, CardBody, Badge, Button, type BadgeTone } from "@/components/ui";
import { overviewKpis, attention, team, teamTotal, type Tone } from "@/lib/rop-data";

/**
 * ДЕМО (не продакшн-экран): как будет выглядеть Обзор РОП на новых примитивах
 * components/ui + токены Stripe/Notion. Реальный /crm/rop НЕ тронут.
 * Данные — реальный мок rop-data. Открыть: /design/rop
 */

// мост старой палитры rop-data → наши тоны бейджа
const toneMap: Record<Tone, BadgeTone> = {
  green: "emerald",
  teal: "teal",
  amber: "amber",
  red: "red",
  violet: "violet",
  blue: "accent",
  slate: "slate",
};

export default function RopDemoPage() {
  return (
    <main className="mx-auto max-w-[1160px] space-y-4 p-6">
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">Демо · РОП на новых примитивах</p>
          <h1 className="mt-1 text-xl font-bold tracking-tight">Обзор РОП — июнь 2026</h1>
        </div>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" size="sm">Экспорт</Button>
          <Button variant="secondary" size="sm">Настроить</Button>
        </div>
      </header>

      {/* KPI-полоса */}
      <Card>
        <div className="grid grid-cols-2 divide-x divide-y divide-line sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
          {overviewKpis.map((k) => (
            <div key={k.label} className="p-4">
              <div
                className={cnTone(k.tone)}
              >
                {k.value}
              </div>
              <div className="mt-1 text-[11px] leading-tight text-muted">{k.label}</div>
              <div className="text-[10px] text-faint">{k.sub}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Требуют внимания */}
        <Card>
          <CardHeader>
            Требуют внимания РОПа
            <Badge tone="slate" className="ml-auto">{attention.length}</Badge>
          </CardHeader>
          <CardBody className="space-y-2.5">
            {attention.map((a) => (
              <div key={a.name} className="rounded-r-lg border-l-2 border-line-strong pl-3" style={borderByTone(a.tone)}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold">{a.name}</span>
                  <span className="text-sm font-semibold tabular-nums text-money">{a.amount}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                  <Badge tone={toneMap[a.tone]}>{a.note}</Badge>
                  {a.action && (
                    <div className="flex gap-1.5">
                      <Button variant="money" size="sm">Согласовать</Button>
                      <Button variant="secondary" size="sm">Отклонить</Button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>

        {/* Команда */}
        <Card>
          <CardHeader>Команда · июнь (BYN)</CardHeader>
          <CardBody>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-faint">
                  <th className="pb-2 text-left font-semibold">Менеджер</th>
                  <th className="pb-2 text-right font-semibold">В работе</th>
                  <th className="pb-2 text-right font-semibold">Обязат.</th>
                  <th className="pb-2 text-right font-semibold">% плана</th>
                  <th className="pb-2 text-right font-semibold">Звонки</th>
                </tr>
              </thead>
              <tbody>
                {team.map((m) => (
                  <tr key={m.name} className="border-t border-line">
                    <td className="py-2">
                      <span className="flex items-center gap-2">
                        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-ink">
                          {m.name[0]}
                        </span>
                        <span className="font-medium">{m.name}</span>
                      </span>
                    </td>
                    <td className="py-2 text-right tabular-nums">{m.inWork}</td>
                    <td className="py-2 text-right tabular-nums">{m.commit}</td>
                    <td className="py-2 text-right">
                      <Badge tone={toneMap[m.planTone]}>{m.plan}%</Badge>
                    </td>
                    <td className="py-2 text-right tabular-nums">{m.calls}</td>
                  </tr>
                ))}
                <tr className="border-t border-line-strong font-bold">
                  <td className="py-2">Итого</td>
                  <td className="py-2 text-right tabular-nums">{teamTotal.inWork}</td>
                  <td className="py-2 text-right tabular-nums text-money">{teamTotal.commit}</td>
                  <td className="py-2 text-right tabular-nums text-[#B45309]">{teamTotal.plan}%</td>
                  <td className="py-2 text-right tabular-nums">{teamTotal.calls}</td>
                </tr>
              </tbody>
            </table>
          </CardBody>
        </Card>
      </div>
    </main>
  );
}

// крупное KPI-число с цветом по тону (teal=прогноз, red=риск, иначе ink)
function cnTone(tone?: Tone): string {
  const base = "text-lg font-bold tabular-nums tracking-tight";
  if (tone === "teal") return `${base} text-[#0E9384]`;
  if (tone === "red") return `${base} text-[#DC2626]`;
  return `${base} text-ink`;
}

function borderByTone(tone: Tone): React.CSSProperties {
  const map: Record<Tone, string> = {
    red: "#F87171",
    amber: "#FBBF24",
    violet: "#C4B5FD",
    green: "#34D399",
    teal: "#5EEAD4",
    blue: "#93C5FD",
    slate: "#CBD5E1",
  };
  return { borderColor: map[tone] };
}
