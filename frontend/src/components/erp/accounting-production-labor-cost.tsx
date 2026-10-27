"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/input";
import { AccountingProductionLaborConfirmation, type PreparedProductionLabor } from "./accounting-production-labor-confirmation";
import type { ProductionLaborDraft, ProductionLaborLine } from "@/lib/production-labor-journal";

type Props = { org: string; month: string; policyId: string; disabled: boolean; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };
type Result = { organization_id: number; month: string; policy_id: number; source_digest: string; digest: string;
  status: string; posting_available: true; posted: false; final_cost_certified: false;
  posting_document: { lines: Array<{ account: string; side: "debit" | "credit"; amount: string }> } };
const money = /^\d+\.\d{2}$/;
const emptyLine = (id: string): ProductionLaborLine => ({ source_line_id: id, employee: "", order_id: undefined, order_analytics: undefined,
  department: "", cost_account: "20", role: "direct", amount_byn: "", evidence: "" });
const requestKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
  ? crypto.randomUUID() : `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0")}`;
const cents = (value: string) => { const [whole, fraction] = value.split("."); return Number(whole) * 100 + Number(fraction); };

export function AccountingProductionLaborCost({ org, month, policyId, disabled, onEntry, onLock }: Props) {
  const [sourceDocument, setSourceDocument] = useState(`payroll:${month}:batch-1`), [sourceDigest, setSourceDigest] = useState("");
  const [verifiedBy, setVerifiedBy] = useState(""), [sourceEvidence, setSourceEvidence] = useState("");
  const [payrollAccount, setPayrollAccount] = useState("70"), [postingDate, setPostingDate] = useState(`${month}-01`);
  const [lines, setLines] = useState<ProductionLaborLine[]>([emptyLine("line-1")]);
  const [requestId, setRequestId] = useState(requestKey), [result, setResult] = useState<Result | null>(null);
  const [prepared, setPrepared] = useState<PreparedProductionLabor | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  function updateLine(index: number, patch: Partial<ProductionLaborLine>) {
    setLines(current => current.map((line, i) => i === index ? { ...line, ...patch } : line));
  }
  function draft(): ProductionLaborDraft {
    return {
      request_key: requestId, source_document: sourceDocument.trim(), source_version: 1,
      source_digest: sourceDigest.trim(), verified_by: verifiedBy.trim(), source_evidence: sourceEvidence.trim(),
      policy_id: Number(policyId), posting_date: postingDate, payroll_account: payrollAccount.trim(),
      lines: lines.map(line => ({ ...line, employee: line.employee.trim(), department: line.department.trim(),
        cost_account: line.cost_account.trim(), amount_byn: line.amount_byn.trim(), evidence: line.evidence.trim(),
        ...(line.order_id ? { order_id: Number(line.order_id), order_analytics: line.order_analytics?.trim() } : {}) })),
    };
  }
  async function load() {
    if (busy || disabled) return;
    const command = draft();
    if (!command.source_document || !/^[a-f0-9]{64}$/.test(command.source_digest) || !command.verified_by || command.source_evidence.length < 10
      || !command.posting_date.startsWith(`${month}-`) || !command.payroll_account || command.lines.some(line => !line.source_line_id || !line.employee
        || !line.department || !line.cost_account || !money.test(line.amount_byn) || line.amount_byn === "0.00" || line.evidence.length < 10
        || (line.role === "direct" && (!line.order_id || !line.order_analytics)))) {
      setError("Заполните источник и подтверждение: digest, проверяющего, основание, счёт зарплаты и все строки начислений."); setResult(null); return;
    }
    setBusy(true); setError(""); setResult(null); setPrepared(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/production-labor-import-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(command),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось проверить импорт труда.");
      const posted = data.posting_document?.lines as Array<{ side?: string; amount?: string }> | undefined;
      const debit = posted?.filter(line => line.side === "debit") ?? [], credit = posted?.filter(line => line.side === "credit") ?? [];
      if (String(data.organization_id) !== org || data.month !== month || String(data.policy_id) !== policyId
        || data.status !== "reviewed_verified_payroll" || data.posting_available !== true || data.posted !== false
        || data.final_cost_certified !== false || data.source_digest !== command.source_digest
        || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest) || !debit.length || debit.length !== credit.length
        || debit.some(line => typeof line.amount !== "string" || !money.test(line.amount))
        || credit.some(line => typeof line.amount !== "string" || !money.test(line.amount))
        || debit.reduce((sum, line) => sum + cents(line.amount!), 0) !== credit.reduce((sum, line) => sum + cents(line.amount!), 0))
        throw new Error("Пакет импорта не соответствует выбранному юрлицу, периоду или сбалансированной проводке.");
      setResult(data as Result);
      setPrepared({ draft: command, digest: data.digest, amount_byn: (debit.reduce((sum, line) => sum + cents(line.amount!), 0) / 100).toFixed(2) });
    } catch (e) { setError(e instanceof Error ? e.message : "Импорт труда не подготовлен."); }
    finally { setBusy(false); }
  }
  function reset() { setResult(null); setPrepared(null); setError(""); setRequestId(requestKey()); }
  return <section className="space-y-3 rounded-lg border border-line p-3" aria-label="Начисления труда в НЗП">
    <h3 className="font-semibold">Проверенный импорт труда в производство</h3>
    <p className="text-sm text-muted">Импортирует подтверждённые начисления с расшифровкой. Текущий управленческий расчёт зарплаты автоматически не проводится.</p>
    <div className="grid gap-3 md:grid-cols-3">
      <Input aria-label="Документ ведомости" value={sourceDocument} disabled={disabled || busy || !!result} onChange={e => setSourceDocument(e.target.value)} />
      <Input aria-label="Digest ведомости" value={sourceDigest} disabled={disabled || busy || !!result} onChange={e => setSourceDigest(e.target.value)} placeholder="SHA-256 источника" />
      <Input aria-label="Проверил начисления" value={verifiedBy} disabled={disabled || busy || !!result} onChange={e => setVerifiedBy(e.target.value)} placeholder="Ответственный бухгалтер" />
      <Input aria-label="Счёт задолженности по зарплате" value={payrollAccount} disabled={disabled || busy || !!result} onChange={e => setPayrollAccount(e.target.value)} placeholder="Счёт 70" />
      <Input aria-label="Дата начисления труда" type="date" value={postingDate} disabled={disabled || busy || !!result} onChange={e => setPostingDate(e.target.value)} />
      <Input aria-label="Основание ведомости" value={sourceEvidence} disabled={disabled || busy || !!result} onChange={e => setSourceEvidence(e.target.value)} placeholder="Документ и сверка" />
    </div>
    {lines.map((line, index) => <div className="grid gap-2 rounded border border-line p-2 md:grid-cols-4" key={line.source_line_id}>
      <Input aria-label={`Строка труда ${index + 1}`} value={line.source_line_id} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { source_line_id: e.target.value })} placeholder="ID строки" />
      <Input aria-label={`Сотрудник труда ${index + 1}`} value={line.employee} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { employee: e.target.value })} placeholder="Сотрудник" />
      <Select aria-label={`Роль труда ${index + 1}`} value={line.role} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { role: e.target.value as ProductionLaborLine["role"] })}><option value="direct">Прямой труд</option><option value="overhead">Накладные</option></Select>
      <Input aria-label={`Сумма труда ${index + 1}`} value={line.amount_byn} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { amount_byn: e.target.value })} placeholder="BYN" />
      <Input aria-label={`Наряд труда ${index + 1}`} value={line.order_id ?? ""} disabled={disabled || busy || !!result || line.role === "overhead"} onChange={e => updateLine(index, { order_id: e.target.value ? Number(e.target.value) : undefined })} placeholder="№ наряда" />
      <Input aria-label={`Аналитика труда ${index + 1}`} value={line.order_analytics ?? ""} disabled={disabled || busy || !!result || line.role === "overhead"} onChange={e => updateLine(index, { order_analytics: e.target.value })} placeholder="Заказ" />
      <Input aria-label={`Подразделение труда ${index + 1}`} value={line.department} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { department: e.target.value })} placeholder="Подразделение" />
      <Input aria-label={`Счёт затрат труда ${index + 1}`} value={line.cost_account} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { cost_account: e.target.value })} placeholder="20 или 25" />
      <Input aria-label={`Основание строки труда ${index + 1}`} value={line.evidence} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { evidence: e.target.value })} placeholder="Табель / расчёт" />
    </div>)}
    <div className="flex flex-wrap gap-2"><Button disabled={disabled || busy || !!result} onClick={() => setLines(current => [...current, emptyLine(`line-${current.length + 1}`)])}>Добавить строку</Button>
      <Button disabled={disabled || busy || !!result || !policyId} onClick={() => void load()}>Проверить импорт труда</Button>{result && <Button disabled={disabled || busy} onClick={reset}>Новый импорт</Button>}</div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {result && <article className="space-y-2 rounded border border-accent p-3"><p><strong>Статус:</strong> {result.status}</p><p>Источник подтверждён, пакет содержит равные дебет и кредит. Проводка ещё не создана.</p><p>Финальная себестоимость периода ещё не сертифицирована.</p>
      <p>Итого: {prepared?.amount_byn} BYN · digest пакета {result.digest.slice(0, 12)}…</p></article>}
    <AccountingProductionLaborConfirmation org={org} month={month} disabled={disabled || busy} prepared={prepared} onEntry={onEntry} onLock={onLock}
      onConfirmed={() => { setPrepared(null); setResult(null); setRequestId(requestKey()); }} />
  </section>;
}
