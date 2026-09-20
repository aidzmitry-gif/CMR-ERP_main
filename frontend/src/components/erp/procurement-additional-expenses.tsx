"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { forgetExpense, pendingExpense, rememberExpense, type ExpenseCommand } from "@/lib/additional-expense-journal";
import { AccountingLateCostPreview } from "./accounting-late-cost-preview";
import { AccountingLateCostPosted } from "./accounting-late-cost-posted";
import { AccountingLateCostConfirmation } from "./accounting-late-cost-confirmation";
import type { LateCostPending } from "@/lib/late-cost-journal";

type Organization = { id: number; name: string; unp: string };
type Source = { receipt_id: number; version: number; line_number: number };
type Document = { invoice_reference: string; supplier: string; contract: string; document_date: string;
  operation_date: string; currency: string; amount: string; explanation: string; receipt_lines: Source[] };
type Revision = { version: number; document: Document; actor: string; created_at: string };
type Expense = { id: number; organization_id: number; key: string; version: number; posted: boolean;
  posting?: { entry_id: number; version: number; digest: string; command_version?: number } | null; revisions: Revision[] };
type Receipt = { id: number; posting: { version: number } | null;
  revisions: { version: number; document: { invoice_reference: string; items: { sku: string; lot: string; quantity: string }[] } }[] };
type Context = { organization_id: number; principal: string; can_write: boolean };
const blank = (): Document => ({ invoice_reference: "", supplier: "", contract: "", document_date: "", operation_date: "",
  currency: "", amount: "", explanation: "", receipt_lines: [] });
const sourceKey = (source: Source) => `${source.receipt_id}:${source.version}:${source.line_number}`;

async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const result = await fetch(`/api/procurement${path}`, { cache: "no-store", signal });
  const data = await result.json();
  if (!result.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось загрузить документы.");
  return data as T;
}

export function ProcurementAdditionalExpenses() {
  const [organizations, setOrganizations] = useState<Organization[]>([]), [org, setOrg] = useState("");
  const [locked, setLocked] = useState(false), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void read<Organization[]>("/receipt-organizations", controller.signal).then(setOrganizations)
      .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, []);
  return <main className="min-w-0 flex-1 space-y-4 overflow-auto p-6">
    <h1 className="text-2xl font-semibold">Дополнительные расходы</h1>
    <p className="text-sm text-muted">Документы перевозчика, брокера и других поставщиков услуг, связанные с поступлениями. Сохранённые черновики ожидают бухгалтерской обработки.</p>
    <label className="block">Юрлицо<Select aria-label="Юрлицо" value={org} disabled={locked} onChange={e => setOrg(e.target.value)}>
      <option value="">Выберите организацию</option>{organizations.map(row => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}
    </Select></label>
    {error && <p role="alert">{error}</p>}
    {org && <ExpenseBook key={org} org={org} onLock={setLocked} />}
  </main>;
}

function ExpenseBook({ org, onLock }: { org: string; onLock: (locked: boolean) => void }) {
  const [rows, setRows] = useState<Expense[]>([]), [receipts, setReceipts] = useState<Receipt[]>([]);
  const [context, setContext] = useState<Context | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [document, setDocument] = useState<Document>(blank), [selected, setSelected] = useState<Expense | null>(null);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [loaded, setLoaded] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [postingLocked, setPostingLocked] = useState(false), [preparedPosting, setPreparedPosting] = useState<LateCostPending | null>(null);
  useEffect(() => { onLock(busy || pending || postingLocked); }, [busy, pending, postingLocked, onLock]);
  const active = useRef(true), sending = useRef(false), command = useRef<ExpenseCommand | null>(null);
  const base = `/organizations/${org}`;
  const savedDocument = selected?.revisions[selected.revisions.length - 1].document;
  const unsaved = savedDocument !== undefined && Object.keys(savedDocument).some(key =>
    JSON.stringify(savedDocument[key as keyof Document]) !== JSON.stringify(document[key as keyof Document]));
  useEffect(() => {
    active.current = true;
    const controller = new AbortController();
    void Promise.all([read<Context>(`${base}/additional-expense-context`, controller.signal),
      read<Expense[]>(`${base}/additional-expenses?limit=100`, controller.signal),
      read<Receipt[]>(`${base}/receipt-documents`, controller.signal)])
      .then(([ctx, expenses, sources]) => { if (active.current) {
        if (String(ctx.organization_id) !== org || !ctx.principal || typeof ctx.can_write !== "boolean"
          || !Array.isArray(expenses) || !Array.isArray(sources)) throw new Error("Некорректный ответ загрузки.");
        setContext(ctx); setRows(expenses); setHasMore(expenses.length === 100); setReceipts(sources);
        const recovered = pendingExpense(sessionStorage, org, ctx.principal);
        if (recovered) {
          command.current = recovered; setPending(true); onLock(true);
          setDocument(JSON.parse(recovered.body).document as Document);
          if (recovered.method === "PUT") setSelected(expenses.find(row => `${base}/additional-expenses/${row.id}` === recovered.path) ?? null);
          setNotice("Найден незавершённый запрос. Повторите его, чтобы проверить сохранение без создания дубля.");
        }
        setLoaded(true);
      } }).catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => { active.current = false; controller.abort(); };
  }, [base, org, onLock]);

  async function more() {
    if (sending.current || pending) return;
    sending.current = true; setBusy(true); setError("");
    try {
      const next = await read<Expense[]>(`${base}/additional-expenses?limit=100&offset=${rows.length}`);
      if (active.current) { setRows(previous => [...previous, ...next.filter(row => !previous.some(old => old.id === row.id))]); setHasMore(next.length === 100); }
    } catch (e) { if (active.current) setError((e as Error).message); }
    finally { sending.current = false; if (active.current) setBusy(false); }
  }
  function choose(row: Expense | null) {
    if (sending.current || pending || postingLocked) return;
    setPreparedPosting(null);
    setSelected(row); setDocument(row ? structuredClone(row.revisions[row.revisions.length - 1].document) : blank());
    setNotice(""); setError("");
  }
  async function save() {
    if (postingLocked) return;
    if (selected?.posted && !pending) return;
    if (sending.current || !context?.can_write) return;
    const retry = command.current !== null;
    if (!command.current) {
      if (!document.receipt_lines.length) { setError("Выберите хотя бы одну строку проведённого поступления."); return; }
      const normalized = Object.fromEntries(Object.entries(document).map(([key, value]) => [key, typeof value === "string" ? value.trim() : value]));
      command.current = { path: `${base}/additional-expenses${selected ? `/${selected.id}` : ""}`, method: selected ? "PUT" : "POST",
        body: JSON.stringify(selected ? { expected_version: selected.version, document: normalized } : { key: crypto.randomUUID(), document: normalized }), principal: context.principal };
    }
    const sent = command.current;
    sending.current = true; setBusy(true); setPending(true); onLock(true); setError(""); setNotice("");
    try {
      rememberExpense(sessionStorage, org, sent);
      const result = await fetch(`/api/procurement${sent.path}`, { method: sent.method,
        headers: { "Content-Type": "application/json", "X-Expected-Principal": sent.principal }, body: sent.body });
      if (!result.ok) {
        if ([401, 403, 404, 409, 422].includes(result.status)) {
          if (!retry) {
            forgetExpense(sessionStorage, org, sent); command.current = null;
            if (active.current) { setPending(false); onLock(false); }
          }
          throw new Error(result.status === 409 ? "Версия документа или пользователь изменились. Откройте страницу заново и проверьте историю перед новой правкой." : "Сохранение отклонено. Проверьте реквизиты, ссылки и права доступа.");
        }
        throw new Error("Результат сохранения неизвестен. Повторите тот же запрос.");
      }
      const saved = await result.json() as Expense;
      const body = JSON.parse(sent.body) as { key?: string; expected_version?: number; document: Document };
      const confirmedVersion = body.expected_version === undefined ? 1 : body.expected_version + 1;
      const confirmed = saved.revisions?.find(revision => revision.version === confirmedVersion);
      const matches = confirmed && Object.keys(body.document).every(key => JSON.stringify(confirmed.document[key as keyof Document]) === JSON.stringify(body.document[key as keyof Document]));
      if (!Number.isSafeInteger(saved.id) || saved.id <= 0 || String(saved.organization_id) !== org
        || (body.key && saved.key !== body.key) || (sent.method === "PUT" && !sent.path.endsWith(`/${saved.id}`))
        || !Array.isArray(saved.revisions) || !saved.revisions.length || typeof saved.posted !== "boolean"
        || !matches || confirmed.actor !== sent.principal || saved.version < confirmedVersion) throw new Error("Ответ сохранения не подтверждён. Повторите тот же запрос.");
      forgetExpense(sessionStorage, org, sent);
      command.current = null;
      if (active.current) {
        setPending(false); onLock(false); setSelected(saved); setDocument(structuredClone(saved.revisions[saved.revisions.length - 1].document));
        setRows(previous => [saved, ...previous.filter(row => row.id !== saved.id)]);
        setNotice(saved.posted ? `Документ № ${saved.id} сохранён и уже проведён.` : `Черновик № ${saved.id}, версия ${saved.version} сохранён. Расход ещё не проведён.`);
      }
    } catch (e) { if (active.current) setError((e as Error).message); }
    finally { sending.current = false; if (active.current) setBusy(false); }
  }
  const labels: [keyof Omit<Document, "receipt_lines">, string, string][] = [
    ["invoice_reference", "Номер первичного документа", "text"], ["supplier", "Поставщик услуги", "text"], ["contract", "Договор", "text"],
    ["document_date", "Дата документа", "date"], ["operation_date", "Дата хозяйственной операции", "date"],
    ["currency", "Валюта документа (код из 3 букв)", "text"], ["amount", "Сумма по документу", "text"], ["explanation", "Содержание расхода", "text"]];
  return <>
    {error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!loaded && !error && <p role="status">Загрузка документов…</p>}
    <fieldset disabled={postingLocked} className="min-w-0 space-y-4">
    {loaded && <section className="space-y-3 rounded-xl border border-line p-4"><h2 className="font-semibold">Реестр документов расходов</h2>
      {!rows.length && <p>Документов пока нет.</p>}
      {rows.map(row => { const latest = row.revisions[row.revisions.length - 1]; return <div key={row.id} className="flex flex-wrap items-center gap-3 border-b border-line py-2">
        <Button variant="secondary" disabled={busy || pending} onClick={() => choose(row)}>Открыть № {row.id}</Button>
        <span>{latest.document.invoice_reference} · {latest.document.supplier} · {latest.document.amount} {latest.document.currency} · версия {row.version} · {row.posted ? "проведён" : "черновик"}</span>
      </div>; })}
      {hasMore && <Button variant="secondary" disabled={busy || pending} onClick={() => void more()}>Показать ещё</Button>}
      {context?.can_write && <Button disabled={busy || pending} onClick={() => choose(null)}>Новый документ</Button>}
    </section>}
    {loaded && <form className="space-y-3 rounded-xl border border-line p-4" onSubmit={event => { event.preventDefault(); void save(); }}>
      <h2 className="font-semibold">{selected ? `Документ № ${selected.id} · версия ${selected.version}` : "Новый расход"}</h2>
      <fieldset disabled={!context?.can_write || busy || pending || selected?.posted} className="min-w-0 space-y-3">
        <legend>Реквизиты и строки поступлений</legend>
        <div className="grid gap-3 md:grid-cols-2">{labels.map(([key, label, type]) => <label key={key}>{label}<Input required type={type} value={document[key]}
          maxLength={key === "explanation" ? 700 : key === "currency" ? 3 : 200}
          pattern={key === "amount" ? "[0-9]+(\\.[0-9]{1,2})?" : key === "currency" ? "[A-Z]{3}" : undefined}
          onChange={event => setDocument(previous => ({ ...previous, [key]: event.target.value }))} /></label>)}</div>
        {receipts.filter(row => row.posting).map(row => { const revision = row.revisions.find(item => item.version === row.posting?.version); return revision && <div key={row.id} className="space-y-2 border-t border-line pt-3">
          <Link className="text-accent underline" href={`/erp/procurement/receipts?org=${org}&receipt=${row.id}`}>{revision.document.invoice_reference} · версия {revision.version}</Link>
          {revision.document.items.map((item, index) => { const source = { receipt_id: row.id, version: revision.version, line_number: index + 1 }; const key = sourceKey(source);
            return <label key={key} className="flex items-start gap-2"><input type="checkbox" checked={document.receipt_lines.some(line => sourceKey(line) === key)} onChange={event => {
              const checked = event.target.checked; setDocument(previous => ({ ...previous, receipt_lines: checked ? [...previous.receipt_lines, source] : previous.receipt_lines.filter(line => sourceKey(line) !== key) }));
            }} /><span>Строка {index + 1}: {item.sku} · партия {item.lot} · {item.quantity}</span></label>;
          })}</div>; })}
        {!receipts.some(row => row.posting) && <p>Проведённых поступлений нет. Сначала проведите исходную накладную.</p>}
      </fieldset>
      {context?.can_write && (!selected?.posted || pending) && <Button type="submit" disabled={busy || !document.receipt_lines.length}>{busy ? "Сохранение…" : pending ? "Повторить тот же запрос" : "Сохранить черновик"}</Button>}
      {pending && <p role="status">Запрос ещё не подтверждён. Реквизиты и юрлицо заблокированы до выяснения результата.</p>}
    </form>}
    {selected?.posted && <p role="status">Документ проведён{selected.posting ? ` · операция № ${selected.posting.entry_id}` : ""}. Исправления оформляются отдельной операцией.</p>}
    {selected?.posted && selected.posting && <AccountingLateCostPosted key={`${org}:${selected.id}:${selected.version}:${selected.posting.entry_id}`}
      org={org} expenseId={selected.id} version={selected.version} entryId={selected.posting.entry_id}
      mode={selected.posting.command_version === 3 ? "pool" : selected.posting.command_version === 2 ? "material" : "legacy"} />}
    {selected && !selected.posted && unsaved && <p role="status">Сохраните изменения документа перед расчётом и подготовкой проводок.</p>}
    {selected && !selected.posted && !unsaved && <AccountingLateCostPreview key={`${org}:${selected.id}:${selected.version}`} org={org} expenseId={selected.id}
      version={selected.version} currency={selected.revisions[selected.revisions.length - 1].document.currency}
      initialDate={selected.revisions[selected.revisions.length - 1].document.operation_date} disabled={busy || pending || postingLocked} onPrepared={setPreparedPosting} />}
    {selected && <section className="space-y-2 rounded-xl border border-line p-4"><h2 className="font-semibold">История документа</h2>
      {selected.revisions.map(revision => <details key={revision.version}><summary>Версия {revision.version} · {revision.actor} · {revision.created_at}</summary>
        <p>{revision.document.invoice_reference} · {revision.document.operation_date} · {revision.document.amount} {revision.document.currency}</p>
        <p>{revision.document.explanation}</p><ul>{revision.document.receipt_lines.map(line => <li key={sourceKey(line)}>Поступление № {line.receipt_id}, версия {line.version}, строка {line.line_number}</li>)}</ul>
      </details>)}
    </section>}
    </fieldset>
    {context && <AccountingLateCostConfirmation key={`${org}:${context.principal}`} org={org} principal={context.principal}
      prepared={unsaved ? null : preparedPosting} disabled={busy || pending || !context.can_write} onLock={setPostingLocked}
      onPosted={async id => {
        const saved = await read<Expense>(`${base}/additional-expenses/${id}`);
        if (active.current) {
          setRows(previous => [saved, ...previous.filter(row => row.id !== saved.id)]);
          setSelected(saved); setDocument(saved.revisions[saved.revisions.length - 1].document); setPreparedPosting(null);
        }
      }} />}
  </>;
}
