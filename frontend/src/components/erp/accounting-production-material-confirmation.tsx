"use client";
import { useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  materialPostingAccess,
  pendingMaterialPosting,
  resolveMaterialPosting,
  type MaterialPostingCommand,
  type MaterialPostingReceipt,
  type PendingMaterialPosting,
} from "@/lib/production-material-journal";

export type PreparedMaterialPosting = {
  credit_lines?: { account: string; amount: string; quantity?: string | null }[];
  draft: Omit<MaterialPostingCommand, "basis_digest" | "digest">;
  basis_digest: string;
  digest: string;
  amount_byn: string;
  debit_account: string;
  credit_account: string;
};
type Props = { org: string; month: string; disabled: boolean; prepared: PreparedMaterialPosting | null;
  onConfirmed: () => void; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };

/** Confirmation is independent from the source preview so a reload can recover the exact command. */
export function AccountingProductionMaterialConfirmation({ org, month, disabled, prepared, onConfirmed, onEntry, onLock }: Props) {
  const [pending, setPending] = useState<PendingMaterialPosting | null>(null);
  const [receipt, setReceipt] = useState<MaterialPostingReceipt | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const working = useRef(false), lock = useRef(onLock);
  useLayoutEffect(() => { lock.current = onLock; }, [onLock]);
  async function run(action: "check" | "confirm") {
    if (disabled || working.current || (action === "confirm" && !prepared)) return;
    working.current = true; setBusy(true); lock.current?.(true); setError(""); setNotice("");
    let item: PendingMaterialPosting | null = null;
    try {
      const access = await materialPostingAccess(org);
      item = pendingMaterialPosting(localStorage, org, access.principal, month, prepared?.draft.wms_movement_id);
      setPending(item);
      if (action === "confirm") {
        if (item) throw new Error("Сначала проверьте сохранённое проведение материала. Новый запрос не создан.");
        if (!access.can_confirm) throw new Error("Нет права проводить материал в выбранном юрлице.");
        const draft = prepared!;
        item = { org, month, principal: access.principal, command: {
          ...draft.draft, basis_digest: draft.basis_digest, digest: draft.digest,
        } };
      }
      if (!item) { setNotice("Сохранённого запроса для текущего пользователя, месяца и движения нет."); return; }
      const saved = await resolveMaterialPosting(localStorage, item, action === "confirm");
      if (saved) { setPending(null); setReceipt(saved); onConfirmed(); onEntry?.(saved.entry_id); }
      else { setPending(item); setNotice("Квитанция пока не найдена. Запрос сохранён; можно повторить подтверждение."); }
    } catch (e) {
      setError(e instanceof TypeError ? "Связь прервалась. Проверьте сохранённую проводку перед повторной отправкой." : (e as Error).message);
      if (item) { try { setPending(pendingMaterialPosting(localStorage, org, item.principal, month)); } catch { /* Preserve recovery evidence. */ } }
    } finally { working.current = false; setBusy(false); lock.current?.(false); }
  }
  return <section className="min-w-0 space-y-3 rounded border border-line p-2" aria-label="Проведение материала">
    <h4 className="font-semibold">Проведение списания материала</h4>
    <p>Проводка создаётся только после отдельного подтверждения бухгалтера. После обрыва связи сначала проверьте сохранённый запрос.</p>
    <Button disabled={disabled || busy} onClick={() => void run("check")}>Проверить сохранённое проведение материала</Button>
    {prepared && !pending && !receipt && <div className="space-y-2">
      <p>Дт {prepared.debit_account} {prepared.amount_byn} BYN → Кт {prepared.credit_account} {prepared.amount_byn} BYN.</p>
      {prepared.credit_lines && <ul aria-label="Строки списания материала">{prepared.credit_lines.map((line, index) => <li key={index}>Кт {line.account} · {line.amount} BYN{line.quantity ? ` · Количество ${line.quantity}` : ""}</li>)}</ul>}
      <p className="text-sm text-muted">Основание стоимости: {prepared.basis_digest.slice(0, 12)}… · пакет: {prepared.digest.slice(0, 12)}…</p>
      <Button disabled={disabled || busy} onClick={() => void run("confirm")}>Провести проверенный материал</Button>
    </div>}
    {pending && <section className="space-y-2" aria-label="Сохранённая проводка материала">
      <p>Движение №{pending.command.wms_movement_id} · пользователь: {pending.principal} · дата: {pending.command.posting_date}.</p>
      <p>Команда сохранена до независимой квитанции сервера.</p>
      <Button disabled={disabled || busy} onClick={() => void run("check")}>Повторить проверку результата</Button>
    </section>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {receipt && <div role="status"><p>Материал проведён. Проводка №{receipt.entry_id}.</p>
      <p>Окончательная себестоимость выпуска ещё не сертифицирована.</p>
      <Button disabled={disabled || busy || !onEntry} onClick={() => onEntry?.(receipt.entry_id)}>Открыть проводку материала</Button>
    </div>}
  </section>;
}
