"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { overheadAccess } from "@/lib/production-overhead-journal";
import { pendingCorrection, resolveCorrection, type PendingCorrection, type PreparedCorrection, type CorrectionReceipt } from "@/lib/production-correction-journal";

export function AccountingProductionCorrectionConfirmation({ org, month, disabled, prepared, onConfirmed, onWithdrawn, onEntry, onLock }: {
  org: string; month: string; disabled: boolean; prepared: PreparedCorrection | null; onConfirmed: () => void;
  onWithdrawn: () => void; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void;
}) {
  const [pending, setPending] = useState<PendingCorrection | null>(null), [receipt, setReceipt] = useState<CorrectionReceipt | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [reason, setReason] = useState(""), [busy, setBusy] = useState(false);
  const working = useRef(false), mounted = useRef(true), lock = useRef(onLock);
  useLayoutEffect(() => { lock.current = onLock; }, [onLock]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; lock.current?.(false); }; }, []);
  async function run(action: "check" | "confirm" | "retry" | "withdraw") {
    if (disabled || working.current || (action === "confirm" && !prepared) || (action === "withdraw" && reason.trim().length < 10)) return;
    working.current = true; setBusy(true); lock.current?.(true); setError(""); setNotice("");
    let item: PendingCorrection | null = null;
    try {
      const access = await overheadAccess(org);
      if (!mounted.current) return;
      item = pendingCorrection(localStorage, org, access.principal, month); setPending(item);
      if (action === "confirm") {
        if (item) throw new Error("Сначала проверьте сохранённое исправление. Новый запрос не создан.");
        if (!access.can_confirm) throw new Error("Нет права подтверждать исправления в выбранном юрлице.");
        item = { org, month, principal: access.principal, command: { request_key: crypto.randomUUID(),
          preview: prepared!.command, expected_preview_digest: prepared!.digest } };
      }
      if (!item) { setNotice("Сохранённого исправления для текущего пользователя и месяца нет."); return; }
      if ((action === "retry" || action === "withdraw") && (!pending || pending.principal !== item.principal || pending.command.request_key !== item.command.request_key))
        throw new Error("Пользователь или сохранённое исправление изменились. Повторите проверку.");
      if (action === "withdraw") item = { ...item, withdrawal_reason: reason.trim() };
      const saved = await resolveCorrection(localStorage, item, action !== "check");
      if (!mounted.current) return;
      if (saved) {
        setPending(null);
        if (saved.confirmed) { setReceipt(saved); onConfirmed(); }
        else { setReceipt(null); setNotice("Запрос исправления отозван. Его повторная доставка не создаст новую версию."); onWithdrawn(); }
      } else { setPending(item); setNotice("Результат пока не найден. Сохранённый запрос можно повторить или отозвать."); }
    } catch (e) {
      if (mounted.current) {
        setError(e instanceof TypeError ? "Связь прервалась. Проверьте сохранённое исправление перед повторной отправкой." : (e as Error).message);
        if (item) { try { setPending(pendingCorrection(localStorage, org, item.principal, month)); } catch { /* Keep storage failure evidence. */ } }
      }
    } finally { working.current = false; if (mounted.current) { setBusy(false); lock.current?.(false); } }
  }
  return <section className="min-w-0 space-y-3 rounded border border-line p-2" aria-label="Подтверждение исправления затрат">
    <h4 className="font-semibold">Подтверждение исправления</h4>
    <p>Проверка сохранённого запроса не создаёт проводок или новых версий расчёта.</p>
    <Button disabled={disabled || busy} onClick={() => void run("check")}>Проверить сохранённое исправление</Button>
    {prepared && !pending && <div className="space-y-2">
      <p>Проводка №{prepared.command.original_entry_id} · {prepared.command.posting_date} · {prepared.command.evidence}</p>
      <p>{prepared.createsEntry ? "Будет сохранена версия расчёта и проводка на показанную разницу." : "Будет сохранена версия расчёта без денежной проводки."}</p>
      <Button disabled={disabled || busy} onClick={() => void run("confirm")}>Подтвердить проверенное исправление</Button>
    </div>}
    {pending && <section className="space-y-2" aria-label="Сохранённое исправление">
      <p>Проводка №{pending.command.preview.original_entry_id} · {pending.command.preview.posting_date} · {pending.principal}</p>
      <p>Запрос: {pending.command.request_key}</p><p>{pending.command.preview.evidence}</p>
      <Button disabled={disabled || busy} onClick={() => void run("retry")}>{pending.withdrawal_reason ? "Повторить отзыв исправления" : "Повторить сохранённое исправление"}</Button>
      {pending.withdrawal_reason ? <p>Основание отзыва: {pending.withdrawal_reason}</p> : <>
        <label className="block">Основание отзыва исправления<textarea aria-label="Основание отзыва исправления" rows={4} maxLength={1000}
          className="w-full rounded border border-line bg-transparent p-2" value={reason} onChange={e => setReason(e.target.value)} disabled={disabled || busy} /></label>
        <Button disabled={disabled || busy || reason.trim().length < 10} onClick={() => void run("withdraw")}>Отозвать неподтверждённое исправление</Button>
      </>}
    </section>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {receipt && <div role="status"><p>Исправление подтверждено · версия {receipt.sequence}.</p>
      {receipt.entry_id === null ? <p>Разница равна нулю. Денежная проводка не создавалась.</p> :
        <Button disabled={disabled || busy || !onEntry} onClick={() => onEntry?.(receipt.entry_id!)}>Открыть проводку исправления №{receipt.entry_id}</Button>}
      <p>Окончательная себестоимость требует завершения остальных расчётов.</p>
    </div>}
  </section>;
}
