import { AppShell } from "@/components/app-shell";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Avatar, Bar, Card, Caption, Dot, Tag, TEXT_TONE } from "@/components/rop/ui";
import {
  activityFunnel,
  activityFunnelNote,
  activityKpis,
  activityNorms,
  activityNormsNote,
  activityRules,
  activityRulesNote,
  managerActivity,
  managerActivityNote,
  managerActivityTotal,
  staleDeals,
  staleDealsNote,
} from "@/lib/rop-activity-data";

const funnelMax = Math.max(...activityFunnel.map((s) => s.count));

export default function RopActivityPage() {
  return (
    <AppShell crumbs={["CRM", "РОП", "Активность"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          <div>
            <h1 className="text-xl font-bold text-ink">Активность · ведущие индикаторы</h1>
            <p className="mt-1 text-sm text-muted">
              Звонки, встречи, КП и реакция на лид управляемы сегодня и предсказывают выручку завтра —
              в отличие от отстающих результатов (Деньги, Этапы). Неделя 2 июня · отдел продаж.
            </p>
          </div>

          <RopTabs active="activity" />

          <div className="flex items-center justify-between">
            <Caption>Июнь 2026 · Отдел продаж</Caption>
          </div>

          {/* KPI-полоса */}
          <Card className="!p-0">
            <div className="grid grid-cols-2 divide-x divide-y divide-slate-100 sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
              {activityKpis.map((k) => (
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

          {/* Активность vs норма + цепочка активность → результат */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Активность vs норма (неделя)</Caption>
              <div className="mt-3 space-y-3">
                {activityNorms.map((n) => (
                  <div key={n.label}>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-ink">{n.label}</span>
                      <span className="font-semibold tabular-nums text-ink">
                        {n.fact} / {n.norm}
                      </span>
                    </div>
                    <Bar percent={n.percent} tone={n.tone} className="mt-1.5" />
                  </div>
                ))}
              </div>
              <p className="mt-3 text-sm font-semibold text-red-600">{activityNormsNote}</p>
            </Card>

            <Card>
              <Caption>Цепочка: активность → результат</Caption>
              <div className="mt-3 space-y-3">
                {activityFunnel.map((s) => (
                  <div key={s.label}>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-ink">{s.label}</span>
                      <span className="flex items-center gap-2">
                        <span className="font-semibold text-ink">{s.count}</span>
                        {s.conv && <span className="text-xs text-muted">{s.conv}</span>}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <Bar percent={(s.count / funnelMax) * 100} tone={s.tone} />
                      {s.bottleneck && <Tag tone="red">узкое место</Tag>}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-sm text-muted">{activityFunnelNote}</p>
            </Card>
          </div>

          {/* Активность по менеджерам + застрявшие сделки */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Активность по менеджерам (неделя)</Caption>
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-slate-400">
                    <th scope="col" className="pb-2 text-left font-semibold">Менеджер</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Звонки</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Встречи</th>
                    <th scope="col" className="pb-2 text-right font-semibold">КП</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Без шага</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Индекс</th>
                  </tr>
                </thead>
                <tbody>
                  {managerActivity.map((m) => (
                    <tr key={m.name} className="border-t border-slate-100">
                      <td className="py-2.5">
                        <span className="flex items-center gap-2">
                          <Avatar name={m.name} />
                          <span className="font-medium text-ink">{m.name}</span>
                        </span>
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-ink">{m.calls}</td>
                      <td className="py-2.5 text-right tabular-nums text-ink">{m.meetings}</td>
                      <td className="py-2.5 text-right tabular-nums text-ink">{m.kp}</td>
                      <td className={`py-2.5 text-right tabular-nums ${m.noNext === 0 ? "text-muted" : "font-semibold text-red-600"}`}>
                        {m.noNext}
                      </td>
                      <td className="py-2.5">
                        <span className="flex items-center justify-end gap-2">
                          <Bar percent={m.index} tone={m.indexTone} className="w-14" />
                          <span className={`w-8 text-right font-semibold ${TEXT_TONE[m.indexTone]}`}>
                            {m.index}
                          </span>
                        </span>
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-slate-200 font-bold text-ink">
                    <td className="py-2.5">Итого</td>
                    <td className="py-2.5 text-right tabular-nums">{managerActivityTotal.calls}</td>
                    <td className="py-2.5 text-right tabular-nums">{managerActivityTotal.meetings}</td>
                    <td className="py-2.5 text-right tabular-nums">{managerActivityTotal.kp}</td>
                    <td className="py-2.5 text-right tabular-nums text-red-600">{managerActivityTotal.noNext}</td>
                    <td className="py-2.5" />
                  </tr>
                </tbody>
              </table>
              <p className="mt-3 text-xs text-slate-400">{managerActivityNote}</p>
            </Card>

            <Card>
              <Caption>Сделки без следующего шага · гигиена воронки</Caption>
              <div className="mt-3 space-y-2.5">
                {staleDeals.map((d) => (
                  <div key={d.name} className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0">
                      <span className="text-sm font-semibold text-ink">{d.name}</span>
                      <span className="ml-2 text-[11px] text-slate-400">{d.owner}</span>
                      <span className="mt-1 block">
                        <Tag tone={d.idleTone}>{d.idle}</Tag>
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="text-sm font-semibold tabular-nums text-teal-700">{d.amount}</span>
                      {d.action && (
                        <button className="rounded-lg bg-teal-600 px-3 py-1 text-xs font-semibold text-white">
                          {d.action}
                        </button>
                      )}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-sm font-semibold text-red-600">{staleDealsNote}</p>
            </Card>
          </div>

          {/* Нормативы активности */}
          <Card>
            <Caption>Нормативы активности — правила</Caption>
            <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {activityRules.map((r) => (
                <li key={r} className="flex items-start gap-2 text-sm text-ink">
                  <span className="mt-1.5">
                    <Dot tone="teal" />
                  </span>
                  {r}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-slate-400">{activityRulesNote}</p>
          </Card>
        </div>
      </main>
    </AppShell>
  );
}
