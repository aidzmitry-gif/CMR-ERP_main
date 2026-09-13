"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

export function AccountingReceiptConfirm({ org, receiptId, version, command, onLock, onVerified }: { org: string; receiptId: number; version: number; command: Record<string, unknown>; onLock: () => void; onVerified?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [entry, setEntry] = useState<number | null>(null);
  const saved = useRef<string | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function confirm() {
    if (running.current || entry !== null) return;
    running.current = true; onLock(); setBusy(true); setError("");
    saved.current ??= JSON.stringify(command);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/receipts/${receiptId}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: saved.current });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проведение не подтверждено.");
      if (String(data.organization_id) !== org || data.source !== `procurement:receipt:${receiptId}` || data.source_version !== version || data.digest !== command.digest || !Number.isInteger(data.entry_id) || data.entry_id < 1) throw new Error("Ответ не подтверждает проведение выбранного пакета.");
      const read = await fetch(`/api/accounting/organizations/${org}/receipts/${receiptId}/source`, { cache: "no-store" });
      if (!read.ok) throw new Error("Пакет принят, но состояние поступления не удалось перечитать. Повторите проверку тем же запросом.");
      const source = await read.json();
      if (String(source.organization_id) !== org || source.id !== receiptId || source.version !== version || source.status !== "posted" || source.entry_id !== data.entry_id) throw new Error("Состояние поступления не подтверждает полученную операцию. Повторите проверку.");
      if (mounted.current) { setEntry(data.entry_id); onVerified?.(); }
    } catch (reason) {
      if (mounted.current) setError(`${reason instanceof Error ? reason.message : "Ответ не получен."} Параметры зафиксированы; повтор отправит тот же пакет.`);
    } finally { running.current = false; if (mounted.current) setBusy(false); }
  }
  return <div className="space-y-2 border-t border-line pt-3">
    {entry === null ? <><p>Проверьте проводки и аналитику перед записью в учёт.</p><Button disabled={busy} onClick={() => void confirm()}>{busy ? "Проверяется проведение…" : error ? "Повторить подтверждение" : "Подтвердить и провести поступление"}</Button></> : <p role="status">Поступление проведено. Операция № {entry}.</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
