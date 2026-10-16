"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AccountingReceiptConfirm } from "./accounting-receipt-confirm";

type Options = { expected_version: number; posting_date: string; policy_id: number;
  settlement_account: string; vat_account: string | null; inventory_accounts: string[] };
type Preview = { digest: string; organization_id: number; source: string; source_version: number;
  posted: false; resolved_options: Options;
  lines: { account: string; title: string; side: string; amount: string }[] };
export function AccountingAutomaticReceipt({ org, receiptId, version, date, onLock, onVerified,
  blocked = false, onBusy }: { org: string; receiptId: number; version: number; date: string;
  onLock: () => void; onVerified?: (entryId: number) => void; blocked?: boolean; onBusy?: (value: boolean) => void }) {
  const [busy, setBusy] = useState(false), [locked, setLocked] = useState(false);
  const [result, setResult] = useState<Preview | null>(null), [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  const busyHandler = useRef(onBusy);
  useEffect(() => { busyHandler.current = onBusy; }, [onBusy]);
  useEffect(() => () => {
    if (pending.current) { pending.current.abort(); busyHandler.current?.(false); }
  }, []);
  async function preview() {
    if (busy || locked || blocked) return;
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); onBusy?.(true); setResult(null); setError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/receipts/${receiptId}/auto-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ expected_version: version, posting_date: date }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте правила проводок и документ.");
      const options = data.resolved_options;
      if (String(data.organization_id) !== org || data.source !== `procurement:receipt:${receiptId}`
        || data.source_version !== version || data.posted !== false || !/^[a-f0-9]{64}$/.test(data.digest)
        || !Array.isArray(data.lines) || !options || options.expected_version !== version
        || options.posting_date !== date || !Number.isInteger(options.policy_id) || options.policy_id < 1
        || typeof options.settlement_account !== "string" || !options.settlement_account
        || !(options.vat_account === null || (typeof options.vat_account === "string" && options.vat_account.length > 0))
        || !Array.isArray(options.inventory_accounts) || !options.inventory_accounts.length
        || options.inventory_accounts.some((code: unknown) => typeof code !== "string" || !code))
        throw new Error("Расчёт не соответствует выбранному поступлению.");
      if (!controller.signal.aborted) setResult(data);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка расчёта."); }
    finally {
      if (pending.current === controller) pending.current = null;
      if (!controller.signal.aborted) { setBusy(false); onBusy?.(false); }
    }
  }
  return <div className="space-y-3">
    <p>Счета выбираются автоматически по учётной политике юрлица: товар → группа → общий счёт.</p>
    <Button disabled={busy || locked || blocked || !date} onClick={() => void preview()}>Рассчитать автоматические проводки</Button>
    {error && <p role="alert">{error}</p>}
    {result && <><div aria-label="Автоматические проводки поступления"><p>Предварительный расчёт. Проверьте проводки перед проведением.</p>
      {result.lines.map((line, index) => <p key={index}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN</p>)}</div>
      <AccountingReceiptConfirm automatic blocked={blocked} org={org} receiptId={receiptId} version={version}
        key={result.digest} command={{ ...result.resolved_options, digest: result.digest }}
        onLock={() => { setLocked(true); onLock(); }} onVerified={onVerified} /></>}
  </div>;
}
