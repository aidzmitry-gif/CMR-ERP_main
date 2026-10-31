"use client";

import { Phone, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchCallsResult, triggerIncomingCall, type CallRow, type FetchCallsResult } from "@/lib/api";
import { CALL_STATUS as STATUS } from "@/lib/call-status";

// Тестовый номер используется только в dev-сборке.
const DEMO_PHONE = "+375291112233";

export function CallsWorkspace({ initialCounterpartyId, initialCallId }: { initialCounterpartyId?: number; initialCallId?: number }) {
  const [unlinked, setUnlinked] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState<{ counterpartyId?: number; unlinked: boolean; revision: number; result: FetchCallsResult } | null>(null);
  const [busy, setBusy] = useState(false);
  const result = loaded && loaded.counterpartyId === initialCounterpartyId
    && loaded.unlinked === unlinked && loaded.revision === revision ? loaded.result : null;
  useEffect(() => {
    let current = true;
    void fetchCallsResult({ unlinked, ...(initialCounterpartyId ? { counterparty_id: initialCounterpartyId } : {}) }).then((next) => {
      if (current) setLoaded({ counterpartyId: initialCounterpartyId, unlinked, revision, result: next });
    });
    return () => { current = false; };
  }, [unlinked, revision, initialCounterpartyId]);

  useEffect(() => {
    if (!initialCallId || !result?.ok || !result.rows.some((call) => call.id === initialCallId)) return;
    const node = document.getElementById(`call-${initialCallId}`);
    if (node && typeof node.scrollIntoView === "function") node.scrollIntoView({ block: "center" });
  }, [initialCallId, result]);

  async function simulate() {
    setBusy(true);
    try {
      const sent = await triggerIncomingCall({
        call_id: `demo-${Date.now()}`,
        direction: "in",
        phone_e164: DEMO_PHONE,
      });
      if (sent) window.setTimeout(() => setRevision((value) => value + 1), 500);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1100px] space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-ink">Звонки</h1>
            <p className="mt-0.5 text-sm text-muted">
              Журнал звонков и входящие через облачную АТС. Окно звонка всплывает на любом экране.
            </p>
            {initialCounterpartyId != null && <p className="mt-1 text-xs text-muted">Фильтр по подтверждённому контрагенту ID {initialCounterpartyId}</p>}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setRevision((value) => value + 1)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken"
            >
              <RefreshCw size={15} /> Обновить
            </button>
            {process.env.NODE_ENV !== "production" && <button
              onClick={() => void simulate()}
              disabled={busy}
              title="Эмуляция события АТС (только dev): входящий с тестового номера"
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-white hover:bg-accent-ink disabled:opacity-60"
            >
              <Phone size={15} /> Симулировать входящий
            </button>}
          </div>
        </div>

        <label className="inline-flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={unlinked} onChange={(event) => setUnlinked(event.target.checked)} />
          Без привязанной сделки
        </label>

        <div className="overflow-x-auto rounded-2xl bg-surface shadow-card">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Номер</th>
                <th className="px-4 py-2.5 font-semibold">Направление</th>
                <th className="px-4 py-2.5 font-semibold">Клиент</th>
                <th className="px-4 py-2.5 font-semibold">Продавец</th>
                <th className="px-4 py-2.5 font-semibold">Статус</th>
                <th className="px-4 py-2.5 font-semibold">Итог</th>
                <th className="px-4 py-2.5 font-semibold">Время</th>
              </tr>
            </thead>
            <tbody>
              {!result && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted" role="status">
                    Загрузка звонков…
                  </td>
                </tr>
              )}
              {result && !result.ok && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-red-600" role="alert">
                    {result.error} <button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Повторить</button>
                  </td>
                </tr>
              )}
              {result?.ok && result.rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted">
                    Звонков по выбранному фильтру нет.
                  </td>
                </tr>
              )}
              {result?.ok && result.rows.map((c: CallRow) => {
                const st = STATUS[c.status] ?? STATUS.ended;
                return (
                  <tr id={`call-${c.id}`} key={c.id} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-4 py-2.5 font-medium text-ink">{c.phone_e164 ?? "—"}</td>
                    <td className="px-4 py-2.5 text-muted">
                      {c.direction === "out" ? "Исходящий" : "Входящий"}
                    </td>
                    <td className="px-4 py-2.5 text-muted">
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {Number.isSafeInteger(c.crm_client_id) && (c.crm_client_id ?? 0) > 0
                          && <Link className="underline" href={`/crm/clients/${c.crm_client_id}`}>CRM-клиент</Link>}
                        {Number.isSafeInteger(c.counterparty_id) && (c.counterparty_id ?? 0) > 0
                          && <Link className="underline" href={`/erp/spravochniki/counterparty/${c.counterparty_id}`}>Компания</Link>}
                        {Number.isSafeInteger(c.contact_id) && (c.contact_id ?? 0) > 0
                          && Number.isSafeInteger(c.counterparty_id) && (c.counterparty_id ?? 0) > 0
                          && <Link className="underline" href={`/erp/spravochniki/counterparty/${c.counterparty_id}?contact=${c.contact_id}#counterparty-contact-${c.contact_id}`}>Контакт</Link>}
                        {Number.isSafeInteger(c.deal_id) && (c.deal_id ?? 0) > 0
                          && <Link className="underline" href={`/crm/deals/${c.deal_id}`}>Сделка</Link>}
                        {!Number.isSafeInteger(c.crm_client_id) && !Number.isSafeInteger(c.counterparty_id)
                          && <span>Контекст не сопоставлен по точному ID</span>}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-muted">{c.owner || "Не назначен"}</td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${st.cls}`}
                      >
                        {st.label}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-muted">{c.result || "—"}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-muted">
                      {c.started_at.slice(0, 16).replace("T", " ")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
