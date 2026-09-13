"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { clearRejectedLateCost, pendingLateCost, rememberLateCost, settleLateCost, type LateCostPending } from "@/lib/late-cost-journal";

export function AccountingLateCostConfirmation({ org, principal, prepared, onLock, onPosted, disabled = false }: {
  org: string; principal: string; prepared: LateCostPending | null; disabled?: boolean;
  onLock: (locked: boolean) => void; onPosted: (expenseId: number) => void | Promise<void>;
}) {
  const [pending, setPending] = useState<LateCostPending | null>(null), [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [completedBody, setCompletedBody] = useState<string | null>(null);
  const running = useRef(false), active = useRef(true);
  useEffect(() => {
    active.current = true;
    void Promise.resolve().then(() => {
      if (!active.current) return;
      try { const saved = pendingLateCost(sessionStorage, org, principal); setPending(saved); onLock(saved !== null); setLoaded(true); }
      catch (e) { setError((e as Error).message); onLock(true); }
    });
    return () => { active.current = false; };
  }, [org, principal, onLock]);
  const candidate = prepared?.org === org && prepared.principal === principal ? prepared : null;
  const command = pending ?? candidate;
  const done = completedBody !== null && (!command || command.body === completedBody);
  async function execute(readback: boolean) {
    if (running.current || !loaded || !command || disabled) return;
    running.current = true; setBusy(true); setError("");
    try {
      const fresh = !pending && pendingLateCost(sessionStorage, org, principal) === null;
      // Persist exact bytes before the request can leave this tab.
      rememberLateCost(sessionStorage, command);
      setPending(command); onLock(true);
      const path = `/api/accounting/organizations/${org}/additional-expenses/${command.expenseId}`;
      const response = await fetch(path + (readback ? "/posting" : "/confirm"), readback ? { cache: "no-store" } : {
        method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": principal }, body: command.body,
      });
      const data = await response.json();
      if (!response.ok) {
        if (fresh && !readback && [401, 403, 404, 409, 422].includes(response.status)) {
          clearRejectedLateCost(sessionStorage, command);
          if (active.current) { setPending(null); onLock(false); }
        }
        throw new Error(typeof data.detail === "string" ? data.detail : "Результат проведения не подтверждён. Проверьте его или повторите ту же команду.");
      }
      settleLateCost(sessionStorage, command, data);
      if (active.current) { setPending(null); setCompletedBody(command.body); onLock(false); await onPosted(command.expenseId); }
    } catch (e) { if (active.current) setError((e as Error).message); }
    finally { running.current = false; if (active.current) setBusy(false); }
  }
  if (!command && !error && !done) return null;
  return <section className="space-y-3 rounded-xl border border-line p-4">
    <h3 className="font-semibold">Подтверждение проведения</h3>
    {pending && <p role="status">Результат проведения документа № {pending.expenseId} ещё не подтверждён. Сохранена исходная команда.</p>}
    {error && <p role="alert">{error}</p>}
    {done && !pending && <p role="status">Проведение подтверждено.</p>}
    {!done && command && <Button disabled={disabled || busy || !loaded} onClick={() => void execute(false)}>
      {busy ? "Проверка…" : pending ? "Повторить проведение без дубля" : "Подтвердить проводки"}
    </Button>}
    {pending && <Button variant="secondary" disabled={disabled || busy || !loaded} onClick={() => void execute(true)}>Проверить результат проведения</Button>}
  </section>;
}
