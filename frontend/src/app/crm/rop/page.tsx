import { AppShell } from "@/components/app-shell";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Avatar, Bar, BAR_TONE, BORDER_TONE, Card, Caption, Dot, Tag, TEXT_TONE } from "@/components/rop/ui";
import { formatByn } from "@/lib/format";
import {
  accuracy,
  accuracyNote,
  attention,
  focus,
  focusFootnote,
  focusSummary,
  forecast,
  funnel,
  funnelNote,
  movement,
  movementNet,
  overviewKpis,
  team,
  teamTotal,
} from "@/lib/rop-data";

const funnelMax = Math.max(...funnel.map((f) => f.count));

export default function RopOverviewPage() {
  return (
    <AppShell crumbs={["CRM", "РОП · Обзор"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          {/* Заголовок */}
          <div>
            <h1 className="text-xl font-bold text-ink">Обзор РОП — прогноз и здоровье воронки</h1>
            <p className="mt-1 text-sm text-muted">
              Когорта рядом с канбаном · валюта — бел. руб. (BYN). Внизу — фокусные сделки (Итерация 1).
            </p>
          </div>

          <RopTabs active="overview" />

          <div className="flex items-center justify-between">
            <Caption>Июнь 2026 · Отдел продаж</Caption>
          </div>

          {/* KPI-полоса */}
          <Card className="!p-0">
            <div className="grid grid-cols-2 divide-x divide-y divide-slate-100 sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
              {overviewKpis.map((k) => (
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

          {/* Точность прогноза + движение пайплайна */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Точность прогноза (план → факт)</Caption>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {accuracy.map((m) => (
                  <Tag key={m.label} tone={m.tone}>
                    {m.label} · {m.value}
                  </Tag>
                ))}
              </div>
              <p className="mt-3 text-sm text-muted">{accuracyNote}</p>
            </Card>

            <Card>
              <Caption>Движение пайплайна за неделю</Caption>
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
                {movement.map((m) => (
                  <span key={m.label} className="flex items-center gap-1.5 text-sm">
                    <Dot tone={m.tone} />
                    <span className="text-ink">{m.label}</span>
                    <span className={`font-semibold ${TEXT_TONE[m.tone]}`}>{m.value}</span>
                  </span>
                ))}
              </div>
              <p className="mt-3 text-sm font-semibold text-emerald-600">{movementNet}</p>
            </Card>
          </div>

          {/* Прогноз + воронка */}
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Прогноз */}
            <Card>
              <div className="flex items-center justify-between">
                <Caption>Прогноз на июнь по категориям</Caption>
                <span className="text-xs font-semibold text-muted">План {formatByn(forecast.plan)}</span>
              </div>

              <div className="mt-4 flex h-6 w-full overflow-hidden rounded-md bg-slate-100">
                {forecast.parts
                  .filter((p) => p.inBar)
                  .map((p) => (
                    <div
                      key={p.id}
                      className={`h-full ${BAR_TONE[p.tone]}`}
                      style={{ width: `${(p.amount / forecast.plan) * 100}%` }}
                      title={`${p.label}: ${formatByn(p.amount)}`}
                    />
                  ))}
              </div>
              <div className="mt-1 text-right text-[11px] text-muted">
                до плана {formatByn(forecast.toPlan)}
              </div>

              <div className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
                {forecast.parts.map((p) => (
                  <div key={p.id} className="flex items-center gap-2 text-sm">
                    <Dot tone={p.tone} />
                    <span className="text-ink">{p.label}</span>
                    <span className="ml-auto flex items-baseline gap-1">
                      <span className="font-semibold text-ink">{formatByn(p.amount)}</span>
                      <span className="text-xs text-muted">({p.count})</span>
                    </span>
                  </div>
                ))}
              </div>

              <p className="mt-3 text-sm text-muted">
                Прогноз (закрыто + обязательство + лучший) = {formatByn(forecast.forecastSum)} · покрытие{" "}
                {forecast.coverage} (норма 3–5×) · вся воронка {forecast.pipelineTotal}.
              </p>
              <div className="mt-3 rounded-xl bg-amber-50 p-3 text-sm leading-snug text-amber-800">
                {forecast.warn}
              </div>
            </Card>

            {/* Воронка */}
            <Card>
              <Caption>Где люди — сколько сейчас на этапах</Caption>
              <div className="mt-3 space-y-3">
                {funnel.map((r) => (
                  <div key={r.stage}>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-ink">{r.stage}</span>
                      <span className="flex items-center gap-2">
                        <span className="font-semibold text-ink">{r.count}</span>
                        {r.conv && <span className="text-xs text-muted">{r.conv}</span>}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <Bar percent={(r.count / funnelMax) * 100} tone={r.tone} />
                      {r.bottleneck && <Tag tone="red">узкое место</Tag>}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-sm font-semibold text-red-600">{funnelNote}</p>
            </Card>
          </div>

          {/* Внимание + команда */}
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Требуют внимания */}
            <Card>
              <Caption>Требуют внимания РОПа · {attention.length}</Caption>
              <div className="mt-3 space-y-2.5">
                {attention.map((d) => (
                  <div key={d.name} className={`rounded-r-lg border-l-2 pl-3 ${BORDER_TONE[d.tone]}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-ink">{d.name}</span>
                      <span className="text-sm font-semibold text-teal-700">{d.amount}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                      <Tag tone={d.tone}>{d.note}</Tag>
                      {d.action && (
                        <div className="flex gap-1.5">
                          <button className="rounded-lg bg-teal-600 px-3 py-1 text-xs font-semibold text-white">
                            Согласовать
                          </button>
                          <button className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600">
                            Отклонить
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            {/* Команда */}
            <Card>
              <Caption>Команда · июнь (BYN)</Caption>
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-slate-400">
                    <th className="pb-2 text-left font-semibold">Менеджер</th>
                    <th className="pb-2 text-right font-semibold">В работе</th>
                    <th className="pb-2 text-right font-semibold">Обязат.</th>
                    <th className="pb-2 text-right font-semibold">% плана</th>
                    <th className="pb-2 text-right font-semibold">Звонки</th>
                  </tr>
                </thead>
                <tbody>
                  {team.map((t) => (
                    <tr key={t.name} className="border-t border-slate-100">
                      <td className="py-2">
                        <span className="flex items-center gap-2">
                          <Avatar name={t.name} />
                          <span className="font-medium text-ink">{t.name}</span>
                        </span>
                      </td>
                      <td className="py-2 text-right tabular-nums text-ink">{t.inWork}</td>
                      <td className="py-2 text-right tabular-nums text-ink">{t.commit}</td>
                      <td className="py-2">
                        <span className="flex items-center justify-end gap-2">
                          <Bar percent={t.plan} tone={t.planTone} className="w-14" />
                          <span className={`w-9 text-right font-semibold ${TEXT_TONE[t.planTone]}`}>
                            {t.plan}%
                          </span>
                        </span>
                      </td>
                      <td className="py-2 text-right tabular-nums text-ink">{t.calls}</td>
                    </tr>
                  ))}
                  <tr className="border-t border-slate-200 font-bold text-ink">
                    <td className="py-2">Итого</td>
                    <td className="py-2 text-right tabular-nums">{teamTotal.inWork}</td>
                    <td className="py-2 text-right tabular-nums text-teal-700">{teamTotal.commit}</td>
                    <td className="py-2 text-right tabular-nums text-amber-600">{teamTotal.plan}%</td>
                    <td className="py-2 text-right tabular-nums">{teamTotal.calls}</td>
                  </tr>
                </tbody>
              </table>
            </Card>
          </div>

          {/* AI фокусные сделки */}
          <Card className="border-l-4 border-violet-400">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Caption className="text-violet-600">Ассистент РОП · фокусные сделки</Caption>
              <Tag tone="violet">Итерация 1 · ИИ</Tag>
            </div>
            <p className="mt-2 text-sm text-muted">{focusSummary}</p>

            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-slate-400">
                    <th className="pb-2 text-left font-semibold">Сделка</th>
                    <th className="pb-2 text-right font-semibold">Сумма</th>
                    <th className="pb-2 text-center font-semibold">Вероятн.</th>
                    <th className="pb-2 text-left font-semibold">Риск</th>
                    <th className="pb-2 text-left font-semibold">Рекомендация ИИ</th>
                    <th className="pb-2 text-right font-semibold">Прогноз</th>
                  </tr>
                </thead>
                <tbody>
                  {focus.map((d) => (
                    <tr key={d.name} className="border-t border-slate-100">
                      <td className="py-2 font-medium text-ink">{d.name}</td>
                      <td className="py-2 text-right tabular-nums text-ink">{d.amount}</td>
                      <td className="py-2 text-center">
                        <Tag tone={d.probTone}>{d.prob}</Tag>
                      </td>
                      <td className="py-2">
                        <Tag tone={d.riskTone}>{d.risk}</Tag>
                      </td>
                      <td className="py-2 text-slate-600">{d.rec}</td>
                      <td className="py-2 text-right text-muted">{d.date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-slate-400">{focusFootnote}</p>
          </Card>
        </div>
      </main>
    </AppShell>
  );
}
