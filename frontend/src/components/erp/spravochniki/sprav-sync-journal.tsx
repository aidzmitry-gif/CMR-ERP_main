"use client";

import { ArrowUpFromLine } from "lucide-react";

import type { SyncJournalEntry } from "@/lib/reference-data";
import { formatTouchTs, syncEntityLabel, syncStateMeta } from "@/lib/spravochniki-card";

const STATE_TONE: Record<string, string> = {
  ok: "bg-emerald-50 text-emerald-700",
  wait: "bg-amber-50 text-amber-700",
  err: "bg-red-50 text-red-700",
};

export function SpravSyncJournal({ entries }: { entries: SyncJournalEntry[] }) {
  const pending = entries.filter((e) => e.state === "pending").length;
  const errors = entries.filter((e) => e.state === "error").length;
  const synced = entries.filter((e) => e.state === "synced").length;

  return (
    <div className="flex-1 overflow-y-auto bg-canvas p-6">
      <div className="mx-auto max-w-5xl space-y-4">

        {/* Header */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
                <ArrowUpFromLine className="h-5 w-5 text-faint" />
                Журнал синхронизации с 1С
              </h1>
              <p className="mt-1 text-sm text-muted">
                Исходящая выгрузка мастер-данных ERP → 1С (M3). ERP — система-истина: запись,
                рождённая здесь, ставится в очередь и доезжает в 1С. Реальная запись в 1С пока
                отключена — выгрузка идёт через каркас-шлюз.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-[12px]">
              <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-emerald-700">
                выгружено: <b>{synced}</b>
              </span>
              <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-700">
                в очереди: <b>{pending}</b>
              </span>
              <span className="rounded-full bg-red-50 px-2.5 py-1 text-red-700">
                ошибок: <b>{errors}</b>
              </span>
            </div>
          </div>
        </div>

        {/* Journal table */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
            Последние выгрузки
          </p>
          {entries.length === 0 ? (
            <p className="mt-3 text-sm text-muted">
              Очередь пуста — нет записей на выгрузку. Записи попадают сюда из «Создать здесь» или
              ручной переотправки.
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                    <th className="px-3 py-2 font-semibold">Сущность</th>
                    <th className="px-3 py-2 font-semibold">Куда</th>
                    <th className="px-3 py-2 font-semibold">Статус</th>
                    <th className="px-3 py-2 font-semibold">Внешний id</th>
                    <th className="px-3 py-2 font-semibold">Когда</th>
                    <th className="px-3 py-2 font-semibold">Ошибка</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {entries.map((e) => {
                    const st = syncStateMeta(e.state);
                    return (
                      <tr key={e.id} className="hover:bg-sunken/60">
                        <td className="px-3 py-2.5">
                          <span className="text-ink">{syncEntityLabel(e.entity_type)}</span>
                          <span className="ml-1.5 font-mono text-[12px] text-faint">#{e.entity_id}</span>
                        </td>
                        <td className="px-3 py-2.5 font-mono text-[13px] text-muted">{e.system}</td>
                        <td className="px-3 py-2.5">
                          <span
                            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATE_TONE[st.tone]}`}
                          >
                            {st.label}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 font-mono text-[13px] text-muted">
                          {e.external_ref ?? "—"}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-[13px] text-muted">
                          {e.last_synced_at ? formatTouchTs(e.last_synced_at) : "—"}
                        </td>
                        <td className="px-3 py-2.5 text-[13px] text-red-700">{e.error_text ?? ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 border-t border-line pt-3 text-[11px] text-faint">
            «в очереди» — ждёт выгрузки; «ошибка» — 1С отклонила или запись не найдена (ручной
            повтор). Реальная запись в 1С включается без правки UI, когда ERP станет источником
            истины мастер-данных.
          </p>
        </div>

      </div>
    </div>
  );
}
