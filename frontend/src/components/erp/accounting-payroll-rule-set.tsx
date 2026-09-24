"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select, Textarea } from "@/components/ui/input";
import { fetchStatutoryRequirements, type StatutoryRequirement } from "@/lib/statutory-requirements-api";
import { AccountingPayrollEvidenceUpload, type PayrollEvidenceReceipt } from "./accounting-payroll-evidence-upload";

type Policy = { id: number; effective_from: string; reference: string; normative_verified: boolean };
type Role = "employee_deduction" | "employer_contribution";
type BaseMode = "gross" | "gross_less_adjustment";
type ObligationCode = "period_income_tax_withholding_rule" | "period_fszn_rules_and_limits" | "period_work_injury_insurance_tariff";
type RuleDraft = { code: string; role: Role | ""; base_mode: BaseMode | ""; obligation_code: ObligationCode | ""; classification_evidence: string };
type RateRule = { code: string; role: Role; base_mode: BaseMode; obligation_code?: ObligationCode; classification_evidence: string };
type RateVersion = { code: string; requirement_id: number; requirement_digest: string };
type RuleCommand = {
  request_key: string; policy_id: number; effective_from: string;
  gross_method: "monthly_salary_by_hours"; rounding: "half_up_cent";
  rate_rules: RateRule[]; expected_rate_versions: RateVersion[];
  source_reference: string; source_digest: string; source_file_id: number; evidence: string;
};
type RuleSet = Omit<RuleCommand, "expected_rate_versions"> & {
  rule_set_id: number; organization_id: number; revision: number; rate_versions: RateVersion[];
  source_document_verified: boolean; statutory_completeness_verified: boolean;
};
type Access = { organization_id: number; can_review: boolean; can_upload: boolean };
type Props = {
  org: string; month: string; policies: Policy[]; disabled: boolean;
  onOpenRates?: () => void; onBusyChange?: (busy: boolean) => void;
};

class RuleError extends Error { constructor(message: string, readonly status?: number) { super(message); } }
class ReceiptMismatchError extends Error {}
const blankRule = (): RuleDraft => ({ code: "", role: "", base_mode: "", obligation_code: "", classification_evidence: "" });
const obligationLabels: Record<ObligationCode, string> = {
  period_income_tax_withholding_rule: "Подоходный налог",
  period_fszn_rules_and_limits: "Взносы ФСЗН",
  period_work_injury_insurance_tariff: "Страхование от несчастных случаев",
};
const message = (cause: unknown) => cause instanceof Error ? cause.message : "Запрос не выполнен.";
const validOrg = (org: string) => /^[1-9]\d*$/.test(org) && Number.isSafeInteger(Number(org));
const validMonth = (month: string) => /^\d{4}-(0[1-9]|1[0-2])$/.test(month);
const digest = (value: string) => /^[a-f0-9]{64}$/.test(value);

async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store", signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data && typeof data.detail === "string" ? data.detail : null;
    throw new RuleError(detail ?? `Бухгалтерия вернула ошибку ${response.status}.`, response.status);
  }
  if (data === null) throw new RuleError("Бухгалтерия вернула некорректный ответ.");
  return data as T;
}

function policyFile(row: PayrollEvidenceReceipt, org: string) {
  return row.organization_id === Number(org) && row.kind === "payroll_policy"
    && row.employment_binding_id === null && row.month === null && row.file_id > 0
    && !!row.reference && digest(row.sha256);
}

function sameVersions(actual: RateVersion[], expected: RateVersion[]) {
  return Array.isArray(actual) && actual.length === expected.length && actual.every((row, i) =>
    row.code === expected[i].code && row.requirement_id === expected[i].requirement_id
    && row.requirement_digest === expected[i].requirement_digest);
}

function sameRules(actual: RateRule[], expected: RateRule[]) {
  return Array.isArray(actual) && actual.length === expected.length && actual.every((row, i) =>
    row.code === expected[i].code && row.role === expected[i].role
    && row.base_mode === expected[i].base_mode && row.obligation_code === expected[i].obligation_code
    && row.classification_evidence === expected[i].classification_evidence);
}

function validReceipt(value: RuleSet, command: RuleCommand, org: string) {
  return value.organization_id === Number(org) && Number.isSafeInteger(value.rule_set_id) && value.rule_set_id > 0
    && Number.isSafeInteger(value.revision) && value.revision > 0
    && value.request_key === command.request_key && value.policy_id === command.policy_id
    && value.effective_from === command.effective_from && value.gross_method === command.gross_method
    && value.rounding === command.rounding && value.source_reference === command.source_reference
    && value.source_digest === command.source_digest && value.source_file_id === command.source_file_id
    && value.evidence === command.evidence && !value.source_document_verified
    && !value.statutory_completeness_verified && sameVersions(value.rate_versions, command.expected_rate_versions)
    && sameRules(value.rate_rules, command.rate_rules);
}

export function AccountingPayrollRuleSet(props: Props) {
  return <ScopedPayrollRuleSet key={`${props.org}:${props.month}`} {...props} />;
}

function ScopedPayrollRuleSet({ org, month, policies, disabled, onOpenRates, onBusyChange }: Props) {
  const ready = validOrg(org) && validMonth(month);
  const monthStart = `${month}-01`;
  const [access, setAccess] = useState<Access | null>(null);
  const [catalog, setCatalog] = useState<StatutoryRequirement[] | null>(null);
  const [files, setFiles] = useState<PayrollEvidenceReceipt[]>([]);
  const [current, setCurrent] = useState<RuleSet | null>(null);
  const [policyId, setPolicyId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [grossMethod, setGrossMethod] = useState("");
  const [rounding, setRounding] = useState("");
  const [rules, setRules] = useState<RuleDraft[]>([blankRule()]);
  const [evidence, setEvidence] = useState("");
  const [pending, setPending] = useState<RuleCommand | null>(null);
  const [loading, setLoading] = useState(ready);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const submitting = useRef(false);
  const eligiblePolicies = policies.filter((row) => row.normative_verified && row.effective_from <= monthStart);
  const rates = (catalog ?? []).filter((row) => row.kind === "rate" && row.rate_unit === "percent");
  const selectedFile = files.find((row) => String(row.file_id) === sourceId);
  const base = `/organizations/${encodeURIComponent(org)}`;

  useEffect(() => { onBusyChange?.(saving || uploading); return () => onBusyChange?.(false); }, [saving, uploading, onBusyChange]);
  useEffect(() => {
    if (!ready) return;
    let active = true;
    const controller = new AbortController();
    void Promise.all([
      api<Access>(`${base}/payroll-workpaper-access`, undefined, controller.signal),
      fetchStatutoryRequirements(org, month),
      api<PayrollEvidenceReceipt[]>(`${base}/payroll-evidence-files?kind=payroll_policy`, undefined, controller.signal),
      api<RuleSet>(`${base}/payroll-rule-sets/current?as_of=${monthStart}`, undefined, controller.signal)
        .catch((cause) => { if (cause instanceof RuleError && cause.status === 404) return null; throw cause; }),
    ]).then(([role, requirements, sources, ruleSet]) => {
      if (!active) return;
      if (role.organization_id !== Number(org) || !Array.isArray(sources) || sources.some((row) => !policyFile(row, org))
          || (ruleSet && (ruleSet.organization_id !== Number(org) || ruleSet.effective_from > monthStart
            || !Array.isArray(ruleSet.rate_rules) || !Array.isArray(ruleSet.rate_versions)))) {
        throw new Error("Ответ относится к другой бухгалтерской книге или источнику.");
      }
      setAccess(role); setCatalog(requirements); setFiles(sources); setCurrent(ruleSet);
    }).catch((cause) => { if (active && !controller.signal.aborted) { setCatalog(null); setError(message(cause)); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [base, month, monthStart, org, ready, refresh]);

  function updateRule(index: number, patch: Partial<RuleDraft>) {
    setRules((rows) => rows.map((row, i) => i === index ? { ...row, ...patch } : row));
    setError("");
  }

  function build(): RuleCommand {
    const policy = eligiblePolicies.find((row) => String(row.id) === policyId);
    if (!policy) throw new Error("Выберите действующую подтверждённую учётную политику.");
    if (!selectedFile || !policyFile(selectedFile, org)) throw new Error("Выберите сохранённый файл правил зарплаты.");
    if (grossMethod !== "monthly_salary_by_hours" || rounding !== "half_up_cent") throw new Error("Явно выберите метод начисления и округления.");
    if (evidence.trim().length < 10) throw new Error("Укажите основание набора правил не короче 10 символов.");
    if (!rules.length || rules.length > 20 || rules.some((row) => !row.code || !row.role || !row.base_mode || !row.obligation_code || row.classification_evidence.trim().length < 10)
        || new Set(rules.map((row) => row.code)).size !== rules.length) {
      throw new Error("Для каждой ставки выберите уникальный код, вид, базу, обязательство и основание классификации.");
    }
    const selectedRates = rules.map((row) => rates.find((rate) => rate.code === row.code));
    if (selectedRates.some((row) => !row || !digest(row.digest))) throw new Error("Каталог ставок изменился; обновите данные.");
    return {
      request_key: crypto.randomUUID(), policy_id: policy.id, effective_from: monthStart,
      gross_method: "monthly_salary_by_hours", rounding: "half_up_cent",
      rate_rules: rules.map((row) => ({ code: row.code, role: row.role as Role,
        base_mode: row.base_mode as BaseMode, obligation_code: row.obligation_code as ObligationCode,
        classification_evidence: row.classification_evidence.trim() })),
      expected_rate_versions: selectedRates.map((rate) => ({ code: rate!.code,
        requirement_id: rate!.requirement_id, requirement_digest: rate!.digest })),
      source_reference: selectedFile.reference, source_digest: selectedFile.sha256,
      source_file_id: selectedFile.file_id, evidence: evidence.trim(),
    };
  }

  function accept(value: RuleSet, command: RuleCommand) {
    if (!validReceipt(value, command, org)) throw new ReceiptMismatchError("Квитанция набора правил не совпадает с сохранённой командой.");
    setCurrent(value); setPending(null); setError("");
    setNotice(`Редакция ${value.revision} сохранена. Расчёт остаётся предварительным.`);
    setPolicyId(""); setSourceId(""); setGrossMethod(""); setRounding(""); setRules([blankRule()]); setEvidence("");
  }

  async function submit() {
    if (!ready || disabled || !access?.can_review || submitting.current || saving || uploading || loading) return;
    let command = pending;
    try { if (!command) { command = build(); setPending(command); } }
    catch (cause) { setError(message(cause)); return; }
    submitting.current = true; setSaving(true); setError(""); setNotice("");
    let rejectedPost = false;
    try {
      try { accept(await api<RuleSet>(`${base}/payroll-rule-sets`, command), command); }
      catch (cause) {
        if (cause instanceof RuleError && cause.status !== undefined && cause.status < 500 && cause.status !== 408 && cause.status !== 429) { rejectedPost = true; throw cause; }
        try { accept(await api<RuleSet>(`${base}/payroll-rule-sets/by-request/${command.request_key}`), command); }
        catch (lookupError) {
          if (lookupError instanceof ReceiptMismatchError) throw lookupError;
          if (lookupError instanceof RuleError && lookupError.status !== 404) throw lookupError;
          throw new Error("Результат сохранения неизвестен. Проверьте или повторите тот же запрос.");
        }
      }
    } catch (cause) {
      if (rejectedPost) setPending(null);
      setError(message(cause));
    } finally { submitting.current = false; setSaving(false); }
  }

  function uploaded(row: PayrollEvidenceReceipt) {
    if (!policyFile(row, org)) { setError("Квитанция файла относится к другому юрлицу или области."); return; }
    setFiles((rows) => [row, ...rows.filter((item) => item.file_id !== row.file_id)]);
    setSourceId(String(row.file_id)); setError("");
  }

  if (!ready) return <section aria-label="Правила зарплаты" className="rounded-xl border border-line p-4">Выберите юрлицо и месяц.</section>;
  const locked = disabled || loading || saving || uploading || pending !== null || !access?.can_review;
  return <section aria-label="Правила зарплаты" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="text-lg font-semibold">Правила расчёта зарплаты · {month}</h2>
    <p className="text-sm text-muted">Только настройка арифметического черновика. Ставки, классификация и файл основания выбираются явно; нормативная полнота, содержание файла и право на официальное начисление не подтверждаются этим экраном.</p>
    {loading && <p role="status">Загрузка правил…</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {current && <div className="space-y-2 rounded-lg border border-line p-3 text-sm"><h3 className="font-semibold">Действующая редакция № {current.revision} с {current.effective_from}</h3><p>Политика № {current.policy_id}; основание: {current.source_reference}{current.source_file_id ? ` · файл № ${current.source_file_id}` : " · файл не привязан"}.</p><ul className="list-disc pl-5">{current.rate_rules.map((rule) => { const version = current.rate_versions.find((row) => row.code === rule.code); return <li key={rule.code}>{rule.code}: {rule.role === "employee_deduction" ? "удержание работника" : "взнос нанимателя"}, {rule.base_mode === "gross" ? "от начисленного" : "с корректировкой базы"}, {rule.obligation_code ? obligationLabels[rule.obligation_code] : "обязательство не сопоставлено"}; ставка № {version?.requirement_id ?? "не найдена"}.</li>; })}</ul><p>Проверка содержания источника и нормативной полноты: не выполнена.</p></div>}
    {!current && !loading && catalog && <p className="text-sm text-muted">На выбранный месяц набор правил ещё не задан.</p>}
    {access && !access.can_review && <p className="text-sm text-muted">Новую редакцию настраивает главный бухгалтер.</p>}
    {access?.can_review && <>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm">Учётная политика<Select aria-label="Учётная политика для зарплаты" value={policyId} disabled={locked} onChange={(event) => setPolicyId(event.target.value)}><option value="">Выберите подтверждённую политику</option>{eligiblePolicies.map((row) => <option key={row.id} value={row.id}>№ {row.id} · {row.reference} · с {row.effective_from}</option>)}</Select></label>
        <label className="text-sm">Файл правил<Select aria-label="Файл правил" value={sourceId} disabled={locked} onChange={(event) => setSourceId(event.target.value)}><option value="">Выберите сохранённый файл</option>{files.map((row) => <option key={row.file_id} value={row.file_id}>№ {row.file_id} · {row.reference} · {row.filename}</option>)}</Select></label>
        <label className="text-sm">Метод начисления<Select aria-label="Метод начисления" value={grossMethod} disabled={locked} onChange={(event) => setGrossMethod(event.target.value)}><option value="">Выберите метод</option><option value="monthly_salary_by_hours">Оклад × отработанные часы / норма часов</option></Select></label>
        <label className="text-sm">Округление<Select aria-label="Округление зарплаты" value={rounding} disabled={locked} onChange={(event) => setRounding(event.target.value)}><option value="">Выберите округление</option><option value="half_up_cent">До копейки: половина вверх</option></Select></label>
      </div>
      {access.can_upload && <AccountingPayrollEvidenceUpload key={`policy:${org}`} org={org} policyOnly disabled={disabled || loading || saving || pending !== null} onUploaded={uploaded} onBusyChange={setUploading} />}
      <div className="space-y-3"><h3 className="font-semibold">Ставки и классификация</h3>
        {!rates.length && <p className="text-sm text-muted">Процентных ставок на месяц нет. Сначала внесите подтверждённые ставки в каталог.</p>}
        {onOpenRates && <Button variant="secondary" disabled={disabled || saving || uploading || pending !== null} onClick={onOpenRates}>Открыть формы и ставки</Button>}
        {rules.map((row, index) => <div key={index} className="grid gap-2 rounded-lg border border-line p-3 md:grid-cols-3">
          <label className="text-sm">Ставка {index + 1}<Select aria-label={`Ставка ${index + 1}`} value={row.code} disabled={locked} onChange={(event) => updateRule(index, { code: event.target.value })}><option value="">Выберите ставку</option>{rates.map((rate) => <option key={rate.requirement_id} value={rate.code}>{rate.code} · {rate.title} · {rate.rate_value}% от {rate.rate_basis} · версия {rate.revision}</option>)}</Select></label>
          <label className="text-sm">Вид суммы<Select aria-label={`Вид суммы ${index + 1}`} value={row.role} disabled={locked} onChange={(event) => updateRule(index, { role: event.target.value as Role | "" })}><option value="">Выберите вид</option><option value="employee_deduction">Удержание работника</option><option value="employer_contribution">Взнос нанимателя</option></Select></label>
          <label className="text-sm">База<Select aria-label={`База ${index + 1}`} value={row.base_mode} disabled={locked} onChange={(event) => updateRule(index, { base_mode: event.target.value as BaseMode | "" })}><option value="">Выберите базу</option><option value="gross">Начисленная сумма</option><option value="gross_less_adjustment">Начисленная сумма за вычетом подтверждённой корректировки</option></Select></label>
          <label className="text-sm md:col-span-3">Обязательство<Select aria-label={`Обязательство ${index + 1}`} value={row.obligation_code} disabled={locked} onChange={(event) => updateRule(index, { obligation_code: event.target.value as ObligationCode | "" })}><option value="">Выберите обязательство</option>{(Object.entries(obligationLabels) as [ObligationCode, string][]).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</Select></label>
          <label className="text-sm md:col-span-3">Основание классификации<Textarea aria-label={`Основание классификации ${index + 1}`} value={row.classification_evidence} disabled={locked} onChange={(event) => updateRule(index, { classification_evidence: event.target.value })} /></label>
          {rules.length > 1 && <Button variant="ghost" disabled={locked} onClick={() => setRules((rows) => rows.filter((_, i) => i !== index))}>Удалить ставку {index + 1}</Button>}
        </div>)}
        <Button variant="secondary" disabled={locked || rules.length >= 20} onClick={() => setRules((rows) => [...rows, blankRule()])}>Добавить ставку</Button>
      </div>
      <label className="block text-sm">Основание всей редакции<Textarea aria-label="Основание правил" value={evidence} disabled={locked} onChange={(event) => setEvidence(event.target.value)} /></label>
      <Button disabled={disabled || loading || saving || uploading || !access.can_review} onClick={() => void submit()}>{pending ? "Проверить или повторить запрос" : "Сохранить новую редакцию"}</Button>
      {pending && <p className="break-all text-xs text-muted">Поля заблокированы до подтверждения ключа {pending.request_key}.</p>}
    </>}
    <Button variant="secondary" disabled={loading || saving || uploading || pending !== null} onClick={() => { setLoading(true); setError(""); setRefresh((value) => value + 1); }}>Обновить каталог и правила</Button>
  </section>;
}
