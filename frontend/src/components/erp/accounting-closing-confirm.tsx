"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Command = { request_key: string; expected_basis_digest: string; expected_generation: number; evidence: Record<string, string> };
export function AccountingClosingConfirm({ org, month, command, onLock, onClosed }: {
  org: string; month: string; command: Command; onLock: (locked: boolean) => void;
  onClosed: (receiptId: number, currentlyClosed: boolean) => void | Promise<void>;
}) {
  const [state, setState] = useState<"ready" | "sending" | "uncertain" | "done" | "rejected">("ready");
  const [message, setMessage] = useState("");
  const sending = useRef(false);
  const mounted = useRef(true);
  const closedCallback = useRef(onClosed);
  useLayoutEffect(() => { closedCallback.current = onClosed; }, [onClosed]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [request] = useState(() => ({ org, month, body: JSON.stringify(command), requestKey: command.request_key }));
  async function confirm() {
    if (sending.current || state === "done" || state === "rejected") return;
    sending.current = true; setState("sending"); onLock(true);
    let receiptId: number;
    let currentlyClosed: boolean;
    try {
      const frozen = request;
      const response = await fetch(`/api/accounting/organizations/${frozen.org}/periods/${frozen.month}/financial-closing-confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: frozen.body,
      });
      const data = await response.json();
      if (!response.ok) {
        if ([401,403,404,409,422].includes(response.status)) {
          setState("rejected"); onLock(false);
          setMessage("Закрытие отклонено. Обновите расчёт и проверьте основания: " + (typeof data.detail === "string" ? data.detail : "проверьте обязательные поля"));
          return;
        }
        throw new Error("Uncertain closing result");
      }
      if (data.organization_id !== Number(frozen.org) || data.month !== frozen.month || data.request_key !== frozen.requestKey
          || typeof data.closed !== "boolean" || !Number.isSafeInteger(data.receipt_id) || data.receipt_id <= 0
          || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest)) throw new Error("Unverified closing receipt");
      receiptId = data.receipt_id;
      currentlyClosed = data.closed;
      setState("done"); setMessage(currentlyClosed ? `Месяц ${frozen.month} закрыт. Квитанция № ${receiptId}.` : `Закрытие № ${receiptId} ранее выполнено. Сейчас месяц ${frozen.month} открыт для исправлений.`); onLock(false);
    } catch {
      setState("uncertain");
      setMessage("Результат закрытия не подтверждён. Повторите тот же запрос для проверки результата без повторных проводок.");
      return;
    } finally { sending.current = false; }
    if (!mounted.current) return;
    try { await closedCallback.current(receiptId, currentlyClosed); }
    catch { setMessage(`Закрытие зарегистрировано, квитанция № ${receiptId}. Не удалось обновить отчёты; обновите раздел.`); }
  }
  return <section aria-label="Подтверждение финансового закрытия" className="space-y-2">
    <p>Будут проведены показанные переносы и заблокирован месяц {request.month}.</p>
    {message && <p role={state === "done" ? "status" : "alert"}>{message}</p>}
    {state !== "done" && state !== "rejected" && <Button disabled={state === "sending"} onClick={() => void confirm()}>
      {state === "sending" ? "Закрывается месяц…" : state === "uncertain" ? "Проверить результат закрытия" : "Подтвердить переносы и закрыть месяц"}
    </Button>}
  </section>;
}
