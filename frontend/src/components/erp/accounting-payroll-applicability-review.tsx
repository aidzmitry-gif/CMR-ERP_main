"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";
import { AccountingPayrollEvidenceUpload, type PayrollEvidenceReceipt } from "./accounting-payroll-evidence-upload";

const factLabels: Record<string, string> = {
  income_kind_and_tax_agent_treatment: "Вид дохода и действия налогового агента",
  year_to_date_taxable_income: "Облагаемый доход с начала года",
  main_workplace_and_deduction_basis: "Основное место работы и стандартный вычет",
  dependants_special_status_and_deduction_documents: "Иждивенцы, особый статус и документы",
  other_deduction_claims_and_documents: "Другие заявленные вычеты и документы",
  insurance_applicability_and_base: "Страховой статус и база",
};
const factCodes = Object.keys(factLabels).sort();
type Fact = { code: string; finding: string; source_locator: string };
type FileReceipt = Pick<PayrollEvidenceReceipt, "file_id" | "organization_id" | "employment_binding_id" | "kind" | "month" | "reference" | "sha256">;
type ReviewReceipt = {
  review_id: number; organization_id: number; employment_binding_id: number; month: string;
  revision: number; supersedes_id: number | null; source_file_id: number; source_document: string;
  facts: Fact[]; evidence: string; request_key: string; digest: string;
  source_file_bytes_verified_now: boolean; statutory_payroll_certified: false; posting_available: false;
};
type ReviewCommand = {
  request_key: string; employment_binding_id: number; source_file_id: number;
  source_document: string; facts: Fact[]; evidence: string; supersedes_id: number | null;
};
type Access = { organization_id: number; can_review: boolean };
type Props = { org: string; month: string; bindingIds: number[]; onReviewed: () => void };

class ReviewError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store", signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data && typeof data.detail === "string" ? data.detail : null;
    throw new ReviewError(detail ?? `Бухгалтерия вернула ошибку ${response.status}.`, response.status);
  }
  if (data === null) throw new ReviewError("Бухгалтерия вернула некорректный ответ.");
  return data as T;
}

function asFactMap(facts: Fact[]): Record<string, { selected: boolean; finding: string; source_locator: string }> {
  return Object.fromEntries(factCodes.map((code) => {
    const current = facts.find((row) => row.code === code);
    return [code, { selected: !!current, finding: current?.finding ?? "", source_locator: current?.source_locator ?? "" }];
  }));
}

export function AccountingPayrollApplicabilityReview({ org, month, bindingIds, onReviewed }: Props) {
  const [bindingId, setBindingId] = useState(String(bindingIds[0] ?? ""));
  const [access, setAccess] = useState<Access | null>(null);
  const [files, setFiles] = useState<FileReceipt[]>([]);
  const [fileId, setFileId] = useState("");
  const [latest, setLatest] = useState<ReviewReceipt | null>(null);
  const [facts, setFacts] = useState(asFactMap([]));
  const [evidence, setEvidence] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<ReviewCommand | null>(null);
  const submitting = useRef(false);
  const selectedFile = files.find((row) => String(row.file_id) === fileId);
  const scope = `/organizations/${encodeURIComponent(org)}`;

  useEffect(() => {
    if (!bindingId || !bindingIds.includes(Number(bindingId))) return;
    const controller = new AbortController();
    void Promise.all([
      api<Access>(`${scope}/payroll-workpaper-access`, undefined, controller.signal),
      api<FileReceipt[]>(`${scope}/payroll-evidence-files?employment_binding_id=${bindingId}&month=${month}&kind=payroll_applicability`, undefined, controller.signal),
      api<ReviewReceipt>(`${scope}/periods/${month}/payroll-applicability-reviews/${bindingId}`, undefined, controller.signal)
        .catch((cause: unknown) => cause instanceof ReviewError && cause.status === 404 ? null : Promise.reject(cause)),
    ]).then(([newAccess, newFiles, review]) => {
      if (controller.signal.aborted) return;
      if (newAccess.organization_id !== Number(org)
          || newFiles.some((row) => row.organization_id !== Number(org)
            || row.employment_binding_id !== Number(bindingId)
            || row.month !== month || row.kind !== "payroll_applicability")
          || (review && (review.organization_id !== Number(org)
            || review.employment_binding_id !== Number(bindingId) || review.month !== month
            || review.posting_available !== false || review.statutory_payroll_certified !== false
            || !review.source_file_bytes_verified_now))) {
        throw new ReviewError("Ответ относится к другому юридическому лицу, договору или месяцу.");
      }
      setAccess(newAccess); setFiles(newFiles); setLatest(review);
      setFileId(review ? String(review.source_file_id) : "");
      setFacts(asFactMap(review?.facts ?? [])); setEvidence(""); setLoading(false);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : "Не удалось загрузить проверку."); setLoading(false); }
    });
    return () => controller.abort();
  }, [bindingId, bindingIds, month, org, reload, scope]);

  function changeFact(code: string, patch: Partial<(typeof facts)[string]>) {
    setFacts((previous) => ({ ...previous, [code]: { ...previous[code], ...patch } }));
  }

  function command(): ReviewCommand {
    if (!selectedFile) throw new Error("Выберите сохранённый файл оснований.");
    const selectedFacts = factCodes.filter((code) => facts[code].selected).map((code) => ({
      code, finding: facts[code].finding.trim(), source_locator: facts[code].source_locator.trim(),
    }));
    if (!selectedFacts.length || selectedFacts.some((row) => row.finding.length < 10 || row.source_locator.length < 3)) {
      throw new Error("Укажите вывод и место в документе для каждого отмеченного факта.");
    }
    if (evidence.trim().length < 10) throw new Error("Поясните проверку главбуха не короче 10 символов.");
    return {
      request_key: crypto.randomUUID(), employment_binding_id: Number(bindingId),
      source_file_id: selectedFile.file_id, source_document: selectedFile.reference,
      facts: selectedFacts, evidence: evidence.trim(), supersedes_id: latest?.review_id ?? null,
    };
  }

  function validReceipt(receipt: ReviewReceipt, sent: ReviewCommand) {
    return receipt.organization_id === Number(org) && receipt.month === month
      && receipt.employment_binding_id === sent.employment_binding_id
      && receipt.source_file_id === sent.source_file_id
      && receipt.source_document === sent.source_document
      && receipt.evidence === sent.evidence
      && JSON.stringify(receipt.facts) === JSON.stringify(sent.facts)
      && receipt.request_key === sent.request_key
      && receipt.supersedes_id === sent.supersedes_id
      && receipt.revision === (latest?.revision ?? 0) + 1
      && receipt.posting_available === false && receipt.statutory_payroll_certified === false
      && /^[a-f0-9]{64}$/.test(receipt.digest);
  }

  async function submit() {
    if (submitting.current || busy || loading || !access?.can_review || !bindingId) return;
    submitting.current = true; setBusy(true); setError(""); setNotice("");
    let sent = pending;
    let definitiveRejection = false;
    try {
      if (!sent) { sent = command(); setPending(sent); }
      const endpoint = `${scope}/periods/${month}/payroll-applicability-reviews`;
      let receipt: ReviewReceipt;
      try {
        receipt = await api<ReviewReceipt>(endpoint, sent);
      } catch (cause) {
        if (cause instanceof ReviewError && cause.status !== undefined
            && cause.status < 500 && cause.status !== 408 && cause.status !== 429) {
          definitiveRejection = true; throw cause;
        }
        try {
          receipt = await api<ReviewReceipt>(`${scope}/payroll-applicability-reviews/by-request/${sent.request_key}`);
        } catch (lookup) {
          if (lookup instanceof ReviewError && lookup.status !== 404) throw lookup;
          throw new Error("Результат неизвестен. Повторите тот же сохранённый запрос.");
        }
      }
      if (!validReceipt(receipt, sent)) throw new Error("Квитанция проверки не совпадает с запросом.");
      setPending(null); setNotice(`Квитанция № ${receipt.review_id} сохранена; проводки не созданы.`);
      setLoading(true);
      setReload((value) => value + 1); onReviewed();
    } catch (cause) {
      if (definitiveRejection) setPending(null);
      setError(cause instanceof Error ? cause.message : "Проверка не сохранена.");
    } finally { submitting.current = false; setBusy(false); }
  }

  if (!bindingIds.length) return null;
  return <section aria-label="Проверка налоговых условий главбухом" className="space-y-3 rounded-lg border border-line p-3 text-sm">
    <h4 className="font-semibold">Подтверждение фактов сотрудника</h4>
    <p className="text-muted">Главбух фиксирует вывод и точное место в частном документе. Это запись проверки, а не выбор ставки или начисление зарплаты.</p>
    <label className="block">Договор<Select aria-label="Договор налоговых условий" value={bindingId} disabled={busy || pending !== null} onChange={(event) => { setLoading(true); setError(""); setNotice(""); setLatest(null); setFiles([]); setFileId(""); setBindingId(event.target.value); setPending(null); }}>
      {bindingIds.map((id) => <option key={id} value={id}>Договор № {id}</option>)}
    </Select></label>
    {loading && <p role="status">Загрузка оснований…</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {!loading && access?.can_review && <>
      {latest && <p>Текущая редакция № {latest.revision}, квитанция № {latest.review_id}. Исправление создаст новую редакцию; прежняя останется в истории.</p>}
      <AccountingPayrollEvidenceUpload key={`${org}:${month}:${bindingId}`} org={org} month={month} bindingId={Number(bindingId)} applicabilityOnly disabled={busy || pending !== null} onUploaded={(receipt) => {
        setFiles((previous) => [receipt, ...previous]); setFileId(String(receipt.file_id));
      }} />
      <label className="block">Файл оснований<Select aria-label="Файл налоговых условий" value={fileId} disabled={busy || pending !== null} onChange={(event) => setFileId(event.target.value)}>
        <option value="">Выберите сохранённый файл</option>
        {files.map((row) => <option key={row.file_id} value={row.file_id}>{row.reference} · № {row.file_id}</option>)}
      </Select></label>
      <div className="space-y-2">{factCodes.map((code) => <div key={code} className="rounded border border-line p-2">
        <label className="flex items-center gap-2"><input type="checkbox" checked={facts[code].selected} disabled={busy || pending !== null} onChange={(event) => changeFact(code, { selected: event.target.checked })} />{factLabels[code]}</label>
        {facts[code].selected && <div className="mt-2 grid gap-2 md:grid-cols-2"><label>Вывод по документу<Textarea aria-label={`Вывод ${code}`} value={facts[code].finding} disabled={busy || pending !== null} onChange={(event) => changeFact(code, { finding: event.target.value })} /></label><label>Страница, строка или пункт<Input aria-label={`Место ${code}`} value={facts[code].source_locator} disabled={busy || pending !== null} onChange={(event) => changeFact(code, { source_locator: event.target.value })} /></label></div>}
      </div>)}</div>
      <label className="block">Пояснение проверки<Textarea aria-label="Пояснение проверки налоговых условий" value={evidence} disabled={busy || pending !== null} onChange={(event) => setEvidence(event.target.value)} /></label>
      <Button disabled={busy || loading || (!pending && (!selectedFile || evidence.trim().length < 10))} onClick={() => void submit()}>{pending ? "Проверить или повторить сохранение" : latest ? "Сохранить исправление фактов" : "Подтвердить факты"}</Button>
      {pending && <p className="break-all text-xs text-muted">Ключ запроса: {pending.request_key}. Ввод заблокирован до подтверждения результата.</p>}
    </>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
