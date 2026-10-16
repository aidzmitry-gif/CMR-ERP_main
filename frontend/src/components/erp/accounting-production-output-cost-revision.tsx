"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { clearRevision, pendingRevision, saveRevision, type PendingRevision } from "@/lib/production-output-cost-revision-journal";

type Props = { org: string; month: string; disabled: boolean; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };
type Access = { principal: string; can_confirm: boolean };
type Preview = {
  organization_id: string | number; month: string; original_entry_id: number; posting_date: string; request_evidence: string;
  basis_digest: string; source: { candidate_transfer_byn: string }; destinations: {
    key: string; kind: "remaining" | "disposed"; account: string; dimensions: Record<string,string>;
    amount_byn: string; side: string; destination: {entry_id:number} | null }[];
  posting_document: { lines: { account: string; side: string; amount: string; dimensions: Record<string,string> }[] } | null; final_cost_certified: false;
};

const staleBasis = "Output cost basis changed; preview again";
const isId = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
const dimensionNames: Record<string,string> = {warehouse:"Склад",sku:"Товар",lot:"Партия",department:"Подразделение",order:"Заказ"};
const analytics = (dimensions: Record<string,string>) => Object.entries(dimensions).map(([key,value])=>`${dimensionNames[key] ?? key}: ${value}`).join(" · ");
const validDimensions = (value: unknown) => Boolean(value && typeof value === "object" && !Array.isArray(value) && Object.values(value).every(item=>typeof item === "string"));
const validMoney = (value: unknown) => typeof value === "string" && /^\d+\.\d{2}$/.test(value);
const lastDay = (month: string) => `${month}-${String(new Date(+month.slice(0, 4), +month.slice(5), 0).getDate()).padStart(2, "0")}`;
const dateInMonth = (date: string, month: string) => /^\d{4}-\d{2}-\d{2}$/.test(date) && date >= `${month}-01` && date <= lastDay(month);

export function AccountingProductionOutputCostRevision({ org, month, disabled, onEntry, onLock }: Props) {
  const [order, setOrder] = useState("");
  const [date, setDate] = useState(lastDay(month));
  const [evidence, setEvidence] = useState("");
  const [entry, setEntry] = useState<number | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewPrincipal, setPreviewPrincipal] = useState("");
  const [pending, setPending] = useState<PendingRevision | null>(null);
  const [principal, setPrincipal] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const inFlight = useRef(false);

  const active = (token: number) => generation.current === token;
  const begin = () => {
    if (disabled || inFlight.current) return false;
    inFlight.current = true;
    setBusy(true);
    onLock?.(true);
    return true;
  };
  const end = () => { inFlight.current = false; setBusy(false); onLock?.(false); };

  async function readAccess(token: number): Promise<Access> {
    const response = await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
    const value = await response.json();
    if (!response.ok || String(value.organization_id) !== org || typeof value.principal !== "string" || !value.principal.trim() || typeof value.can_confirm !== "boolean") {
      throw Error("Не удалось проверить права корректировки.");
    }
    if (active(token)) setPrincipal(value.principal);
    return value;
  }

  useEffect(() => {
    const token = ++generation.current;
    setBusy(false);
    setOrder(""); setDate(lastDay(month)); setEvidence(""); setEntry(null); setPreview(null); setPreviewPrincipal(""); setPending(null); setPrincipal(""); setError(""); setNotice("");
    void (async () => {
      try {
        const access = await readAccess(token);
        const saved = pendingRevision(localStorage, org, month, access.principal);
        if (active(token)) setPending(saved);
      } catch (reason) {
        if (active(token)) setError(reason instanceof Error ? reason.message : "Не удалось восстановить сохранённый запрос.");
      }
    })();
    return () => {
      generation.current++;
      if (inFlight.current) { inFlight.current = false; onLock?.(false); }
    };
  }, [org, month]);

  function invalidate() { setPreview(null); setPreviewPrincipal(""); setError(""); setNotice(""); }

  async function resolve() {
    if (!begin()) return;
    const token = generation.current;
    setError("");
    try {
      if (!/^\d+$/.test(order)) throw Error("Укажите номер наряда.");
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-output-transfer-status/${order}`, { cache: "no-store" });
      const value = await response.json();
      if (!response.ok || String(value.organization_id) !== org || value.month !== month || String(value.order_id) !== order || !isId(value.entry_id)) {
        throw Error("Не найден неизменяемый выпуск для выбранного наряда.");
      }
      if (active(token)) { setEntry(value.entry_id); setPreview(null); }
    } catch (reason) { if (active(token)) setError(reason instanceof Error ? reason.message : "Выпуск не найден."); }
    finally { if (active(token)) end(); }
  }

  async function makePreview() {
    if (!begin()) return;
    const token = generation.current;
    setError("");
    try {
      if (!entry || !evidence.trim() || !dateInMonth(date, month)) throw Error("Укажите дату периода и основание корректировки.");
      const access = await readAccess(token);
      if (!active(token)) return;
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-output-cost-revision-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ original_entry_id: entry, posting_date: date, request_evidence: evidence.trim() }),
      });
      const value = await response.json();
      if (!response.ok || String(value.organization_id) !== org || value.month !== month || value.original_entry_id !== entry ||
        value.posting_date !== date || value.request_evidence !== evidence.trim() || typeof value.basis_digest !== "string" ||
        !/^[a-f0-9]{64}$/.test(value.basis_digest) || !Array.isArray(value.destinations) ||
        !validMoney(value.source?.candidate_transfer_byn) || value.final_cost_certified !== false ||
        !value.destinations.every((line: Preview["destinations"][number]) => line && typeof line.key === "string" &&
          ["remaining","disposed"].includes(line.kind) && typeof line.account === "string" && validDimensions(line.dimensions) &&
          validMoney(line.amount_byn) && ["debit","credit"].includes(line.side) &&
          (line.kind === "remaining" ? line.destination === null : isId(line.destination?.entry_id))) ||
        !(value.posting_document === null || Array.isArray(value.posting_document?.lines) &&
          value.posting_document.lines.every((line: NonNullable<Preview["posting_document"]>["lines"][number]) =>
            typeof line.account === "string" && ["debit","credit"].includes(line.side) && validMoney(line.amount) && validDimensions(line.dimensions)))) {
        throw Error(value.detail || "Предварительный расчёт корректировки недоступен.");
      }
      if (active(token)) { setPreview(value); setPreviewPrincipal(access.principal); }
    } catch (reason) { if (active(token)) setError(reason instanceof Error ? reason.message : "Предварительный расчёт не получен."); }
    finally { if (active(token)) end(); }
  }

  async function confirm(retry: boolean) {
    if (!begin()) return;
    const token = generation.current;
    setError(""); setNotice("");
    let item: PendingRevision | null = null;
    try {
      const access = await readAccess(token);
      if (!active(token)) return;
      if (retry) {
        if (!pending || pending.principal !== access.principal) throw Error("Пользователь изменился; сохранённый запрос не отправлен.");
        item = pendingRevision(localStorage, org, month, access.principal);
        if (!item) throw Error("Сохранённый запрос не найден; сформируйте новый предварительный расчёт.");
        if (JSON.stringify(item) !== JSON.stringify(pending)) throw Error("Сохранённый запрос изменился в другой вкладке. Обновите страницу перед повтором.");
      } else {
        if (previewPrincipal !== access.principal) throw Error("Пользователь изменился; сформируйте новый предварительный расчёт.");
        if (!access.can_confirm || !preview || !entry || !evidence.trim() || !dateInMonth(date, month)) throw Error("Нет права или подготовленного пакета.");
        item = { org, month, principal: access.principal, command: { original_entry_id: entry, posting_date: date, request_evidence: evidence.trim(), request_key: crypto.randomUUID(), basis_digest: preview.basis_digest } };
        saveRevision(localStorage, item);
        if (active(token)) setPending(item);
      }
      if (item.principal !== access.principal) throw Error("Пользователь изменился; сохранённый запрос не отправлен.");
      if (!access.can_confirm) throw Error("Нет права подтверждать корректировку.");
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-output-cost-revision-confirm`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": item.principal }, body: JSON.stringify(item.command),
      });
      const value = await response.json();
      if (!active(token)) return;
      if (response.status === 409 && value.detail === staleBasis) {
        clearRevision(localStorage, item); setPending(null); setPreview(null); throw Error("Основание изменилось; выполните новый preview.");
      }
      if (!response.ok || String(value.organization_id) !== org || value.month !== month || value.actor !== item.principal ||
        value.original_entry_id !== item.command.original_entry_id || value.request_key !== item.command.request_key || value.basis_digest !== item.command.basis_digest ||
        !isId(value.revision_id) || !isId(value.sequence) || value.posted !== true || value.final_cost_certified !== false || !(value.entry_id === null || isId(value.entry_id))) {
        throw Error("Результат подтверждения неизвестен; запрос сохранён.");
      }
      clearRevision(localStorage, item); setPending(null); setPreview(null);
      if (value.entry_id === null) setNotice("Корректировка зарегистрирована; новой проводки не создано.");
      else { onEntry?.(value.entry_id); setNotice(`Корректировка зарегистрирована. Проводка №${value.entry_id}.`); }
    } catch (reason) { if (active(token)) setError(reason instanceof Error ? reason.message : "Запрос сохранён для повтора."); }
    finally { if (active(token)) end(); }
  }

  const locked = disabled || busy || Boolean(pending);
  return <section className="space-y-3 rounded-lg border border-line p-3" aria-label="Корректировка себестоимости выпуска">
    <h3 className="font-semibold">Корректировка себестоимости выпуска</h3>
    <p className="text-sm text-muted">Корректировка не сертифицирует окончательную себестоимость периода.</p>
    <div className="grid gap-2 md:grid-cols-3">
      <Input aria-label="Номер наряда" value={order} disabled={locked} onChange={(event) => { setOrder(event.target.value); setEntry(null); invalidate(); }} placeholder="№ наряда" />
      <Input aria-label="Дата корректировки" type="date" value={date} disabled={locked} onChange={(event) => { setDate(event.target.value); invalidate(); }} />
      <Input aria-label="Основание корректировки" value={evidence} disabled={locked} onChange={(event) => { setEvidence(event.target.value); invalidate(); }} placeholder="Основание" />
    </div>
    <Button disabled={locked} onClick={() => void resolve()}>Найти выпуск</Button>
    {entry && <Button disabled={locked} onClick={() => void makePreview()}>Подготовить корректировку</Button>}
    {preview && <div className="space-y-1 text-sm">
      <p>Источник: {preview.source.candidate_transfer_byn} BYN</p>
      {preview.destinations.map((line) => <div key={line.key} className="break-words rounded border border-line p-2">
        <p>{line.kind === "remaining" ? "Остаток на складе" : "Выбывший товар"} · счёт {line.account}: {line.side === "debit" ? "+" : "-"}{line.amount_byn} BYN</p>
        <p className="text-muted">{analytics(line.dimensions)}</p>
        {line.destination && <button className="underline" disabled={disabled || busy || !onEntry} onClick={()=>onEntry?.(line.destination!.entry_id)}>Проводка выбытия №{line.destination.entry_id}</button>}
      </div>)}
      {preview.posting_document?.lines.map((line, index) => <p className="break-words" key={`${line.account}-${index}`}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.amount} BYN{Object.keys(line.dimensions).length>0 ? ` · ${analytics(line.dimensions)}` : ""}</p>)}
      <Button disabled={disabled || busy} onClick={() => void confirm(false)}>Подтвердить корректировку</Button>
    </div>}
    {pending && <div className="space-y-1 text-sm"><p>Сохранён запрос пользователя {pending.principal}. Автоматически не отправлен.</p><Button disabled={disabled || busy} onClick={() => void confirm(true)}>Повторить тот же запрос</Button></div>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {principal && <p className="text-sm text-muted">Пользователь: {principal}</p>}
  </section>;
}
