"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

type Difference = { account: string; dimensions: Record<string, string>; currency: string; off_balance: boolean; presence: string; fields: Record<string, { left: string | null; right: string | null; right_minus_left: string | null }> };
type Protocol = { status: string; reconciliation_ready?: boolean; cutover_ready?: boolean; accepted_by_accountant?: boolean; erp_ledger_verified?: boolean; eligibility_blockers?: string[]; receipt_id?: number; left: { from: string; to: string; sha256: string; status: string; pending_documents?: number }; right: { sha256: string; status: string; pending_documents?: number }; differences: Difference[] };
type Issue = { organization_id: number; issue_id: number; request_key: string; period_from: string; period_to: string; left_digest: string; right_digest: string; difference_count: number; eligibility_blockers: string[]; responsible: string; evidence: string; requires_fresh_comparison: boolean; accepted_by_accountant: boolean; reconciliation_ready: boolean; cutover_ready: boolean; already_queued?: boolean; created_at?: string };
type IssueItem = Difference & { item_id: number; item_key: string; digest: string };
type IssuePage = { organization_id: number; rows: Issue[]; next_after_id: number | null };
type IssueDetail = { organization_id: number; issue: Issue; items: IssueItem[]; next_after_item_id: number | null };
type QueueCommand = { request_key: string; responsible: string; evidence: string; left_base64: string; right_base64: string };

async function encoded(file: File) {
  if (file.size > 2_000_000) throw new Error("Каждый файл должен быть не больше 2 МБ.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
  return btoa(binary);
}

const labels: Record<string, string> = { opening: "Начальное сальдо BYN", debit: "Дебет BYN", credit: "Кредит BYN", closing: "Конечное сальдо BYN", original_opening: "Начальное сальдо в валюте", original_debit: "Дебет в валюте", original_credit: "Кредит в валюте", original_closing: "Конечное сальдо в валюте", quantity_opening: "Начальное количество", quantity_debit: "Приход количества", quantity_credit: "Расход количества", quantity_closing: "Конечное количество" };
const blockers: Record<string, string> = { numeric_differences: "числовые расхождения", reports_not_closed: "периоды не закрыты", pending_documents: "есть непроведённые документы", erp_snapshot_mismatch: "правая ОСВ не совпадает с текущими проводками ERP" };
const reportStatus = (status: string) => status === "preliminary" ? "предварительные данные" : status === "closed_periods" ? "периоды закрыты" : "неизвестный статус";
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const failureDetail = (value: unknown, fallback: string) => isRecord(value) && typeof value.detail === "string" ? value.detail : fallback;
const newKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function" ? crypto.randomUUID() : "";

function assertIssue(value: unknown, org: string, key?: string): Issue {
  if (!isRecord(value) || String(value.organization_id) !== org || !Number.isInteger(value.issue_id) || Number(value.issue_id) <= 0 || typeof value.request_key !== "string" || (key && value.request_key !== key) || typeof value.period_from !== "string" || typeof value.period_to !== "string" || typeof value.left_digest !== "string" || typeof value.right_digest !== "string" || !Number.isInteger(value.difference_count) || Number(value.difference_count) < 0 || !Array.isArray(value.eligibility_blockers) || !value.eligibility_blockers.every((item) => typeof item === "string") || typeof value.responsible !== "string" || typeof value.evidence !== "string" || value.requires_fresh_comparison !== true || value.accepted_by_accountant !== false || value.reconciliation_ready !== false || value.cutover_ready !== false) throw new Error("Сервер не подтвердил сохранение очереди сверки для выбранного юрлица.");
  return value as unknown as Issue;
}

function displayBlockers(values: string[] | undefined) {
  return (values ?? []).map((value) => blockers[value] ?? value).join(", ");
}

export function AccountingReconciliation({ org, start, end }: { org: string; start?: string; end?: string }) {
  const [left, setLeft] = useState<File | null>(null), [right, setRight] = useState<File | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [protocol, setProtocol] = useState<Protocol | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false), [confirmKey, setConfirmKey] = useState("");
  const [evidence, setEvidence] = useState("");
  const [queueBusy, setQueueBusy] = useState(false), [queueRetry, setQueueRetry] = useState(false);
  const [queueKey, setQueueKey] = useState(""), [responsible, setResponsible] = useState(""), [queueEvidence, setQueueEvidence] = useState("");
  const [queueCommand, setQueueCommand] = useState<QueueCommand | null>(null), [queuedIssue, setQueuedIssue] = useState<Issue | null>(null);
  const [issuesBusy, setIssuesBusy] = useState(false), [issues, setIssues] = useState<Issue[]>([]), [nextIssueId, setNextIssueId] = useState<number | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<IssueDetail | null>(null), [detailBusy, setDetailBusy] = useState(false);

  const clear = () => { setProtocol(null); setError(""); setConfirmKey(""); setEvidence(""); setQueueKey(""); setResponsible(""); setQueueEvidence(""); setQueueCommand(null); setQueueRetry(false); setQueuedIssue(null); setSelectedIssue(null); };

  async function compare() {
    if (!org || !left || !right || busy || confirmBusy || queueBusy || queueRetry) return;
    setBusy(true); setError(""); setProtocol(null); setQueuedIssue(null); setSelectedIssue(null);
    try {
      const [left_base64, right_base64] = await Promise.all([encoded(left), encoded(right)]);
      const response = await fetch(`/api/accounting/organizations/${org}/reconciliation`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ left_base64, right_base64 }) });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) throw new Error(failureDetail(result, "Проверьте формат файлов и доступ к книге."));
      if (!isRecord(result) || !Array.isArray(result.differences) || !isRecord(result.left) || !isRecord(result.right)) throw new Error("ERP вернула неполный протокол сверки.");
      const value = result as unknown as Protocol;
      setProtocol(value); setConfirmKey(value.reconciliation_ready ? newKey() : ""); setQueueKey(value.reconciliation_ready ? "" : newKey()); setEvidence(""); setResponsible(""); setQueueEvidence("");
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось выполнить сверку."); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!org || !left || !right || !protocol?.reconciliation_ready || protocol.accepted_by_accountant || !confirmKey || evidence.trim().length < 10 || confirmBusy || busy || queueBusy || queueRetry) return;
    setConfirmBusy(true); setError("");
    try {
      const [left_base64, right_base64] = await Promise.all([encoded(left), encoded(right)]);
      const response = await fetch(`/api/accounting/organizations/${org}/reconciliation/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ left_base64, right_base64, request_key: confirmKey, evidence: evidence.trim() }) });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) throw new Error(failureDetail(result, "Не удалось сохранить протокол сверки."));
      if (!isRecord(result) || String(result.organization_id) !== org || result.request_key !== confirmKey || result.accepted_by_accountant !== true || result.reconciliation_ready !== true || result.cutover_ready !== false) throw new Error("Сервер вернул неподтверждённый протокол сверки.");
      setProtocol({ ...protocol, accepted_by_accountant: true, receipt_id: Number(result.receipt_id) });
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить протокол сверки."); }
    finally { setConfirmBusy(false); }
  }

  async function queue() {
    if (!org || !left || !right || !protocol || protocol.reconciliation_ready || busy || confirmBusy || queueBusy || (!queueRetry && (!queueKey || !responsible.trim() || queueEvidence.trim().length < 10))) return;
    let command = queueCommand;
    if (!queueRetry || !command) {
      const [left_base64, right_base64] = await Promise.all([encoded(left), encoded(right)]);
      command = { request_key: queueKey, responsible: responsible.trim(), evidence: queueEvidence.trim(), left_base64, right_base64 };
    }
    if (!command?.request_key) { setError("Браузер не создал ключ очереди. Обновите страницу перед сохранением."); return; }
    setQueueBusy(true); setError("");
    let uncertain = true;
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/reconciliation/issues`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(command) });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        if (response.status < 500 && isRecord(result) && typeof result.detail === "string") { uncertain = false; throw new Error(result.detail); }
        throw new Error("Результат сохранения очереди не подтверждён.");
      }
      const issue = assertIssue(result, org, command.request_key);
      uncertain = false;
      setQueueRetry(false); setQueueCommand(null); setQueuedIssue(issue);
      setIssues((current) => current.some((row) => row.issue_id === issue.issue_id) ? current : [issue, ...current]);
    } catch (e) {
      if (uncertain) {
        setQueueCommand(command); setQueueRetry(true);
        setError("Результат сохранения очереди неизвестен. Файлы и команда заблокированы: повторите только ту же команду или проверьте журнал очереди.");
      } else setError(e instanceof Error ? e.message : "Не удалось сохранить очередь сверки.");
    } finally { setQueueBusy(false); }
  }

  async function loadIssues(after?: number) {
    if (!org || issuesBusy || detailBusy) return;
    setIssuesBusy(true); setError("");
    try {
      const suffix = after ? `?after_id=${encodeURIComponent(String(after))}` : "";
      const response = await fetch(`/api/accounting/organizations/${org}/reconciliation/issues${suffix}`, { cache: "no-store" });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) throw new Error(failureDetail(result, "Не удалось загрузить очередь сверки."));
      if (!isRecord(result) || String(result.organization_id) !== org || !Array.isArray(result.rows)) throw new Error("ERP вернула очередь другого юрлица или неполный ответ.");
      const page = result as unknown as IssuePage;
      const safe = page.rows.map((row) => assertIssue(row, org));
      setIssues((current) => after ? [...current, ...safe.filter((item) => !current.some((row) => row.issue_id === item.issue_id))] : safe);
      setNextIssueId(Number.isInteger(page.next_after_id) ? page.next_after_id : null);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось загрузить очередь сверки."); }
    finally { setIssuesBusy(false); }
  }

  async function openIssue(issueId: number, after?: number) {
    if (!org || detailBusy || issuesBusy) return;
    setDetailBusy(true); setError("");
    try {
      const suffix = after ? `?after_item_id=${encodeURIComponent(String(after))}` : "";
      const response = await fetch(`/api/accounting/organizations/${org}/reconciliation/issues/${issueId}${suffix}`, { cache: "no-store" });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) throw new Error(failureDetail(result, "Не удалось загрузить строки очереди."));
      if (!isRecord(result) || String(result.organization_id) !== org || !isRecord(result.issue) || !Array.isArray(result.items)) throw new Error("ERP вернула неполные строки очереди сверки.");
      const value = result as unknown as IssueDetail;
      const issue = assertIssue(value.issue, org);
      const items = value.items.filter((item) => Number.isInteger(item.item_id) && item.item_id > 0);
      setSelectedIssue((current) => after && current?.issue.issue_id === issueId ? { ...value, issue, items: [...current.items, ...items] } : { ...value, issue, items });
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось загрузить строки очереди."); }
    finally { setDetailBusy(false); }
  }

  function download() {
    if (!protocol) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(protocol, null, 2)], { type: "application/json;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `osv-comparison-${org}-${protocol.left.from}-${protocol.left.to}.json`;
    document.body.appendChild(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const locked = busy || confirmBusy || queueBusy || queueRetry || !org;
  return <section aria-label="Сверка ОСВ" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Сверка двух ОСВ</h2>
    <p>Выберите два CSV для одного юрлица и периода. Правую ОСВ скачайте из ERP; выгрузку 1С сначала приведите к этому формату по утверждённому соответствию счетов и аналитики. До 2 МБ на файл. Файлы отправляются серверу для сравнения; проводки не создаются.</p>
    {org && start && end && <a className="text-accent underline" href={`/api/accounting/organizations/${encodeURIComponent(org)}/reconciliation/erp-osv.csv?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`} download>Скачать ОСВ ERP за выбранный период</a>}
    <p className="text-sm text-muted">Период берётся из файлов. Разница: правая ОСВ минус левая. Отсутствующие строки не считаются нулевыми. Совпадение не заменяет проверку бухгалтера и закрытие месяца.</p>
    <fieldset disabled={locked} className="space-y-3">
      <label className="block">Левая ОСВ<input className="block" type="file" accept=".csv,text/csv" onChange={(e) => { setLeft(e.target.files?.[0] ?? null); clear(); }} /></label>
      <label className="block">Правая ОСВ<input className="block" type="file" accept=".csv,text/csv" onChange={(e) => { setRight(e.target.files?.[0] ?? null); clear(); }} /></label>
      <Button disabled={!left || !right} onClick={() => void compare()}>Сравнить ОСВ</Button>
    </fieldset>
    {!org && <p>Выберите юрлицо.</p>}{busy && <p role="status">Сравнение файлов…</p>}{error && <p role="alert">{error}</p>}
    {protocol && <>
      <p>{protocol.status === "no_numeric_differences" ? "Числовых расхождений не найдено." : `Строк с расхождениями: ${protocol.differences.length}.`}</p>
      {protocol.erp_ledger_verified === false && <p role="status">Правая ОСВ не совпадает с текущим отчётом ERP. Скачайте новую ОСВ и повторите сверку.</p>}
      <p>{protocol.left.from} — {protocol.left.to} · Левая: {reportStatus(protocol.left.status)} · Правая: {reportStatus(protocol.right.status)}</p>
      {protocol.accepted_by_accountant ? <p role="status">Протокол принят бухгалтером{protocol.receipt_id ? ` · квитанция №${protocol.receipt_id}` : ""}. Повторная запись не создаётся. Одна принятая сверка не означает готовность к отказу от 1С.</p> : protocol.reconciliation_ready ? <div className="space-y-2 rounded border border-accent p-3"><p>ОСВ совпадают, оба отчёта закрыты и необработанных документов нет. Перед подтверждением проверьте протокол. Одна принятая сверка не означает готовность к отказу от 1С.</p><label className="block">Основание проверки<input aria-label="Основание принятия сверки" disabled={busy || confirmBusy || queueBusy} className="mt-1 block w-full rounded border border-line px-2 py-1" value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Протокол сверки и подпись бухгалтера" /></label><Button disabled={confirmBusy || evidence.trim().length < 10} onClick={() => void confirm()}>{confirmBusy ? "Сохраняем…" : "Принять протокол бухгалтером"}</Button></div> : <div className="space-y-2 rounded border border-amber-300 p-3"><p className="text-sm">Подтверждение недоступно: {displayBlockers(protocol.eligibility_blockers) || "нужны закрытые отчёты без необработанных документов"}.</p><p className="text-sm text-muted">Сохраните расхождения в очередь с ответственным. Это не исправляет старую ОСВ и не делает её принятой: после исправления нужна новая выгрузка и сверка.</p><label className="block">Ответственный за исправление<input aria-label="Ответственный за исправление" disabled={queueBusy || queueRetry} className="mt-1 block w-full rounded border border-line px-2 py-1" value={responsible} onChange={(e) => setResponsible(e.target.value)} placeholder="Устойчивый ID сотрудника или подразделения" /></label><label className="block">Основание постановки в очередь<input aria-label="Основание постановки в очередь" disabled={queueBusy || queueRetry} className="mt-1 block w-full rounded border border-line px-2 py-1" value={queueEvidence} onChange={(e) => setQueueEvidence(e.target.value)} placeholder="Причина и первичный источник расхождения" /></label>{queueRetry && <p role="status" className="text-sm text-amber-700">Команда сохранена в неизменном виде. Изменение файлов или ответственного заблокировано до её повторения.</p>}<Button disabled={queueBusy || (!queueRetry && (!queueKey || !responsible.trim() || queueEvidence.trim().length < 10))} onClick={() => void queue()}>{queueBusy ? "Сохраняем…" : queueRetry ? "Повторить сохранение той же очереди" : "Сохранить очередь сверки"}</Button></div>}
      <Button variant="secondary" onClick={download}>Скачать протокол JSON</Button>
      <p className="break-all text-xs">SHA-256 левой: {protocol.left.sha256}<br />SHA-256 правой: {protocol.right.sha256}</p>
      {protocol.differences.slice(0, 100).map((row, index) => <DifferenceCard key={index} row={row} />)}
      {protocol.differences.length > 100 && <p>Показаны первые 100 строк. Полный список находится в скачиваемом протоколе и сохранённой очереди.</p>}
    </>}
    <section aria-label="Очередь несопоставленных строк" className="space-y-3 border-t border-line pt-4">
      <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">Очередь несопоставленных строк</h3><Button variant="secondary" disabled={!org || issuesBusy || detailBusy} onClick={() => void loadIssues()}>{issuesBusy ? "Загружаем…" : "Обновить очередь"}</Button></div>
      <p className="text-sm text-muted">Очередь хранит снимок источников и каждую несовпавшую строку. Её нельзя закрыть вручную: только новая закрытая ОСВ без расхождений может быть принята бухгалтером.</p>
      {queuedIssue && <p role="status">Очередь №{queuedIssue.issue_id} сохранена для {queuedIssue.responsible}; нужна новая сверка после исправления.</p>}
      {issues.map((issue) => <article key={issue.issue_id} className="rounded border border-line p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p>№{issue.issue_id} · {issue.period_from} — {issue.period_to} · строк: {issue.difference_count}</p><Button variant="secondary" disabled={detailBusy || issuesBusy} onClick={() => void openIssue(issue.issue_id)}>Открыть строки</Button></div><p className="text-sm">Ответственный: {issue.responsible}</p><p className="text-sm text-muted">Блокеры: {displayBlockers(issue.eligibility_blockers)}</p></article>)}
      {nextIssueId && <Button variant="secondary" disabled={issuesBusy || detailBusy} onClick={() => void loadIssues(nextIssueId)}>Загрузить следующие очереди</Button>}
      {selectedIssue && <div className="space-y-2 rounded border border-accent p-3"><p className="font-semibold">Очередь №{selectedIssue.issue.issue_id} · требуется новая сверка</p>{selectedIssue.items.length === 0 ? <p className="text-sm">Числовых строк нет; устраните показанные блокеры и сформируйте новую ОСВ.</p> : selectedIssue.items.map((item) => <DifferenceCard key={item.item_key} row={item} />)}{selectedIssue.next_after_item_id && <Button variant="secondary" disabled={detailBusy} onClick={() => void openIssue(selectedIssue.issue.issue_id, selectedIssue.next_after_item_id ?? undefined)}>Загрузить следующие строки</Button>}</div>}
    </section>
  </section>;
}

function DifferenceCard({ row }: { row: Difference }) {
  return <article className="rounded border border-line p-3">
    <p>{row.account} · {row.currency}{row.off_balance ? " · Забалансовый" : ""} · {row.presence === "left_only" ? "Только в левой ОСВ" : row.presence === "right_only" ? "Только в правой ОСВ" : "Есть в обеих ОСВ"}</p>
    <p>{JSON.stringify(row.dimensions)}</p>
    {Object.entries(row.fields).map(([field, values]) => <p key={field}>{labels[field] ?? field}: слева {values.left ?? "нет строки"}; справа {values.right ?? "нет строки"}; разница {values.right_minus_left ?? "не рассчитывается"}</p>)}
  </article>;
}
