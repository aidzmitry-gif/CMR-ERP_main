"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { fetchRegisterOrganizations, fetchRegisterOriginal, type RegisterOrganization } from "@/lib/document-register-api";
import { kindTitle, loadRegistry, loadSourcePreview, type RegistryPage, type RegistryRow, type SourcePreview } from "@/lib/global-document-register";

const box = "rounded-xl border border-line bg-surface px-3 py-2";
const emptyFilters = { q: "", kind: "", date_from: "", date_to: "", limit: 50 };
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Документы временно недоступны.";
const money = (amount: string | null, currency: string | null) => amount === null ? "Сумма не указана" : `${amount}${currency ? ` ${currency}` : " · валюта не указана"}`;
const dateLabel = (date: string | null) => date ? date.slice(0, 10).split("-").reverse().join(".") : "Дата не указана";

export function DocsRegistry() {
  const [organizations, setOrganizations] = useState<RegisterOrganization[]>([]);
  const [orgError, setOrgError] = useState("");
  const [org, setOrg] = useState("");
  useEffect(() => {
    let active = true;
    void fetchRegisterOrganizations().then(rows => { if (active) setOrganizations(rows); }).catch(error => { if (active) setOrgError(errorMessage(error)); });
    return () => { active = false; };
  }, []);
  return <main className="flex-1 overflow-auto p-4 sm:p-6"><div className="mx-auto max-w-6xl space-y-5">
    <div><h1 className="text-2xl font-bold">Реестр документов</h1><p className="mt-2 text-sm text-muted">Документы выбранной организации. Список, поиск и просмотр учитывают ваши права доступа.</p></div>
    <label className="block max-w-xl text-sm font-semibold">Организация<select className={`${box} mt-2 w-full`} value={org} onChange={event => setOrg(event.target.value)}><option value="">Выберите организацию</option>{organizations.map(row => <option key={row.id} value={row.id}>{row.name} · УНП {row.unp}</option>)}</select></label>
    {orgError && <p role="alert" className="text-red-700">{orgError}</p>}
    {!org && <p className="rounded-xl bg-surface p-5 text-muted">Выберите организацию, чтобы открыть её документы. Данные разных организаций отображаются отдельно.</p>}
    {org && <OrganizationRegistry key={org} org={org} />}
  </div></main>;
}

function OrganizationRegistry({ org }: { org: string }) {
  const [source, setSource] = useState<"1c" | "erp">("1c");
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<RegistryPage | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<RegistryRow | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void loadRegistry(org, source, page, filters, controller.signal).then(value => { if (!controller.signal.aborted) { setResult(value); setError(""); } })
      .catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); });
    return () => controller.abort();
  }, [org, source, page, filters, reload]);
  function clearView() { setResult(null); setSelected(null); setError(""); }
  function search(event: FormEvent) { event.preventDefault(); if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setError("Дата начала периода позже даты окончания."); return; } clearView(); setFilters({ ...draft, q: draft.q.trim() }); setPage(1); }
  function move(next: number) { clearView(); setPage(next); }
  return <>
    <div className="flex flex-wrap gap-3" role="group" aria-label="Источник документов">{([['1c', 'Импортированные документы 1С'], ['erp', 'Документы сделок ERP']] as const).map(([value, label]) => <button key={value} className={`${box} ${source === value ? 'border-accent text-accent' : ''}`} aria-pressed={source === value} onClick={() => { if (value === source) return; clearView(); setSource(value); setPage(1); setDraft(emptyFilters); setFilters(emptyFilters); }}>{label}</button>)}</div>
    {source === '1c' && <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Сохранённые документы 1С доступны для просмотра. Они ещё не проведены в ERP. Предпросмотр показывает данные источника и не заменяет подписанный оригинал или накладную ERP.</p>}
    <form onSubmit={search} className="flex flex-wrap items-end gap-3 rounded-2xl bg-surface p-4">
      <label className="min-w-56 flex-1 text-sm">Номер или контрагент<input type="search" className={`${box} mt-1 w-full`} value={draft.q} onChange={event => setDraft({ ...draft, q: event.target.value })} /></label>
      <label className="text-sm">Тип<select className={`${box} mt-1 block max-w-80`} value={draft.kind} onChange={event => setDraft({ ...draft, kind: event.target.value })}><option value="">Все доступные типы</option>{result?.kinds.map(kind => <option key={kind} value={kind}>{kindTitle(kind)}</option>)}</select></label>
      <label className="text-sm">Дата с<input type="date" className={`${box} mt-1 block`} value={draft.date_from} onChange={event => setDraft({ ...draft, date_from: event.target.value })} /></label>
      <label className="text-sm">Дата по<input type="date" className={`${box} mt-1 block`} value={draft.date_to} onChange={event => setDraft({ ...draft, date_to: event.target.value })} /></label>
      <label className="text-sm">На странице<select className={`${box} mt-1 block`} value={draft.limit} onChange={event => setDraft({ ...draft, limit: Number(event.target.value) })}>{[25, 50, 100].map(limit => <option key={limit}>{limit}</option>)}</select></label>
      <button className={`${box} border-accent text-accent`} type="submit">Найти</button>
      <button className={box} type="button" onClick={() => { clearView(); setPage(1); setDraft(emptyFilters); setFilters(emptyFilters); setReload(value => value+1); }}>Сбросить</button>
      <button className={box} type="button" onClick={() => { clearView(); setReload(value => value+1); }}>Обновить</button>
    </form>
    {error && <p role="alert" className="rounded-xl border border-red-200 p-4 text-red-700">{error}</p>}
    {!result && !error && <p role="status">Загружаем документы…</p>}
    {result && <>
      <div className="flex flex-wrap items-center justify-between gap-3"><p>Найдено: {result.total}. Показано {result.total ? (page-1)*filters.limit+1 : 0}–{Math.min(page*filters.limit, result.total)}</p><Pagination page={page} pages={result.pages} onMove={move} /></div>
      {result.items.length === 0 ? <p className="rounded-xl bg-surface p-5">Документов по выбранным условиям нет.</p> : <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">{result.items.map(row => <li key={row.id} className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="min-w-0"><button className="text-left font-semibold text-accent hover:underline" onClick={() => setSelected(row)}>{kindTitle(row.kind)} № {row.number}</button><p className="mt-1 text-sm text-muted">{dateLabel(row.date)} · {money(row.amount, row.currency)} · Версия {row.revision}</p>{row.client && <Link className="text-sm text-accent" href={`/erp/spravochniki/counterparty/${row.client.id}`}>{row.client.name}</Link>}<p className="mt-1 text-xs text-muted">{row.source === '1c' ? 'Данные 1С · Не проведено в ERP' : `ERP · ${row.status}`}</p></div>
        <button className={box} onClick={() => setSelected(row)}>Открыть / предпросмотр</button>
      </li>)}</ul>}
      <Pagination page={page} pages={result.pages} onMove={move} />
    </>}
    {selected && <DocumentView key={`${source}/${selected.id}`} org={org} row={selected} onClose={() => setSelected(null)} />}
  </>;
}

function Pagination({ page, pages, onMove }: { page: number; pages: number; onMove: (page: number) => void }) {
  return <nav aria-label="Страницы документов" className="flex items-center gap-3"><button className={box} disabled={page <= 1} onClick={() => onMove(page-1)}>Назад</button><span>Страница {page} из {pages}</span><button className={box} disabled={page >= pages} onClick={() => onMove(page+1)}>Далее</button></nav>;
}

function DocumentView({ org, row, onClose }: { org: string; row: RegistryRow; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [preview, setPreview] = useState<SourcePreview | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [linePage, setLinePage] = useState(1);
  useEffect(() => { const node = dialog.current; node?.showModal(); return () => node?.close(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    if (row.source === '1c') void loadSourcePreview(org, row.id, linePage, controller.signal).then(value => { if (!controller.signal.aborted) setPreview(value); }).catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); });
    else if (row.original_available && row.deal_id) void fetchRegisterOriginal(org, String(row.deal_id), row.id).then(value => { if (!controller.signal.aborted) setHtml(value); }).catch(error => { if (!controller.signal.aborted) setError(errorMessage(error)); });
    return () => controller.abort();
  }, [org, row, linePage]);
  return <dialog ref={dialog} onCancel={onClose} aria-label={`Документ ${row.number}`} className="max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-6xl overflow-auto rounded-2xl border-2 border-accent bg-surface p-5 text-ink shadow-card backdrop:bg-black/40">
    <div className="flex items-start justify-between gap-4"><h2 className="text-xl font-bold">{kindTitle(row.kind)} № {row.number}</h2><button className={box} onClick={onClose}>Закрыть документ</button></div>
    {error && <p role="alert" className="mt-3 text-red-700">{error}</p>}
    {row.source === '1c' && !preview && !error && <p role="status">Загружаем предпросмотр…</p>}
    {preview && <div className="mt-4 space-y-4"><p className="rounded-xl bg-amber-50 p-4 text-sm text-amber-900">{preview.explanation}</p>
      <p>Дата: {dateLabel(preview.date)} · {money(preview.amount, preview.currency)}</p><p>Контрагент: {preview.client?.name ?? 'Не сопоставлен с карточкой'}</p>
      {preview.line_total > 0 ? <><p>Строк товаров: {preview.line_total}</p><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Номенклатура</th><th className="p-2">Данные строки</th></tr></thead><tbody>{preview.lines.map((line, index) => <tr key={index} className="border-t border-line"><td className="p-2">{line.name}</td><td className="p-2"><dl className="flex flex-wrap gap-x-5 gap-y-1">{Object.entries(line.fields).map(([key, value]) => <div key={key}><dt className="inline text-muted">{key}: </dt><dd className="inline">{value}</dd></div>)}</dl></td></tr>)}</tbody></table></div>{preview.line_pages > 1 && <Pagination page={linePage} pages={preview.line_pages} onMove={page => { setPreview(null); setError(""); setLinePage(page); }} />}</> : <p className="text-sm text-muted">В источнике нет табличной части «Товары». Здесь показаны реквизиты документа; кадровые и банковские поля не выводятся.</p>}
      <details className="text-sm text-muted"><summary>Сведения об источнике</summary><p className="mt-2 break-all">ID: {preview.source_guid} · версия {preview.revision}<br />SHA-256: {preview.source_sha256}</p><p className="mt-2">Данные сохранены для просмотра; проведение и преобразование в документ ERP ещё не выполнены.</p></details>
    </div>}
    {row.source === 'erp' && <div className="mt-4 space-y-3"><p>{dateLabel(row.date)} · {money(row.amount, row.currency)} · {row.status}</p>{row.deal_id && <Link className="text-accent underline" href={`/crm/deals/${row.deal_id}?org=${org}&invoice=${row.id}#document-register`}>Открыть документ в сделке</Link>}{!row.original_available && <p className="text-sm text-muted">Сохранённый оригинал отсутствует. Черновик и доступные действия откройте в карточке сделки.</p>}{row.original_available && !html && !error && <p role="status">Проверка оригинала…</p>}{html !== null && <iframe title={`Оригинал документа ${row.number}`} sandbox="" referrerPolicy="no-referrer" srcDoc={html} className="h-[36rem] w-full rounded-xl border border-line bg-white" />}</div>}
  </dialog>;
}
