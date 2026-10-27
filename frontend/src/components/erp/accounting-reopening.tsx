"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Plan = { organization_id: number; from_month: string; basis_digest: string; posted: false; status: string;
  periods: { month: string; closed: boolean; generation: number }[];
  reversals: { entry_id: number; month: string; lines: { account: string; side: string; amount: string; dimensions: Record<string,string> }[] }[] };
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function validRows(periods: unknown, reversals: unknown, month: string): boolean {
  if (!Array.isArray(periods) || !periods.length || !Array.isArray(reversals)) return false;
  const months = new Set<string>();
  let previous = "";
  for (const row of periods) {
    if (!record(row) || typeof row.month !== "string" || !/^\d{4}-(0[1-9]|1[0-2])$/.test(row.month)
      || row.month < month || row.month <= previous || typeof row.closed !== "boolean"
      || !Number.isSafeInteger(row.generation) || Number(row.generation) < 0) return false;
    months.add(row.month); previous = row.month;
  }
  if (periods[0].month !== month || periods[0].closed !== true) return false;
  const entries = new Set<number>();
  return reversals.every(row => {
    if (!record(row) || !Number.isSafeInteger(row.entry_id) || Number(row.entry_id) <= 0
      || entries.has(Number(row.entry_id)) || typeof row.month !== "string" || !months.has(row.month)
      || !Array.isArray(row.lines) || !row.lines.length) return false;
    entries.add(Number(row.entry_id));
    return row.lines.every(line => record(line) && typeof line.account === "string" && line.account.length > 0
      && (line.side === "debit" || line.side === "credit") && typeof line.amount === "string"
      && /^\d+\.\d{2}$/.test(line.amount) && record(line.dimensions)
      && Object.values(line.dimensions).every(value => typeof value === "string"));
  });
}
export function AccountingReopening({ org, month, onLock, onReopened }: {
  org: string; month: string; onLock: (locked: boolean) => void; onReopened: (currentlyOpen: boolean) => void;
}) {
  const [reason, setReason] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [state, setState] = useState<"idle"|"loading"|"sending"|"uncertain"|"done">("idle");
  const [message, setMessage] = useState("");
  const request = useRef<{ path: string; body: string; key: string } | null>(null);
  const pending = useRef<AbortController | null>(null);
  const sending = useRef(false);
  const mounted = useRef(true);
  const callback = useRef(onReopened);
  useLayoutEffect(() => { callback.current = onReopened; }, [onReopened]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; pending.current?.abort(); }; }, []);
  const locked = state === "sending" || state === "uncertain";
  async function preview() {
    if (locked) return;
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setState("loading"); setPlan(null); setMessage(""); request.current = null;
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/financial-reopening-preview`, { cache: "no-store", signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось проверить открытие периода.");
      if (data.organization_id !== Number(org) || data.from_month !== month || data.status !== "preview" || data.posted !== false
          || typeof data.basis_digest !== "string" || !/^[a-f0-9]{64}$/.test(data.basis_digest)
          || !validRows(data.periods, data.reversals, month)) throw new Error("Получен неполный расчёт или расчёт другой книги/периода.");
      if (!controller.signal.aborted) setPlan(data);
    } catch (error) { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "Ошибка просмотра."); }
    finally { if (!controller.signal.aborted) setState("idle"); }
  }
  async function confirm() {
    if (sending.current || state === "sending" || state === "done" || !plan || reason.trim().length < 10) return;
    if (!request.current) {
      const key = crypto.randomUUID();
      request.current = { key, path: `/api/accounting/organizations/${org}/periods/${month}/financial-reopening-confirm`,
        body: JSON.stringify({ request_key: key, reason: reason.trim(), expected_basis_digest: plan.basis_digest }) };
    }
    const frozen = request.current;
    sending.current = true;
    let currentlyOpen = false;
    setState("sending"); onLock(true);
    try {
      const response = await fetch(frozen.path, { method: "POST", headers: { "Content-Type": "application/json" }, body: frozen.body });
      const data = await response.json();
      if (!response.ok) {
        if ([401,403,404,409,422].includes(response.status)) {
          setState("idle"); setPlan(null); request.current = null; onLock(false);
          setMessage("Открытие отклонено. Повторите просмотр: " + (typeof data.detail === "string" ? data.detail : "проверьте причину и права"));
          return;
        }
        throw new Error("Unknown reopening outcome");
      }
      if (data.organization_id !== Number(org) || data.from_month !== month || data.request_key !== frozen.key
          || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest)
          || !Number.isSafeInteger(data.receipt_id) || data.receipt_id <= 0 || !Array.isArray(data.periods)
          || data.periods.length !== plan.periods.length || data.periods.some((row: { month: string; closed: boolean }, i: number) => row.closed !== false || row.month !== plan.periods[i].month)) throw new Error("Unverified reopening result");
      if (!Array.isArray(data.current_periods) || data.current_periods.length < plan.periods.length
          || !data.current_periods.every((row: unknown) => record(row) && typeof row.month === "string" && typeof row.closed === "boolean")
          || !plan.periods.every(period => data.current_periods.some((row: { month: string }) => row.month === period.month))) throw new Error("Missing current period state");
      currentlyOpen = data.current_periods.every((row: { closed: boolean }) => !row.closed);
      setState("done"); setMessage(currentlyOpen ? "Периоды открыты. Обратные проводки сохранены; проверки необходимо повторить." : "Открытие ранее выполнено. Часть периодов уже закрыта повторно; обновите состояние книги."); onLock(false);
    } catch { setState("uncertain"); setMessage("Ответ не подтверждён. Повторите проверку результата тем же запросом."); return; }
    finally { sending.current = false; }
    if (mounted.current) { try { callback.current(currentlyOpen); } catch { setMessage("Операция открытия зарегистрирована. Обновите раздел для получения актуальных данных."); } }
  }
  return <section aria-label="Открытие периодов для исправлений" className="min-w-0 space-y-3 rounded border border-line p-3">
    <p>Будут открыты выбранный и последующие периоды. Проводки закрытия компенсируются связанными записями.</p>
    <Input aria-label="Причина открытия" maxLength={1000} disabled={locked || state === "done"} value={reason} onChange={event => setReason(event.target.value)} placeholder="Причина исправления, минимум 10 символов" />
    <Button disabled={locked || state === "loading" || state === "done"} onClick={() => void preview()}>Просмотреть последствия открытия</Button>
    {message && <p role={state === "done" ? "status" : "alert"}>{message}</p>}
    {plan && <><p>Периоды: {plan.periods.map(row => row.month).join(", ")}</p>
      {plan.reversals.map(row => <div key={row.entry_id} className="max-w-full overflow-x-auto"><p>Обратные проводки к операции № {row.entry_id} · {row.month}</p>
        <table className="w-full text-left text-sm"><thead><tr><th>Сторона</th><th>Счёт</th><th>BYN</th><th>Аналитика</th></tr></thead><tbody>{row.lines.map((line,i) => <tr key={i}><td>{line.side === "debit" ? "Дт" : "Кт"}</td><td>{line.account}</td><td>{line.amount}</td><td>{Object.entries(line.dimensions).map(([key,value]) => `${key}: ${value}`).join("; ")}</td></tr>)}</tbody></table></div>)}
      {state !== "done" && <Button disabled={state === "sending" || reason.trim().length < 10} onClick={() => void confirm()}>{state === "uncertain" ? "Проверить результат открытия" : "Подтвердить открытие периодов"}</Button>}
    </>}
  </section>;
}
