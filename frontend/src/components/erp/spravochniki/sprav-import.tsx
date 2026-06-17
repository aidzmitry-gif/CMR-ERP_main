"use client";

import { RefreshCw } from "lucide-react";
import { Fragment, useState } from "react";

import { formatSyncSummary, type SyncSummary } from "@/lib/spravochniki-import";

// ── Demo data (static, no backend) ───────────────────────────────────────────

const MAPPING_ROWS = [
  { src: "Наименование", dst: "title", type: "string", keyBadge: null },
  { src: "ИНН/УНП", dst: "unp", type: "string", keyBadge: "🔑 ключ сопоставления" },
  { src: "Код 1С", dst: "alias_1c", type: "string, вторичный alias", keyBadge: "alias" },
  { src: "ВидКонтрагента", dst: "type", type: "enum", keyBadge: null },
  { src: "Телефон", dst: "phone", type: "string", keyBadge: null },
] as const;

type PreviewAction = "new" | "update" | "merge" | "conflict";

const PREVIEW_ROWS: { name: string; unp: string; action: PreviewAction; comment: string }[] = [
  { name: "ООО «Аккум-Сервис»", unp: "192556210", action: "new", comment: "Будет создана эталонная запись" },
  { name: "ЗАО «Энергополюс»", unp: "100345678", action: "update", comment: "Совпал по УНП → CP-000312, обновлён телефон" },
  { name: "ООО «Старт»", unp: "191234567", action: "merge", comment: "Совпал с CP-001045 — будет склеен как алиас" },
  { name: "ИП Ковалёв А.С.", unp: "490112233", action: "new", comment: "Будет создана эталонная запись" },
  { name: "ООО «Прогресс-Бат»", unp: "—", action: "conflict", comment: "УНП пуст — пропуск (нет natural key)" },
  { name: "ОДО «ТехноЛайн»", unp: "191007788", action: "update", comment: "Совпал по УНП → CP-000877, обновлён адрес" },
];

const ACTION_BADGE: Record<PreviewAction, { cls: string; label: string }> = {
  new: { cls: "bg-emerald-50 text-emerald-700", label: "Новый" },
  update: { cls: "bg-blue-50 text-blue-700", label: "Обновление" },
  merge: { cls: "bg-amber-50 text-amber-700", label: "Дубль → merge" },
  conflict: { cls: "bg-rose-50 text-rose-700", label: "Конфликт" },
};

const ROW_HIGHLIGHT: Record<PreviewAction, string> = {
  new: "",
  update: "",
  merge: "bg-amber-50/40",
  conflict: "bg-rose-50/40",
};

const STEPPER = [
  { n: 1, label: "Источник", state: "done" as const },
  { n: 2, label: "Маппинг полей", state: "done" as const },
  { n: 3, label: "Предпросмотр и конфликты", state: "active" as const },
  { n: 4, label: "Импорт", state: "idle" as const },
];

const HOW_IT_WORKS = [
  {
    icon: "🔑",
    title: "Идемпотентность по natural key УНП.",
    body: "Повторный импорт того же файла не плодит дубли — записи находятся по УНП и обновляются на месте.",
  },
  {
    icon: "↧",
    title: "id 1С — вторичный alias.",
    body: "«Код 1С» хранится как alias_1c, не как первичный идентификатор; ссылки документов идут на эталон ERP.",
  },
  {
    icon: "★",
    title: "Golden record.",
    body: "Дубли склеиваются в одну эталонную запись, исходники остаются алиасами; merge обратим, все правки — в аудит.",
  },
  {
    icon: "🔒",
    title: "При отказе от 1С адаптер просто выключается.",
    body: "Система-источник данных — ERP; структура и записи не меняются, перестаёт поступать только входной поток.",
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function stepClass(state: "done" | "active" | "idle") {
  if (state === "done") return "flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2 font-medium text-emerald-700";
  if (state === "active") return "flex items-center gap-2 rounded-xl bg-accent-soft px-3 py-2 font-semibold text-accent-ink";
  return "flex items-center gap-2 rounded-xl bg-sunken px-3 py-2 font-medium text-faint";
}

function stepNumClass(state: "done" | "active" | "idle") {
  if (state === "done") return "flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-[11px]";
  if (state === "active") return "flex h-5 w-5 items-center justify-center rounded-full bg-accent text-[11px] text-white";
  return "flex h-5 w-5 items-center justify-center rounded-full bg-line-strong text-[11px] text-muted";
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SpravImport() {
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncSummary | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  async function handleSync() {
    setSyncing(true);
    setSyncError(null);
    try {
      const res = await fetch("/api/integrations/1c/sync", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as SyncSummary;
      setSyncResult(data);
    } catch (e) {
      setSyncError(e instanceof Error ? e.message : "Ошибка синхронизации");
    } finally {
      setSyncing(false);
    }
  }

  const summaryItems = syncResult ? formatSyncSummary(syncResult) : null;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-[1100px] space-y-4">

        {/* Header */}
        <div>
          <h1 className="text-xl font-bold text-ink">Импорт из 1С — контрагенты</h1>
          <p className="mt-1 text-sm text-muted">
            Сопоставление по natural key (УНП), идемпотентно. Повторный запуск не плодит дубли.
          </p>
        </div>

        {/* Adapter warning banner */}
        <div className="rounded-2xl bg-amber-50 px-4 py-3 text-[12px] text-amber-800 ring-1 ring-amber-200">
          <span className="font-semibold">↧ 1С — временный входной источник</span> через шлюз{" "}
          <span className="font-mono">integrations</span>. Владелец и система-источник данных —{" "}
          <span className="font-semibold">ERP</span>. Отключение 1С = выключить адаптер, без изменения структуры данных.
        </div>

        {/* ── LIVE: Sync card ─────────────────────────────────────────────────── */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">LIVE</div>
              <h2 className="mt-0.5 text-base font-semibold text-ink">Синхронизация с 1С</h2>
            </div>
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white shadow-card disabled:opacity-60"
            >
              <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
              {syncing ? "Синхронизируется…" : "Синхронизировать"}
            </button>
          </div>

          {syncError && (
            <div className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">
              {syncError}
            </div>
          )}

          {summaryItems && (
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {summaryItems.map((item) => (
                <div key={item.label} className="rounded-xl bg-sunken px-3 py-2.5">
                  <div className="text-xl font-bold text-ink">{item.value.toLocaleString("ru-RU")}</div>
                  <div className="mt-0.5 text-[12px] text-muted">{item.label}</div>
                </div>
              ))}
            </div>
          )}

          {!syncResult && !syncError && (
            <p className="mt-3 text-[12px] text-muted">
              Нажмите «Синхронизировать», чтобы запустить синк и получить итоги.
            </p>
          )}
        </div>

        {/* ── DEMO section label ──────────────────────────────────────────────── */}
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
            ДЕМО
          </span>
          <span className="text-[12px] text-muted">
            Маппинг, предпросмотр конфликтов и импорт — демо-прототип; бэкенд для этих шагов не реализован (gap C).
          </span>
        </div>

        {/* DEMO: Stepper */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            {STEPPER.map((step, i) => (
              <Fragment key={step.n}>
                {i > 0 && <div className="h-px w-6 bg-line-strong" />}
                <div className={stepClass(step.state)}>
                  <span className={stepNumClass(step.state)}>
                    {step.state === "done" ? "✓" : step.n}
                  </span>
                  <span>{step.n} · {step.label}</span>
                </div>
              </Fragment>
            ))}
          </div>
        </div>

        {/* DEMO: Field mapping (step 2 — confirmed) */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between border-b border-line pb-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Шаг 2 · подтверждено
              </div>
              <h2 className="mt-0.5 text-base font-semibold text-ink">Маппинг полей</h2>
            </div>
            <button className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line">
              Изменить маппинг
            </button>
          </div>
          <div className="mt-3 overflow-hidden rounded-xl ring-1 ring-line">
            <table className="w-full">
              <thead>
                <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                  <th className="px-3 py-2 font-semibold">Поле 1С</th>
                  <th className="px-3 py-2 font-semibold" />
                  <th className="px-3 py-2 font-semibold">Поле ERP</th>
                  <th className="px-3 py-2 font-semibold">Тип</th>
                  <th className="px-3 py-2 font-semibold">Ключ</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {MAPPING_ROWS.map((row) => (
                  <tr
                    key={row.dst}
                    className={
                      row.dst === "unp"
                        ? "bg-amber-50/40 hover:bg-amber-50/60"
                        : "hover:bg-sunken/60"
                    }
                  >
                    <td className="px-3 py-2.5 text-sm">{row.src}</td>
                    <td className="px-3 py-2.5 text-center text-faint">→</td>
                    <td className="px-3 py-2.5 font-mono text-[13px] text-muted">{row.dst}</td>
                    <td className="px-3 py-2.5 text-sm text-muted">{row.type}</td>
                    <td className="px-3 py-2.5">
                      {row.keyBadge && (
                        <span
                          className={
                            row.keyBadge === "alias"
                              ? "rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted"
                              : "rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700"
                          }
                        >
                          {row.keyBadge}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* DEMO: Preview + conflicts (step 3 — current) */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Шаг 3 · текущий
              </div>
              <h2 className="mt-0.5 text-base font-semibold text-ink">Предпросмотр (218 строк)</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">Новых 140</span>
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">Обновлений 62</span>
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">Дублей → merge 14</span>
              <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] text-rose-700">Конфликтов 2</span>
            </div>
          </div>

          {/* Search bar (static demo) */}
          <div className="mt-3 flex items-center gap-3">
            <div className="flex-1 rounded-xl bg-sunken px-3 py-2">
              <input
                className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-faint"
                placeholder="Поиск по наименованию или УНП…"
                readOnly
              />
            </div>
            <button className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line">
              Только конфликты
            </button>
          </div>

          <div className="mt-3 overflow-hidden rounded-xl ring-1 ring-line">
            <table className="w-full">
              <thead>
                <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                  <th className="px-3 py-2 font-semibold">Наименование</th>
                  <th className="px-3 py-2 font-semibold">УНП</th>
                  <th className="px-3 py-2 font-semibold">Действие</th>
                  <th className="px-3 py-2 font-semibold">Комментарий</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {PREVIEW_ROWS.map((row) => {
                  const badge = ACTION_BADGE[row.action];
                  return (
                    <tr key={row.name} className={`${ROW_HIGHLIGHT[row.action]} hover:bg-sunken/60`}>
                      <td className="px-3 py-2.5 text-sm">{row.name}</td>
                      <td className="px-3 py-2.5 font-mono text-[13px] text-muted">{row.unp}</td>
                      <td className="px-3 py-2.5">
                        <span className={`rounded-full px-2 py-0.5 text-[11px] ${badge.cls}`}>
                          {badge.label}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-sm text-muted">{row.comment}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-[12px] text-muted">
            Показаны 6 из 218 строк. Конфликтные строки в импорт не попадают и помечаются для ручного разбора.
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              disabled
              className="rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card opacity-50"
            >
              Импортировать 216
            </button>
            <button
              disabled
              className="rounded-xl bg-surface px-3 py-2 text-sm font-medium text-muted shadow-card ring-1 ring-line opacity-50"
            >
              Скачать отчёт
            </button>
          </div>
        </div>

        {/* DEMO: Dry-run log */}
        <div className="rounded-2xl bg-ink p-5 text-faint shadow-card">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                Лог · сухой прогон (dry-run)
              </div>
              <div className="mt-0.5 text-sm font-semibold text-ink">Что произойдёт при импорте</div>
            </div>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
              🤖 идемпотентно
            </span>
          </div>
          <pre className="mt-3 overflow-x-auto rounded-xl bg-black/30 p-3 text-[12px] leading-relaxed text-ink">
{`scan       source=1c gateway=integrations rows=218
matched    by УНП 100345678 -> CP-000312   (update phone)
matched    by УНП 191007788 -> CP-000877   (update address)
merge      CP-000777 -> CP-001045           (УНП 191234567, alias kept)
created    CP-001312                         (УНП 192556210)
created    CP-001313                         (УНП 490112233)
alias      add alias_1c=00-0042145 -> CP-001045
skip       no УНП — конфликт                 (ООО «Прогресс-Бат»)
------------------------------------------------------------
summary    created=140 updated=62 merged=14 skipped=2  → apply=216`}
          </pre>
        </div>

        {/* DEMO: How it works */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Как это работает</div>
          <ul className="mt-2 space-y-2">
            {HOW_IT_WORKS.map((item) => (
              <li key={item.title} className="flex gap-2 text-sm text-muted">
                <span className="text-faint">{item.icon}</span>
                <span>
                  <span className="font-medium text-ink">{item.title}</span> {item.body}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="px-1 text-[11px] text-faint">
          Макет, демо-данные. Концепция — coordination/db-and-reference-data-concept.md (v3).
        </p>
      </div>
    </div>
  );
}
