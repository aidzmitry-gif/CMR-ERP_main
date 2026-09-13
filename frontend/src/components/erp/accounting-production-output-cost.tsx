"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AccountingProductionOutputTransferConfirmation, type PreparedOutputTransfer } from "./accounting-production-output-transfer-confirmation";
import type { OutputTransferDraft } from "@/lib/production-output-transfer-journal";

type Output = { planned_quantity: string; confirmed_quantity: string; accepted_quantity: string;
  rejected_quantity: string; pending_quantity: string; sku_code?: string | null; lot?: string | null; unit: string | null;
  documents?: { document_id: number; operation_date: string }[] };
type Basis = { organization_id: number; month: string; policy_id: number; analytical_order: string; warehouse: string;
  output: Output; wip: { account: string; balance_byn: string; unit_cost_byn?: string; source_lines: { entry_id: number; line_id: number; side: string; amount_byn: string }[] };
  target: { finished_goods_account: string | null }; status: string; explanation: string; candidate_transfer_byn: string | null;
  posting_available: boolean; final_cost_certified: boolean; scope: string; basis_digest?: string };
type Props = { org: string; month: string; policyId: string; disabled: boolean; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };

const money = /^-?\d+\.\d{2}$/;
const quantity = /^\d+\.\d{2}$/;
const statuses = new Set(["awaiting_wip_cost", "awaiting_full_accepted_output", "awaiting_output_period_alignment", "awaiting_finished_goods_policy", "ready_for_transfer_review"]);
const monthEnd = (month: string) => { const [year, value] = month.split("-").map(Number); return `${month}-${String(new Date(year, value, 0).getDate()).padStart(2, "0")}`; };

export function AccountingProductionOutputCost({ org, month, policyId, disabled, onEntry, onLock }: Props) {
  const [orderId, setOrderId] = useState(""), [orderAnalytics, setOrderAnalytics] = useState("");
  const [warehouse, setWarehouse] = useState("Главный"), [department, setDepartment] = useState(""), [postingDate, setPostingDate] = useState(monthEnd(month)), [result, setResult] = useState<Basis | null>(null), [prepared, setPrepared] = useState<PreparedOutputTransfer | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    if (busy || disabled) return;
    if (!/^\d+$/.test(orderId) || Number(orderId) <= 0 || !orderAnalytics.trim() || !warehouse.trim()) {
      setError("Укажите номер наряда, аналитический заказ и склад."); setResult(null); return;
    }
    setBusy(true); setError(""); setResult(null); setPrepared(null);
    try {
      const query = new URLSearchParams({ policy_id: policyId, order_id: orderId, order_analytics: orderAnalytics.trim(), warehouse: warehouse.trim() });
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-output-cost-preview?${query}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось сверить выпуск и НЗП.");
      const output = data.output ?? {};
      if (String(data.organization_id) !== org || data.month !== month || String(data.policy_id) !== policyId || data.scope !== "production_output_cost_basis"
        || !statuses.has(data.status) || data.posting_available !== false || data.final_cost_certified !== false
        || ![output.planned_quantity, output.confirmed_quantity, output.accepted_quantity, output.rejected_quantity, output.pending_quantity].every((v: unknown) => typeof v === "string" && quantity.test(v))
        || typeof data.wip?.balance_byn !== "string" || !money.test(data.wip.balance_byn)
        || (data.candidate_transfer_byn !== null && !money.test(data.candidate_transfer_byn)))
        throw new Error("Результат сверки не соответствует выбранному юрлицу, периоду или денежному формату.");
      setResult(data as Basis);
    } catch (e) { setError(e instanceof Error ? e.message : "Сверка не подтверждена."); }
    finally { setBusy(false); }
  }
  const draft = (): OutputTransferDraft => ({ policy_id: Number(policyId), order_id: Number(orderId), analytical_order: orderAnalytics.trim(),
    department: department.trim(), warehouse: warehouse.trim(), posting_date: postingDate, output_document_ids: (result?.output.documents ?? []).map(item => item.document_id) });
  async function prepareTransfer() {
    if (busy || disabled || !result || result.status !== "ready_for_transfer_review" || !department.trim() || !result.basis_digest) return;
    const value = draft(); setBusy(true); setError(""); setPrepared(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-output-transfer-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(value) });
      const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось подготовить перенос НЗП.");
      if (String(data.organization_id) !== org || data.month !== month || String(data.policy_id) !== policyId || data.scope !== "production_output_cost_basis"
        || data.posting_available !== true || data.final_cost_certified !== false || data.basis_digest !== result.basis_digest
        || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest) || !Array.isArray(data.posting?.lines) || data.posting.lines.length !== 2)
        throw new Error("Пакет переноса не соответствует выбранному юрлицу, периоду или основанию.");
      const debit = data.posting.lines.find((line: { side?: string }) => line.side === "debit"); const credit = data.posting.lines.find((line: { side?: string }) => line.side === "credit");
      if (!debit || !credit || debit.amount !== credit.amount || typeof debit.account !== "string" || typeof credit.account !== "string") throw new Error("Пакет переноса не сбалансирован.");
      setPrepared({ draft: value, basis_digest: data.basis_digest, digest: data.digest, amount_byn: debit.amount, debit_account: debit.account, credit_account: credit.account });
    } catch (e) { setError(e instanceof Error ? e.message : "Перенос НЗП не подготовлен."); } finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-lg border border-line p-3" aria-label="Фактическая себестоимость выпуска">
    <h3 className="font-semibold">Фактическая база выпуска и НЗП</h3>
    <p className="text-sm text-muted">Сверяет принятый складом выпуск с проведённой стоимостью НЗП. Результат предварительный и сам проводку не создаёт.</p>
    <div className="grid gap-3 md:grid-cols-3">
      <Input aria-label="Номер производственного наряда" value={orderId} disabled={disabled || busy || !!result} onChange={e => setOrderId(e.target.value)} placeholder="№ наряда" />
      <Input aria-label="Аналитический заказ" value={orderAnalytics} disabled={disabled || busy || !!result} onChange={e => setOrderAnalytics(e.target.value)} placeholder="Аналитика заказа" />
      <Input aria-label="Склад выпуска" value={warehouse} disabled={disabled || busy || !!result} onChange={e => setWarehouse(e.target.value)} placeholder="Склад" />
      <Input aria-label="Подразделение выпуска" value={department} disabled={disabled || busy || !!result} onChange={e => setDepartment(e.target.value)} placeholder="Подразделение" />
      <Input aria-label="Дата переноса выпуска" type="date" value={postingDate} disabled={disabled || busy || !!result} onChange={e => setPostingDate(e.target.value)} />
    </div>
    <Button disabled={disabled || busy || !policyId} onClick={() => void load()}>Сверить выпуск и НЗП</Button>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {result && <article className="space-y-2 rounded border border-accent p-3">
      <p><strong>Статус:</strong> {result.status}</p><p>{result.explanation}</p>
      <p>Выпуск: подтверждено {result.output.confirmed_quantity}, принято {result.output.accepted_quantity}, брак {result.output.rejected_quantity}, ожидает {result.output.pending_quantity} {result.output.unit ?? ""}</p>
      <p>НЗП по счёту {result.wip.account}: {result.wip.balance_byn} BYN{result.wip.unit_cost_byn ? ` · ${result.wip.unit_cost_byn} BYN/ед.` : ""}</p>
      <p>Счёт готовой продукции: {result.target.finished_goods_account ?? "не настроен"}. К переносу: {result.candidate_transfer_byn ?? "не определяется"} BYN.</p>
      {result.wip.source_lines.map(line => <p key={line.line_id} className="text-sm"><button className="underline" disabled={!onEntry || disabled} onClick={() => onEntry?.(line.entry_id)}>Проводка №{line.entry_id}</button>{` · ${line.side === "debit" ? "Дт" : "Кт"} ${line.amount_byn} BYN`}</p>)}
      {!prepared && result.status === "ready_for_transfer_review" && <><p className="text-sm text-muted">Полный выпуск найден. Введите подразделение и подготовьте отдельное подтверждение проводки.</p><Button disabled={disabled || busy || !department.trim() || !result.basis_digest} onClick={() => void prepareTransfer()}>Подготовить перенос НЗП</Button></>}
      {prepared && <p className="text-sm text-muted">Пакет переноса подготовлен, но ещё не проведён. Окончательная себестоимость периода остаётся непроверенной.</p>}
    </article>}
    <AccountingProductionOutputTransferConfirmation org={org} month={month} disabled={disabled || busy} prepared={prepared}
      onEntry={onEntry} onLock={onLock} onConfirmed={() => { setPrepared(null); setResult(null); }} />
  </section>;
}
