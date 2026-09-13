"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { validOverheadDate, type OverheadReceipt } from "@/lib/production-overhead-journal";
import type { CorrectionTarget } from "./accounting-production-overhead-correction-preview";
type CostLine = { account: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string> };
type Revision = { id: number; sequence: number; previous_id: number | null; organization_id: number; month: string;
  original_entry_id: number; entry_id: number | null; actor: string; posting_date: string; evidence: string; lines: CostLine[] };
type Row = OverheadReceipt & { source_state: "unchanged" | "changed" | "unavailable";
  posting: { lines: CostLine[] }; corrections?: Revision[] };

function validLines(lines: CostLine[]) {
  return Array.isArray(lines) && lines.every(line => line && typeof line.account === "string" && ["debit", "credit"].includes(line.side)
    && typeof line.amount === "string" && /^\d+\.\d{2}$/.test(line.amount) && line.dimensions && !Array.isArray(line.dimensions)
    && typeof line.dimensions === "object" && Object.values(line.dimensions).every(value => typeof value === "string"));
}
type History = { organization_id: number; month: string; allocations: Row[] };
const states = { unchanged: "Учтённые источники не изменились после распределения.",
  changed: "После распределения изменились учтённые источники затрат. Требуется проверка и корректировка.",
  unavailable: "Актуальность источников не удалось проверить. Историческая проводка показана без изменений." };
export function AccountingProductionOverheadHistory({ org, month, disabled, onEntry, onCorrection }: {
  org: string; month: string; disabled: boolean; onEntry?: (id: number) => void; onCorrection?: (target: CorrectionTarget) => void;
}) {
  const [data, setData] = useState<History | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function load() {
    if (disabled || busy) return;
    const controller = new AbortController(); pending.current = controller; setBusy(true); setError(""); setData(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-overhead-history`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("История распределения недоступна. Повторите загрузку.");
      const result = await response.json() as History;
      if (!result || String(result.organization_id) !== org || result.month !== month || !Array.isArray(result.allocations)
        || result.allocations.some(row => !row || String(row.organization_id) !== org || row.month !== month || row.posted !== true || row.final_cost_certified !== false
          || !Number.isSafeInteger(row.entry_id) || row.entry_id <= 0 || !Object.hasOwn(states, row.source_state)
          || typeof row.actor !== "string" || typeof row.command?.posting_date !== "string" || !validOverheadDate(row.command.posting_date, month)
          || !Number.isSafeInteger(row.command.review?.policy_id) || row.command.review.policy_id <= 0
          || typeof row.command.evidence !== "string" || !Array.isArray(row.posting?.lines) || !row.posting.lines.length
          || !validLines(row.posting.lines)
          || (row.corrections !== undefined && (!Array.isArray(row.corrections) || row.corrections.some((rev, index, all) =>
            !rev || rev.organization_id !== row.organization_id || rev.month !== month || rev.original_entry_id !== row.entry_id
            || !Number.isSafeInteger(rev.id) || rev.id <= 0 || rev.sequence !== index + 1 || rev.previous_id !== (index ? all[index - 1].id : null)
            || typeof rev.actor !== "string" || !validOverheadDate(rev.posting_date, month) || typeof rev.evidence !== "string"
            || !validLines(rev.lines) || (rev.entry_id === null ? rev.lines.length !== 0 : !Number.isSafeInteger(rev.entry_id) || rev.entry_id <= 0 || !rev.lines.length))))))
        throw new Error("История не соответствует выбранному юрлицу, периоду или формату проводок.");
      if (!controller.signal.aborted) setData(result);
    } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="min-w-0 space-y-3 rounded border border-line p-2" aria-label="История распределения затрат">
    <h4 className="font-semibold">История распределения · {month}</h4>
    <Button variant="secondary" disabled={disabled || busy} onClick={() => void load()}>Загрузить историю распределения</Button>
    {error && <p role="alert">{error}</p>}
    {data && <><p>Проверка источников выполнена при этой загрузке. Она не подтверждает окончательную себестоимость.</p>
      {!data.allocations.length && <p>Проведённых распределений за выбранный месяц нет.</p>}
      {data.allocations.map(row => <article key={row.entry_id} className="space-y-2 border-t border-line pt-2">
        <p>Проводка №{row.entry_id} · {row.command.posting_date} · {row.actor}</p>
        <p role={row.source_state === "unchanged" ? "status" : "alert"}>{row.corrections?.length && row.source_state === "unchanged"
          ? "Источники соответствуют последней подтверждённой версии расчёта." : states[row.source_state]}</p>
        <p>{row.command.evidence}</p>
        {row.posting.lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.amount} BYN
          {Object.entries(line.dimensions).map(([key, value]) => ` · ${key === "department" ? "Подразделение" : key === "order" ? "Заказ" : key}: ${value}`)}</p>)}
        <Button disabled={disabled || busy || !onEntry} onClick={() => onEntry?.(row.entry_id)}>Открыть историческую проводку №{row.entry_id}</Button>
        {row.corrections?.map(rev => <section key={rev.id} className="space-y-2 border-t border-line pt-2">
          <p>Исправление · версия {rev.sequence} · {rev.posting_date} · {rev.actor}</p><p>{rev.evidence}</p>
          {rev.entry_id === null ? <p>Подтверждено без денежной проводки: разница равна нулю.</p> : <>
            {rev.lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.amount} BYN
              {Object.entries(line.dimensions).map(([key, value]) => ` · ${key === "department" ? "Подразделение" : key === "order" ? "Заказ" : key}: ${value}`)}</p>)}
            <Button disabled={disabled || busy || !onEntry} onClick={() => onEntry?.(rev.entry_id!)}>Открыть исправление №{rev.entry_id}</Button>
          </>}
        </section>)}
        {onCorrection && <Button disabled={disabled || busy} onClick={() => onCorrection({ entryId: row.entry_id,
          policyId: row.command.review.policy_id, postingDate: row.corrections?.at(-1)?.posting_date ?? row.command.posting_date })}>Подготовить расчёт исправления №{row.entry_id}</Button>}
      </article>)}
    </>}
  </section>;
}
