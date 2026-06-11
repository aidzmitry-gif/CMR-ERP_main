import { AppShell } from "@/components/app-shell";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Avatar, Bar, Card, Caption, Dot, Tag, TEXT_TONE } from "@/components/rop/ui";
import {
  ageBuckets,
  ageBucketsNote,
  managerAging,
  managerAgingNote,
  managerAgingTotal,
  stageAging,
  stageAgingNote,
  stageKpis,
  stageSla,
  stageSlaNote,
  stuckDeals,
} from "@/lib/rop-stages-data";

const stageMax = Math.max(...stageAging.map((s) => s.avgDays));
const bucketMax = Math.max(...ageBuckets.map((b) => b.count));

export default function RopStagesPage() {
  return (
    <AppShell crumbs={["CRM", "РОП", "Этапы воронки"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          <div>
            <h1 className="text-xl font-bold text-ink">Этапы воронки · старение сделок</h1>
            <p className="mt-1 text-sm text-muted">
              Где сделки застревают и теряют темп. Время на этапе против норматива, узкие места
              конверсии и «протухающие» сделки без следующего шага. Валюта — BYN.
            </p>
          </div>

          <RopTabs active="stages" />

          <div className="flex items-center justify-between">
            <Caption>Июнь 2026 · Отдел продаж</Caption>
          </div>

          {/* KPI-полоса */}
          <Card className="!p-0">
            <div className="grid grid-cols-2 divide-x divide-y divide-slate-100 sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
              {stageKpis.map((k) => (
                <div key={k.label} className="p-4">
                  <div className={`text-lg font-bold ${k.tone ? TEXT_TONE[k.tone] : "text-ink"}`}>
                    {k.value}
                  </div>
                  <div className="mt-1 text-[11px] leading-tight text-muted">{k.label}</div>
                  <div className="text-[10px] text-slate-400">{k.sub}</div>
                </div>
              ))}
            </div>
          </Card>

          {/* Старение по этапам — центр экрана */}
          <Card>
            <Caption>Старение по этапам · время на этапе против норматива</Caption>
            <div className="mt-3 space-y-3">
              {stageAging.map((s) => (
                <div key={s.stage} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
                  <span className="flex w-52 shrink-0 items-center gap-2">
                    <span className="font-medium text-ink">{s.stage}</span>
                    <span className="text-[11px] text-slate-400">{s.count} сд.</span>
                  </span>
                  <Bar percent={(s.avgDays / stageMax) * 100} tone={s.tone} className="min-w-[120px] flex-1" />
                  <span className="w-32 text-right tabular-nums text-ink">
                    <span className={s.over ? `font-semibold ${TEXT_TONE[s.tone]}` : "font-semibold"}>
                      {s.avgDays} дн
                    </span>
                    <span className="text-[11px] text-slate-400"> · {s.norm}</span>
                  </span>
                  <span className="w-20 text-right">
                    {s.conv === "—" ? (
                      <span className="text-[11px] text-slate-300">старт</span>
                    ) : (
                      <Tag tone={s.tone}>{s.conv}</Tag>
                    )}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-sm font-semibold text-red-600">{stageAgingNote}</p>
          </Card>

          {/* Корзины старения + застрявшие сделки */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Возраст сделок на текущем этапе</Caption>
              <div className="mt-3 space-y-2.5">
                {ageBuckets.map((b) => (
                  <div key={b.bucket} className="flex items-center gap-3 text-sm">
                    <span className="w-44 shrink-0 text-ink">{b.bucket}</span>
                    <Bar percent={(b.count / bucketMax) * 100} tone={b.tone} className="flex-1" />
                    <span className="w-16 text-right font-semibold tabular-nums text-ink">
                      {b.count} сд.
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-sm font-semibold text-amber-600">{ageBucketsNote}</p>
            </Card>

            <Card>
              <Caption>Застрявшие сделки · требуют следующего шага</Caption>
              <div className="mt-3 space-y-2.5">
                {stuckDeals.map((d) => (
                  <div key={d.name} className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0">
                      <span className="text-sm font-semibold text-ink">{d.name}</span>
                      <span className="ml-2 text-[11px] text-slate-400">{d.owner}</span>
                      <span className="mt-1 flex items-center gap-2">
                        <Tag tone={d.tone}>{d.stage}</Tag>
                        <span className="text-[11px] text-muted">{d.reason}</span>
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className={`text-sm font-semibold tabular-nums ${TEXT_TONE[d.tone]}`}>
                        {d.age}
                      </span>
                      {d.action && (
                        <button className="rounded-lg bg-teal-600 px-3 py-1 text-xs font-semibold text-white">
                          {d.action}
                        </button>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          {/* Старение по менеджерам + SLA по этапам */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Старение по менеджерам</Caption>
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-slate-400">
                    <th scope="col" className="pb-2 text-left font-semibold">Менеджер</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Сделок</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Ср. возраст</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Застряли</th>
                  </tr>
                </thead>
                <tbody>
                  {managerAging.map((m) => (
                    <tr key={m.name} className="border-t border-slate-100 align-top">
                      <td className="py-2.5">
                        <span className="flex items-center gap-2">
                          <Avatar name={m.name} />
                          <span className="font-medium text-ink">{m.name}</span>
                        </span>
                        <div className="ml-9 text-[11px] text-muted">{m.note}</div>
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-ink">{m.count}</td>
                      <td className={`py-2.5 text-right font-semibold tabular-nums ${TEXT_TONE[m.tone]}`}>
                        {m.avgDays}
                      </td>
                      <td className={`py-2.5 text-right tabular-nums ${TEXT_TONE[m.tone]}`}>{m.stuck}</td>
                    </tr>
                  ))}
                  <tr className="border-t border-slate-200 font-bold text-ink">
                    <td className="py-2.5">Итого</td>
                    <td className="py-2.5 text-right tabular-nums">{managerAgingTotal.count}</td>
                    <td className="py-2.5 text-right tabular-nums text-amber-600">{managerAgingTotal.avgDays}</td>
                    <td className="py-2.5 text-right tabular-nums text-red-600">{managerAgingTotal.stuck}</td>
                  </tr>
                </tbody>
              </table>
              <p className="mt-3 text-xs text-slate-400">{managerAgingNote}</p>
            </Card>

            <Card>
              <Caption>SLA по этапам — как расшить старение</Caption>
              <ul className="mt-3 grid gap-1.5">
                {stageSla.map((r) => (
                  <li key={r} className="flex items-start gap-2 text-sm text-ink">
                    <span className="mt-1.5">
                      <Dot tone="teal" />
                    </span>
                    {r}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-slate-400">{stageSlaNote}</p>
            </Card>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
