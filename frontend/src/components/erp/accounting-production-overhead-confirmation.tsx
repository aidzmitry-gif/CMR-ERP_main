"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { overheadAccess, pendingOverhead, resolveOverhead, validOverheadDate,
  type CostReviewCommand, type PendingOverhead, type OverheadReceipt } from "@/lib/production-overhead-journal";

export type PreparedOverhead = { review: CostReviewCommand; digest: string; earliestDate: string };
type Props = { org: string; month: string; disabled: boolean; prepared: PreparedOverhead | null;
  onConfirmed: () => void; onWithdrawn?: () => void; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };
/** Mounted independently of the source preview so a reload can recover the original command. */
export function AccountingProductionOverheadConfirmation({ org, month, disabled, prepared, onConfirmed, onWithdrawn, onEntry, onLock }: Props) {
  const [date, setDate] = useState(""), [evidence, setEvidence] = useState("");
  const [pending, setPending] = useState<PendingOverhead | null>(null), [receipt, setReceipt] = useState<OverheadReceipt | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [withdrawalReason, setWithdrawalReason] = useState("");
  const working = useRef(false), mounted = useRef(true), lock = useRef(onLock);
  useLayoutEffect(() => { lock.current = onLock; }, [onLock]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; lock.current?.(false); }; }, []);
  const ready = prepared && validOverheadDate(date, month) && date >= prepared.earliestDate && evidence.trim().length >= 10;
  async function run(action: "check" | "retry" | "confirm" | "withdraw") {
    if (disabled || working.current || (action === "confirm" && !ready) || (action === "withdraw" && withdrawalReason.trim().length < 10)) return;
    working.current = true; setBusy(true); lock.current?.(true); setError(""); setNotice("");
    let item: PendingOverhead | null = null;
    try {
      const access = await overheadAccess(org);
      if (!mounted.current) return;
      item = pendingOverhead(localStorage, org, access.principal, month);
      setPending(item);
      if (action === "confirm") {
        if (item) throw new Error("Сначала проверьте сохранённое проведение. Новый запрос не создан.");
        if (!access.can_confirm) throw new Error("Нет права проводить распределение в выбранном юрлице.");
        item = { org, month, principal: access.principal, command: { request_key: crypto.randomUUID(), review: prepared!.review,
          expected_review_digest: prepared!.digest, posting_date: date, evidence: evidence.trim() } };
      }
      if (!item) { setNotice("Сохранённого запроса для текущего пользователя и месяца нет."); return; }
      // Never reuse a pending command from the previous principal shown on screen.
      if ((action === "retry" || action === "withdraw") && (!pending || pending.principal !== item.principal || pending.command.request_key !== item.command.request_key))
        throw new Error("Сохранённый запрос или пользователь изменился. Повторите проверку результата.");
      if (action === "withdraw") item = { ...item, withdrawal_reason: withdrawalReason.trim() };
      const saved = await resolveOverhead(localStorage, item, action !== "check");
      if (!mounted.current) return;
      if (saved) {
        setPending(null);
        if (saved.posted) { setReceipt(saved); onConfirmed(); }
        else { setReceipt(null); setNotice("Запрос отозван и больше не может создать проводку. Подготовьте новый расчёт."); onWithdrawn?.(); }
      } else { setPending(item); setNotice(item.withdrawal_reason ? "Результат отзыва пока не подтверждён. Сохранённое проведение не будет отправлено повторно."
        : "Квитанция пока не найдена. Запрос сохранён; можно повторить проведение или отозвать непроведённый запрос."); }
    } catch (e) {
      if (mounted.current) {
        setError(e instanceof TypeError ? "Связь прервалась. Проверьте сохранённое проведение перед повторной отправкой." : (e as Error).message);
        // A storage failure must not be presented as a durably saved request.
        if (item) { try { setPending(pendingOverhead(localStorage, org, item.principal, month)); } catch { /* Preserve the storage error and recovery evidence. */ } }
      }
    } finally { working.current = false; if (mounted.current) { setBusy(false); lock.current?.(false); } }
  }
  return <section className="min-w-0 space-y-3 rounded border border-line p-2" aria-label="Проведение распределения затрат">
    <h4 className="font-semibold">Проведение распределения</h4>
    <p>После обрыва связи сначала проверьте сохранённый запрос. Проверка результата не создаёт проводок.</p>
    <Button disabled={disabled || busy} onClick={() => void run("check")}>Проверить сохранённое проведение</Button>
    {prepared && !pending && !receipt && <fieldset disabled={disabled || busy} className="min-w-0 space-y-2">
      <p>Проведение относится к показанному распределению за {month}. Дата — не ранее {prepared.earliestDate}.</p>
      <label className="block">Дата проведения распределения<Input type="date" aria-label="Дата проведения распределения" min={prepared.earliestDate} value={date} onChange={e => setDate(e.target.value)} /></label>
      <label className="block">Основание проведения распределения<textarea className="w-full rounded border border-line bg-transparent p-2" aria-label="Основание проведения распределения"
        rows={4} maxLength={1000} value={evidence} onChange={e => setEvidence(e.target.value)} /></label>
      <Button disabled={!ready} onClick={() => void run("confirm")}>Провести проверенное распределение</Button>
    </fieldset>}
    {pending && <section className="space-y-2" aria-label="Сохранённое распределение">
      <p>Дата: {pending.command.posting_date} · Пользователь: {pending.principal} · Запрос: {pending.command.request_key}</p>
      <p>{pending.command.evidence}</p>
      <p>Политика №{pending.command.review.policy_id}; проверено строк: {pending.command.review.classifications.length}; нарядов: {pending.command.review.orders.length}.</p>
      {pending.withdrawal_reason && <p>Основание отзыва: {pending.withdrawal_reason}</p>}
      <Button disabled={disabled || busy} onClick={() => void run("retry")}>{pending.withdrawal_reason ? "Повторить отзыв запроса" : "Повторить сохранённое проведение"}</Button>
      {!pending.withdrawal_reason && <fieldset className="min-w-0 space-y-2" disabled={disabled || busy}>
        <p>Если запрос устарел, отзовите его перед новым расчётом. Уже созданная проводка сохранится.</p>
        <label className="block">Основание отзыва запроса<textarea aria-label="Основание отзыва запроса" rows={4} maxLength={1000}
          className="w-full rounded border border-line bg-transparent p-2" value={withdrawalReason} onChange={e => setWithdrawalReason(e.target.value)} /></label>
        <Button disabled={withdrawalReason.trim().length < 10} onClick={() => void run("withdraw")}>Отозвать непроведённый запрос</Button>
      </fieldset>}
    </section>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {receipt && <div role="status"><p>Распределение проведено. Проводка №{receipt.entry_id} · {receipt.command.posting_date}.</p>
      <p>Это распределение накладных расходов. Окончательная себестоимость и закрытие месяца ещё требуют проверки.</p>
      <Button disabled={disabled || busy || !onEntry} onClick={() => onEntry?.(receipt.entry_id)}>Открыть проводку распределения</Button>
    </div>}
  </section>;
}
