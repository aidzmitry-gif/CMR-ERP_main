import { Sparkles } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Avatar, Bar, Card, Caption, Dot, Tag, TEXT_TONE } from "@/components/rop/ui";
import {
  aiForecast,
  aiHeader,
  aiRecs,
  discountLeak,
  leakageNote,
  managerMargins,
  managerMarginsNote,
  marginAvg,
  marginMix,
  marginPendingNote,
  paceAiFootnote,
  paceBadge,
  paceHeader,
  paceMeters,
  profitLeversDept,
  profitLeversManagers,
  velocity,
  velocityFooter,
} from "@/lib/rop-data";

export default function RopPacePage() {
  return (
    <AppShell crumbs={["CRM", "РОП", "Темп"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          <div>
            <h1 className="text-xl font-bold text-ink">Темп · прибыль и скорость сделок</h1>
            <p className="mt-1 text-sm text-muted">
              Пульс (факт к дате, прогноз) → диагностика (скорость, маржа) → ИИ-рекомендации (Итерация 1)
              → рычаги прибыли по отделу и менеджерам. Валюта — BYN.
            </p>
          </div>

          <RopTabs active="pace" />

          {/* Пульс темпа */}
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Caption>{paceHeader}</Caption>
              <Tag tone="amber">{paceBadge}</Tag>
            </div>
            <div className="mt-3 grid gap-5 md:grid-cols-3">
              {paceMeters.map((m) => (
                <div key={m.label}>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{m.label}</span>
                    <Tag tone={m.stateTone}>{m.state}</Tag>
                  </div>
                  <Bar percent={m.percent} tone={m.stateTone} className="mt-2" />
                  <div className="mt-2 text-[12px] text-slate-600">{m.toDate}</div>
                  <div className="text-[11px] text-slate-400">
                    {m.forecast}
                    {m.note && <span className={`ml-1 font-semibold ${TEXT_TONE[m.noteTone ?? "slate"]}`}>· {m.note}</span>}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Sales velocity */}
          <Card>
            <Caption>Скорость сделок (sales velocity) · оборот в день</Caption>
            <p className="mt-2 break-words text-sm text-ink">
              {velocity.formula} ={" "}
              <span className="font-bold text-teal-700">{velocity.result}</span>
            </p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              {velocity.cells.map((c) => (
                <div
                  key={c.label}
                  className={`rounded-xl border p-3 ${
                    c.accent ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50"
                  }`}
                >
                  <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {c.label}
                  </div>
                  <div className={`mt-1 text-lg font-bold ${c.accent ? "text-amber-700" : "text-ink"}`}>
                    {c.value}
                  </div>
                  {c.badge && (
                    <span className="mt-1 inline-block">
                      <Tag tone={c.badgeTone ?? "slate"}>{c.badge}</Tag>
                    </span>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-3 text-sm font-semibold text-emerald-600">{velocity.highlight}</p>
            <p className="mt-1 text-xs text-muted">{velocity.note}</p>
          </Card>

          {/* ИИ-рекомендации (Итерация 1, ghost) */}
          <div className="rounded-2xl border border-dashed border-violet-300 bg-violet-50 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <Sparkles size={15} className="text-violet-500" />
                <Caption className="text-violet-600">{aiHeader}</Caption>
              </span>
              <Tag tone="violet">Итерация 1 · ИИ (позже)</Tag>
            </div>
            <p className="mt-2 text-xs text-violet-400">{aiForecast}</p>
            <div className="mt-3 space-y-2">
              {aiRecs.map((r) => (
                <div key={r.n} className="flex items-start justify-between gap-3">
                  <span className="text-sm text-violet-700">
                    <span className="font-semibold">{r.n} ·</span> {r.text}
                  </span>
                  <span className="shrink-0">
                    <Tag tone="violet">{r.badge}</Tag>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Маржа/утечка + рычаги прибыли */}
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Маржа (ждёт себестоимости) и измеримая скидка от прайса */}
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Caption>Маржа и скидки</Caption>
                <Tag tone="violet">demo · ждёт себестоимости</Tag>
              </div>
              <p className="mt-2 text-[12px] text-violet-500">{marginPendingNote}</p>

              <div className="mt-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-ink">{marginAvg.label}</span>
                  <span className={`font-semibold ${TEXT_TONE[marginAvg.valueTone]}`}>{marginAvg.value}</span>
                </div>
                <Bar percent={marginAvg.percent} tone={marginAvg.tone} className="mt-1.5" />
              </div>

              <hr className="my-3 border-slate-100" />

              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-ink">
                  Скидка от прайса <span className="text-[11px] font-normal text-teal-600">· измеримо</span>
                </span>
                <span className="font-semibold text-amber-600">{discountLeak.value}</span>
              </div>
              <p className="mt-1 text-[12px] text-muted">{discountLeak.note}</p>

              <hr className="my-3 border-slate-100" />

              <div>
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-ink">{marginMix.label}</span>
                  <span className={`font-semibold ${TEXT_TONE[marginMix.valueTone]}`}>{marginMix.value}</span>
                </div>
                <Bar percent={marginMix.percent} tone={marginMix.tone} className="mt-1.5" />
              </div>

              <hr className="my-3 border-slate-100" />

              <Caption>Маржа по менеджерам</Caption>
              <div className="mt-2 space-y-2">
                {managerMargins.map((m) => (
                  <div key={m.name} className="flex items-center gap-3 text-sm">
                    <span className="w-24 shrink-0 text-ink">{m.name}</span>
                    <Bar percent={m.percent} tone={m.tone} className="flex-1" />
                    <span className={`w-10 text-right font-semibold ${TEXT_TONE[m.tone]}`}>{m.margin}</span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[12px] font-semibold text-red-600">{managerMarginsNote}</p>
              <p className="mt-2 text-xs text-slate-400">{leakageNote}</p>
            </Card>

            {/* Рычаги прибыли */}
            <Card>
              <Caption>Рычаги прибыли — отдел</Caption>
              <ul className="mt-3 space-y-1.5">
                {profitLeversDept.map((l) => (
                  <li key={l} className="flex items-start gap-2 text-sm text-ink">
                    <span className="mt-1.5">
                      <Dot tone="teal" />
                    </span>
                    {l}
                  </li>
                ))}
              </ul>

              <hr className="my-3 border-slate-100" />

              <Caption>Рычаги прибыли — менеджеры</Caption>
              <div className="mt-2 divide-y divide-slate-100">
                {profitLeversManagers.map((m) => (
                  <div key={m.name} className="py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2">
                        <Avatar name={m.name} />
                        <span className="text-sm font-semibold text-ink">{m.name}</span>
                      </span>
                      <Tag tone={m.badgeTone}>{m.badge}</Tag>
                    </div>
                    <div className="mt-1 text-[12px] text-muted">{m.text}</div>
                  </div>
                ))}
              </div>

              <hr className="my-3 border-slate-100" />
              <p className="text-xs font-semibold text-slate-600">{velocityFooter}</p>
              <p className="mt-1 text-xs text-slate-400">{paceAiFootnote}</p>
            </Card>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
