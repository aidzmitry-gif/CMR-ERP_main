import { useLayoutEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  pendingPayrollStatutory,
  payrollStatutoryAccess,
  resolvePayrollStatutory,
  type PayrollStatutoryDraft,
  type PayrollStatutoryLine,
  type PayrollStatutoryReceipt,
  type PendingPayrollStatutory,
} from "@/lib/payroll-statutory-journal";

type Props = { org: string; month: string; policyId: string; disabled: boolean; onEntry?: (id: number) => void; onLock?: (busy: boolean) => void };
type LineDraft = PayrollStatutoryLine & { dimensions_json: string };
type Result = {
  organization_id: number;
  month: string;
  policy_id: number;
  source_digest: string;
  digest: string;
  status: string;
  posting_available: true;
  posted: false;
  statutory_payroll_certified: false;
  deductions_and_contributions_available: true;
  posting_document: { lines: Array<{ account: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string> }> };
};

const money = /^\d+\.\d{2}$/;
const digest = /^[a-f0-9]{64}$/;
const emptyLine = (id: string): LineDraft => ({ source_line_id: id, employee: "", department: "", kind: "employee_deduction", liability_account: "68.1", cost_account: null, amount_byn: "", dimensions: {}, dimensions_json: "{}", evidence: "" });
const requestKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
  ? crypto.randomUUID() : `00000000-0000-4000-8000-${Date.now().toString(16).padStart(12, "0").slice(-12)}`;
const cents = (value: string) => BigInt(value.replace(".", ""));

export function AccountingPayrollStatutoryImport({ org, month, policyId, disabled, onEntry, onLock }: Props) {
  const [sourceDocument, setSourceDocument] = useState(`payroll:${month}:statutory-1`);
  const [sourceDigest, setSourceDigest] = useState("");
  const [verifiedBy, setVerifiedBy] = useState("");
  const [sourceEvidence, setSourceEvidence] = useState("");
  const [payrollAccount, setPayrollAccount] = useState("70");
  const [postingDate, setPostingDate] = useState(`${month}-01`);
  const [lines, setLines] = useState<LineDraft[]>([emptyLine("line-1")]);
  const [requestId, setRequestId] = useState(requestKey);
  const [result, setResult] = useState<Result | null>(null);
  const [prepared, setPrepared] = useState<{ draft: PayrollStatutoryDraft; digest: string } | null>(null);
  const [pending, setPending] = useState<PendingPayrollStatutory | null>(null);
  const [receipt, setReceipt] = useState<PayrollStatutoryReceipt | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState(false);

  useLayoutEffect(() => () => onLock?.(false), [onLock]);

  function updateLine(index: number, patch: Partial<LineDraft>) {
    setLines(current => current.map((line, i) => i === index ? { ...line, ...patch } : line));
  }

  function parseLineDimensions(line: LineDraft): Record<string, string> | null {
    try {
      const value = JSON.parse(line.dimensions_json || "{}");
      if (!value || typeof value !== "object" || Array.isArray(value)) return null;
      const dimensions = value as Record<string, unknown>;
      if (Object.values(dimensions).some(item => typeof item !== "string")) return null;
      return Object.fromEntries(Object.entries(dimensions).map(([key, item]) => [key, (item as string).trim()]));
    } catch { return null; }
  }

  function draft(): PayrollStatutoryDraft {
    return {
      request_key: requestId,
      source_document: sourceDocument.trim(),
      source_version: 1,
      source_digest: sourceDigest.trim(),
      verified_by: verifiedBy.trim(),
      source_evidence: sourceEvidence.trim(),
      policy_id: Number(policyId),
      posting_date: postingDate,
      payroll_account: payrollAccount.trim(),
      lines: lines.map(line => ({
        source_line_id: line.source_line_id.trim(), employee: line.employee.trim(), department: line.department.trim(),
        kind: line.kind, liability_account: line.liability_account.trim(), cost_account: line.cost_account?.trim() || null,
        amount_byn: line.amount_byn.trim(), evidence: line.evidence.trim(), dimensions: line.dimensions,
      })),
    };
  }

  async function preview() {
    if (busy || disabled) return;
    const parsed = lines.map(parseLineDimensions);
    const command = draft();
    if (!policyId || !command.source_document || !digest.test(command.source_digest) || !command.verified_by
      || command.source_evidence.length < 10 || !command.posting_date.startsWith(`${month}-`) || !command.payroll_account
      || lines.some((line, index) => !parsed[index] || !line.source_line_id.trim() || !line.employee.trim() || !line.department.trim()
        || !line.liability_account.trim() || !money.test(line.amount_byn) || line.amount_byn === "0.00"
        || (line.kind === "employer_contribution" && !line.cost_account?.trim())
        || (line.kind === "employee_deduction" && line.cost_account !== null && !!line.cost_account.trim())
        || line.evidence.trim().length < 10)
      || new Set(lines.map(line => line.source_line_id.trim())).size !== lines.length) {
      setError("Заполните источник и проверку: SHA-256, ответственного, основание и строки удержаний/взносов."); setResult(null); return;
    }
    command.lines = command.lines.map((line, index) => ({ ...line, dimensions: parsed[index]! }));
    setBusy(true); setError(""); setNotice(""); setResult(null); setPrepared(null); setReceipt(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/payroll-statutory-import-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(command),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось проверить импорт удержаний.");
      const posted = data.posting_document?.lines as Array<{ side?: string; amount?: string }> | undefined;
      const debit = posted?.filter(line => line.side === "debit") ?? [];
      const credit = posted?.filter(line => line.side === "credit") ?? [];
      const debitTotal = debit.reduce((sum, line) => sum + (typeof line.amount === "string" && money.test(line.amount) ? cents(line.amount) : 0n), 0n);
      const creditTotal = credit.reduce((sum, line) => sum + (typeof line.amount === "string" && money.test(line.amount) ? cents(line.amount) : 0n), 0n);
      if (String(data.organization_id) !== org || data.month !== month || String(data.policy_id) !== policyId
        || data.status !== "reviewed_verified_payroll_statutory" || data.posting_available !== true || data.posted !== false
        || data.statutory_payroll_certified !== false || data.deductions_and_contributions_available !== true
        || data.source_digest !== command.source_digest || !digest.test(data.digest) || !debit.length || debit.length !== credit.length
        || debit.some(line => typeof line.amount !== "string" || !money.test(line.amount))
        || credit.some(line => typeof line.amount !== "string" || !money.test(line.amount)) || debitTotal !== creditTotal)
        throw new Error("Пакет не соответствует выбранному юрлицу, периоду или сбалансированной проводке.");
      setResult(data as Result);
      setPrepared({ draft: command, digest: data.digest });
    } catch (e) { setError(e instanceof Error ? e.message : "Импорт удержаний не подготовлен."); }
    finally { setBusy(false); }
  }

  async function resolve(action: "check" | "confirm") {
    if (disabled || working || (action === "confirm" && !prepared)) return;
    setWorking(true); onLock?.(true); setError(""); setNotice("");
    try {
      const access = await payrollStatutoryAccess(org);
      const item = action === "confirm"
        ? { org, principal: access.principal, month, command: { ...prepared!.draft, digest: prepared!.digest } }
        : pendingPayrollStatutory(localStorage, org, access.principal, month);
      setPending(item);
      if (!item) { setNotice("Сохранённого импорта удержаний для текущего пользователя и месяца нет."); return; }
      const outcome = await resolvePayrollStatutory(localStorage, item, action === "confirm");
      if (outcome) { setPending(null); setReceipt(outcome); setPrepared(null); setResult(null); onEntry?.(outcome.entry_id); }
      else { setPending(item); setNotice("Квитанция пока не найдена. Запрос сохранён; повторите проверку."); }
    } catch (e) { setError(e instanceof Error ? e.message : "Импорт удержаний не подтверждён."); }
    finally { setWorking(false); onLock?.(false); }
  }

  function reset() {
    setResult(null); setPrepared(null); setPending(null); setReceipt(null); setError(""); setNotice(""); setRequestId(requestKey());
  }

  return <section className="space-y-3 rounded-lg border border-line p-3" aria-label="Проверенные удержания и взносы">
    <h3 className="font-semibold">Проверенный импорт удержаний и взносов</h3>
    <p className="text-sm text-muted">Суммы приходят из проверенной внешней ведомости. Ставки и расчёт от оклада не угадываются; импорт не является нормативной сертификацией.</p>
    <div className="grid gap-3 md:grid-cols-3">
      <Input aria-label="Документ удержаний" value={sourceDocument} disabled={disabled || busy || !!result} onChange={e => setSourceDocument(e.target.value)} />
      <Input aria-label="Digest удержаний" value={sourceDigest} disabled={disabled || busy || !!result} onChange={e => setSourceDigest(e.target.value)} placeholder="SHA-256 источника" />
      <Input aria-label="Проверил удержания" value={verifiedBy} disabled={disabled || busy || !!result} onChange={e => setVerifiedBy(e.target.value)} placeholder="Ответственный бухгалтер" />
      <Input aria-label="Счёт задолженности по зарплате удержаний" value={payrollAccount} disabled={disabled || busy || !!result} onChange={e => setPayrollAccount(e.target.value)} placeholder="Счёт 70" />
      <Input aria-label="Дата удержаний" type="date" value={postingDate} disabled={disabled || busy || !!result} onChange={e => setPostingDate(e.target.value)} />
      <Input aria-label="Основание удержаний" value={sourceEvidence} disabled={disabled || busy || !!result} onChange={e => setSourceEvidence(e.target.value)} placeholder="Ведомость и расчёт" />
    </div>
    {lines.map((line, index) => <div className="grid gap-2 rounded border border-line p-2 md:grid-cols-4" key={`${line.source_line_id}:${index}`}>
      <Input aria-label={`Строка удержаний ${index + 1}`} value={line.source_line_id} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { source_line_id: e.target.value })} placeholder="ID строки" />
      <Input aria-label={`Сотрудник удержаний ${index + 1}`} value={line.employee} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { employee: e.target.value })} placeholder="Сотрудник" />
      <Input aria-label={`Подразделение удержаний ${index + 1}`} value={line.department} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { department: e.target.value })} placeholder="Подразделение" />
      <select aria-label={`Тип строки удержаний ${index + 1}`} value={line.kind} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { kind: e.target.value as LineDraft["kind"], cost_account: e.target.value === "employer_contribution" ? line.cost_account : null })}>
        <option value="employee_deduction">Удержание сотрудника</option><option value="employer_contribution">Взнос работодателя</option>
      </select>
      <Input aria-label={`Счёт обязательства удержаний ${index + 1}`} value={line.liability_account} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { liability_account: e.target.value })} placeholder="Счёт обязательства" />
      <Input aria-label={`Счёт затрат взноса ${index + 1}`} value={line.cost_account || ""} disabled={disabled || busy || !!result || line.kind === "employee_deduction"} onChange={e => updateLine(index, { cost_account: e.target.value || null })} placeholder="Счёт затрат / НЗП" />
      <Input aria-label={`Сумма удержаний ${index + 1}`} value={line.amount_byn} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { amount_byn: e.target.value })} placeholder="BYN" />
      <Input aria-label={`Дополнительная аналитика удержаний ${index + 1}`} value={line.dimensions_json} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { dimensions_json: e.target.value })} placeholder='JSON: {"contract":"STAFF"}' />
      <Input aria-label={`Основание строки удержаний ${index + 1}`} value={line.evidence} disabled={disabled || busy || !!result} onChange={e => updateLine(index, { evidence: e.target.value })} placeholder="Расчёт / ведомость" />
      <Button variant="ghost" disabled={disabled || busy || !!result || lines.length === 1} onClick={() => setLines(current => current.filter((_, i) => i !== index))}>Удалить строку</Button>
    </div>)}
    <div className="flex flex-wrap gap-2">
      <Button disabled={disabled || busy || !!result || lines.length >= 20} onClick={() => setLines(current => [...current, emptyLine(`line-${current.length + 1}`)])}>Добавить строку</Button>
      <Button disabled={disabled || busy || !!result || !policyId} onClick={() => void preview()}>Проверить импорт удержаний</Button>
      {result && <Button disabled={disabled || busy || working} onClick={reset}>Новый импорт</Button>}
    </div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {result && <div className="space-y-2 rounded border border-accent p-3"><p className="font-semibold">Пакет проверен, но ещё не проведён</p>{result.posting_document.lines.map((line, index) => <p key={index}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} — {line.amount} BYN</p>)}<Button disabled={disabled || working} onClick={() => void resolve("confirm")}>Подтвердить и провести</Button></div>}
    {receipt && <div className="rounded border border-green-300 p-3" role="status"><p className="font-semibold">Импорт проведён, операция № {receipt.entry_id}</p><p className="text-sm text-muted">Квитанция сохранена; нормативная сертификация и отчётность остаются отдельным этапом.</p></div>}
    <div className="rounded border border-line p-3"><p className="font-semibold">Восстановление незавершённого запроса</p><p className="text-sm text-muted">Сохранённый пакет привязан к юрлицу, месяцу и пользователю; он удаляется только после подтверждённой квитанции.</p><Button variant="secondary" disabled={disabled || working} onClick={() => void resolve("check")}>Проверить сохранённый импорт</Button>{pending && <p className="mt-2 text-sm">Запрос сохранён: {pending.command.source_document}</p>}</div>
  </section>;
}
