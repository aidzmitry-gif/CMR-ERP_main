"use client";
import { useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { pendingOutputTransfer, resolveOutputTransfer, type OutputTransferCommand, type OutputTransferReceipt, type PendingOutputTransfer } from "@/lib/production-output-transfer-journal";

export type PreparedOutputTransfer = { draft: Omit<OutputTransferCommand, "basis_digest" | "digest">; basis_digest: string; digest: string;
  amount_byn: string; debit_account: string; credit_account: string };
type Props = { org: string; month: string; disabled: boolean; prepared: PreparedOutputTransfer | null;
  onConfirmed: () => void; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };

export function AccountingProductionOutputTransferConfirmation({ org, month, disabled, prepared, onConfirmed, onEntry, onLock }: Props) {
  const [pending, setPending] = useState<PendingOutputTransfer | null>(null), [receipt, setReceipt] = useState<OutputTransferReceipt | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const working = useRef(false), lock = useRef(onLock); useLayoutEffect(() => { lock.current = onLock; }, [onLock]);
  async function run(action: "check" | "confirm") {
    if (disabled || working.current || (action === "confirm" && !prepared)) return;
    working.current = true; setBusy(true); lock.current?.(true); setError(""); setNotice("");
    let item: PendingOutputTransfer | null = null;
    try {
      const current = await (await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" })).json();
      if (String(current?.organization_id) !== org || typeof current.principal !== "string" || typeof current.can_confirm !== "boolean") throw new Error("Ответ о правах повреждён.");
      item = pendingOutputTransfer(localStorage, org, current.principal, month);
      setPending(item);
      if (action === "confirm") {
        if (item) throw new Error("Сначала проверьте сохранённый перенос НЗП. Новый запрос не создан.");
        if (!current.can_confirm) throw new Error("Нет права проводить перенос выпуска.");
        const draft = prepared!; item = { org, month, principal: current.principal, command: { ...draft.draft, basis_digest: draft.basis_digest, digest: draft.digest } };
      }
      if (!item) { setNotice("Сохранённого переноса для текущего пользователя и месяца нет."); return; }
      const result = await resolveOutputTransfer(localStorage, item, action === "confirm");
      if (result) { setPending(null); setReceipt(result); onConfirmed(); onEntry?.(result.entry_id); }
      else { setPending(item); setNotice("Квитанция пока не найдена. Запрос сохранён; повторите проверку."); }
    } catch (e) { setError(e instanceof Error ? e.message : "Перенос не подтверждён."); if (item) { try { setPending(pendingOutputTransfer(localStorage, org, item.principal, month)); } catch { /* Keep recovery evidence. */ } } }
    finally { working.current = false; setBusy(false); lock.current?.(false); }
  }
  return <section className="min-w-0 space-y-3 rounded border border-line p-2" aria-label="Проведение выпуска">
    <h4 className="font-semibold">Перенос НЗП в готовую продукцию</h4>
    <p>Требует полного принятия выпуска, явного счёта готовой продукции и отдельного подтверждения бухгалтера.</p>
    <Button disabled={disabled || busy} onClick={() => void run("check")}>Проверить сохранённый перенос выпуска</Button>
    {prepared && !pending && !receipt && <div className="space-y-2"><p>Дт {prepared.debit_account} {prepared.amount_byn} BYN → Кт {prepared.credit_account} {prepared.amount_byn} BYN.</p>
      <p className="text-sm text-muted">Basis: {prepared.basis_digest.slice(0, 12)}… · пакет: {prepared.digest.slice(0, 12)}…</p>
      <Button disabled={disabled || busy} onClick={() => void run("confirm")}>Провести проверенный выпуск</Button></div>}
    {pending && <section className="space-y-2" aria-label="Сохранённый перенос выпуска"><p>Наряд №{pending.command.order_id} · пользователь: {pending.principal} · дата: {pending.command.posting_date}.</p>
      <Button disabled={disabled || busy} onClick={() => void run("check")}>Повторить проверку результата</Button></section>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {receipt && <div role="status"><p>Выпуск проведён в готовую продукцию. Проводка №{receipt.entry_id}.</p><p>Окончательная себестоимость периода ещё не сертифицирована.</p>
      <Button disabled={disabled || busy || !onEntry} onClick={() => onEntry?.(receipt.entry_id)}>Открыть проводку выпуска</Button></div>}
  </section>;
}
