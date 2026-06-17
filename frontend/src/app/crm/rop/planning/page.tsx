import { AppShell } from "@/components/app-shell";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Avatar, Bar, Card, Caption, Dot, Tag, TEXT_TONE } from "@/components/rop/ui";
import {
  capacity,
  capacityNote,
  capacityTotal,
  conversionLevers,
  leversNote,
  planActions,
  planCards,
  planCardsNote,
  planNorm,
  planRule,
} from "@/lib/rop-data";

export default function RopPlanningPage() {
  return (
    <AppShell crumbs={["CRM", "РОП", "Планирование"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          <div>
            <h1 className="text-xl font-bold text-ink">
              Планирование месяца — нагрузка и план действий
            </h1>
            <p className="mt-1 text-sm text-muted">
              Три плана: контракты · прибыль по отгрузке · поступление денег. По каждому менеджеру —
              хватает ли воронки, брать ли новые сделки и где коучинг. Валюта — BYN.
            </p>
          </div>

          <RopTabs active="planning" />

          <div className="flex items-center justify-between">
            <Caption>Июнь 2026 · Отдел продаж</Caption>
          </div>

          {/* Модель плана: 4 карты */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {planCards.map((c) => (
              <Card key={c.label} className={c.accent ? "border-l-4 border-violet-400" : undefined}>
                <Caption>{c.label}</Caption>
                <div className={`mt-2 text-base font-bold ${c.accent ? "text-ink" : TEXT_TONE[c.tone]}`}>
                  {c.value}
                </div>
                {c.note && <div className="mt-1 text-[11px] text-muted">{c.note}</div>}
                {!c.accent && <Bar percent={c.percent} tone={c.tone} className="mt-3" />}
                <div className="mt-2 text-[11px] text-amber-700">{c.gap}</div>
              </Card>
            ))}
          </div>
          <p className="text-xs text-faint">{planCardsNote}</p>

          {/* Ёмкость по менеджерам */}
          <Card>
            <Caption>Хватает ли воронки под план (BYN)</Caption>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[920px] text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-faint">
                    <th scope="col" className="pb-2 text-left font-semibold">Менеджер</th>
                    <th scope="col" className="pb-2 text-right font-semibold">План</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Прогноз</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Разрыв</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Воронка взвеш.</th>
                    <th scope="col" className="pb-2 text-center font-semibold">Win%</th>
                    <th scope="col" className="pb-2 text-left font-semibold">Вердикт</th>
                    <th scope="col" className="pb-2 text-left font-semibold">Коучинг</th>
                  </tr>
                </thead>
                <tbody>
                  {capacity.map((r) => (
                    <tr key={r.name} className="border-t border-line align-top">
                      <td className="py-3">
                        <span className="flex items-center gap-2">
                          <Avatar name={r.name} />
                          <span className="font-medium text-ink">{r.name}</span>
                        </span>
                      </td>
                      <td className="py-3 text-right tabular-nums text-ink">{r.plan}</td>
                      <td className="py-3 text-right tabular-nums text-ink">{r.forecast}</td>
                      <td className={`py-3 text-right font-semibold tabular-nums ${TEXT_TONE[r.gapTone]}`}>
                        {r.gap}
                      </td>
                      <td className={`py-3 text-right tabular-nums ${r.pipelineTone ? `font-semibold ${TEXT_TONE[r.pipelineTone]}` : "text-ink"}`}>
                        {r.pipeline}
                      </td>
                      <td className={`py-3 text-center tabular-nums ${r.winTone ? `font-semibold ${TEXT_TONE[r.winTone]}` : "text-ink"}`}>
                        {r.win}
                      </td>
                      <td className="py-3">
                        <Tag tone={r.verdictTone}>{r.verdict}</Tag>
                        <div className="mt-1 text-[11px] text-muted">{r.verdictNote}</div>
                      </td>
                      <td className="py-3">
                        <div className="text-[12px] text-muted">{r.stage}</div>
                        <div className="text-[11px] text-faint">{r.coaching}</div>
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-line-strong font-bold text-ink">
                    <td className="py-3">Итого</td>
                    <td className="py-3 text-right tabular-nums">{capacityTotal.plan}</td>
                    <td className="py-3 text-right tabular-nums">{capacityTotal.forecast}</td>
                    <td className="py-3 text-right tabular-nums text-amber-700">{capacityTotal.gap}</td>
                    <td className="py-3 text-right tabular-nums">{capacityTotal.pipeline}</td>
                    <td className="py-3 text-center text-muted">—</td>
                    <td className="py-3" />
                    <td className="py-3" />
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-faint">{capacityNote}</p>
          </Card>

          {/* План действий + рычаги конверсии */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>План действий на июнь</Caption>
              <ul className="mt-3 space-y-2.5">
                {planActions.map((a) => (
                  <li key={a.who} className="flex items-start gap-2.5 text-sm">
                    <span className="mt-1.5">
                      <Dot tone={a.tone} />
                    </span>
                    <span className="text-ink">
                      <span className="font-semibold">{a.who}</span> — {a.text}
                    </span>
                  </li>
                ))}
              </ul>
              <hr className="my-3 border-line" />
              <p className="text-xs text-faint">{planRule}</p>
              <p className="mt-1 text-xs text-faint">{planNorm}</p>
            </Card>

            <Card>
              <Caption>Рычаги конверсии по этапам</Caption>
              <div className="mt-3 divide-y divide-line">
                {conversionLevers.map((l) => (
                  <div key={l.title} className="py-2.5">
                    <div className="text-sm font-semibold text-ink">{l.title}</div>
                    <div className="mt-0.5 text-[12px] text-muted">{l.text}</div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-faint">{leversNote}</p>
            </Card>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
