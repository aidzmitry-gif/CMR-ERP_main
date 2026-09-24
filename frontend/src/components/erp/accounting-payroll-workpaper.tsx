"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";
import { AccountingPayrollEvidenceUpload, type PayrollEvidenceReceipt } from "./accounting-payroll-evidence-upload";

type RateRule = { code: string; role: "employee_deduction" | "employer_contribution"; base_mode: "gross" | "gross_less_adjustment"; obligation_code?: string; classification_evidence: string };
type RateVersion = { code: string; requirement_id: number; requirement_digest: string };
type RuleSet = { rule_set_id: number; organization_id: number; policy_id: number; effective_from: string; revision: number; rate_rules: RateRule[]; rate_versions: RateVersion[]; source_reference: string; source_file_id: number | null };
type Binding = { binding_id: number; organization_id: number; employee_id: number; employee_name: string; contract_ref: string; source_document: string; personnel_identifier: string | null; state: "active" | "ended"; effective_from: string };
type SourceFile = { file_id: number; organization_id: number; employment_binding_id: number | null; kind: string; month: string | null; reference: string; filename: string; content_type: string; sha256: string; size_bytes: number };
type TimesheetCheck = { file_id: number; organization_id: number; employment_binding_id: number | null; period: string; source_sha256: string; status: "structure_checked" | "structure_failed" | "uncheckable" | "manual_source"; structure_ok: boolean | null; employee_row_numbers?: number[]; issues: { code: string; rows: number[] }[]; document_facts_verified: false };
type Component = { requirement_id: number; adjustment_byn: string; adjustment_document?: string; adjustment_evidence?: string; adjustment_file_id?: number };
type WorkpaperCommand = { policy_id: number; rule_set_id: number; employment_binding_id: number; work_from: string; work_to: string; monthly_salary_byn: string; contract_document: string; contract_digest: string; contract_file_id: number; contract_amount_evidence: string; timesheet_document: string; timesheet_digest: string; timesheet_file_id: number; timesheet_row?: number; timesheet_evidence: string; work_schedule_document?: string; work_schedule_digest?: string; work_schedule_file_id?: number; work_schedule_cell?: string; norm_hours_evidence?: string; month_norm_hours: string; worked_hours: string; components: Component[] };
type Preview = { status: string; basis_digest: string; gross_byn: string; listed_employee_deductions_byn: string; after_listed_deductions_byn: string; listed_employer_contributions_byn: string; cost_including_listed_contributions_byn: string; contract_and_timesheet_hashes_verified: boolean; timesheet_numeric_hours_verified: boolean; timesheet_name_matches_binding: boolean; timesheet_identifier_matches_binding: boolean; schedule_file_bytes_verified: boolean; schedule_numeric_hours_verified: boolean; rule_source_file_bytes_verified: boolean; posting_available: boolean; statutory_payroll_certified: boolean; basis: { organization_id: number; month: string; employee_name: string; work_from: string; work_to: string; timesheet_row: number | null; timesheet_uninterpreted_code_days: number | null; work_schedule_cell: string | null; components: { rate_code: string; role: string; base_byn: string; rate_value: string; amount_byn: string }[] } };
type Adjustment = { amount: string; fileId: string; evidence: string };
type Access = { organization_id: number; can_preview: boolean; can_upload: boolean; can_review: boolean };
type ReviewSegment = { review_id: number; revision: number; work_from: string; work_to: string; basis_digest: string; source_facts_attested_by_chief: boolean; fszn_base_classified_by_chief: boolean };
type ReviewSummary = { status: string; organization_id: number; month: string; bindings: { employment_binding_id: number; segments: ReviewSegment[] }[] };
type ReviewCommand = WorkpaperCommand & { request_key: string; basis_digest: string; reviewer_evidence: string; supersedes_review_id?: number; source_fact_attestation?: "contract_salary_time_norm_checked"; source_fact_evidence?: string; fszn_base_attestation?: "listed_salary_base_checked"; fszn_base_evidence?: string; fszn_base_contract_locator?: string };
type ReviewReceipt = { review_id: number; organization_id: number; employment_binding_id: number; month: string; work_from: string; work_to: string; request_key: string; basis_digest: string; revision: number; supersedes_review_id: number | null; status: string; source_facts_attested_by_chief: boolean; fszn_base_classified_by_chief: boolean; posting_available: boolean; statutory_payroll_certified: boolean };

const monthPattern = /^\d{4}-(0[1-9]|1[0-2])$/;
const moneyPattern = /^(0|[1-9]\d*)\.\d{2}$/;
const spreadsheetType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const errorText = (error: unknown) => error instanceof Error ? error.message : "Запрос не выполнен.";
const timesheetIssue: Record<string, string> = {
  sheet_period_unconfirmed: "месяц листа",
  day_header_mismatch: "даты",
  summary_header_mismatch: "столбцы итогов",
  employee_rows_missing: "строки сотрудников",
  employee_rows_after_gap: "строки после пустого промежутка",
  personnel_identifier_missing: "табельный номер отсутствует",
  personnel_identifier_repeated: "табельный номер повторяется",
  employee_name_missing: "ФИО отсутствует",
  formula_in_day_cell: "формула в дневной ячейке",
  invalid_daily_hours: "дневные часы",
  worked_days_invalid: "итог рабочих дней",
  worked_days_requires_review: "итог дней требует сверки",
  hours_formula_range: "формула часов охватывает не все дни",
  hours_cache_missing: "итог часов отсутствует",
  hours_total_mismatch: "итог часов расходится с днями",
  unsupported_workbook: "формат книги не распознан",
};

class WorkpaperError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

function monthLast(month: string) {
  const [year, number] = month.split("-").map(Number);
  return `${month}-${String(new Date(Date.UTC(year, number, 0)).getUTCDate()).padStart(2, "0")}`;
}

async function request<T>(path: string, signal: AbortSignal, body?: unknown): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data && typeof data.detail === "string" ? data.detail : null;
    throw new WorkpaperError(detail ?? `Бухгалтерия вернула ошибку ${response.status}.`, response.status);
  }
  if (data === null) throw new WorkpaperError("Бухгалтерия вернула некорректный ответ.");
  return data as T;
}

type Props = { org: string; month: string; disabled: boolean; onBusyChange?: (busy: boolean) => void; onOpenRules?: () => void };

export function AccountingPayrollWorkpaper(props: Props) {
  return <ScopedPayrollWorkpaper key={`${props.org}:${props.month}`} {...props} />;
}

function ScopedPayrollWorkpaper({ org, month, disabled, onBusyChange, onOpenRules }: Props) {
  const [rules, setRules] = useState<RuleSet | null>(null);
  const [access, setAccess] = useState<Access | null>(null);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [bindingId, setBindingId] = useState("");
  const [contractId, setContractId] = useState("");
  const [timesheetId, setTimesheetId] = useState("");
  const [scheduleId, setScheduleId] = useState("");
  const [scheduleCell, setScheduleCell] = useState("");
  const [timesheetRow, setTimesheetRow] = useState("");
  const [timesheetCheckState, setTimesheetCheckState] = useState<{ key: string; report?: TimesheetCheck; error?: string } | null>(null);
  const [workFrom, setWorkFrom] = useState(`${month}-01`);
  const [workTo, setWorkTo] = useState(monthPattern.test(month) ? monthLast(month) : "");
  const [salary, setSalary] = useState("");
  const [normHours, setNormHours] = useState("");
  const [workedHours, setWorkedHours] = useState("");
  const [contractEvidence, setContractEvidence] = useState("");
  const [timesheetEvidence, setTimesheetEvidence] = useState("");
  const [normEvidence, setNormEvidence] = useState("");
  const [adjustments, setAdjustments] = useState<Record<string, Adjustment>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewCommand, setPreviewCommand] = useState<WorkpaperCommand | null>(null);
  const [latestReview, setLatestReview] = useState<ReviewSegment | null>(null);
  const [reviewReceipt, setReviewReceipt] = useState<ReviewReceipt | null>(null);
  const [reviewEvidence, setReviewEvidence] = useState("");
  const [sourceFactsChecked, setSourceFactsChecked] = useState(false);
  const [sourceFactEvidence, setSourceFactEvidence] = useState("");
  const [fsznBaseChecked, setFsznBaseChecked] = useState(false);
  const [fsznBaseEvidence, setFsznBaseEvidence] = useState("");
  const [fsznContractLocator, setFsznContractLocator] = useState("");
  const [pendingReview, setPendingReview] = useState<ReviewCommand | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [personnelCode, setPersonnelCode] = useState("");
  const [personnelEvidence, setPersonnelEvidence] = useState("");
  const [personnelBusy, setPersonnelBusy] = useState(false);
  const [personnelError, setPersonnelError] = useState("");
  const [personnelNotice, setPersonnelNotice] = useState("");
  const pendingPersonnel = useRef<{ scope: string; code: string; evidence: string; key: string } | null>(null);
  const [loading, setLoading] = useState(/^[1-9]\d*$/.test(org) && monthPattern.test(month));
  const [busy, setBusy] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [error, setError] = useState("");
  const [fileError, setFileError] = useState("");
  const generation = useRef(0);
  const previewController = useRef<AbortController | null>(null);
  const reviewing = useRef(false);
  const ready = /^[1-9]\d*$/.test(org) && monthPattern.test(month);
  const selectedBinding = bindings.find((row) => String(row.binding_id) === bindingId);
  const contractFiles = files.filter((row) => row.kind === "employment_contract" && row.reference === selectedBinding?.source_document);
  const timesheetFiles = files.filter((row) => row.kind === "timesheet" && row.month === month);
  const scheduleFiles = files.filter((row) => row.kind === "work_schedule" && row.month === month);
  const adjustmentFiles = files.filter((row) => row.kind === "base_adjustment" && row.month === month);
  const selectedContract = contractFiles.find((row) => String(row.file_id) === contractId);
  const selectedTimesheet = timesheetFiles.find((row) => String(row.file_id) === timesheetId);
  const selectedSchedule = scheduleFiles.find((row) => String(row.file_id) === scheduleId);
  const needsXlsxScheduleCell = selectedSchedule?.content_type === spreadsheetType;
  const needsXlsxCheck = selectedTimesheet?.content_type === spreadsheetType;
  const selectedTimesheetFileId = selectedTimesheet?.file_id;
  const selectedTimesheetSha = selectedTimesheet?.sha256;
  const timesheetCheckKey = `${org}:${month}:${bindingId}:${selectedTimesheetFileId ?? ""}:${selectedTimesheetSha ?? ""}`;
  const timesheetCheck = timesheetCheckState?.key === timesheetCheckKey ? timesheetCheckState.report : null;
  const timesheetCheckError = timesheetCheckState?.key === timesheetCheckKey ? timesheetCheckState.error : "";
  const formLocked = disabled || busy || uploadBusy || pendingReview !== null || reviewBusy || personnelBusy;
  const hasFsznRate = !!rules?.rate_rules.some((rule) => rule.obligation_code === "period_fszn_rules_and_limits");
  const sameReviewedBasis = !!preview && latestReview?.basis_digest === preview.basis_digest;
  const attestationUpgrade = sourceFactsChecked && !latestReview?.source_facts_attested_by_chief
    || fsznBaseChecked && !latestReview?.fszn_base_classified_by_chief;

  useEffect(() => { onBusyChange?.(busy || uploadBusy || reviewBusy || personnelBusy); return () => onBusyChange?.(false); }, [busy, uploadBusy, reviewBusy, personnelBusy, onBusyChange]);

  function invalidate() {
    previewController.current?.abort();
    setPreview(null);
    setPreviewCommand(null); setLatestReview(null); setReviewReceipt(null); setReviewError(""); setReviewEvidence(""); setSourceFactsChecked(false); setSourceFactEvidence(""); setFsznBaseChecked(false); setFsznBaseEvidence(""); setFsznContractLocator("");
    setError("");
  }

  async function recordPersonnelIdentifier() {
    if (!selectedBinding || selectedBinding.personnel_identifier || !access?.can_review || formLocked) return;
    const code = personnelCode.trim();
    const evidence = personnelEvidence.trim();
    if (!code || code.length > 40 || /\s/.test(code) || evidence.length < 10) {
      setPersonnelError("Укажите табельный номер без пробелов и место его проверки в кадровом источнике (не менее 10 символов).");
      return;
    }
    const scope = `${org}:${month}:${selectedBinding.binding_id}`;
    const previous = pendingPersonnel.current;
    const key = previous?.scope === scope && previous.code === code && previous.evidence === evidence
      ? previous.key : crypto.randomUUID();
    pendingPersonnel.current = { scope, code, evidence, key };
    const token = generation.current;
    setPersonnelBusy(true); setPersonnelError(""); setPersonnelNotice("");
    try {
      const base = `/organizations/${encodeURIComponent(org)}/payroll-employments`;
      await request<Binding>(base, new AbortController().signal, {
        request_key: key, employee_id: selectedBinding.employee_id,
        contract_ref: selectedBinding.contract_ref,
        effective_from: selectedBinding.effective_from > `${month}-01`
          ? selectedBinding.effective_from : `${month}-01`,
        state: "active", source_document: selectedBinding.source_document,
        evidence, personnel_identifier: code, personnel_identifier_evidence: evidence,
      });
      const current = await request<Binding[]>(`${base}?as_of=${monthLast(month)}`, new AbortController().signal);
      if (token !== generation.current) return;
      const replacement = current.find((row) => row.organization_id === Number(org)
        && row.employee_id === selectedBinding.employee_id
        && row.contract_ref === selectedBinding.contract_ref
        && row.personnel_identifier === code && row.state === "active");
      if (!replacement || current.some((row) => row.organization_id !== Number(org))) {
        throw new Error("Новая редакция договора не подтверждена текущим реестром.");
      }
      invalidate(); setBindings(current.filter((row) => row.state === "active"));
      setBindingId(String(replacement.binding_id)); setFiles([]); setContractId("");
      setTimesheetId(""); setTimesheetRow(""); setScheduleId(""); setScheduleCell(""); setNormEvidence("");
      setAdjustments({}); setPersonnelCode(""); setPersonnelEvidence("");
      setPersonnelNotice("Новая редакция привязки сохранена. Загрузите файлы договора, табеля и графика для неё.");
      pendingPersonnel.current = null;
    } catch (cause) {
      if (cause instanceof WorkpaperError && cause.status !== undefined
          && cause.status < 500 && cause.status !== 408 && cause.status !== 429) pendingPersonnel.current = null;
      if (token === generation.current) setPersonnelError(errorText(cause));
    } finally { if (token === generation.current) setPersonnelBusy(false); }
  }

  useEffect(() => {
    const token = ++generation.current;
    const controller = new AbortController();
    if (ready) {
      const base = `/organizations/${encodeURIComponent(org)}`;
      void Promise.all([
        request<RuleSet>(`${base}/payroll-rule-sets/current?as_of=${month}-01`, controller.signal),
        request<Binding[]>(`${base}/payroll-employments?as_of=${monthLast(month)}`, controller.signal),
        request<Access>(`${base}/payroll-workpaper-access`, controller.signal),
      ]).then(([ruleSet, employment, roleAccess]) => {
        if (token !== generation.current) return;
        if (ruleSet.organization_id !== Number(org) || roleAccess.organization_id !== Number(org) || employment.some((row) => row.organization_id !== Number(org))) throw new Error("Ответ относится к другому юридическому лицу.");
        if (!ruleSet.rate_versions?.length || ruleSet.rate_versions.length !== ruleSet.rate_rules.length || ruleSet.rate_rules.some((row) => !ruleSet.rate_versions.some((version) => version.code === row.code))) throw new Error("Набор ставок неполон; расчёт заблокирован.");
        setRules(ruleSet);
        setAccess(roleAccess);
        setBindings(employment.filter((row) => row.state === "active"));
      }).catch((cause) => { if (token === generation.current && !controller.signal.aborted) setError(errorText(cause)); })
        .finally(() => { if (token === generation.current) setLoading(false); });
    }
    return () => { generation.current += 1; controller.abort(); previewController.current?.abort(); };
  }, [org, month, ready]);

  useEffect(() => {
    const token = generation.current;
    const controller = new AbortController();
    if (ready && bindingId) {
      const path = `/organizations/${encodeURIComponent(org)}/payroll-evidence-files?employment_binding_id=${encodeURIComponent(bindingId)}`;
      void Promise.all([
        request<SourceFile[]>(`${path}&kind=employment_contract`, controller.signal),
        request<SourceFile[]>(`${path}&kind=timesheet&month=${month}`, controller.signal),
        request<SourceFile[]>(`${path}&kind=work_schedule&month=${month}`, controller.signal),
        request<SourceFile[]>(`${path}&kind=base_adjustment&month=${month}`, controller.signal),
      ]).then((groups) => {
          if (token !== generation.current || controller.signal.aborted) return;
          const rows = groups.flat();
          if (rows.some((row) => row.organization_id !== Number(org) || row.employment_binding_id !== Number(bindingId))) throw new Error("Источники относятся к другому юрлицу или договору.");
          setFiles(rows);
        }).catch((cause) => { if (token === generation.current && !controller.signal.aborted) setFileError(errorText(cause)); });
    }
    return () => controller.abort();
  }, [org, month, ready, bindingId]);

  useEffect(() => {
    const controller = new AbortController();
    if (needsXlsxCheck && selectedTimesheetFileId && selectedTimesheetSha) {
      void request<TimesheetCheck>(`/organizations/${encodeURIComponent(org)}/payroll-evidence-files/${selectedTimesheetFileId}/timesheet-preflight`, controller.signal)
        .then((check) => {
          if (controller.signal.aborted) return;
          if (check.file_id !== selectedTimesheetFileId || check.organization_id !== Number(org)
              || check.employment_binding_id !== Number(bindingId) || check.period !== month
              || check.source_sha256 !== selectedTimesheetSha || check.document_facts_verified !== false
              || !["structure_checked", "structure_failed", "uncheckable"].includes(check.status)
              || (check.status === "structure_checked") !== (check.structure_ok === true)) {
            throw new Error("Проверка табеля относится к другому файлу или договору.");
          }
          setTimesheetCheckState({ key: timesheetCheckKey, report: check });
        }).catch((cause) => { if (!controller.signal.aborted) setTimesheetCheckState({ key: timesheetCheckKey, error: errorText(cause) }); });
    }
    return () => controller.abort();
  }, [org, month, bindingId, needsXlsxCheck, selectedTimesheetFileId, selectedTimesheetSha, timesheetCheckKey]);

  function buildCommand(): WorkpaperCommand {
    if (!rules || !selectedBinding || !selectedContract || !selectedTimesheet) throw new Error("Выберите договор и сохранённые файлы договора и табеля.");
    if (needsXlsxCheck && timesheetCheck?.status === "structure_checked"
        && !selectedBinding.personnel_identifier) throw new Error("Для XLSX-табеля главбух должен указать табельный номер в привязке договора к юрлицу.");
    if (needsXlsxCheck && !timesheetCheck) throw new Error("Дождитесь предварительной проверки XLSX-табеля.");
    if (needsXlsxCheck && timesheetCheck?.status === "structure_checked"
        && !timesheetCheck.employee_row_numbers?.includes(Number(timesheetRow))) {
      throw new Error("Выберите строку работника в проверенном XLSX-табеле.");
    }
    if (!moneyPattern.test(salary) || Number(salary) <= 0 || !moneyPattern.test(normHours) || Number(normHours) <= 0 || !moneyPattern.test(workedHours)) throw new Error("Введите оклад, норму и отработанные часы с двумя знаками после запятой.");
    if (contractEvidence.trim().length < 10 || timesheetEvidence.trim().length < 10) throw new Error("Укажите, где в договоре и табеле проверены суммы и часы (не менее 10 символов).");
    if (selectedSchedule && normEvidence.trim().length < 10) throw new Error("Укажите, где в графике подтверждена месячная норма часов.");
    if (needsXlsxScheduleCell && !/^[A-Z]{1,3}[1-9][0-9]{0,6}$/.test(scheduleCell.trim())) throw new Error("Укажите ячейку месячной нормы XLSX-графика, например B5.");
    if (workFrom.slice(0, 7) !== month || workTo.slice(0, 7) !== month || workFrom > workTo) throw new Error("Отрезок работы должен относиться к выбранному месяцу.");
    const components = rules.rate_rules.map((rule) => {
      const version = rules.rate_versions.find((row) => row.code === rule.code);
      if (!version) throw new Error(`Нет версии ставки ${rule.code}.`);
      if (rule.base_mode === "gross") return { requirement_id: version.requirement_id, adjustment_byn: "0.00" };
      const adjustment = adjustments[rule.code];
      const source = adjustmentFiles.find((row) => String(row.file_id) === adjustment?.fileId);
      if (!adjustment || !moneyPattern.test(adjustment.amount) || !source || adjustment.evidence.trim().length < 10) throw new Error(`Для ${rule.code} укажите корректировку, файл основания и пояснение.`);
      return { requirement_id: version.requirement_id, adjustment_byn: adjustment.amount, adjustment_document: source.reference, adjustment_evidence: adjustment.evidence.trim(), adjustment_file_id: source.file_id };
    });
    return {
      policy_id: rules.policy_id, rule_set_id: rules.rule_set_id, employment_binding_id: selectedBinding.binding_id,
      work_from: workFrom, work_to: workTo, monthly_salary_byn: salary,
      contract_document: selectedContract.reference, contract_digest: selectedContract.sha256, contract_file_id: selectedContract.file_id,
      contract_amount_evidence: contractEvidence.trim(),
      timesheet_document: selectedTimesheet.reference, timesheet_digest: selectedTimesheet.sha256, timesheet_file_id: selectedTimesheet.file_id,
      ...(needsXlsxCheck && timesheetCheck?.status === "structure_checked"
        ? { timesheet_row: Number(timesheetRow) } : {}),
      ...(selectedSchedule ? {
        work_schedule_document: selectedSchedule.reference, work_schedule_digest: selectedSchedule.sha256,
        work_schedule_file_id: selectedSchedule.file_id, norm_hours_evidence: normEvidence.trim(),
        ...(needsXlsxScheduleCell ? { work_schedule_cell: scheduleCell.trim() } : {}),
      } : {}),
      timesheet_evidence: timesheetEvidence.trim(), month_norm_hours: normHours, worked_hours: workedHours, components,
    };
  }

  async function calculate() {
    if (!ready || busy || formLocked || !access?.can_preview) return;
    let command: WorkpaperCommand;
    try { command = buildCommand(); } catch (cause) { setError(errorText(cause)); return; }
    const token = generation.current;
    const controller = new AbortController();
    previewController.current = controller;
    setBusy(true); setError(""); setPreview(null); setPreviewCommand(null);
    setLatestReview(null); setReviewReceipt(null); setReviewError(""); setReviewLoading(false); setSourceFactsChecked(false); setSourceFactEvidence("");
    try {
      const result = await request<Preview>(`/organizations/${encodeURIComponent(org)}/periods/${month}/payroll-workpaper-preview`, controller.signal, command);
      if (token !== generation.current || controller.signal.aborted) return;
      if (result.status !== "arithmetic_workpaper_only" || result.basis.organization_id !== Number(org) || result.basis.month !== month || result.posting_available || result.statutory_payroll_certified) throw new Error("Расчёт имеет неожиданный статус или область данных.");
      setPreview(result); setPreviewCommand(command); setReviewLoading(true);
      try {
        const summary = await request<ReviewSummary>(`/organizations/${encodeURIComponent(org)}/periods/${month}/payroll-arithmetic-summary`, controller.signal);
        if (token !== generation.current || controller.signal.aborted) return;
        if (summary.status !== "arithmetic_reviews_aggregate_only" || summary.organization_id !== Number(org) || summary.month !== month) throw new Error("История проверок относится к другой бухгалтерской книге.");
        const segment = summary.bindings.find((row) => row.employment_binding_id === command.employment_binding_id)?.segments.find((row) => row.work_from === command.work_from && row.work_to === command.work_to);
        setLatestReview(segment ?? null);
      } catch (cause) { if (token === generation.current && !controller.signal.aborted) setReviewError(`История проверок: ${errorText(cause)}`); }
      finally { if (token === generation.current) setReviewLoading(false); }
    } catch (cause) { if (token === generation.current && !controller.signal.aborted) setError(errorText(cause)); }
    finally { if (token === generation.current) setBusy(false); }
  }

  function uploaded(receipt: PayrollEvidenceReceipt) {
    if (receipt.organization_id !== Number(org) || receipt.employment_binding_id !== Number(bindingId)) { setFileError("Квитанция относится к другой книге или договору."); return; }
    invalidate(); setFiles((current) => [receipt, ...current.filter((row) => row.file_id !== receipt.file_id)]);
    if (receipt.kind === "employment_contract") setContractId(String(receipt.file_id));
    if (receipt.kind === "timesheet") { setTimesheetId(String(receipt.file_id)); setTimesheetRow(""); }
    if (receipt.kind === "work_schedule") { setScheduleId(String(receipt.file_id)); setScheduleCell(""); setNormEvidence(""); }
  }

  function acceptReview(receipt: ReviewReceipt, command: ReviewCommand) {
    if (receipt.organization_id !== Number(org) || receipt.employment_binding_id !== command.employment_binding_id
        || receipt.month !== month || receipt.work_from !== command.work_from || receipt.work_to !== command.work_to
        || receipt.request_key !== command.request_key || receipt.basis_digest !== command.basis_digest
         || receipt.supersedes_review_id !== (command.supersedes_review_id ?? null)
         || receipt.source_facts_attested_by_chief !== Boolean(command.source_fact_attestation)
         || receipt.fszn_base_classified_by_chief !== Boolean(command.fszn_base_attestation)
        || receipt.status !== "arithmetic_review_only" || receipt.posting_available || receipt.statutory_payroll_certified) {
      throw new Error("Квитанция проверки относится к другому расчёту или имеет неожиданный статус.");
    }
    setReviewReceipt(receipt); setLatestReview({ review_id: receipt.review_id, revision: receipt.revision, work_from: receipt.work_from, work_to: receipt.work_to, basis_digest: receipt.basis_digest, source_facts_attested_by_chief: receipt.source_facts_attested_by_chief, fszn_base_classified_by_chief: receipt.fszn_base_classified_by_chief });
    setPendingReview(null); setReviewError("");
  }

  async function confirmReview() {
    if (reviewing.current || reviewBusy || !access?.can_review || !preview || !previewCommand) return;
    const stored = pendingReview;
    if (!stored && (reviewLoading || reviewError || !preview.rule_source_file_bytes_verified
        || !preview.schedule_file_bytes_verified
         || !preview.contract_and_timesheet_hashes_verified || reviewEvidence.trim().length < 10
         || (sourceFactsChecked && sourceFactEvidence.trim().length < 20)
         || (fsznBaseChecked && (!sourceFactsChecked || fsznBaseEvidence.trim().length < 20 || fsznContractLocator.trim().length < 3))
         || (sameReviewedBasis && !attestationUpgrade))) return;
    const command: ReviewCommand = stored ?? {
      ...previewCommand, request_key: crypto.randomUUID(), basis_digest: preview.basis_digest,
      reviewer_evidence: reviewEvidence.trim(),
      ...(sourceFactsChecked ? { source_fact_attestation: "contract_salary_time_norm_checked" as const, source_fact_evidence: sourceFactEvidence.trim() } : {}),
      ...(fsznBaseChecked ? { fszn_base_attestation: "listed_salary_base_checked" as const, fszn_base_evidence: fsznBaseEvidence.trim(), fszn_base_contract_locator: fsznContractLocator.trim() } : {}),
      ...(latestReview ? { supersedes_review_id: latestReview.review_id } : {}),
    };
    reviewing.current = true; setReviewBusy(true); setReviewError(""); setPendingReview(command);
    const base = `/organizations/${encodeURIComponent(org)}`;
    try {
      try {
        const receipt = await request<ReviewReceipt>(`${base}/periods/${month}/payroll-workpaper-reviews`, new AbortController().signal, command);
        acceptReview(receipt, command);
      } catch (cause) {
        if (cause instanceof WorkpaperError && cause.status !== undefined && cause.status < 500) throw cause;
        try {
          const receipt = await request<ReviewReceipt>(`${base}/payroll-workpaper-reviews/${command.request_key}`, new AbortController().signal);
          acceptReview(receipt, command);
        } catch (lookup) {
          if (lookup instanceof WorkpaperError && lookup.status !== 404) throw lookup;
          if (!(lookup instanceof WorkpaperError)) throw lookup;
          throw new Error("Статус проверки не подтверждён. Повторите запрос с тем же ключом.");
        }
      }
    } catch (cause) {
      if (cause instanceof WorkpaperError && cause.status !== undefined && cause.status < 500 && cause.status !== 408 && cause.status !== 429) {
        setPendingReview(null);
      }
      setReviewError(errorText(cause));
    } finally { reviewing.current = false; setReviewBusy(false); }
  }

  if (!ready) return <section aria-label="Расчётный лист бухгалтера"><p>Выберите юрлицо и месяц.</p></section>;
  return <section aria-label="Расчётный лист бухгалтера" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div><h2 className="text-lg font-semibold">Расчётный лист по документам</h2><p className="text-sm text-muted">{month} · арифметический черновик по выбранному юрлицу. Он не начисляет зарплату, не создаёт проводки и не подтверждает законность ставок.</p></div>
    {loading && <p role="status">Загрузка правил и договоров…</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {!rules && !loading && onOpenRules && <Button variant="secondary" disabled={disabled} onClick={onOpenRules}>Открыть правила расчёта</Button>}
    {access && !access.can_preview && <p role="alert">Для расчёта нужна роль бухгалтера или главбуха в выбранном юрлице.</p>}
    {rules && <div className="rounded-lg border border-line p-3 text-sm"><p>Набор правил № {rules.rule_set_id}, редакция {rules.revision}, действует с {rules.effective_from}.</p><p>Источник: {rules.source_reference} · {rules.source_file_id ? `файл № ${rules.source_file_id}` : "файл источника не привязан; подтверждение главбуха недоступно"}.</p></div>}
    {rules && <label className="block text-sm">Договор работника
      <Select aria-label="Договор работника" value={bindingId} disabled={formLocked} onChange={(event) => { invalidate(); setBindingId(event.target.value); setFiles([]); setFileError(""); setContractId(""); setTimesheetId(""); setTimesheetRow(""); setScheduleId(""); setScheduleCell(""); setNormEvidence(""); setAdjustments({}); setPersonnelCode(""); setPersonnelEvidence(""); setPersonnelError(""); setPersonnelNotice(""); pendingPersonnel.current = null; }}><option value="">Выберите договор</option>{bindings.map((row) => <option key={row.binding_id} value={row.binding_id}>{row.employee_name} · {row.contract_ref} · № {row.binding_id}</option>)}</Select>
    </label>}
    {rules && !bindings.length && <p className="text-sm text-muted">На конец месяца нет известных действующих привязок работников к этому юрлицу. Проверьте реестр договоров.</p>}
    {selectedBinding && <>
      <p className="text-sm">Основание договора: {selectedBinding.source_document}. Для расчёта выберите сохранённые документы этого юрлица.</p>
      {personnelNotice && <p role="status" className="text-sm">{personnelNotice}</p>}
      {!selectedBinding.personnel_identifier && access?.can_review && <div className="space-y-2 rounded-lg border border-line p-3 text-sm">
        <h3 className="font-semibold">Привязать табельный номер</h3>
        <p className="text-muted">Главбух указывает номер из кадрового источника. Создаётся новая редакция договора для выбранного месяца; файлы нужно загрузить к ней заново.</p>
        <div className="grid gap-2 md:grid-cols-2">
          <label>Табельный номер<Input aria-label="Табельный номер работника" value={personnelCode} disabled={formLocked} onChange={(event) => { setPersonnelCode(event.target.value); setPersonnelError(""); }} /></label>
          <label>Где проверен номер<Textarea aria-label="Основание табельного номера" value={personnelEvidence} disabled={formLocked} onChange={(event) => { setPersonnelEvidence(event.target.value); setPersonnelError(""); }} /></label>
        </div>
        {personnelError && <p role="alert" className="text-red-700">{personnelError}</p>}
        <Button variant="secondary" disabled={formLocked || !personnelCode.trim() || personnelEvidence.trim().length < 10} onClick={() => void recordPersonnelIdentifier()}>{personnelBusy ? "Сохранение…" : "Сохранить новую редакцию договора"}</Button>
      </div>}
      {fileError && <p role="alert" className="text-red-700">Источники: {fileError}</p>}
      {access?.can_upload && <AccountingPayrollEvidenceUpload key={`${org}:${month}:${bindingId}`} org={org} month={month} bindingId={selectedBinding.binding_id} contractReference={selectedBinding.source_document} disabled={disabled || busy || pendingReview !== null || reviewBusy} onBusyChange={setUploadBusy} onUploaded={uploaded} />}
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm">Файл договора<Select aria-label="Файл договора" value={contractId} disabled={formLocked} onChange={(event) => { invalidate(); setContractId(event.target.value); }}><option value="">Выберите файл</option>{contractFiles.map((row) => <option key={row.file_id} value={row.file_id}>{row.reference} · #{row.file_id}</option>)}</Select></label>
        <label className="text-sm">Файл табеля<Select aria-label="Файл табеля" value={timesheetId} disabled={formLocked} onChange={(event) => { invalidate(); setTimesheetId(event.target.value); setTimesheetRow(""); }}><option value="">Выберите файл</option>{timesheetFiles.map((row) => <option key={row.file_id} value={row.file_id}>{row.reference} · #{row.file_id}</option>)}</Select></label>
      </div>
      <label className="block text-sm">Файл графика работы и месячной нормы<Select aria-label="Файл графика работы" value={scheduleId} disabled={formLocked} onChange={(event) => { invalidate(); setScheduleId(event.target.value); setScheduleCell(""); setNormEvidence(""); }}><option value="">Выберите файл для подтверждения главбухом</option>{scheduleFiles.map((row) => <option key={row.file_id} value={row.file_id}>{row.reference} · #{row.file_id}</option>)}</Select></label>
      {selectedContract && <a className="text-sm text-accent underline" href={`/api/accounting/organizations/${encodeURIComponent(org)}/payroll-evidence-files/${selectedContract.file_id}/download`} target="_blank" rel="noreferrer">Скачать выбранный договор</a>}
      {selectedTimesheet && <a className="ml-3 text-sm text-accent underline" href={`/api/accounting/organizations/${encodeURIComponent(org)}/payroll-evidence-files/${selectedTimesheet.file_id}/download`} target="_blank" rel="noreferrer">Скачать выбранный табель</a>}
      {selectedTimesheet && !needsXlsxCheck && <p className="text-sm text-muted">Содержание этого табеля проверяется бухгалтером вручную; структура XLSX не проверялась.</p>}
      {timesheetCheck?.status === "structure_checked" && selectedBinding && !selectedBinding.personnel_identifier && <p role="alert" className="text-sm text-red-700">Для расчёта по XLSX главбух должен указать табельный номер в новой редакции привязки договора к юрлицу.</p>}
      {needsXlsxCheck && !timesheetCheck && !timesheetCheckError && <p className="text-sm">Проверяем структуру XLSX…</p>}
      {timesheetCheckError && <p role="alert" className="text-sm text-red-700">Проверка XLSX недоступна: {timesheetCheckError}. Подтверждение арифметики заблокировано.</p>}
      {timesheetCheck?.status === "structure_checked" && <p role="status" className="text-sm">Структура XLSX согласована. Содержание кодов и привязка строки к договору остаются на проверке бухгалтера.</p>}
      {timesheetCheck?.status === "structure_checked" && <label className="block text-sm">Строка работника в XLSX<Select aria-label="Строка работника в XLSX" value={timesheetRow} disabled={formLocked} onChange={(event) => { invalidate(); setTimesheetRow(event.target.value); }}><option value="">Выберите строку из документа</option>{timesheetCheck.employee_row_numbers?.map((row) => <option key={row} value={row}>Строка {row}</option>)}</Select></label>}
      {timesheetCheck && timesheetCheck.status !== "structure_checked" && <div role="alert" className="text-sm text-red-700"><p>Структура XLSX не прошла проверку; подтверждение арифметики заблокировано.</p><ul className="list-disc pl-5">{timesheetCheck.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{timesheetIssue[issue.code] ?? issue.code}{issue.rows.length ? ` · строки ${issue.rows.join(", ")}` : ""}</li>)}</ul></div>}
      <div className="grid gap-3 md:grid-cols-2"><label className="text-sm">Работа с<Input aria-label="Работа с" type="date" value={workFrom} disabled={formLocked} onChange={(event) => { invalidate(); setWorkFrom(event.target.value); }} /></label><label className="text-sm">Работа по<Input aria-label="Работа по" type="date" value={workTo} disabled={formLocked} onChange={(event) => { invalidate(); setWorkTo(event.target.value); }} /></label></div>
      <div className="grid gap-3 md:grid-cols-3"><label className="text-sm">Оклад по договору, BYN<Input aria-label="Оклад по договору" inputMode="decimal" value={salary} disabled={formLocked} onChange={(event) => { invalidate(); setSalary(event.target.value); }} placeholder="Из договора, 0.00" /></label><label className="text-sm">Норма часов<Input aria-label="Норма часов" inputMode="decimal" value={normHours} disabled={formLocked} onChange={(event) => { invalidate(); setNormHours(event.target.value); }} placeholder="Из утверждённого графика" /></label><label className="text-sm">Отработано часов<Input aria-label="Отработано часов" inputMode="decimal" value={workedHours} disabled={formLocked} onChange={(event) => { invalidate(); setWorkedHours(event.target.value); }} placeholder="Из табеля" /></label></div>
      <div className="grid gap-3 md:grid-cols-2"><label className="text-sm">Где в договоре указан оклад<Textarea aria-label="Основание оклада" value={contractEvidence} disabled={formLocked} onChange={(event) => { invalidate(); setContractEvidence(event.target.value); }} /></label><label className="text-sm">Где в табеле указаны часы<Textarea aria-label="Основание часов" value={timesheetEvidence} disabled={formLocked} onChange={(event) => { invalidate(); setTimesheetEvidence(event.target.value); }} /></label></div>
      {selectedSchedule && <label className="block text-sm">Где в графике указана месячная норма<Textarea aria-label="Основание нормы часов" value={normEvidence} disabled={formLocked} onChange={(event) => { invalidate(); setNormEvidence(event.target.value); }} /></label>}
      {needsXlsxScheduleCell && <label className="block text-sm">Ячейка нормы в XLSX-графике за {month}<Input aria-label="Ячейка нормы XLSX" value={scheduleCell} disabled={formLocked} onChange={(event) => { invalidate(); setScheduleCell(event.target.value.toUpperCase()); }} placeholder="Например B5" /></label>}
      <div className="space-y-2"><h3 className="font-semibold">Ставки выбранной редакции</h3>{rules?.rate_rules.map((rule) => <div key={rule.code} className="rounded-lg border border-line p-3 text-sm"><p><strong>{rule.code}</strong> · {rule.role === "employee_deduction" ? "удержание" : "взнос работодателя"} · {rule.base_mode === "gross" ? "база: начислено" : "база: начислено минус документированная корректировка"}</p>{rule.base_mode === "gross_less_adjustment" && <div className="mt-2 grid gap-2 md:grid-cols-3"><label>Корректировка, BYN<Input aria-label={`Корректировка ${rule.code}`} inputMode="decimal" value={adjustments[rule.code]?.amount ?? ""} disabled={formLocked} onChange={(event) => { invalidate(); setAdjustments((previous) => ({ ...previous, [rule.code]: { ...previous[rule.code], amount: event.target.value, fileId: previous[rule.code]?.fileId ?? "", evidence: previous[rule.code]?.evidence ?? "" } })); }} /></label><label>Файл основания<Select aria-label={`Файл корректировки ${rule.code}`} value={adjustments[rule.code]?.fileId ?? ""} disabled={formLocked} onChange={(event) => { invalidate(); setAdjustments((previous) => ({ ...previous, [rule.code]: { ...previous[rule.code], amount: previous[rule.code]?.amount ?? "", fileId: event.target.value, evidence: previous[rule.code]?.evidence ?? "" } })); }}><option value="">Выберите файл</option>{adjustmentFiles.map((row) => <option key={row.file_id} value={row.file_id}>{row.reference} · #{row.file_id}</option>)}</Select></label><label>Пояснение<Textarea aria-label={`Основание корректировки ${rule.code}`} value={adjustments[rule.code]?.evidence ?? ""} disabled={formLocked} onChange={(event) => { invalidate(); setAdjustments((previous) => ({ ...previous, [rule.code]: { ...previous[rule.code], amount: previous[rule.code]?.amount ?? "", fileId: previous[rule.code]?.fileId ?? "", evidence: event.target.value } })); }} /></label></div>}</div>)}</div>
      <Button disabled={formLocked || !access?.can_preview || !selectedContract || !selectedTimesheet || (needsXlsxCheck && (!timesheetCheck || (timesheetCheck.status === "structure_checked" && (!selectedBinding?.personnel_identifier || !timesheetCheck.employee_row_numbers?.includes(Number(timesheetRow))))))} onClick={() => void calculate()}>{busy ? "Расчёт…" : "Проверить арифметику"}</Button>
    </>}
    {preview && <div className="space-y-3 rounded-lg border border-accent p-4"><h3 className="font-semibold">Предварительный результат</h3><p className="text-sm">{preview.basis.employee_name}, {preview.basis.work_from}–{preview.basis.work_to}. Файлы договора и табеля {preview.contract_and_timesheet_hashes_verified ? "сверены по байтам" : "не сверены"}; источник набора правил {preview.rule_source_file_bytes_verified ? "сверен по байтам" : "не сверен по байтам"}.</p>{preview.timesheet_numeric_hours_verified && <p className="text-sm">Числовые часы проверены по строке {preview.basis.timesheet_row} и отрезку работы. {(preview.timesheet_name_matches_binding && preview.timesheet_identifier_matches_binding) ? "ФИО и табельный номер строки совпали с привязкой договора; подлинность источника подтверждает бухгалтер." : "ФИО и табельный номер строки не сверены с привязкой договора."} Текстовые коды в {preview.basis.timesheet_uninterpreted_code_days ?? 0} днях не интерпретированы; соответствие строки договору подтверждает бухгалтер.</p>}<dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{[["Начислено", preview.gross_byn], ["Указанные удержания", preview.listed_employee_deductions_byn], ["После указанных удержаний", preview.after_listed_deductions_byn], ["Указанные взносы работодателя", preview.listed_employer_contributions_byn], ["Стоимость с указанными взносами", preview.cost_including_listed_contributions_byn]].map(([label, amount]) => <div key={label} className="rounded-lg bg-canvas p-2"><dt className="text-xs text-muted">{label}</dt><dd className="font-semibold tabular-nums">{amount} BYN</dd></div>)}</dl><div className="text-sm">{preview.basis.components.map((row) => <p key={row.rate_code}>{row.rate_code}: {row.base_byn} × {row.rate_value}% = {row.amount_byn} BYN</p>)}</div><p className="break-all text-xs text-muted">Отпечаток расчёта: {preview.basis_digest}</p><p className="text-sm font-medium">Это не сумма зарплаты к выплате и не подтверждённый расчёт. Для принятия нужна отдельная проверка главбуха, затем сверка с источниками начислений и проводками.</p></div>}
    {preview && <p className="text-sm" role="status">График месячной нормы {preview.schedule_numeric_hours_verified ? `сверен по ячейке ${preview.basis.work_schedule_cell}; подлинность и применимость графика подтверждает бухгалтер` : preview.schedule_file_bytes_verified ? "сверен по байтам; число часов в документе подтверждает бухгалтер" : "не привязан; подтверждение арифметики недоступно"}.</p>}
    {preview && access?.can_review && <div className="space-y-3 rounded-lg border border-line p-4" aria-label="Проверка главбуха">
      <h3 className="font-semibold">Проверка арифметики главбухом</h3>
      <p className="text-sm text-muted">Проверка сохранит отдельную неизменяемую квитанцию. Она не начисляет зарплату и не подтверждает полноту налоговых правил.</p>
      {reviewLoading && <p role="status">Проверка предыдущих редакций…</p>}
      {reviewError && <p role="alert" className="text-red-700">{reviewError}</p>}
      {!preview.rule_source_file_bytes_verified && <p role="status">Для проверки привяжите сохранённый файл политики к действующему набору правил.</p>}
      {!preview.schedule_file_bytes_verified && <p role="status">Для проверки приложите график работы с месячной нормой и укажите место нормы в документе.</p>}
      {latestReview?.basis_digest === preview.basis_digest && <p role="status">Эта арифметика уже рассмотрена: квитанция № {latestReview.review_id}, редакция {latestReview.revision}. {latestReview.source_facts_attested_by_chief ? "Исходные данные подтверждены главбухом." : "Исходные данные отдельно не подтверждены."} {latestReview.fszn_base_classified_by_chief ? "Состав показанной базы ФСЗН отдельно проверен." : "Состав показанной базы ФСЗН не подтверждён."}</p>}
      {latestReview && latestReview.basis_digest !== preview.basis_digest && <p className="text-sm">Исправление квитанции № {latestReview.review_id}; прежняя редакция сохранится в истории.</p>}
      {(!latestReview || latestReview.basis_digest !== preview.basis_digest || !latestReview.source_facts_attested_by_chief || (hasFsznRate && !latestReview.fszn_base_classified_by_chief)) && <>
        <label className="block text-sm">Что именно проверено в документах<Textarea aria-label="Основание проверки главбуха" value={reviewEvidence} disabled={formLocked} onChange={(event) => setReviewEvidence(event.target.value)} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" aria-label="Подтверждаю исходные данные" checked={sourceFactsChecked} disabled={formLocked} onChange={(event) => setSourceFactsChecked(event.target.checked)} />Я сверил оклад с договором, отработанные часы с табелем и месячную норму с графиком.</label>
        {sourceFactsChecked && <label className="block text-sm">Где проверены исходные данные<Textarea aria-label="Основание подтверждения исходных данных" value={sourceFactEvidence} disabled={formLocked} onChange={(event) => setSourceFactEvidence(event.target.value)} /></label>}
        {hasFsznRate && <label className="flex items-start gap-2 text-sm"><input type="checkbox" aria-label="Подтверждаю состав базы ФСЗН" checked={fsznBaseChecked} disabled={formLocked || !sourceFactsChecked} onChange={(event) => setFsznBaseChecked(event.target.checked)} />Я отдельно сверил включённый оклад и документированные исключения из показанной базы ФСЗН.</label>}
        {hasFsznRate && fsznBaseChecked && <div className="grid gap-2 md:grid-cols-2"><label className="text-sm">Место оклада в договоре<Input aria-label="Место оклада для базы ФСЗН" value={fsznContractLocator} disabled={formLocked} onChange={(event) => setFsznContractLocator(event.target.value)} /></label><label className="text-sm">Состав и основания исключений<Textarea aria-label="Основание состава базы ФСЗН" value={fsznBaseEvidence} disabled={formLocked} onChange={(event) => setFsznBaseEvidence(event.target.value)} /></label></div>}
        <p className="text-xs text-muted">Это подтверждение фактов главбухом; оно не заменяет проверку применимости ставок и обязательной отчётности. В новой редакции подтверждение не переносится автоматически.</p>
        <Button disabled={disabled || reviewBusy || reviewLoading || (needsXlsxCheck && timesheetCheck?.status !== "structure_checked") || (!pendingReview && (!preview.rule_source_file_bytes_verified || !preview.schedule_file_bytes_verified || !preview.contract_and_timesheet_hashes_verified || !!reviewError || reviewEvidence.trim().length < 10 || (sourceFactsChecked && sourceFactEvidence.trim().length < 20) || (fsznBaseChecked && (!sourceFactsChecked || fsznBaseEvidence.trim().length < 20 || fsznContractLocator.trim().length < 3)) || (sameReviewedBasis && !attestationUpgrade)))} onClick={() => void confirmReview()}>{pendingReview ? "Проверить или повторить подтверждение" : latestReview ? "Подтвердить исправление" : "Подтвердить арифметику"}</Button>
      </>}
      {pendingReview && <p className="break-all text-xs text-muted">Ключ подтверждения: {pendingReview.request_key}. Ввод заблокирован до получения квитанции.</p>}
      {reviewReceipt && <p role="status">Квитанция № {reviewReceipt.review_id}, редакция {reviewReceipt.revision}, сохранена без проводок.</p>}
    </div>}
  </section>;
}
