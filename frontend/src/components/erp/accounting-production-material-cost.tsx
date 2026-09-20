"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AccountingProductionMaterialConfirmation, type PreparedMaterialPosting } from "./accounting-production-material-confirmation";
import type { MaterialPostingDraft } from "@/lib/production-material-journal";

type Props = { org: string; month: string; policyId: string; disabled: boolean; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };
type Result = { organization_id: number; month: string; policy_id: number; scope: string; status: string; explanation: string;
  wms_movement: { id: number; reason: string; sku: string; warehouse: string; lot: string; quantity: string; doc_ref: string };
  inventory_cost: { issue_cost_byn: string; account: string; basis_digest: string };
  candidate_posting: { debit: { account: string; amount_byn: string; dimensions: Record<string, string> };
    credit: { account: string; amount_byn: string; quantity?: string; dimensions: Record<string, string> } };
  posting_available: false; final_cost_certified: false };
const money = /^\d+\.\d{2}$/;

export function AccountingProductionMaterialCost({ org, month, policyId, disabled, onEntry, onLock }: Props) {
  const [orderId, setOrderId] = useState(""), [orderAnalytics, setOrderAnalytics] = useState("");
  const [department, setDepartment] = useState(""), [movementId, setMovementId] = useState("");
  const [account, setAccount] = useState("10"), [warehouse, setWarehouse] = useState("Главный");
  const [sku, setSku] = useState(""), [lot, setLot] = useState(""), [quantity, setQuantity] = useState("");
  const [postingDate, setPostingDate] = useState(`${month}-01`), [result, setResult] = useState<Result | null>(null), [prepared, setPrepared] = useState<PreparedMaterialPosting | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const command = (): MaterialPostingDraft => ({ policy_id: Number(policyId), order_id: Number(orderId), order_analytics: orderAnalytics.trim(),
    department: department.trim(), wms_movement_id: Number(movementId), posting_date: postingDate,
    account: account.trim(), warehouse: warehouse.trim(), sku: sku.trim(), lot: lot.trim(), quantity });
  async function load() {
    if (busy || disabled) return;
    if (![orderId, movementId, orderAnalytics, department, account, warehouse, sku, lot, quantity, postingDate].every(v => v.trim())) {
      setError("Заполните наряд, аналитику, подразделение, WMS-движение, партию и количество."); setResult(null); return;
    }
    if (!/^\d+$/.test(orderId) || !/^\d+$/.test(movementId) || !/^\d+(?:\.\d{1,6})?$/.test(quantity)) {
      setError("Номер наряда, WMS-движение и количество должны быть точными числовыми значениями."); setResult(null); return;
    }
    setBusy(true); setError(""); setResult(null); setPrepared(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-material-issue-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
        body: JSON.stringify({ policy_id: Number(policyId), order_id: Number(orderId), order_analytics: orderAnalytics.trim(), department: department.trim(),
          wms_movement_id: Number(movementId), posting_date: postingDate, account: account.trim(), warehouse: warehouse.trim(), sku: sku.trim(), lot: lot.trim(), quantity }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось сверить списание материалов.");
      if (String(data.organization_id) !== org || data.month !== month || String(data.policy_id) !== policyId || data.scope !== "production_material_cost_basis"
        || data.posting_available !== false || data.final_cost_certified !== false || !money.test(data.inventory_cost?.issue_cost_byn)
        || data.wms_movement?.reason !== "production_issue" || !money.test(data.candidate_posting?.debit?.amount_byn)
        || data.candidate_posting.debit.amount_byn !== data.candidate_posting.credit.amount_byn)
        throw new Error("Результат сверки не соответствует выбранной организации или денежному формату.");
      setResult(data as Result);
    } catch (e) { setError(e instanceof Error ? e.message : "Сверка материалов не подтверждена."); }
    finally { setBusy(false); }
  }
  async function preparePosting() {
    if (busy || disabled || !result) return;
    setBusy(true); setError(""); setPrepared(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-material-issue-posting-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(command()),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось подготовить проводку материала.");
      if (data.zero_value === true) {
        const zero = data.zero_value_receipt;
        const normalizeQuantity = (value: unknown) => typeof value === "string" && /^\d+(?:\.\d{1,6})?$/.test(value)
          ? value.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "") : null;
        if (String(data.organization_id) !== org || data.month !== month || String(data.policy_id) !== policyId
          || data.scope !== "production_material_cost_basis" || data.posting_available !== false
          || data.quantity_registered !== false || data.entry_id !== null || data.final_cost_certified !== false
          || typeof data.basis_digest !== "string" || !/^[a-f0-9]{64}$/.test(data.basis_digest)
          || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest)
          || zero?.command_version !== 5 || zero.operation !== "inventory_issue"
          || zero.basis_digest !== data.basis_digest || zero.material_binding?.movement_id !== Number(movementId)
          || zero.material_binding?.order_id !== Number(orderId) || zero.document?.account !== account
          || zero.document?.warehouse !== warehouse || zero.document?.sku !== sku || zero.document?.lot !== lot
          || normalizeQuantity(zero.document?.quantity) !== normalizeQuantity(quantity)
          || data.inventory_cost?.issue_cost_byn !== "0.00" || typeof zero.destination_account !== "string")
          throw new Error("Квитанция количественного списания не соответствует проверенному материалу.");
        setPrepared({ draft: { ...command(), zero_value: true }, basis_digest: data.basis_digest,
          digest: data.digest, amount_byn: "0.00", debit_account: zero.destination_account, credit_account: account });
        return;
      }
      if (String(data.organization_id) !== org || data.month !== month || String(data.policy_id) !== policyId
        || data.scope !== "production_material_cost_basis" || data.posting_available !== true || data.final_cost_certified !== false
        || typeof data.basis_digest !== "string" || !/^[a-f0-9]{64}$/.test(data.basis_digest)
        || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest)
        || !data.posting?.lines?.length || data.posting.lines.some((line: { amount?: string }) => typeof line.amount !== "string" || !/^\d+\.\d{2}$/.test(line.amount)))
        throw new Error("Пакет проводки не соответствует выбранному юрлицу, периоду или денежному формату.");
      const lines = data.posting.lines as { side: string; account: string; amount: string; quantity?: string | null }[];
      const debits = lines.filter(line => line.side === "debit"), credits = lines.filter(line => line.side === "credit");
      const debit = debits[0], credit = credits[0];
      const cents = (amount: string) => BigInt(amount.replace(".", ""));
      if (debits.length !== 1 || !credit || lines.length !== debits.length + credits.length
        || typeof debit.account !== "string" || credits.some(line => typeof line.account !== "string" || line.account !== credit.account)
        || credits.reduce((total, line) => total + cents(line.amount), BigInt(0)) !== cents(debit.amount))
        throw new Error("Пакет проводки не содержит равные дебет и кредит.");
      setPrepared({ draft: command(), basis_digest: data.basis_digest, digest: data.digest, amount_byn: debit.amount,
        debit_account: debit.account, credit_account: credit.account, credit_lines: credits });
    } catch (e) { setError(e instanceof Error ? e.message : "Проводка материала не подготовлена."); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-lg border border-line p-3" aria-label="Материалы в НЗП">
    <h3 className="font-semibold">Списание материала в НЗП</h3>
    <p className="text-sm text-muted">Проверяет одну партию по бухгалтерской стоимости и точному WMS-движению production_issue. Просмотр не создаёт проводку.</p>
    <div className="grid gap-3 md:grid-cols-3">
      <Input aria-label="Наряд для материала" value={orderId} disabled={disabled || busy || !!result} onChange={e => setOrderId(e.target.value)} placeholder="№ наряда" />
      <Input aria-label="Аналитика наряда" value={orderAnalytics} disabled={disabled || busy || !!result} onChange={e => setOrderAnalytics(e.target.value)} placeholder="Заказ" />
      <Input aria-label="Подразделение материала" value={department} disabled={disabled || busy || !!result} onChange={e => setDepartment(e.target.value)} placeholder="Подразделение" />
      <Input aria-label="WMS движение материала" value={movementId} disabled={disabled || busy || !!result} onChange={e => setMovementId(e.target.value)} placeholder="ID WMS-движения" />
      <Input aria-label="Счёт материала" value={account} disabled={disabled || busy || !!result} onChange={e => setAccount(e.target.value)} placeholder="Счёт 10/41" />
      <Input aria-label="Склад материала" value={warehouse} disabled={disabled || busy || !!result} onChange={e => setWarehouse(e.target.value)} placeholder="Склад" />
      <Input aria-label="SKU материала" value={sku} disabled={disabled || busy || !!result} onChange={e => setSku(e.target.value)} placeholder="SKU" />
      <Input aria-label="Партия материала" value={lot} disabled={disabled || busy || !!result} onChange={e => setLot(e.target.value)} placeholder="Партия" />
      <Input aria-label="Количество материала" value={quantity} disabled={disabled || busy || !!result} onChange={e => setQuantity(e.target.value)} placeholder="Количество" />
      <Input aria-label="Дата списания материала" type="date" value={postingDate} disabled={disabled || busy || !!result} onChange={e => setPostingDate(e.target.value)} />
    </div>
    <Button disabled={disabled || busy || !policyId} onClick={() => void load()}>Проверить материал и НЗП</Button>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {result && <article className="space-y-2 rounded border border-accent p-3">
      <p><strong>Статус:</strong> {result.status}</p><p>{result.explanation}</p>
      <p>WMS-движение №{result.wms_movement.id}: {result.wms_movement.sku} · {result.wms_movement.quantity} · партия {result.wms_movement.lot} · {result.wms_movement.reason}</p>
      <p>Стоимость партии: {result.inventory_cost.issue_cost_byn} BYN · основание {result.inventory_cost.basis_digest.slice(0, 12)}…</p>
      {result.inventory_cost.issue_cost_byn === "0.00"
        ? <p>Будет зарегистрировано количество без денежной проводки.</p>
        : <p>Кандидат: Дт {result.candidate_posting.debit.account} {result.candidate_posting.debit.amount_byn} BYN → Кт {result.candidate_posting.credit.account} {result.candidate_posting.credit.amount_byn} BYN.</p>}
      {!prepared && <><p className="text-sm text-muted">Проводка не создана; требуется отдельная подготовка и подтверждение бухгалтера.</p>
        <Button disabled={disabled || busy} onClick={() => void preparePosting()}>Подготовить подтверждение проводки</Button></>}
      {prepared && <p className="text-sm text-muted">Пакет проводки подготовлен, но ещё не проведён. Полная себестоимость остаётся непроверенной.</p>}
    </article>}
    <AccountingProductionMaterialConfirmation org={org} month={month} disabled={disabled || busy} prepared={prepared}
      onEntry={onEntry} onLock={onLock} onConfirmed={() => { setPrepared(null); setResult(null); }} />
  </section>;
}
