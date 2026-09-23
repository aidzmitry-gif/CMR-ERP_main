"use client";

import { Printer } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

// ──────────────────────────── Типы ────────────────────────────

interface Employee {
  id: number;
  full_name: string;
  position: string;
}

interface PayrollEntry {
  id: number;
  employee_id: number;
  period: string;
  amount_byn: string;
  status: string;
}

interface PayrollPeriodSummary {
  period: string;
  total_byn: string;
  count: number;
  pending_count: number;
}

interface PayrollPreviewInputs {
  target_net_byn: string;
  advance_byn: string;
  tax_deduction_byn: string;
  other_withholding_byn: string;
  income_tax_rate_pct: string;
  employee_fszn_rate_pct: string;
  employer_fszn_rate_pct: string;
  belgos_rate_pct: string;
}

interface PayrollPreview {
  status: "draft";
  currency: "BYN";
  inputs: Omit<PayrollPreviewInputs, "belgos_rate_pct"> & { belgos_rate_pct: string | null };
  gross_byn: string;
  taxable_base_byn: string;
  income_tax_byn: string;
  employee_fszn_byn: string;
  employer_fszn_byn: string;
  belgos_byn: string | null;
  net_byn: string;
  payout_byn: string;
  warnings: string[];
  assumptions: string[];
}

type PolicyRole = "seller" | "assemblerSenior" | "assembler" | "salary";
type PolicyMoneyField = "monthly_norm_hours" | "worked_hours" | "norm_hours" |
  "contractual_salary_byn" | "shipment_revenue_byn" | "shipment_cost_byn" |
  "return_revenue_byn" | "return_cost_byn" | "confirmed_penalties_byn" |
  "opening_carry_byn" | "advance_byn" | "tax_deduction_byn" |
  "other_withholding_byn" | "income_tax_rate_pct" | "employee_fszn_rate_pct" |
  "employer_fszn_rate_pct" | "belgos_rate_pct" | "target_net_byn";

interface PolicyDraft {
  key: number;
  employee_id: number;
  employee_name: string;
  role: PolicyRole;
  period: string;
  worked_days: string;
  source_ref: string;
  mode: "policy" | "manual";
  manual_reason: string;
  manual_document_ref: string;
  values: Record<PolicyMoneyField, string>;
}

interface PolicyRow {
  employee_id: number;
  employee_name: string;
  role: PolicyRole;
  period: string;
  status: "ready" | "unknown";
  error: string | null;
  source_ref: string;
  worked_days: number | null;
  monthly_norm_hours: string | null;
  worked_hours: string | null;
  norm_hours: string | null;
  base_byn: string | null;
  salary_byn: string | null;
  bonus_byn: string | null;
  gross_byn: string | null;
  taxable_base_byn: string | null;
  tax_deduction_byn: string | null;
  income_tax_byn: string | null;
  employee_fszn_byn: string | null;
  other_withholding_byn: string | null;
  employer_fszn_byn: string | null;
  belgos_byn: string | null;
  net_byn: string | null;
  advance_byn: string | null;
  payout_byn: string | null;
  manual: boolean;
  manual_reason: string | null;
  manual_document_ref: string | null;
  policy_net_byn: string | null;
  seller_gross_profit_byn: string | null;
  seller_opening_carry_byn: string | null;
  seller_closing_carry_byn: string | null;
}

interface PolicyResult {
  status: "draft";
  currency: "BYN";
  can_manual_adjust: boolean;
  rows: PolicyRow[];
  warnings: string[];
}

const POLICY_MONEY_FIELDS: Array<[PolicyMoneyField, string]> = [
  ["monthly_norm_hours", "Норма часов месяца"],
  ["worked_hours", "Часы по табелю"],
  ["norm_hours", "Выполненные нормо-часы"],
  ["contractual_salary_byn", "Договорной оклад, BYN"],
  ["shipment_revenue_byn", "Отгрузка без НДС, BYN"],
  ["shipment_cost_byn", "Себестоимость отгрузки, BYN"],
  ["return_revenue_byn", "Возвраты без НДС, BYN"],
  ["return_cost_byn", "Себестоимость возвратов, BYN"],
  ["confirmed_penalties_byn", "Подтверждённые штрафы, BYN"],
  ["opening_carry_byn", "Входящий перенос первого месяца, BYN"],
  ["advance_byn", "Аванс, BYN"],
  ["tax_deduction_byn", "Налоговый вычет, BYN"],
  ["other_withholding_byn", "Прочие удержания, BYN"],
  ["income_tax_rate_pct", "Подоходный, %"],
  ["employee_fszn_rate_pct", "ФСЗН работника, %"],
  ["employer_fszn_rate_pct", "ФСЗН нанимателя, %"],
  ["belgos_rate_pct", "Белгосстрах, %"],
  ["target_net_byn", "Ручная сумма на руки до аванса, BYN"],
];

const POLICY_ROLES: Record<PolicyRole, string> = {
  seller: "Продавец", assemblerSenior: "Старший сборщик",
  assembler: "Сборщик", salary: "Оклад",
};

function newPolicyDraft(employee: Employee, role: PolicyRole, period: string, key: number): PolicyDraft {
  return {
    key, employee_id: employee.id, employee_name: employee.full_name, role, period,
    worked_days: "", source_ref: "", mode: "policy", manual_reason: "", manual_document_ref: "",
    values: Object.fromEntries(POLICY_MONEY_FIELDS.map(([field]) => [field, ""]).concat([
      ["income_tax_rate_pct", "13"], ["employee_fszn_rate_pct", "1"],
      ["employer_fszn_rate_pct", "34"], ["belgos_rate_pct", "0.52"],
    ])) as Record<PolicyMoneyField, string>,
  };
}

function sumPolicy(rows: PolicyRow[], field: keyof PolicyRow): string | null {
  if (rows.length === 0 || rows.some((row) => row.status !== "ready" || row[field] === null)) return null;
  const cents = rows.reduce((sum, row) => {
    const [whole, fraction = ""] = String(row[field]).split(".");
    return sum + BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  }, 0n);
  return `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
}

const policyAmount = (value: string | null | undefined) => value === null || value === undefined
  ? "Не рассчитано"
  : Number(value).toLocaleString("ru-BY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function CompactPayrollSlip({ row }: { row: PolicyRow }) {
  const amounts: Array<[string, string | null]> = [
    ["Оклад за отработанное время", row.salary_byn],
    ["Премия", row.bonus_byn],
    ["Начислено", row.gross_byn],
    ["Подоходный налог", row.income_tax_byn],
    ["ФСЗН работника", row.employee_fszn_byn],
    ["Прочие удержания", row.other_withholding_byn],
    ["На руки за месяц", row.net_byn],
    ["Аванс", row.advance_byn],
    ["К выплате", row.payout_byn],
  ];
  return <article className="payroll-handout-slip" aria-label={`Расчётный листок ${row.employee_name} ${row.period}`}>
    <div className="payroll-handout-head">
      <div><strong>Расчётный листок</strong><span>Черновик · {row.period} · BYN</span></div>
      <div className="payroll-handout-name">{row.employee_name}<span>{POLICY_ROLES[row.role]} · № {row.employee_id}</span></div>
    </div>
    <p className="payroll-handout-time">Отработано: {row.worked_days} дн. / {row.worked_hours} ч. · Норма месяца: {row.monthly_norm_hours} ч.</p>
    <table className="payroll-handout-amounts"><tbody>{amounts.map(([label, value]) => <tr key={label} className={label === "Начислено" || label === "На руки за месяц" || label === "К выплате" ? "payroll-handout-total" : ""}>
      <th>{label}</th><td>{policyAmount(value)}</td>
    </tr>)}</tbody></table>
    <p className="payroll-handout-note">На руки — сумма после удержаний до аванса. К выплате — после вычета аванса.</p>
    {row.manual && <p className="payroll-handout-note">Ручная сумма директора: {row.manual_reason}; документ {row.manual_document_ref}.</p>}
    <p className="payroll-handout-draft">Черновик для проверки. Не является подтверждённым начислением или платёжным документом.</p>
  </article>;
}

type StatusFilter = "all" | "pending" | "paid";
type ViewMode = "summary" | "detail";

const EMPTY_PREVIEW_INPUTS: PayrollPreviewInputs = {
  target_net_byn: "",
  advance_byn: "",
  tax_deduction_byn: "",
  other_withholding_byn: "",
  income_tax_rate_pct: "",
  employee_fszn_rate_pct: "",
  employer_fszn_rate_pct: "",
  belgos_rate_pct: "",
};

function previewErrorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((item) => {
        if (!item || typeof item !== "object") return [];
        const issue = item as { loc?: unknown; msg?: unknown };
        if (typeof issue.msg !== "string") return [];
        const loc = Array.isArray(issue.loc) ? issue.loc[issue.loc.length - 1] : null;
        return [typeof loc === "string" ? `${loc}: ${issue.msg}` : issue.msg];
      });
      if (messages.length > 0) return messages.join("; ");
    }
  }
  return status === 422 ? "Проверьте формат и значения условий сценария." : `Ошибка расчёта (${status})`;
}

// ──────────────────────────── Вспомогательные компоненты ────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    paid: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  };
  const labels: Record<string, string> = { pending: "ожидает", paid: "выплачено" };
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${styles[status] ?? "bg-sunken text-muted"}`}>
      {labels[status] ?? status}
    </span>
  );
}

function PayrollPreviewBreakdown({
  preview,
  formatByn,
}: {
  preview: PayrollPreview;
  formatByn: (value: string) => string;
}) {
  const amounts: Array<[string, string | null]> = [
    ["Начислено, BYN", preview.gross_byn],
    ["База подоходного налога, BYN", preview.taxable_base_byn],
    ["Подоходный налог, BYN", preview.income_tax_byn],
    ["ФСЗН работника, BYN", preview.employee_fszn_byn],
    ["ФСЗН нанимателя, BYN", preview.employer_fszn_byn],
    ["Белгосстрах, BYN", preview.belgos_byn],
    ["На руки за месяц, BYN", preview.net_byn],
    ["Остаток к выплате после аванса, BYN", preview.payout_byn],
  ];

  return (
    <>
      <table className="mt-2 w-full max-w-2xl text-sm">
        <tbody>
          {amounts.map(([label, value]) => (
            <tr key={label} className="border-b border-line last:border-0 print:break-inside-avoid">
              <th scope="row" className="py-1.5 pr-4 text-left text-xs font-medium text-muted">{label}</th>
              <td className="py-1.5 text-right tabular-nums font-medium text-ink">
                {value === null ? "Неизвестно" : formatByn(value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 grid gap-3 lg:grid-cols-2 print:break-inside-avoid">
        <div>
          <h3 className="text-xs font-semibold text-ink">Предупреждения</h3>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted">
            {preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        </div>
        <div>
          <h3 className="text-xs font-semibold text-ink">Допущения сценария</h3>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-muted">
            {preview.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}
          </ul>
        </div>
      </div>
    </>
  );
}

function PayrollPreviewScenario({
  inputs,
  formatByn,
}: {
  inputs: PayrollPreview["inputs"];
  formatByn: (value: string) => string;
}) {
  const formatRate = (value: string | null) => (
    value === null
      ? "Не задано / неизвестно"
      : `${Number(value).toLocaleString("ru-BY", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %`
  );
  const monetaryInputs: Array<[string, string]> = [
    ["Целевая сумма на руки до аванса, BYN", inputs.target_net_byn],
    ["Аванс, BYN", inputs.advance_byn],
    ["Налоговый вычет, BYN", inputs.tax_deduction_byn],
    ["Прочие удержания, BYN", inputs.other_withholding_byn],
  ];
  const rates: Array<[string, string | null]> = [
    ["Подоходный налог, %", inputs.income_tax_rate_pct],
    ["ФСЗН работника, %", inputs.employee_fszn_rate_pct],
    ["ФСЗН нанимателя, %", inputs.employer_fszn_rate_pct],
    ["Белгосстрах, %", inputs.belgos_rate_pct],
  ];

  return (
    <section className="mt-4 print:break-inside-avoid" aria-label="Условия сценария расчёта">
      <h2 className="text-sm font-semibold text-ink">Условия сценария</h2>
      <table className="mt-2 w-full max-w-2xl text-sm">
        <tbody>
          {monetaryInputs.map(([label, value]) => (
            <tr key={label} className="border-b border-line last:border-0">
              <th scope="row" className="py-1.5 pr-4 text-left text-xs font-medium text-muted">{label}</th>
              <td className="py-1.5 text-right tabular-nums font-medium text-ink">{formatByn(value)}</td>
            </tr>
          ))}
          {rates.map(([label, value]) => (
            <tr key={label} className="border-b border-line last:border-0">
              <th scope="row" className="py-1.5 pr-4 text-left text-xs font-medium text-muted">{label}</th>
              <td className="py-1.5 text-right tabular-nums font-medium text-ink">{formatRate(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PayrollPolicyPanel({ employees, onPrint, legacyPreviewOpen }: {
  employees: Employee[]; onPrint: () => void; legacyPreviewOpen: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [drafts, setDrafts] = useState<PolicyDraft[]>([]);
  const [employeeId, setEmployeeId] = useState("");
  const [role, setRole] = useState<PolicyRole>("salary");
  const [period, setPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const [result, setResult] = useState<PolicyResult | null>(null);
  const [canManual, setCanManual] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [printMode, setPrintMode] = useState<"sheet" | "slip" | "slips" | null>(null);
  const [printEmployeeId, setPrintEmployeeId] = useState<number | null>(null);
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const requestId = useRef(0);
  const nextKey = useRef(1);

  useEffect(() => {
    let active = true;
    fetch("/api/system/access", { cache: "no-store" })
      .then((response) => response.ok ? response.json() as Promise<{ current_roles?: string[] }> : null)
      .then((access) => { if (active) setCanManual(access?.current_roles?.includes("director") === true); })
      .catch(() => { if (active) setCanManual(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!legacyPreviewOpen) return;
    const timer = window.setTimeout(() => setPrintMode(null), 0);
    return () => window.clearTimeout(timer);
  }, [legacyPreviewOpen]);

  const invalidate = () => {
    requestId.current += 1;
    setResult(null);
    setPrintMode(null);
    setError(null);
    setLoading(false);
  };

  const update = (key: number, change: Partial<PolicyDraft>) => {
    invalidate();
    setDrafts((current) => current.map((row) => row.key === key ? { ...row, ...change } : row));
  };

  const updateValue = (key: number, field: PolicyMoneyField, value: string) => {
    invalidate();
    setDrafts((current) => current.map((row) => row.key === key
      ? { ...row, values: { ...row.values, [field]: value } } : row));
  };

  const addRow = () => {
    const employee = employees.find((item) => String(item.id) === employeeId);
    if (!employee || !period) { setError("Выберите сотрудника и месяц."); return; }
    if (drafts.some((item) => item.employee_id === employee.id && item.period === period)) {
      setError("Строка сотрудника за этот месяц уже добавлена."); return;
    }
    if (drafts.some((item) => item.employee_id === employee.id && item.role !== role)) {
      setError("Для одного сотрудника в черновике должна быть одна категория оплаты."); return;
    }
    invalidate();
    setDrafts((current) => [...current, newPolicyDraft(employee, role, period, nextKey.current++)]);
    setSelectedPeriod(period);
  };

  const calculate = async () => {
    if (drafts.length === 0) { setError("Добавьте хотя бы одну строку ведомости."); return; }
    if (drafts.some((row) => ["advance_byn", "tax_deduction_byn", "other_withholding_byn"]
      .some((field) => row.values[field as PolicyMoneyField].trim() === ""))) {
      setError("Аванс, вычет и прочие удержания укажите явно, включая подтверждённый 0."); return;
    }
    if (drafts.some((row) => row.role === "salary" && drafts.some((other) =>
      other.employee_id === row.employee_id && other.values.contractual_salary_byn !== row.values.contractual_salary_byn))) {
      setError("Для сотрудника с окладом в одном черновике укажите одинаковый договорной оклад во всех месяцах."); return;
    }
    const byEmployee = new Map<number, { employee_id: number; employee_name: string; role: PolicyRole; contractual_salary_byn: string | null; months: Record<string, unknown>[] }>();
    for (const row of [...drafts].sort((a, b) => a.period.localeCompare(b.period))) {
      const employee = byEmployee.get(row.employee_id) ?? {
        employee_id: row.employee_id, employee_name: row.employee_name, role: row.role,
        contractual_salary_byn: row.values.contractual_salary_byn || null, months: [],
      };
      const values = row.values;
      employee.months.push({
        period: row.period, worked_days: row.worked_days === "" ? null : Number(row.worked_days),
        source_ref: row.source_ref, mode: row.mode,
        manual_reason: row.manual_reason, manual_document_ref: row.manual_document_ref,
        ...Object.fromEntries(POLICY_MONEY_FIELDS.filter(([field]) => field !== "contractual_salary_byn")
          .map(([field]) => [field, values[field].trim() || null])),
        advance_byn: values.advance_byn, tax_deduction_byn: values.tax_deduction_byn,
        other_withholding_byn: values.other_withholding_byn,
        income_tax_rate_pct: values.income_tax_rate_pct,
        employee_fszn_rate_pct: values.employee_fszn_rate_pct,
        employer_fszn_rate_pct: values.employer_fszn_rate_pct,
        belgos_rate_pct: values.belgos_rate_pct || null,
      });
      byEmployee.set(row.employee_id, employee);
    }
    const currentId = ++requestId.current;
    setLoading(true); setError(null); setResult(null);
    try {
      const response = await fetch("/api/hr/payroll/policy-preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ employees: [...byEmployee.values()] }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(previewErrorMessage(body, response.status));
      if (requestId.current === currentId) {
        setResult(body as PolicyResult);
        setCanManual((body as PolicyResult).can_manual_adjust);
      }
    } catch (caught) {
      if (requestId.current === currentId) {
        setError(caught instanceof Error ? caught.message : "Черновик не рассчитан");
      }
    } finally {
      if (requestId.current === currentId) setLoading(false);
    }
  };

  const periods = result ? [...new Set(result.rows.map((row) => row.period))].sort() : [];
  const displayPeriod = periods.includes(selectedPeriod) ? selectedPeriod : periods[0];
  const rows = result?.rows.filter((row) => row.period === displayPeriod) ?? [];
  const printable = rows.filter((row) => row.status === "ready");
  const printRow = printable.find((row) => row.employee_id === printEmployeeId);
  const complete = rows.length > 0 && printable.length === rows.length;
  const sheetColumns: Array<[string, keyof PolicyRow]> = [
    ["Сотрудник", "employee_name"], ["Дни", "worked_days"],
    ["Часы", "worked_hours"], ["Оклад", "salary_byn"],
    ["Премия", "bonus_byn"], ["Начислено", "gross_byn"],
    ["Подоходный", "income_tax_byn"], ["ФСЗН работника", "employee_fszn_byn"],
    ["Прочие удержания", "other_withholding_byn"],
    ["На руки", "net_byn"], ["Аванс", "advance_byn"], ["К выплате", "payout_byn"],
  ];
  const slipFields: Array<[string, keyof PolicyRow]> = [
    ["Дней отработано", "worked_days"], ["Часов по табелю", "worked_hours"],
    ["Месячная норма часов", "monthly_norm_hours"],
    ["Полный месячный оклад, BYN", "base_byn"],
    ["Оклад за время, BYN", "salary_byn"], ["Премия, BYN", "bonus_byn"],
    ["Начислено = оклад + премия, BYN", "gross_byn"],
    ["Подтверждённый налоговый вычет, BYN", "tax_deduction_byn"],
    ["База подоходного налога, BYN", "taxable_base_byn"],
    ["Подоходный налог, BYN", "income_tax_byn"],
    ["ФСЗН работника, BYN", "employee_fszn_byn"],
    ["Прочие удержания, BYN", "other_withholding_byn"],
    ["На руки = начислено − удержания, BYN", "net_byn"],
    ["Аванс, BYN", "advance_byn"], ["К выплате = на руки − аванс, BYN", "payout_byn"],
    ["ФСЗН нанимателя, BYN", "employer_fszn_byn"],
    ["Белгосстрах, BYN", "belgos_byn"],
  ];
  const startPrint = (mode: "sheet" | "slip" | "slips", id: number | null = null) => {
    onPrint();
    setPrintMode(mode); setPrintEmployeeId(id);
    window.setTimeout(() => window.print(), 0);
  };

  return (
    <section className="mt-4 rounded-xl border border-line bg-surface p-4 shadow-card" aria-label="Черновая месячная ведомость по правилам оплаты">
      <button type="button" onClick={() => setOpen(!open)} className="text-sm font-semibold text-ink">
        {open ? "Скрыть" : "Открыть"} черновую месячную ведомость
      </button>
      {open && <>
        <p className="mt-2 text-xs text-amber-800">Только предпросмотр: ни начисления, ни выплаты. ERP не подтверждает источник табеля и валовой прибыли — внесите документ и каждое значение вручную. Пустое поле остаётся неизвестным; ноль вводится явно.</p>
        <div className="mt-3 flex flex-wrap items-end gap-2 print:hidden">
          <label className="flex flex-col gap-1 text-xs">Сотрудник
            <select aria-label="Сотрудник черновика" value={employeeId} onChange={(event) => setEmployeeId(event.target.value)} className="rounded border border-line p-1">
              <option value="">— выбрать —</option>
              {employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.full_name}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">Категория
            <select aria-label="Категория оплаты" value={role} onChange={(event) => setRole(event.target.value as PolicyRole)} className="rounded border border-line p-1">
              {Object.entries(POLICY_ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">Месяц
            <input aria-label="Месяц черновика" type="month" value={period} onChange={(event) => setPeriod(event.target.value)} className="rounded border border-line p-1" />
          </label>
          <button type="button" onClick={addRow} className="rounded bg-sunken px-3 py-1.5 text-sm">Добавить строку</button>
        </div>
        {drafts.map((draft) => {
          const seller = draft.role === "seller";
          const assembler = draft.role === "assembler" || draft.role === "assemblerSenior";
          const fields = POLICY_MONEY_FIELDS.filter(([field]) => (
            field === "norm_hours" ? assembler :
            field === "contractual_salary_byn" ? draft.role === "salary" :
            ["shipment_revenue_byn", "shipment_cost_byn", "return_revenue_byn", "return_cost_byn", "confirmed_penalties_byn", "opening_carry_byn"].includes(field) ? seller :
            field === "target_net_byn" ? canManual && draft.mode === "manual" : true
          ));
          return <details key={draft.key} className="mt-3 rounded-lg border border-line p-3" open>
            <summary className="font-medium">{draft.employee_name} · {POLICY_ROLES[draft.role]} · {draft.period}</summary>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <label className="flex flex-col gap-1 text-xs">Отработано дней
                <input aria-label={`Отработано дней ${draft.employee_name} ${draft.period}`} type="number" min="0" max="31" step="1" value={draft.worked_days} onChange={(event) => update(draft.key, { worked_days: event.target.value })} className="rounded border border-line p-1" />
              </label>
              <label className="flex flex-col gap-1 text-xs">Документы-основания
                <input aria-label={`Документы-основания ${draft.employee_name} ${draft.period}`} value={draft.source_ref} onChange={(event) => update(draft.key, { source_ref: event.target.value })} className="rounded border border-line p-1" />
              </label>
              {fields.map(([field, label]) => <label key={field} className="flex flex-col gap-1 text-xs">{label}
                <input aria-label={`${label} ${draft.employee_name} ${draft.period}`} inputMode="decimal" value={draft.values[field]} onChange={(event) => updateValue(draft.key, field, event.target.value)} className="rounded border border-line p-1 tabular-nums" />
              </label>)}
              {canManual && <label className="flex flex-col gap-1 text-xs">Режим
                <select aria-label={`Режим ${draft.employee_name} ${draft.period}`} value={draft.mode} onChange={(event) => update(draft.key, { mode: event.target.value as "policy" | "manual" })} className="rounded border border-line p-1">
                  <option value="policy">По правилам</option><option value="manual">Ручная сумма директора</option>
                </select>
              </label>}
              {canManual && draft.mode === "manual" && <>
                <label className="flex flex-col gap-1 text-xs">Причина корректировки
                  <input aria-label={`Причина корректировки ${draft.employee_name} ${draft.period}`} value={draft.manual_reason} onChange={(event) => update(draft.key, { manual_reason: event.target.value })} className="rounded border border-line p-1" />
                </label>
                <label className="flex flex-col gap-1 text-xs">Документ корректировки
                  <input aria-label={`Документ корректировки ${draft.employee_name} ${draft.period}`} value={draft.manual_document_ref} onChange={(event) => update(draft.key, { manual_document_ref: event.target.value })} className="rounded border border-line p-1" />
                </label>
              </>}
            </div>
            <button type="button" onClick={() => { invalidate(); setDrafts((current) => current.filter((item) => item.key !== draft.key)); }} className="mt-2 text-xs text-rose-700">Удалить строку</button>
          </details>;
        })}
        <button type="button" disabled={loading} onClick={() => void calculate()} className="mt-3 rounded bg-emerald-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">{loading ? "Расчёт…" : "Рассчитать ведомость-черновик"}</button>
        {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
        {result && <>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <label className="text-sm">Расчётный месяц <select aria-label="Расчётный месяц ведомости" value={displayPeriod} onChange={(event) => setSelectedPeriod(event.target.value)} className="ml-2 rounded border border-line p-1">{periods.map((item) => <option key={item}>{item}</option>)}</select></label>
            {complete && <button type="button" onClick={() => startPrint("sheet")} className="rounded bg-sunken px-2 py-1 text-sm">Печать месячной ведомости</button>}
            {complete && <button type="button" onClick={() => startPrint("slips")} className="rounded bg-sunken px-2 py-1 text-sm">Листки для выдачи · 2 на A4</button>}
          </div>
          <p className="mt-2 text-sm">Готово {printable.length} из {rows.length}. {complete ? "Все строки рассчитаны." : "Итоги не рассчитаны, пока есть неизвестные строки."}</p>
          <div className="mt-2 max-w-full overflow-x-auto">
            <table className="min-w-[1000px] w-full text-xs" aria-label="Месячная ведомость черновик">
              <thead><tr className="border-b border-line">{sheetColumns.map(([label]) => <th key={label} className="p-1 text-left">{label}</th>)}<th className="p-1">Листок</th></tr></thead>
              <tbody>{rows.map((row) => <tr key={`${row.employee_id}-${row.period}`} className="border-b border-line">
                {sheetColumns.map(([label, field]) => <td key={label} className="p-1 tabular-nums">{field === "employee_name" ? row.employee_name : field === "worked_days" ? row.worked_days ?? "Неизвестно" : policyAmount(row[field] as string | null)}</td>)}
                <td>{row.status === "ready" && <button type="button" onClick={() => startPrint("slip", row.employee_id)} className="text-emerald-700">Печать листка</button>}</td>
              </tr>)}</tbody>
            </table>
          </div>
          {rows.filter((row) => row.status === "unknown").map((row) => <p key={row.employee_id} className="mt-1 text-xs text-rose-700">{row.employee_name}: {row.error}</p>)}
          {rows.filter((row) => row.role === "seller" && row.status === "ready").map((row) => <p key={row.employee_id} className="mt-1 text-xs text-muted">{row.employee_name}: личная прибыль {policyAmount(row.seller_gross_profit_byn)}, входящий перенос {policyAmount(row.seller_opening_carry_byn)}, перенос на следующий месяц {policyAmount(row.seller_closing_carry_byn)} BYN. Перенос не печатается.</p>)}
          {rows.filter((row) => row.manual).map((row) => <p key={row.employee_id} className="mt-1 text-xs text-amber-800">{row.employee_name}: ручная сумма директора по документу {row.manual_document_ref}; по правилам на руки {policyAmount(row.policy_net_byn)} BYN.</p>)}
          {rows.filter((row) => row.status === "ready").map((row) => <p key={`math-${row.employee_id}`} className="mt-1 text-xs text-muted">{row.employee_name}: оклад {policyAmount(row.base_byn)} × {row.worked_hours}/{row.monthly_norm_hours} ч = {policyAmount(row.salary_byn)} BYN; начислено {policyAmount(row.salary_byn)} + {policyAmount(row.bonus_byn)} = {policyAmount(row.gross_byn)}; база налога max(начислено − вычет {policyAmount(row.tax_deduction_byn)}, 0) = {policyAmount(row.taxable_base_byn)}; на руки = начислено − подоходный {policyAmount(row.income_tax_byn)} − ФСЗН работника {policyAmount(row.employee_fszn_byn)} − прочие удержания {policyAmount(row.other_withholding_byn)} = {policyAmount(row.net_byn)} BYN.</p>)}
          {complete && <p className="mt-2 text-sm">Итого начислено {policyAmount(sumPolicy(rows, "gross_byn"))} BYN; на руки {policyAmount(sumPolicy(rows, "net_byn"))} BYN; к выплате {policyAmount(sumPolicy(rows, "payout_byn"))} BYN.</p>}
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            <div className="rounded border border-line p-2 text-xs">4-фонд · подготовка: ФСЗН нанимателя {policyAmount(sumPolicy(rows, "employer_fszn_byn"))} BYN; ФСЗН работника {policyAmount(sumPolicy(rows, "employee_fszn_byn"))} BYN. Не официальный отчёт.</div>
            <div className="rounded border border-line p-2 text-xs">ПУ-3 · подготовка: {printable.length} из {rows.length} строк; начислено {policyAmount(sumPolicy(rows, "gross_byn"))} BYN. Не официальный отчёт.</div>
            <div className="rounded border border-line p-2 text-xs">Сведения о доходах · подготовка: подоходный {policyAmount(sumPolicy(rows, "income_tax_byn"))} BYN; на руки {policyAmount(sumPolicy(rows, "net_byn"))} BYN. Не официальный отчёт.</div>
          </div>
          <ul className="mt-2 list-disc pl-4 text-xs text-muted">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </>}
      </>}
      {result && printMode && !legacyPreviewOpen && typeof document !== "undefined" && createPortal(<>
        <style data-testid="payroll-policy-print-css">{`@media print {
          @page { size: A4 ${printMode === "sheet" ? "landscape" : "portrait"}; margin: 10mm; }
          html, body { overflow: visible !important; background: white !important; }
          body > *:not([data-payroll-policy-print]):not(style) { display: none !important; }
          [data-payroll-policy-print] { display: block !important; width: 100%; background: white !important; color: black !important; }
          [data-payroll-policy-print] * { color: black !important; border-color: black !important; }
          [data-payroll-policy-print][data-print-mode="slips"] { padding: 0 !important; }
          .payroll-handout-page { box-sizing: border-box; height: 276mm; display: grid; grid-template-rows: 1fr 1fr; break-inside: avoid; page-break-inside: avoid; }
          .payroll-handout-page:not(:last-child) { break-after: page; page-break-after: always; }
          .payroll-handout-slip { box-sizing: border-box; min-height: 0; padding: 5mm 4mm; font: 10pt/1.25 Arial, sans-serif; break-inside: avoid; page-break-inside: avoid; overflow-wrap: anywhere; }
          .payroll-handout-slip:nth-child(2), .payroll-handout-empty { border-top: 1px dashed #555 !important; }
          .payroll-handout-head { display: flex; justify-content: space-between; gap: 8mm; border-bottom: 1px solid #777 !important; padding-bottom: 2mm; }
          .payroll-handout-head strong { display: block; font-size: 13pt; }
          .payroll-handout-head span { display: block; font-size: 8pt; }
          .payroll-handout-name { text-align: right; font-weight: bold; }
          .payroll-handout-time { margin: 2mm 0; }
          .payroll-handout-amounts { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
          .payroll-handout-amounts th, .payroll-handout-amounts td { padding: .6mm 0; border-bottom: 1px solid #ddd !important; }
          .payroll-handout-amounts th { text-align: left; font-weight: normal; }
          .payroll-handout-amounts td { text-align: right; font-variant-numeric: tabular-nums; }
          .payroll-handout-total th, .payroll-handout-total td { font-weight: bold; border-top: 1px solid #777 !important; }
          .payroll-handout-note { margin: 2mm 0 0; font-size: 8pt; }
          .payroll-handout-draft { margin: 2mm 0 0; font-size: 7pt; }
        }`}</style>
        <section data-payroll-policy-print data-print-mode={printMode} role="document" aria-label={printMode === "sheet" ? "Печатная черновая месячная ведомость" : printMode === "slips" ? "Печатные расчётные листки для сотрудников" : "Печатный черновой расчётный листок"} className="hidden bg-white p-4 text-black print:block">
          {printMode === "slips" ? Array.from({ length: Math.ceil(printable.length / 2) }, (_, index) => <div className="payroll-handout-page" key={index}>
            {printable.slice(index * 2, index * 2 + 2).map((row) => <CompactPayrollSlip key={row.employee_id} row={row} />)}
            {index * 2 + 1 >= printable.length && <div className="payroll-handout-empty" aria-hidden="true" />}
          </div>) : <>
          <h2 className="text-lg font-bold">{printMode === "sheet" ? "Месячная ведомость" : "Расчётный листок"} · {displayPeriod}</h2>
          <p className="mb-3 text-xs">Черновик. Не является начислением, платёжным документом или официальным отчётом.</p>
          {printMode === "sheet" ? <table className="w-full table-fixed border-collapse text-[8px]">
            <thead><tr>{sheetColumns.map(([label]) => <th key={label} className="break-words border p-1 text-left">{label}</th>)}</tr></thead>
            <tbody>{rows.map((row) => <tr key={row.employee_id}>{sheetColumns.map(([label, field]) => <td key={label} className="break-words border p-1">{field === "employee_name" ? row.employee_name : field === "worked_days" ? row.worked_days ?? "Неизвестно" : policyAmount(row[field] as string | null)}</td>)}</tr>)}</tbody>
          </table> : printRow && <>
            <p className="mb-2 text-sm font-medium">{printRow.employee_name} · {POLICY_ROLES[printRow.role]}</p>
            <p className="mb-2 text-xs">Оклад за время: {policyAmount(printRow.base_byn)} × {printRow.worked_hours}/{printRow.monthly_norm_hours} ч = {policyAmount(printRow.salary_byn)} BYN. База налога = max(начислено − вычет, 0).</p>
            <table className="w-full max-w-[170mm] border-collapse text-xs"><tbody>{slipFields.map(([label, field]) => <tr key={label}><th className="border-b p-1 text-left font-normal">{label}</th><td className="border-b p-1 text-right">{field === "worked_days" ? printRow.worked_days : policyAmount(printRow[field] as string | null)}</td></tr>)}</tbody></table>
            {printRow.manual && <p className="mt-2 text-xs">Ручная сумма директора: {printRow.manual_reason}; документ {printRow.manual_document_ref}.</p>}
          </>}
          {printMode === "sheet" && rows.some((row) => row.manual) && <p className="mt-2 text-xs">Ручные исключения ({rows.filter((row) => row.manual).length}): {rows.filter((row) => row.manual).map((row) => `${row.employee_name}: ${row.manual_reason}; документ ${row.manual_document_ref}; по правилам ${policyAmount(row.policy_net_byn)} BYN, вручную ${policyAmount(row.net_byn)} BYN`).join("; ")}</p>}
          <p className="mt-4 text-xs">Документы-основания: {printMode === "slip" ? printRow?.source_ref : rows.map((row) => `${row.employee_name}: ${row.source_ref}`).join("; ")}</p>
          <p className="mt-3 text-xs">Подготовил __________ &nbsp;&nbsp; Проверил __________ &nbsp;&nbsp; Дата __________</p>
          </>}
        </section>
      </>, document.body)}
    </section>
  );
}

// ──────────────────────────── Главный вид ────────────────────────────

export function HrPayrollView() {
  // Detail mode state
  const [entries, setEntries] = useState<PayrollEntry[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // View mode
  const [viewMode, setViewMode] = useState<ViewMode>("summary");

  // Summary mode state
  const [summaries, setSummaries] = useState<PayrollPeriodSummary[]>([]);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [errorSummary, setErrorSummary] = useState(false);
  const [expandedPeriod, setExpandedPeriod] = useState<string | null>(null);
  const [periodEntries, setPeriodEntries] = useState<PayrollEntry[]>([]);
  const [loadingPeriod, setLoadingPeriod] = useState(false);

  // Форма начисления
  const [showForm, setShowForm] = useState(false);
  const [empId, setEmpId] = useState("");
  const [period, setPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const [amount, setAmount] = useState("");
  const [posting, setPosting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Черновой сценарий «на руки» не использует сотрудника, период или PayrollEntry.
  const [showPreviewForm, setShowPreviewForm] = useState(false);
  const [previewInputs, setPreviewInputs] = useState<PayrollPreviewInputs>(EMPTY_PREVIEW_INPUTS);
  const [preview, setPreview] = useState<PayrollPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewRequestId = useRef(0);

  const loadEntries = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const qs = statusFilter !== "all" ? `?status=${statusFilter}` : "";
      const r = await fetch(`/api/hr/payroll${qs}`, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      setEntries((await r.json()) as PayrollEntry[]);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const loadSummaries = useCallback(async () => {
    setLoadingSummary(true);
    setErrorSummary(false);
    try {
      const r = await fetch("/api/hr/payroll/summary", { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      setSummaries((await r.json()) as PayrollPeriodSummary[]);
    } catch {
      setErrorSummary(true);
    } finally {
      setLoadingSummary(false);
    }
  }, []);

  const togglePeriod = useCallback(
    async (p: string) => {
      if (expandedPeriod === p) {
        setExpandedPeriod(null);
        setPeriodEntries([]);
        return;
      }
      setExpandedPeriod(p);
      setLoadingPeriod(true);
      try {
        const r = await fetch(`/api/hr/payroll?period=${encodeURIComponent(p)}`, {
          cache: "no-store",
        });
        if (!r.ok) throw new Error(String(r.status));
        setPeriodEntries((await r.json()) as PayrollEntry[]);
      } catch {
        setPeriodEntries([]);
      } finally {
        setLoadingPeriod(false);
      }
    },
    [expandedPeriod],
  );

  useEffect(() => {
    loadEntries();
  }, [loadEntries]);

  useEffect(() => {
    loadSummaries();
  }, [loadSummaries]);

  useEffect(() => {
    fetch("/api/hr/employees", { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<Employee[]>) : Promise.reject()))
      .then(setEmployees)
      .catch(() => {});
  }, []);

  const empName = useCallback(
    (id: number) => employees.find((e) => e.id === id)?.full_name ?? `#${id}`,
    [employees],
  );

  const onAccrue = useCallback(async () => {
    if (!empId || !period || !amount) {
      setFormError("Заполните все поля");
      return;
    }
    setPosting(true);
    setFormError(null);
    try {
      const r = await fetch("/api/hr/payroll/accrue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ employee_id: Number(empId), period, amount_byn: amount }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? String(r.status));
      }
      setShowForm(false);
      setAmount("");
      await loadEntries();
      await loadSummaries();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Ошибка начисления");
    } finally {
      setPosting(false);
    }
  }, [empId, period, amount, loadEntries, loadSummaries]);

  const onPay = useCallback(
    async (entry: PayrollEntry) => {
      try {
        const r = await fetch("/api/hr/payroll/pay", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ employee_id: entry.employee_id, period: entry.period, entry_id: entry.id }),
        });
        if (!r.ok) throw new Error(String(r.status));
        await loadEntries();
        await loadSummaries();
        if (expandedPeriod === entry.period) {
          const r2 = await fetch(
            `/api/hr/payroll?period=${encodeURIComponent(entry.period)}`,
            { cache: "no-store" },
          );
          if (r2.ok) setPeriodEntries((await r2.json()) as PayrollEntry[]);
        }
      } catch {
        // молчаливый fallback — UI обновится при следующей загрузке
      }
    },
    [loadEntries, loadSummaries, expandedPeriod],
  );

  const updatePreviewInput = useCallback((field: keyof PayrollPreviewInputs, value: string) => {
    previewRequestId.current += 1;
    setPreviewInputs((current) => ({ ...current, [field]: value }));
    // Результат относится только к точному набору условий, с которым был рассчитан.
    setPreview(null);
    setPreviewError(null);
    setPreviewing(false);
  }, []);

  const onPreview = useCallback(async () => {
    const requiredFields: Array<Exclude<keyof PayrollPreviewInputs, "belgos_rate_pct">> = [
      "target_net_byn",
      "advance_byn",
      "tax_deduction_byn",
      "other_withholding_byn",
      "income_tax_rate_pct",
      "employee_fszn_rate_pct",
      "employer_fszn_rate_pct",
    ];
    if (requiredFields.some((field) => previewInputs[field].trim() === "")) {
      setPreviewError("Заполните все обязательные условия сценария. Нули не подставляются автоматически.");
      return;
    }

    const requestId = previewRequestId.current + 1;
    previewRequestId.current = requestId;
    setPreviewing(true);
    setPreviewError(null);
    setPreview(null);
    try {
      const payload = {
        ...previewInputs,
        // Пустой Белгосстрах — неизвестное условие, а не нулевая ставка.
        belgos_rate_pct: previewInputs.belgos_rate_pct.trim() === "" ? null : previewInputs.belgos_rate_pct,
      };
      const r = await fetch("/api/hr/payroll/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(previewErrorMessage(body, r.status));
      }
      const result = (await r.json()) as PayrollPreview;
      if (previewRequestId.current === requestId) setPreview(result);
    } catch (e) {
      if (previewRequestId.current === requestId) {
        setPreviewError(e instanceof Error ? e.message : "Не удалось рассчитать черновик");
      }
    } finally {
      if (previewRequestId.current === requestId) setPreviewing(false);
    }
  }, [previewInputs]);

  const fmtByn = (v: string) =>
    parseFloat(v).toLocaleString("ru-BY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <>
    <main className={`flex-1 overflow-auto p-6 pr-24 print:pr-6${preview ? " print:hidden" : ""}`}>
      {/* Заголовок + кнопка */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">Начисления зарплаты</h1>
          <p className="mt-1 text-sm text-muted">Ручной HR-реестр начислений (BYN). Банковский платёж, налоги и проводки подтверждайте отдельно в <Link href="/erp/accounting" className="text-blue-600 underline">Бухгалтерии</Link>.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => { setShowPreviewForm(true); setPreviewError(null); setShowForm(false); }}
            className="rounded-md bg-sunken px-4 py-2 text-sm font-medium text-ink hover:text-emerald-700"
          >
            Рассчитать от суммы «на руки»
          </button>
          <button
            type="button"
            onClick={() => {
              previewRequestId.current += 1;
              setPreviewing(false);
              setPreview(null);
              setPreviewError(null);
              setShowForm(true);
              setFormError(null);
              setShowPreviewForm(false);
            }}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
          >
            + Начислить
          </button>
        </div>
      </div>

      <PayrollPolicyPanel
        employees={employees}
        legacyPreviewOpen={preview !== null}
        onPrint={() => { previewRequestId.current += 1; setPreview(null); }}
      />

      {/* Вкладки режима */}
      <div className="mt-4 flex gap-2">
        {(["summary", "detail"] as ViewMode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setViewMode(m)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              viewMode === m ? "bg-ink text-surface" : "bg-sunken text-muted hover:text-ink"
            }`}
          >
            {m === "summary" ? "Ведомость" : "Детально"}
          </button>
        ))}
      </div>

      {/* Форма начисления */}
      {showForm && (
        <div className="mt-4 rounded-xl bg-surface p-4 shadow-card">
          <h2 className="mb-3 text-sm font-semibold text-ink">Новое начисление</h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted">
              Сотрудник
              <select
                value={empId}
                onChange={(e) => setEmpId(e.target.value)}
                className="min-w-[14rem] rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
              >
                <option value="">— выберите —</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.full_name} {e.position ? `· ${e.position}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Период (ГГГГ-ММ)
              <input
                type="month"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Сумма BYN
              <input
                type="number"
                step="0.01"
                min="0"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="1 500.00"
                className="w-36 rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <button
              type="button"
              disabled={posting}
              onClick={onAccrue}
              className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
            >
              {posting ? "…" : "Начислить"}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-md bg-sunken px-3 py-1.5 text-sm text-muted"
            >
              Отмена
            </button>
          </div>
          {formError && <p className="mt-2 text-xs text-rose-600">{formError}</p>}
        </div>
      )}

      {/* Изолированный от PayrollEntry черновой расчёт от месячной суммы «на руки». */}
      {showPreviewForm && (
        <section className="mt-4 rounded-xl bg-surface p-4 shadow-card" aria-label="Черновой расчёт от суммы на руки">
          <h2 className="text-sm font-semibold text-ink">Черновой расчёт от суммы «на руки»</h2>
          <p className="mt-1 text-xs text-muted">
            «На руки» — сумма за полный месяц до аванса. Расчёт не создаёт начисление, выплату или проводку.
          </p>
          <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-900/20 dark:text-amber-100">
            Все значения ниже — явные условия сценария. Налоговый вычет и прочие удержания обязательны: укажите
            0.00 только после подтверждения их отсутствия.
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <label className="flex flex-col gap-1 text-xs text-muted">
              На руки за месяц до аванса, BYN
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.target_net_byn}
                onChange={(e) => updatePreviewInput("target_net_byn", e.target.value)}
                placeholder="2000.00"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Аванс, BYN
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.advance_byn}
                onChange={(e) => updatePreviewInput("advance_byn", e.target.value)}
                placeholder="250.00"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Налоговый вычет, BYN
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.tax_deduction_byn}
                onChange={(e) => updatePreviewInput("tax_deduction_byn", e.target.value)}
                placeholder="0.00"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Прочие удержания, BYN
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.other_withholding_byn}
                onChange={(e) => updatePreviewInput("other_withholding_byn", e.target.value)}
                placeholder="0.00"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Подоходный налог, %
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.income_tax_rate_pct}
                onChange={(e) => updatePreviewInput("income_tax_rate_pct", e.target.value)}
                placeholder="13"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              ФСЗН работника, %
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.employee_fszn_rate_pct}
                onChange={(e) => updatePreviewInput("employee_fszn_rate_pct", e.target.value)}
                placeholder="1"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              ФСЗН нанимателя, %
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.employer_fszn_rate_pct}
                onChange={(e) => updatePreviewInput("employer_fszn_rate_pct", e.target.value)}
                placeholder="34"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Белгосстрах, % (необязательно)
              <input
                type="text"
                inputMode="decimal"
                value={previewInputs.belgos_rate_pct}
                onChange={(e) => updatePreviewInput("belgos_rate_pct", e.target.value)}
                placeholder="не задан"
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
          </div>
          {previewInputs.belgos_rate_pct.trim() === "" && (
            <p className="mt-2 text-xs text-amber-800 dark:text-amber-200">
              Белгосстрах не указан: его взнос останется неизвестным, а не нулевым.
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={previewing}
              onClick={onPreview}
              className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
            >
              {previewing ? "Расчёт…" : "Рассчитать черновик"}
            </button>
            <button
              type="button"
              onClick={() => {
                previewRequestId.current += 1;
                setPreviewing(false);
                setPreview(null);
                setShowPreviewForm(false);
                setPreviewError(null);
              }}
              className="rounded-md bg-sunken px-3 py-1.5 text-sm text-muted"
            >
              Закрыть
            </button>
          </div>
          {previewError && <p className="mt-2 text-xs text-rose-600">{previewError}</p>}

          {preview && (
            <>
              <div className="mt-3 print:hidden">
                <button
                  type="button"
                  onClick={() => window.print()}
                  className="inline-flex items-center gap-1.5 rounded-md bg-sunken px-3 py-1.5 text-sm font-medium text-ink hover:text-emerald-700"
                >
                  <Printer size={15} /> Печать черновика
                </button>
              </div>
              <section className="mt-4 rounded-lg border border-amber-200 p-3 dark:border-amber-700" aria-label="Результат чернового расчёта">
                <p className="text-sm font-medium text-ink">Черновик — не ведомость и не платёжный документ.</p>
                <PayrollPreviewBreakdown preview={preview} formatByn={fmtByn} />
              </section>
            </>
          )}
        </section>
      )}

      {/* ── Режим «Ведомость» ── */}
      {viewMode === "summary" && (
        <>
          {loadingSummary && <p className="mt-6 text-sm text-muted">Загрузка…</p>}
          {errorSummary && (
            <p className="mt-6 rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
              Не удалось загрузить ведомость — проверьте подключение к HR-модулю.
            </p>
          )}
          {!loadingSummary && !errorSummary && (
            <div className="mt-4 overflow-hidden rounded-xl bg-surface shadow-card">
              <table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Период</th>
                    <th className="px-4 py-2.5 font-medium">Сотрудников</th>
                    <th className="px-4 py-2.5 text-right font-medium">Итог, BYN</th>
                    <th className="px-4 py-2.5 font-medium">Ожидает</th>
                    <th className="px-4 py-2.5 font-medium">Выплачено</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {summaries.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-muted">
                        Ведомость пуста.
                      </td>
                    </tr>
                  ) : (
                    summaries.flatMap((s) => {
                      const mainRow = (
                        <tr
                          key={s.period}
                          className="cursor-pointer border-b border-line last:border-0 hover:bg-sunken"
                          onClick={() => togglePeriod(s.period)}
                        >
                          <td className="px-4 py-2.5 font-medium text-ink">{s.period}</td>
                          <td className="px-4 py-2.5 tabular-nums text-muted">{s.count}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums font-medium text-ink">
                            {fmtByn(s.total_byn)}
                          </td>
                          <td className="px-4 py-2.5">
                            {s.pending_count > 0 ? (
                              <span className="flex items-center gap-1 text-amber-700 dark:text-amber-300">
                                <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                                {s.pending_count}
                              </span>
                            ) : (
                              <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
                                <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                                0
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 tabular-nums text-muted">
                            {s.count - s.pending_count}
                          </td>
                          <td className="px-4 py-2.5 text-right text-xs text-muted">
                            {expandedPeriod === s.period ? "▲" : "▼"}
                          </td>
                        </tr>
                      );
                      if (expandedPeriod !== s.period) return [mainRow];
                      const detailRow = (
                        <tr key={`${s.period}-detail`} className="bg-sunken">
                          <td colSpan={6} className="px-6 py-3">
                            {loadingPeriod ? (
                              <p className="text-xs text-muted">Загрузка…</p>
                            ) : periodEntries.length === 0 ? (
                              <p className="text-xs text-muted">Нет данных.</p>
                            ) : (
                              <table className="w-full text-xs">
                                <thead className="text-left text-muted">
                                  <tr>
                                    <th className="py-1 pr-4 font-medium">Сотрудник</th>
                                    <th className="py-1 pr-4 text-right font-medium">Сумма, BYN</th>
                                    <th className="py-1 pr-4 font-medium">Статус</th>
                                    <th className="py-1" />
                                  </tr>
                                </thead>
                                <tbody>
                                  {periodEntries.map((e) => (
                                    <tr key={e.id} className="border-t border-line">
                                      <td className="py-1 pr-4 text-ink">{empName(e.employee_id)}</td>
                                      <td className="py-1 pr-4 text-right tabular-nums text-ink">
                                        {fmtByn(e.amount_byn)}
                                      </td>
                                      <td className="py-1 pr-4">
                                        <StatusBadge status={e.status} />
                                      </td>
                                      <td className="py-1 text-right">
                                        {e.status === "pending" && (
                                          <button
                                            type="button"
                                            onClick={(ev) => {
                                              ev.stopPropagation();
                                              void onPay(e);
                                            }}
                                            className="rounded-md bg-emerald-600/10 px-2 py-0.5 text-xs font-medium text-emerald-700 hover:bg-emerald-600/20 dark:text-emerald-300"
                                          >
                                            Выплатить
                                          </button>
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </td>
                        </tr>
                      );
                      return [mainRow, detailRow];
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ── Режим «Детально» ── */}
      {viewMode === "detail" && (
        <>
          {/* Фильтр статуса */}
          <div className="mt-4 flex gap-2">
            {(["all", "pending", "paid"] as StatusFilter[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setStatusFilter(s)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  statusFilter === s
                    ? "bg-ink text-surface"
                    : "bg-sunken text-muted hover:text-ink"
                }`}
              >
                {s === "all" ? "Все" : s === "pending" ? "Ожидают" : "Выплачены"}
              </button>
            ))}
          </div>

          {loading && <p className="mt-6 text-sm text-muted">Загрузка…</p>}
          {error && (
            <p className="mt-6 rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
              Не удалось загрузить начисления — проверьте подключение к HR-модулю.
            </p>
          )}

          {!loading && !error && (
            <div className="mt-4 overflow-hidden rounded-xl bg-surface shadow-card">
              <table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Сотрудник</th>
                    <th className="px-4 py-2.5 font-medium">Период</th>
                    <th className="px-4 py-2.5 text-right font-medium">Сумма, BYN</th>
                    <th className="px-4 py-2.5 font-medium">Статус</th>
                    <th className="px-4 py-2.5 font-medium">Дата</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {entries.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-muted">
                        Начислений пока нет.
                      </td>
                    </tr>
                  ) : (
                    entries.map((e) => (
                      <tr key={e.id} className="border-b border-line last:border-0 hover:bg-sunken">
                        <td className="px-4 py-2.5 text-ink">{empName(e.employee_id)}</td>
                        <td className="px-4 py-2.5 tabular-nums text-muted">{e.period}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-ink font-medium">
                          {fmtByn(e.amount_byn)}
                        </td>
                        <td className="px-4 py-2.5">
                          <StatusBadge status={e.status} />
                        </td>
                        <td className="px-4 py-2.5 text-muted" />
                        <td className="px-4 py-2.5 text-right">
                          {e.status === "pending" && (
                            <button
                              type="button"
                              onClick={() => onPay(e)}
                              className="rounded-md bg-emerald-600/10 px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-600/20 dark:text-emerald-300"
                            >
                              Выплатить
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </main>
    {preview && (
      <>
        <style data-testid="payroll-preview-print-css">{`
          @media print {
            @page { size: A4; margin: 12mm; }
            html, body { background: #fff !important; }
            html, body, body * { overflow: visible !important; }
            body * { visibility: hidden !important; }
            [data-payroll-preview-print], [data-payroll-preview-print] * { visibility: visible !important; }
            [data-payroll-preview-print] {
              display: block !important;
              position: absolute !important;
              inset: 0 auto auto 0;
              width: 100% !important;
              min-height: 100% !important;
              max-height: none !important;
              overflow: visible !important;
              color: #000 !important;
              background: #fff !important;
            }
            [data-payroll-preview-print] * { color: #000 !important; border-color: #000 !important; }
          }
        `}</style>
        <section
          data-payroll-preview-print
          data-testid="payroll-preview-print"
          role="document"
          aria-label="Печатный черновик расчёта зарплаты"
          className="hidden bg-white p-6 text-black print:block"
        >
          <h1 className="text-xl font-bold">Расчёт зарплаты от суммы «на руки»</h1>
          <p className="mt-2 font-medium">Черновик — не ведомость и не платёжный документ.</p>
          <p className="mt-1 text-sm">Валюта: BYN. На руки — сумма за полный месяц до аванса.</p>
          <PayrollPreviewScenario inputs={preview.inputs} formatByn={fmtByn} />
          <PayrollPreviewBreakdown preview={preview} formatByn={fmtByn} />
        </section>
      </>
    )}
    </>
  );
}
