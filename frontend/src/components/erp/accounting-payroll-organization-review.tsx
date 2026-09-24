"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";
import { AccountingPayrollEvidenceUpload, type PayrollEvidenceReceipt } from "./accounting-payroll-evidence-upload";

const ruleLabels = {
  period_fszn_rules_and_limits: "Правила и ограничения взносов ФСЗН за период",
  period_income_tax_withholding_rule: "Правило удержания подоходного налога за период",
  period_work_injury_insurance_tariff: "Тариф страхования от несчастных случаев для организации",
} as const;
type RuleCode = keyof typeof ruleLabels;
type Decision = "applicable" | "not_applicable" | "unresolved";
const ruleCodes = Object.keys(ruleLabels).sort() as RuleCode[];
const decisions: { value: Decision; label: string }[] = [
  { value: "applicable", label: "Применяется" },
  { value: "not_applicable", label: "Не применяется" },
  { value: "unresolved", label: "Не удалось определить" },
];

type WageSource = { reference_wage_month: string; reference_wage_byn: string; reference_wage_published_on: string; reference_wage_url: string };
type Fact = { code: RuleCode; decision: Decision; finding: string; source_locator: string } & Partial<WageSource>;
type DraftFact = { decision: Decision | ""; finding: string; source_locator: string } & WageSource;
type FileReceipt = Pick<PayrollEvidenceReceipt, "file_id" | "organization_id" | "employment_binding_id" | "kind" | "month" | "reference" | "sha256">;
type ReviewReceipt = {
  review_id: number;
  organization_id: number;
  month: string;
  revision: number;
  supersedes_id: number | null;
  source_file_id: number;
  source_document: string;
  facts: Fact[];
  evidence: string;
  request_key: string;
  digest: string;
  source_file_bytes_verified_now: boolean;
  statutory_payroll_certified: false;
  posting_available: false;
};
type ReviewCommand = {
  request_key: string;
  source_file_id: number;
  source_document: string;
  facts: Fact[];
  evidence: string;
  supersedes_id: number | null;
};
type Access = { organization_id: number; can_review: boolean; can_upload?: boolean };
type Props = { org: string; month: string; onReviewed: () => void };

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

function blankFacts(): Record<RuleCode, DraftFact> {
  return Object.fromEntries(ruleCodes.map((code) => [code, { decision: "", finding: "", source_locator: "", reference_wage_month: "", reference_wage_byn: "", reference_wage_published_on: "", reference_wage_url: "" }])) as Record<RuleCode, DraftFact>;
}

function precedingMonth(month: string) {
  const [year, number] = month.split("-").map(Number);
  return new Date(Date.UTC(year, number - 2, 1)).toISOString().slice(0, 7);
}

function fixedMoney(value: string) {
  if (!/^\d{1,17}(?:\.\d{1,2})?$/.test(value) || /^0+(?:\.0+)?$/.test(value)) return null;
  const [whole, cents = ""] = value.split(".");
  return `${BigInt(whole)}.${cents.padEnd(2, "0")}`;
}

function validFile(row: FileReceipt, org: string, month: string) {
  return row.organization_id === Number(org) && row.employment_binding_id === null
    && row.kind === "payroll_organization_rule" && row.month === month
    && Number.isInteger(row.file_id) && row.file_id > 0
    && typeof row.reference === "string" && row.reference.trim().length > 0
    && /^[a-f0-9]{64}$/.test(row.sha256);
}

function validFacts(facts: Fact[], month: string) {
  return Array.isArray(facts) && facts.length >= 1 && facts.length <= ruleCodes.length
    && facts.every((fact, index) => ruleCodes.includes(fact.code)
      && (index === 0 || facts[index - 1].code < fact.code)
      && decisions.some((decision) => decision.value === fact.decision)
      && typeof fact.finding === "string" && fact.finding.trim().length >= 10
      && typeof fact.source_locator === "string" && fact.source_locator.trim().length >= 3
      && (fact.reference_wage_byn === undefined || (fact.code === "period_fszn_rules_and_limits"
        && fact.decision === "applicable" && fact.reference_wage_month === precedingMonth(month)
        && fixedMoney(fact.reference_wage_byn) === fact.reference_wage_byn
        && /^\d{4}-\d{2}-\d{2}$/.test(fact.reference_wage_published_on ?? "")
        && /^https:\/\/(?:www\.)?belstat\.gov\.by\/[^\s#]+$/.test(fact.reference_wage_url ?? "")))
      && (fact.reference_wage_byn !== undefined || [fact.reference_wage_month, fact.reference_wage_published_on, fact.reference_wage_url].every((field) => field === undefined)));
}

function validReview(receipt: ReviewReceipt, org: string, month: string, files: FileReceipt[], sourceVerifiedNow: boolean) {
  const source = files.find((file) => file.file_id === receipt.source_file_id);
  return receipt.organization_id === Number(org) && receipt.month === month
    && Number.isInteger(receipt.review_id) && receipt.review_id > 0
    && Number.isInteger(receipt.revision) && receipt.revision > 0
    && (receipt.supersedes_id === null || (Number.isInteger(receipt.supersedes_id) && receipt.supersedes_id > 0))
    && !!source && receipt.source_document === source.reference
    && typeof receipt.evidence === "string" && receipt.evidence.trim().length >= 10
    && typeof receipt.request_key === "string" && receipt.request_key.length > 0
    && /^[a-f0-9]{64}$/.test(receipt.digest)
    && receipt.source_file_bytes_verified_now === sourceVerifiedNow
    && receipt.statutory_payroll_certified === false && receipt.posting_available === false
    && validFacts(receipt.facts, month);
}

function factDraft(facts: Fact[]): Record<RuleCode, DraftFact> {
  const draft = blankFacts();
  for (const fact of facts) draft[fact.code] = { decision: fact.decision, finding: fact.finding, source_locator: fact.source_locator,
    reference_wage_month: fact.reference_wage_month ?? "", reference_wage_byn: fact.reference_wage_byn ?? "",
    reference_wage_published_on: fact.reference_wage_published_on ?? "", reference_wage_url: fact.reference_wage_url ?? "" };
  return draft;
}

export function AccountingPayrollOrganizationReview({ org, month, onReviewed }: Props) {
  const [access, setAccess] = useState<Access | null>(null);
  const [files, setFiles] = useState<FileReceipt[]>([]);
  const [fileId, setFileId] = useState("");
  const [latest, setLatest] = useState<ReviewReceipt | null>(null);
  const [facts, setFacts] = useState(blankFacts);
  const [evidence, setEvidence] = useState("");
  const [requestLoading, setRequestLoading] = useState(true);
  const [loadedScope, setLoadedScope] = useState("");
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<ReviewCommand | null>(null);
  const submitting = useRef(false);
  const scope = `/organizations/${encodeURIComponent(org)}`;
  const validScope = /^\d+$/.test(org) && Number(org) > 0 && /^\d{4}-(0[1-9]|1[0-2])$/.test(month);
  const loading = requestLoading || loadedScope !== `${org}:${month}`;
  const selectedFile = files.find((row) => String(row.file_id) === fileId);

  useEffect(() => {
    const controller = new AbortController();
    if (!validScope) return () => controller.abort();
    void Promise.all([
      api<Access>(`${scope}/payroll-workpaper-access`, undefined, controller.signal),
      api<FileReceipt[]>(`${scope}/payroll-evidence-files?month=${encodeURIComponent(month)}&kind=payroll_organization_rule`, undefined, controller.signal),
      api<ReviewReceipt>(`${scope}/periods/${encodeURIComponent(month)}/payroll-organization-reviews/current`, undefined, controller.signal)
        .catch((cause: unknown) => cause instanceof ReviewError && cause.status === 404 ? null : Promise.reject(cause)),
    ]).then(([newAccess, newFiles, review]) => {
      if (controller.signal.aborted) return;
      if (newAccess.organization_id !== Number(org) || typeof newAccess.can_review !== "boolean"
          || !Array.isArray(newFiles) || newFiles.some((row) => !validFile(row, org, month))
          || (review && !validReview(review, org, month, newFiles, true))) {
        throw new ReviewError("Ответ относится к другому юридическому лицу, месяцу или файлу.");
      }
      setAccess(newAccess); setFiles(newFiles); setLatest(review);
      if (review) {
        setFileId(String(review.source_file_id)); setFacts(factDraft(review.facts)); setEvidence(review.evidence);
      } else {
        setFileId(""); setFacts(blankFacts()); setEvidence("");
      }
      setError(""); setLoadedScope(`${org}:${month}`); setRequestLoading(false);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "Не удалось загрузить обзор правил организации.");
        setAccess(null);
        setLoadedScope(`${org}:${month}`); setRequestLoading(false);
      }
    });
    return () => controller.abort();
  }, [month, org, reload, scope, validScope]);

  function changeFact(code: RuleCode, patch: Partial<DraftFact>) {
    setFacts((previous) => ({ ...previous, [code]: { ...previous[code], ...patch } }));
    setError("");
  }

  function buildCommand(): ReviewCommand {
    if (!selectedFile || !validFile(selectedFile, org, month)) throw new Error("Выберите сохранённый файл правил для этого юрлица и месяца.");
    const selectedFacts: Fact[] = [];
    for (const code of ruleCodes) {
      const fact = facts[code];
      const anyField = [fact.decision, fact.finding, fact.source_locator,
        fact.reference_wage_month, fact.reference_wage_byn,
        fact.reference_wage_published_on, fact.reference_wage_url].some((value) => value.trim().length > 0);
      if (!anyField) continue;
      if (!fact.decision || fact.finding.trim().length < 10 || fact.source_locator.trim().length < 3) {
        throw new Error("Для каждого выбранного правила укажите решение, вывод и точное место в документе.");
      }
      const row: Fact = { code, decision: fact.decision, finding: fact.finding.trim(), source_locator: fact.source_locator.trim() };
      if (code === "period_fszn_rules_and_limits") {
        const wageFields = [fact.reference_wage_month, fact.reference_wage_byn,
          fact.reference_wage_published_on, fact.reference_wage_url];
        if (wageFields.some(Boolean)) {
          const amount = fixedMoney(fact.reference_wage_byn.trim());
          if (fact.decision !== "applicable" || fact.reference_wage_month !== precedingMonth(month)
              || !amount || !/^\d{4}-\d{2}-\d{2}$/.test(fact.reference_wage_published_on)
              || !/^https:\/\/(?:www\.)?belstat\.gov\.by\/[^\s#]+$/.test(fact.reference_wage_url.trim())) {
            throw new Error("Для предварительного предела ФСЗН укажите среднюю зарплату именно предыдущего месяца, дату и официальный источник Белстата.");
          }
          Object.assign(row, { reference_wage_month: fact.reference_wage_month,
            reference_wage_byn: amount, reference_wage_published_on: fact.reference_wage_published_on,
            reference_wage_url: fact.reference_wage_url.trim() });
        }
      }
      selectedFacts.push(row);
    }
    if (selectedFacts.length === 0) throw new Error("Выберите хотя бы одно правило для обзора.");
    if (evidence.trim().length < 10) throw new Error("Укажите пояснение проверки главбуха не короче 10 символов.");
    return {
      request_key: crypto.randomUUID(), source_file_id: selectedFile.file_id,
      source_document: selectedFile.reference, facts: selectedFacts,
      evidence: evidence.trim(), supersedes_id: latest?.review_id ?? null,
    };
  }

  function accept(receipt: ReviewReceipt, sent: ReviewCommand) {
    if (!validReview(receipt, org, month, files, false)
        || receipt.source_file_id !== sent.source_file_id
        || receipt.source_document !== sent.source_document
        || receipt.evidence !== sent.evidence
        || JSON.stringify(receipt.facts) !== JSON.stringify(sent.facts)
        || receipt.request_key !== sent.request_key
        || receipt.supersedes_id !== sent.supersedes_id
        || receipt.revision !== (latest?.revision ?? 0) + 1) {
      throw new ReviewError("Квитанция обзора не совпадает с сохранённым запросом.");
    }
    setPending(null); setNotice(`Квитанция № ${receipt.review_id}, редакция ${receipt.revision} сохранена; расчёт и проводки не созданы.`);
    setRequestLoading(true); setReload((value) => value + 1); onReviewed();
  }

  async function submit() {
    if (submitting.current || busy || loading || !access?.can_review) return;
    submitting.current = true; setBusy(true); setError(""); setNotice("");
    let sent = pending;
    let rejectedPost = false;
    try {
      if (!sent) { sent = buildCommand(); setPending(sent); }
      const endpoint = `${scope}/periods/${encodeURIComponent(month)}/payroll-organization-reviews`;
      try {
        accept(await api<ReviewReceipt>(endpoint, sent), sent);
      } catch (cause) {
        if (cause instanceof ReviewError && cause.status !== undefined
            && cause.status < 500 && cause.status !== 408 && cause.status !== 429) {
          rejectedPost = true; throw cause;
        }
        try {
          const receipt = await api<ReviewReceipt>(`${scope}/payroll-organization-reviews/by-request/${encodeURIComponent(sent.request_key)}`);
          accept(receipt, sent);
        } catch (lookupError) {
          if (lookupError instanceof ReviewError && lookupError.status !== 404) throw lookupError;
          throw new Error("Результат неизвестен. Повторите тот же сохранённый запрос с прежним ключом.");
        }
      }
    } catch (cause) {
      if (rejectedPost) setPending(null);
      setError(cause instanceof Error ? cause.message : "Обзор не сохранён.");
    } finally { submitting.current = false; setBusy(false); }
  }

  function uploaded(receipt: PayrollEvidenceReceipt) {
    if (!validFile(receipt, org, month)) { setError("Квитанция файла относится к другому юрлицу, месяцу или виду документа."); return; }
    setFiles((previous) => [receipt, ...previous.filter((row) => row.file_id !== receipt.file_id)]);
    setFileId(String(receipt.file_id)); setError("");
  }

  const locked = busy || loading || uploading || pending !== null;
  return <section aria-label="Проверка применимости правил организации" className="space-y-3 rounded-lg border border-line p-3 text-sm">
    <h3 className="font-semibold">Фактический обзор правил организации · {month}</h3>
    <p className="text-muted">Главбух фиксирует применимость правил по документу за выбранный месяц и точные места в источнике. Это фактический обзор: он не подтверждает полноту законодательства и не сертифицирует расчёт зарплаты.</p>
    <p className="text-muted">Обзор не рассчитывает ставки или суммы, не создаёт платежи и проводки. Удержания и взносы остаются неподтверждёнными до отдельной нормативной проверки.</p>
    {!validScope && <p role="alert" className="text-red-700">Выберите юридическое лицо и корректный месяц.</p>}
    {validScope && loading && <p role="status">Загрузка правил организации…</p>}
    {validScope && !loading && error && <p role="alert" className="text-red-700">{error}</p>}
    {validScope && !loading && access && !access.can_review && <p>Сохранить обзор может только главный бухгалтер.</p>}
    {validScope && !loading && access?.can_review && <>
      {latest && <p>Текущая редакция № {latest.revision}, квитанция № {latest.review_id}. Исправление создаст новую редакцию; предыдущая останется в истории.</p>}
      <AccountingPayrollEvidenceUpload key={`${org}:${month}`} org={org} month={month} organizationRuleOnly disabled={locked || access.can_upload === false} onUploaded={uploaded} onBusyChange={setUploading} />
      <label className="block">Файл правил<Select aria-label="Файл правил организации для обзора" value={fileId} disabled={locked} onChange={(event) => setFileId(event.target.value)}>
        <option value="">Выберите сохранённый файл</option>
        {files.map((row) => <option key={row.file_id} value={row.file_id}>{row.reference} · № {row.file_id}</option>)}
      </Select></label>
      {files.length === 0 && <p className="text-muted">Сначала загрузите файл правил для этого юридического лица и месяца.</p>}
      <div className="space-y-2">{ruleCodes.map((code) => <div key={code} className="space-y-2 rounded border border-line p-2">
        <label className="block">{ruleLabels[code]}<Select aria-label={`Решение ${code}`} value={facts[code].decision} disabled={locked} onChange={(event) => changeFact(code, { decision: event.target.value as Decision | "" })}>
          <option value="">Выберите решение</option>{decisions.map((decision) => <option key={decision.value} value={decision.value}>{decision.label}</option>)}
        </Select></label>
        <label className="block">Фактический вывод по документу<Textarea aria-label={`Вывод ${code}`} value={facts[code].finding} disabled={locked} onChange={(event) => changeFact(code, { finding: event.target.value })} /></label>
        <label className="block">Точный источник: страница, пункт или строка<Input aria-label={`Место ${code}`} value={facts[code].source_locator} disabled={locked} onChange={(event) => changeFact(code, { source_locator: event.target.value })} /></label>
        {code === "period_fszn_rules_and_limits" && <div className="grid gap-2 md:grid-cols-2">
          <p className="text-xs text-muted md:col-span-2">Необязательная справка о месячном пределе: загрузите в выбранный файл официальный источник Белстата. Значение и применимость подтверждает главбух; ERP сверяет байты файла, но не извлекает из него показатель.</p>
          <label>Месяц средней зарплаты<Input aria-label="Месяц средней зарплаты Белстата" type="month" value={facts[code].reference_wage_month} disabled={locked} onChange={(event) => changeFact(code, { reference_wage_month: event.target.value })} /></label>
          <label>Средняя зарплата, BYN<Input aria-label="Средняя зарплата Белстата BYN" inputMode="decimal" value={facts[code].reference_wage_byn} disabled={locked} onChange={(event) => changeFact(code, { reference_wage_byn: event.target.value })} /></label>
          <label>Дата публикации<Input aria-label="Дата публикации Белстата" type="date" value={facts[code].reference_wage_published_on} disabled={locked} onChange={(event) => changeFact(code, { reference_wage_published_on: event.target.value })} /></label>
          <label>Официальная ссылка<Input aria-label="Ссылка на источник Белстата" value={facts[code].reference_wage_url} disabled={locked} onChange={(event) => changeFact(code, { reference_wage_url: event.target.value })} /></label>
        </div>}
      </div>)}</div>
      <label className="block">Пояснение проверки главбуха<Textarea aria-label="Пояснение проверки правил организации" value={evidence} disabled={locked} onChange={(event) => setEvidence(event.target.value)} /></label>
      <Button disabled={busy || loading || uploading || (!pending && !selectedFile)} onClick={() => void submit()}>{pending ? "Проверить или повторить сохранение" : latest ? "Сохранить исправление обзора" : "Сохранить фактический обзор"}</Button>
      {pending && <p className="break-all text-xs text-muted">Ключ запроса: {pending.request_key}. Ввод заблокирован до подтверждения результата.</p>}
    </>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
