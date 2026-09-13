"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Action = { id: number; actor: string; created_at: string; monthly_entry_id: number | null; annual_entry_id: number | null };
type History = { organization_id: number; month: string; period_closed: boolean; receipts: (Action & { policy_id: number; evidence: Record<string,string>; reopening: (Action & { reason: string }) | null })[] };

export function AccountingClosingHistory({ org, month, onEntry }: { org: string; month: string; onEntry?: (id: number) => void }) {
  const [data, setData] = useState<History | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function load() {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(""); setData(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/financial-closing-history`, { cache: "no-store", signal: controller.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "История закрытия недоступна.");
      if (String(result.organization_id) !== org || result.month !== month || typeof result.period_closed !== "boolean" || !Array.isArray(result.receipts)) throw new Error("Получена история другого юрлица или месяца.");
      if (!controller.signal.aborted) setData(result);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить историю."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  function entries(row: Action) {
    return <div className="flex flex-wrap gap-3">{([ ["Месячная операция", row.monthly_entry_id], ["Годовая операция", row.annual_entry_id] ] as const).map(([label,id]) => id !== null && <Button key={label} variant="ghost" disabled={!onEntry} onClick={() => onEntry?.(id)}>{label} № {id}</Button>)}{row.monthly_entry_id === null && row.annual_entry_id === null && <p>Проводки переноса не создавались.</p>}</div>;
  }
  return <section aria-label="История финансового закрытия" className="space-y-3 rounded-lg border border-line p-3">
    <h3 className="font-semibold">История финансового закрытия</h3>
    <Button variant="secondary" disabled={busy} onClick={() => void load()}>{busy ? "Загружается история…" : "Загрузить историю закрытия"}</Button>
    {error && <p role="alert">{error}</p>}
    {data && <><p>Сейчас месяц {data.period_closed ? "закрыт" : "открыт"}.</p>{!data.receipts.length && <p>Пакетов финансового закрытия за месяц нет.</p>}{data.receipts.map(row => <article key={row.id} className="space-y-2 border-t border-line pt-3">
      <h4 className="font-semibold">Закрытие № {row.id}{row.reopening ? " · отменено открытием периода" : ""}</h4>
      <p>{row.actor} · {row.created_at}. Версия политики: {row.policy_id}.</p>{entries(row)}
      <details><summary>Основания контрольных проверок</summary>{Object.entries(row.evidence).map(([key,value]) => <p key={key}>{key}: {value}</p>)}</details>
      {row.reopening && <div className="space-y-2"><p>Открытие № {row.reopening.id} · {row.reopening.actor} · {row.reopening.created_at}</p><p>{row.reopening.reason}</p>{entries(row.reopening)}</div>}
    </article>)}</>}
  </section>;
}
