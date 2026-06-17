import { AppShell } from "@/components/app-shell";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Avatar, Bar, Card, Caption, Dot, Tag, TEXT_TONE } from "@/components/rop/ui";
import { formatByn } from "@/lib/format";
import {
  aging,
  agingNote,
  calendar,
  calendarNote,
  cashDiscipline,
  cashDisciplineNote,
  cashKpis,
  debtors,
  managerDso,
  managerDsoTotal,
} from "@/lib/rop-data";

const agingMax = Math.max(...aging.map((a) => a.amount));

export default function RopCashPage() {
  return (
    <AppShell crumbs={["CRM", "РОП", "Деньги · дебиторка"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          <div>
            <h1 className="text-xl font-bold text-ink">Деньги · дебиторка и поступления</h1>
            <p className="mt-1 text-sm text-muted">
              Отгрузили с прибылью ≠ получили оплату. Старение задолженности, платёжный календарь и
              DSO по менеджерам. Валюта — BYN.
            </p>
          </div>

          <RopTabs active="cash" />

          <div className="flex items-center justify-between">
            <Caption>Июнь 2026 · Отдел продаж</Caption>
          </div>

          {/* KPI-полоса */}
          <Card className="!p-0">
            <div className="grid grid-cols-2 divide-x divide-y divide-line sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
              {cashKpis.map((k) => (
                <div key={k.label} className="p-4">
                  <div className={`text-lg font-bold ${k.tone ? TEXT_TONE[k.tone] : "text-ink"}`}>
                    {k.value}
                  </div>
                  <div className="mt-1 text-[11px] leading-tight text-muted">{k.label}</div>
                  <div className="text-[10px] text-faint">{k.sub}</div>
                </div>
              ))}
            </div>
          </Card>

          {/* Старение + платёжный календарь */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Старение дебиторки (по дням просрочки)</Caption>
              <div className="mt-3 space-y-2.5">
                {aging.map((a) => (
                  <div key={a.bucket} className="flex items-center gap-3 text-sm">
                    <span className="w-40 shrink-0 text-ink">{a.bucket}</span>
                    <Bar percent={(a.amount / agingMax) * 100} tone={a.tone} className="flex-1" />
                    <span className="w-24 text-right font-semibold tabular-nums text-ink">
                      {formatByn(a.amount)}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-sm font-semibold text-red-600">{agingNote}</p>
            </Card>

            <Card>
              <Caption>Платёжный календарь (поступления)</Caption>
              <div className="mt-3 space-y-3">
                {calendar.map((w) => (
                  <div key={w.week}>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-ink">{w.week}</span>
                      <span className="flex items-center gap-2">
                        <span className="font-semibold tabular-nums text-ink">{w.amount}</span>
                        <Tag tone={w.tone}>{w.state}</Tag>
                      </span>
                    </div>
                    <Bar percent={w.percent} tone={w.tone} className="mt-1.5" />
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-faint">{calendarNote}</p>
            </Card>
          </div>

          {/* Топ дебиторов + DSO по менеджерам */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Топ дебиторов · требуют сбора</Caption>
              <div className="mt-3 space-y-2.5">
                {debtors.map((d) => (
                  <div key={d.name} className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0">
                      <span className="text-sm font-semibold text-ink">{d.name}</span>
                      <span className="ml-2 text-[11px] text-faint">{d.owner}</span>
                      <span className="mt-1 block">
                        <Tag tone={d.statusTone}>{d.status}</Tag>
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
            </Card>

            <Card>
              <Caption>DSO по менеджерам (BYN)</Caption>
              <table className="mt-3 w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-faint">
                    <th scope="col" className="pb-2 text-left font-semibold">Менеджер</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Долг</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Просрочка</th>
                    <th scope="col" className="pb-2 text-right font-semibold">DSO</th>
                  </tr>
                </thead>
                <tbody>
                  {managerDso.map((m) => (
                    <tr key={m.name} className="border-t border-line align-top">
                      <td className="py-2.5">
                        <span className="flex items-center gap-2">
                          <Avatar name={m.name} />
                          <span className="font-medium text-ink">{m.name}</span>
                        </span>
                        <div className="ml-9 text-[11px] text-muted">{m.note}</div>
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-ink">{m.debt}</td>
                      <td className={`py-2.5 text-right tabular-nums ${m.overdue === "0" ? "text-muted" : `font-semibold ${TEXT_TONE[m.tone]}`}`}>
                        {m.overdue}
                      </td>
                      <td className={`py-2.5 text-right font-semibold tabular-nums ${TEXT_TONE[m.tone]}`}>
                        {m.dso}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-line font-bold text-ink">
                    <td className="py-2.5">Итого</td>
                    <td className="py-2.5 text-right tabular-nums">{managerDsoTotal.debt}</td>
                    <td className="py-2.5 text-right tabular-nums text-red-600">{managerDsoTotal.overdue}</td>
                    <td className="py-2.5 text-right tabular-nums text-amber-600">{managerDsoTotal.dso}</td>
                  </tr>
                </tbody>
              </table>
            </Card>
          </div>

          {/* Дисциплина платежей */}
          <Card>
            <Caption>Дисциплина платежей — правила</Caption>
            <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
              {cashDiscipline.map((r) => (
                <li key={r} className="flex items-start gap-2 text-sm text-ink">
                  <span className="mt-1.5">
                    <Dot tone="teal" />
                  </span>
                  {r}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-faint">{cashDisciplineNote}</p>
          </Card>
        </div>
      </main>
    </AppShell>
  );
}
