import { Check, CheckSquare, Square } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Bar, Card, Caption, Tag } from "@/components/rop/ui";
import {
  improvements,
  improvementsNote,
  lossQueue,
  lossQueueNorm,
  lossReasons,
  lossReasonsNote,
  lossReview,
} from "@/lib/rop-data";

const lossMax = Math.max(...lossReasons.map((r) => r.percent));

export default function RopLossReviewPage() {
  return (
    <AppShell crumbs={["CRM", "РОП", "Ревью проигрышей"]}>
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-[1220px] space-y-4">
          {/* Заголовок */}
          <div>
            <h1 className="text-xl font-bold text-ink">Ревью закрытия сделок — контроль РОПа</h1>
            <p className="mt-1 text-sm text-muted">
              Каждая «условно проигранная» проходит разбор РОПом: вернуть или извлечь урок. Продавец не
              ставит оценку себе сам.
            </p>
          </div>

          <RopTabs active="loss" />

          {/* Поток статусов */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full bg-sunken px-3 py-1 text-muted">Активна</span>
            <span className="text-faint">→</span>
            <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700 ring-1 ring-amber-200">
              Условно проиграна · проверка РОПа ≤ 24 ч
            </span>
            <span className="text-faint">→</span>
            <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
              Возврат в работу
            </span>
            <span className="text-faint">или</span>
            <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-600">
              Проиграна (с уроком)
            </span>
          </div>

          {/* Очередь + разбор */}
          <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
            {/* Очередь */}
            <Card>
              <Caption>Условно проиграна · проверка · {lossQueue.length}</Caption>
              <div className="mt-3 space-y-2">
                {lossQueue.map((item) => (
                  <div
                    key={item.id}
                    className={`rounded-xl border p-3 ${
                      item.selected ? "border-accent bg-accent-soft" : "border-line"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-ink">{item.name}</span>
                      <span className="text-sm font-semibold text-teal-700">{item.amount}</span>
                    </div>
                    <div className="mt-1.5">
                      <Tag tone="amber">{item.reason}</Tag>
                    </div>
                    <div
                      className={`mt-1.5 text-xs ${
                        item.waitTone === "red" ? "font-semibold text-red-600" : "text-muted"
                      }`}
                    >
                      {item.wait}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-faint">{lossQueueNorm}</p>
            </Card>

            {/* Разбор сделки */}
            <Card>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-base font-bold text-ink">Разбор сделки: {lossReview.name}</h2>
                  <p className="mt-0.5 text-xs text-muted">{lossReview.meta}</p>
                </div>
                <span className="shrink-0 text-sm font-bold text-teal-700">{lossReview.amount}</span>
              </div>

              <hr className="my-3 border-line" />

              <Caption>На каком этапе ушёл</Caption>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Tag tone="amber">{lossReview.reason}</Tag>
                <span className="text-sm text-muted">{lossReview.competitor}</span>
                <button className="text-sm font-medium text-accent-ink">изменить причину</button>
              </div>

              <Caption className="mt-4">Что можно было сделать лучше</Caption>
              <ul className="mt-2 space-y-1.5">
                {lossReview.better.map((b) => (
                  <li key={b} className="flex items-start gap-2 text-sm text-muted">
                    <Check size={16} className="mt-0.5 shrink-0 text-emerald-600" />
                    {b}
                  </li>
                ))}
              </ul>

              <hr className="my-3 border-line" />

              <Caption>Можно ли вернуть сделку?</Caption>
              <div className="mt-2 flex flex-wrap gap-2">
                <button className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white">
                  Да, попробуем вернуть
                </button>
                <button className="rounded-lg border border-line px-4 py-2 text-sm font-semibold text-muted">
                  Нет — проиграна
                </button>
              </div>

              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {/* Win-back */}
                <div className="flex flex-col">
                  <Caption className="text-emerald-600">Если можно вернуть — план win-back</Caption>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {lossReview.winback.map((w, i) => (
                      <span
                        key={w}
                        className={`rounded-lg px-2.5 py-1 text-xs ${
                          i === 0
                            ? "bg-emerald-50 font-semibold text-emerald-700"
                            : "border border-line text-muted"
                        }`}
                      >
                        {w}
                      </span>
                    ))}
                  </div>
                  <button className="mt-3 rounded-lg bg-teal-600 px-3 py-2 text-sm font-semibold text-white">
                    Вернуть в работу — этап «Переговоры»
                  </button>
                </div>

                {/* Уроки */}
                <div className="flex flex-col">
                  <Caption className="text-red-600">Если нет — что улучшить, чтобы не повторить</Caption>
                  <ul className="mt-2 space-y-1.5">
                    {lossReview.lessons.map((l) => (
                      <li key={l.text} className="flex items-start gap-2 text-sm text-muted">
                        {l.done ? (
                          <CheckSquare size={16} className="mt-0.5 shrink-0 text-emerald-600" />
                        ) : (
                          <Square size={16} className="mt-0.5 shrink-0 text-faint" />
                        )}
                        {l.text}
                      </li>
                    ))}
                  </ul>
                  <button className="mt-3 rounded-lg border border-red-200 px-3 py-2 text-sm font-semibold text-red-600">
                    Закрыть как проиграна + поставить задачи
                  </button>
                </div>
              </div>
            </Card>
          </div>

          {/* Причины + трекер улучшений */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <Caption>Причины проигрышей за месяц</Caption>
              <div className="mt-3 space-y-2.5">
                {lossReasons.map((r) => (
                  <div key={r.label} className="flex items-center gap-3 text-sm">
                    <span className="w-40 shrink-0 text-ink">{r.label}</span>
                    <Bar percent={(r.percent / lossMax) * 100} tone={r.tone} className="flex-1" />
                    <span className="w-9 text-right font-semibold text-ink">{r.percent}%</span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-sm font-semibold text-red-600">{lossReasonsNote}</p>
            </Card>

            <Card>
              <Caption>Что улучшаем (по разборам)</Caption>
              <div className="mt-3 divide-y divide-line">
                {improvements.map((i) => (
                  <div key={i.text} className="flex items-center gap-3 py-2.5">
                    <span className="flex-1 text-sm text-ink">{i.text}</span>
                    <Tag tone="slate">{i.owner}</Tag>
                    <Tag tone={i.statusTone}>{i.status}</Tag>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-faint">{improvementsNote}</p>
            </Card>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
