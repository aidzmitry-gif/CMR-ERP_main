"use client";

import { useState } from "react";

import { decideApproval, type ApprovalRow } from "@/lib/reference-data";

/** ISO → ДД.ММ.ГГГГ ЧЧ:ММ; null → «—». */
function fmt(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
}

export function SpravAdmin({ initial }: { initial: ApprovalRow[] }) {
  const [rows, setRows] = useState<ApprovalRow[]>(initial);
  const [busy, setBusy] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2500);
  }

  async function decide(id: number, approve: boolean) {
    setBusy(id);
    const ok = await decideApproval(id, approve);
    setBusy(null);
    if (ok) {
      setRows((prev) => prev.filter((r) => r.id !== id));
      flash(approve ? "Правка одобрена" : "Правка отклонена");
    } else {
      flash("Ошибка: нет права на согласование или сервер недоступен");
    }
  }

  return (
    <div className="space-y-4">
      {toast && (
        <div className="fixed right-6 top-6 z-50 rounded-xl bg-ink px-4 py-2 text-sm text-white shadow-card">
          {toast}
        </div>
      )}

      <div className="rounded-2xl bg-accent-soft/60 px-4 py-2.5 text-[12px] text-muted">
        <span className="font-semibold text-accent-ink">Модерация справочников.</span>{" "}
        Чувствительные правки (ставка НДС, пошлина ТН ВЭД) применяются только после согласования —
        human-in-the-loop через общий движок согласований.
      </div>

      {rows.length === 0 ? (
        <div className="rounded-2xl bg-surface p-8 text-center shadow-card">
          <p className="text-sm font-medium text-muted">Очередь пуста</p>
          <p className="mt-2 text-[12px] text-faint">
            Нет правок справочников, ожидающих согласования.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl bg-surface shadow-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                <th className="px-4 py-2 font-semibold">Что меняется</th>
                <th className="px-4 py-2 font-semibold">Объект</th>
                <th className="px-4 py-2 font-semibold">Роль</th>
                <th className="px-4 py-2 font-semibold">Запросил</th>
                <th className="px-4 py-2 font-semibold">Создано</th>
                <th className="px-4 py-2 text-right font-semibold">Действие</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((a) => (
                <tr key={a.id} className="hover:bg-sunken/40">
                  <td className="px-4 py-2.5 text-ink">{a.subject}</td>
                  <td className="px-4 py-2.5 font-mono text-[12px] text-muted">{a.entity_ref}</td>
                  <td className="px-4 py-2.5">
                    <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
                      {a.route}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-muted">{a.requested_by || "—"}</td>
                  <td className="px-4 py-2.5 tabular-nums text-faint">{fmt(a.created_at)}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex justify-end gap-1.5">
                      <button
                        onClick={() => void decide(a.id, true)}
                        disabled={busy !== null}
                        className="rounded-lg bg-emerald-600 px-2.5 py-1 text-[12px] font-semibold text-white disabled:opacity-50"
                      >
                        {busy === a.id ? "…" : "Одобрить"}
                      </button>
                      <button
                        onClick={() => void decide(a.id, false)}
                        disabled={busy !== null}
                        className="rounded-lg bg-surface px-2.5 py-1 text-[12px] font-medium text-rose-600 shadow-card ring-1 ring-line disabled:opacity-50"
                      >
                        Отклонить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
