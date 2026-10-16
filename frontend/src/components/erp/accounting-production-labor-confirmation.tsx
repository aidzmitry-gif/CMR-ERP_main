"use client";
import { useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { pendingProductionLabor, resolveProductionLabor, type PendingProductionLabor, type ProductionLaborCommand, type ProductionLaborReceipt } from "@/lib/production-labor-journal";

export type PreparedProductionLabor = { draft: Omit<ProductionLaborCommand, "digest">; digest: string; amount_byn: string };
type Props = { org: string; month: string; disabled: boolean; prepared: PreparedProductionLabor | null;
  onConfirmed?: () => void; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };

export function AccountingProductionLaborConfirmation({ org, month, disabled, prepared, onConfirmed, onEntry, onLock }: Props) {
  const [pending, setPending] = useState<PendingProductionLabor | null>(null), [receipt, setReceipt] = useState<ProductionLaborReceipt | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const working = useRef(false), lock = useRef(onLock);
  useLayoutEffect(() => { lock.current = onLock; }, [onLock]);
  async function run(action: "check" | "confirm") {
    if (disabled || working.current || (action === "confirm" && !prepared)) return;
    working.current = true; setBusy(true); lock.current?.(true); setError(""); setNotice("");
    let item: PendingProductionLabor | null = null;
    try {
      const access = await (await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" })).json();
      if (String(access?.organization_id) !== org || typeof access.principal !== "string" || typeof access.can_confirm !== "boolean")
        throw new Error("Ответ о правах проведения труда повреждён.");
      item = pendingProductionLabor(localStorage, org, access.principal, month);
      setPending(item);
      if (action === "confirm") {
        if (item) throw new Error("Сначала проверьте сохранённый импорт труда. Новый запрос не создан.");
        if (!access.can_confirm) throw new Error("Нет права проводить импорт труда.");
        const draft = prepared!;
        item = { org, month, principal: access.principal, command: { ...draft.draft, digest: draft.digest } };
      }
      if (!item) { setNotice("Сохранённого импорта для текущего пользователя и месяца нет."); return; }
      const result = await resolveProductionLabor(localStorage, item, action === "confirm");
      if (result) { setPending(null); setReceipt(result); onConfirmed?.(); onEntry?.(result.entry_id); }
      else { setPending(item); setNotice("Квитанция пока не найдена. Запрос сохранён; повторите проверку."); }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Импорт труда не подтверждён.");
      if (item) { try { setPending(pendingProductionLabor(localStorage, org, item.principal, month)); } catch { /* retain recovery evidence */ } }
    } finally { working.current = false; setBusy(false); lock.current?.(false); }
  }
  return <section className="min-w-0 space-y-3 rounded border border-line p-2" aria-label="Импорт труда в производство">
    <h4 className="font-semibold">Подтверждение начислений труда</h4>
    <p>Проводится только проверенная ведомость с сохранением источника и строк по сотрудникам. Это не расчёт зарплаты.</p>
    <Button disabled={disabled || busy} onClick={() => void run("check")}>Проверить сохранённый импорт труда</Button>
    {prepared && !pending && !receipt && <div className="space-y-2"><p>Итого начислений: {prepared.amount_byn} BYN.</p>
      <p className="text-sm text-muted">Пакет: {prepared.digest.slice(0, 12)}…</p>
      <Button disabled={disabled || busy} onClick={() => void run("confirm")}>Провести подтверждённые начисления</Button></div>}
    {pending && <section className="space-y-2" aria-label="Сохранённый импорт труда"><p>Источник: {pending.command.source_document} · пользователь: {pending.principal}.</p>
      <Button disabled={disabled || busy} onClick={() => void run("check")}>Повторить проверку результата</Button></section>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {receipt && <div role="status"><p>Начисления труда проведены. Проводка №{receipt.entry_id}.</p><p>Финальная себестоимость периода ещё не сертифицирована.</p>
      <Button disabled={disabled || busy || !onEntry} onClick={() => onEntry?.(receipt.entry_id)}>Открыть проводку труда</Button></div>}
  </section>;
}
