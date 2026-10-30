"use client";

import { useEffect, useRef, useState } from "react";
import { InstanceOrganizationGate } from "@/components/instance-organization-gate";
import { searchAccountingSkus, type AccountingSku } from "@/lib/accounting-skus";
import { OpeningRequestError, openingRequest, pasteOpeningRows, readOpeningDraft, type OpeningContext, type OpeningDocument,
  type OpeningResult, type OpeningRow } from "@/lib/accounting-opening-stock";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";

const emptyRow = (): OpeningRow => ({ sku: "", warehouse: "", lot: "", quantity: "", amount_byn: "" });
const field = "rounded-lg border border-line bg-surface p-2 w-full";

export function AccountingOpeningStock() {
  return <InstanceOrganizationGate>{org => <OpeningWorkspace key={org.id} org={org.id} />}</InstanceOrganizationGate>;
}

export function OpeningWorkspace({ org }: { org: number }) {
  const [date, setDate] = useState("2026-07-01");
  const [contextState, setContextState] = useState<{
    org: number; date: string; attempt: number; value: OpeningContext;
  } | null>(null);
  const [doc, setDoc] = useState<OpeningDocument>(() => ({ request_key: crypto.randomUUID(), opening_date: date,
    policy_id: 0, inventory_account: "", counter_account: "", evidence: "", rows: [emptyRow()] }));
  const [result, setResult] = useState<OpeningResult | null>(null);
  const [paste, setPaste] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [ack, setAck] = useState(false);
  const [page, setPage] = useState(0);
  const [lookup, setLookup] = useState("");
  const [matches, setMatches] = useState<AccountingSku[]>([]);
  const [lookupRow, setLookupRow] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const generation = useRef(0);
  const searchGeneration = useRef(0);
  const context = contextState?.org === org && contextState.date === date && contextState.attempt === attempt
    ? contextState.value : null;
  const frozen = busy || fileLoading || uncertain || result?.confirmed === true;
  useEffect(() => {
    let active = true;
    const operationGeneration = generation;
    const lookupGeneration = searchGeneration;
    void openingRequest<OpeningContext>(org, `context?on=${date}`).then(value => {
      if (active) {
        setContextState({ org, date, attempt, value });
        setDoc(d => d.opening_date === date && d.policy_id === 0
          ? { ...d, policy_id: value.policy_id ?? 0 } : d);
      }
    }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; operationGeneration.current++; lookupGeneration.current++; };
  }, [org, date, attempt]);
  useUnsavedDocumentGuard(dirty || uncertain);
  const edit = (change: Partial<OpeningDocument>) => {
    searchGeneration.current++; setMatches([]);
    setDoc(d => ({ ...d, ...change })); setResult(null); setAck(false); setDirty(true); setError("");
  };
  const editRow = (index: number, change: Partial<OpeningRow>) => edit({ rows: doc.rows.map((r, i) => i === index ? { ...r, ...change } : r) });
  async function check() {
    if (frozen) return;
    const current = ++generation.current;
    setBusy(true); setError(""); setResult(null); setAck(false);
    try {
      const value = await openingRequest<OpeningResult>(org, "preview", doc);
      if (current === generation.current) {
        if (value.request_key !== doc.request_key || value.row_count !== doc.rows.length || !/^[a-f0-9]{64}$/.test(value.preview_digest))
          throw new Error("Результат проверки не соответствует документу");
        setResult(value);
      }
    } catch (e) { if (current === generation.current) setError((e as Error).message); }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function post() {
    if (!result || !ack || busy || fileLoading || result.confirmed) return;
    const current = ++generation.current;
    setBusy(true); setError(""); setUncertain(true);
    try {
      const value = await openingRequest<OpeningResult>(org, "confirm", {
        document: doc, preview_digest: result.preview_digest, acknowledge_addition: true,
      });
      if (current === generation.current) {
        if (!value.confirmed || value.request_key !== doc.request_key || value.preview_digest !== result.preview_digest
          || value.row_count !== doc.rows.length || !Array.isArray(value.entry_ids) || value.entry_ids.length < 1)
          throw new Error("Подтверждение не удалось проверить. Повторите с тем же ключом");
        setResult(value); setUncertain(false); setDirty(false);
      }
    } catch (e) { if (current === generation.current) {
      if (e instanceof OpeningRequestError && e.rejected) {
        setUncertain(false); setResult(null); setAck(false); setError(e.message);
        if (!loaded) { setDoc(d => ({ ...d, policy_id: 0 })); setAttempt(a => a + 1); }
      }
      else setError(`${(e as Error).message}. Не создавайте новый документ: повторите подтверждение с тем же ключом.`);
    } }
    finally { if (current === generation.current) setBusy(false); }
  }
  function save() {
    const blob = new Blob([JSON.stringify({ format: "opening-stock-draft-v1", organization_id: org, document: doc }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = `opening-stock-${date}-${doc.request_key}.json`; link.click(); URL.revokeObjectURL(url);
    setDirty(false);
  }
  async function loadFile(file?: File) {
    if (!file || frozen) return;
    const current = ++generation.current; setFileLoading(true);
    try {
      if (file.size > 5_000_000) throw new Error("Файл слишком большой");
      const document = readOpeningDraft(await file.text(), org);
      if (current === generation.current) { edit(document); setDate(document.opening_date); setPage(0); setLoaded(true); }
    } catch (e) { if (current === generation.current) setError((e as Error).message); }
    finally { if (current === generation.current) setFileLoading(false); }
  }
  return <main className="space-y-4 p-6 min-w-0">
    <h1 className="text-2xl font-semibold">Ввод начальных остатков товаров</h1>
    <p>Количество и общая себестоимость в BYN на начало указанного дня. Продажные цены вводятся отдельно.</p>
    <p className="rounded-xl border border-amber-300 bg-amber-50 p-3">Этот документ записывает исторические остатки в бухгалтерский учёт. Текущее наличие и резервы складов он не меняет. Полный переход с 1С подтверждается отдельно.</p>
    <label className="block max-w-xs">Дата остатков<input aria-label="Дата остатков" type="date" className={field} value={date} disabled={frozen}
      onChange={e => { setDate(e.target.value); edit({ opening_date: e.target.value, policy_id: 0 }); }} /></label>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {!context && <button onClick={() => { setError(""); setAttempt(a => a + 1); }} disabled={frozen}>Повторить проверку возможности ввода</button>}
    <div className="flex gap-3 flex-wrap"><button disabled={busy || fileLoading} onClick={save}>Скачать черновик</button>
      <label>Загрузить черновик <input aria-label="Загрузить черновик" type="file" accept=".json" disabled={frozen} onChange={e => void loadFile(e.target.files?.[0])} /></label></div>
    {loaded && !context && <button disabled={frozen} onClick={check}>Проверить загруженный документ</button>}
    {context && <>
      <p>Ранее введено начальных проводок: {context.existing_opening_entries}. Новый документ добавляет остатки; ранее введённые строки не заменяются.</p>
      {!context.policy_id && <p role="alert">Сначала утвердите учётную политику в бухгалтерии.</p>}
      <fieldset disabled={frozen} className="min-w-0 space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <label>Счёт запасов<select aria-label="Счёт запасов" className={field} value={doc.inventory_account} onChange={e => edit({ inventory_account: e.target.value })}>
            <option value="">Выберите счёт</option>{context.inventory_accounts.map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</select></label>
          <label>Корреспондирующий счёт<select aria-label="Корреспондирующий счёт" className={field} value={doc.counter_account} onChange={e => edit({ counter_account: e.target.value })}>
            <option value="">Выберите с бухгалтером</option>{context.counter_accounts.map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</select></label>
        </div>
        <label className="block">Основание / исходный отчёт<input aria-label="Основание" className={field} maxLength={300} value={doc.evidence} onChange={e => edit({ evidence: e.target.value })} /></label>
        <details className="rounded border border-line p-3"><summary>Вставить из Excel</summary>
          <p>Пять столбцов без заголовка: код товара → точное имя склада → партия / слой → количество → общая себестоимость BYN. Десятичная запятая поддерживается. Партия обязательна; нулевая или неизвестная стоимость не подменяется числом.</p>
          <textarea aria-label="Строки из Excel" className={field} rows={4} value={paste} onChange={e => setPaste(e.target.value)} />
          <button onClick={() => { try { const rows = pasteOpeningRows(paste); edit({ rows: [...doc.rows.filter(r => r.sku || r.quantity || r.amount_byn), ...rows] }); setPaste(""); } catch (e) { setError((e as Error).message); } }}>Добавить строки из Excel</button>
        </details>
        <button onClick={() => { edit({ rows: [...doc.rows, emptyRow()] }); setPage(Math.floor(doc.rows.length / 50)); }}>+ Строка</button>
        <div className="max-w-full overflow-x-auto"><table className="w-full text-sm" style={{ minWidth: 900 }}><thead><tr>{["№", "Код товара", "Склад", "Партия / слой", "Количество", "Себестоимость BYN", ""].map(h => <th key={h} className="p-2 text-left">{h}</th>)}</tr></thead>
          <tbody>{doc.rows.slice(page * 50, page * 50 + 50).map((r, offset) => { const index = page * 50 + offset; return <tr key={index}>
            <td>{index + 1}</td><td className="min-w-48"><input aria-label={`Товар ${index + 1}`} className={field} value={r.sku} onChange={e => editRow(index, { sku: e.target.value })} />
              <button onClick={() => { searchGeneration.current++; setLookupRow(index); setLookup(r.sku); setMatches([]); }}>Найти товар</button></td>
            <td className="min-w-40"><select aria-label={`Склад ${index + 1}`} className={field} value={r.warehouse} onChange={e => editRow(index, { warehouse: e.target.value })}>
              <option value="">Выберите склад</option>{context.warehouses.map(w => <option key={w.name} value={w.name}>{w.name} · {w.title}</option>)}</select></td>
            <td><input aria-label={`Партия ${index + 1}`} className={field} value={r.lot} onChange={e => editRow(index, { lot: e.target.value })} /></td>
            <td><input aria-label={`Количество ${index + 1}`} inputMode="decimal" className={field} value={r.quantity} onChange={e => editRow(index, { quantity: e.target.value.replace(",", ".") })} /></td>
            <td><input aria-label={`Себестоимость ${index + 1}`} inputMode="decimal" className={field} value={r.amount_byn} onChange={e => editRow(index, { amount_byn: e.target.value.replace(",", ".") })} /></td>
            <td><button aria-label={`Удалить строку ${index + 1}`} onClick={() => { edit({ rows: doc.rows.filter((_, i) => i !== index) }); setPage(0); }}>×</button></td></tr>; })}</tbody></table></div>
        <div className="flex gap-3"><button disabled={page === 0} onClick={() => setPage(p => p - 1)}>Назад</button><span>Строк: {doc.rows.length} · страница {page + 1}</span><button disabled={(page + 1) * 50 >= doc.rows.length} onClick={() => setPage(p => p + 1)}>Далее</button></div>
        <details><summary>Поиск товара для строки {lookupRow + 1}</summary><input aria-label="Название или код товара" className={field} value={lookup} onChange={e => { searchGeneration.current++; setLookup(e.target.value); setMatches([]); }} />
          <button onClick={async () => { const current = ++searchGeneration.current; try { const items = await searchAccountingSkus(String(org), lookup); if (current === searchGeneration.current) setMatches(items); } catch (e) { if (current === searchGeneration.current) setError((e as Error).message); } }}>Найти</button>
          <ul>{matches.map(s => <li key={s.id}><button onClick={() => { editRow(lookupRow, { sku: s.code }); setMatches([]); }}>{s.title} · {s.code} · {s.unit}</button></li>)}</ul></details>
        <button className="rounded-lg bg-accent p-3 text-white" disabled={!doc.rows.length || !context.policy_id} onClick={check}>Проверить документ</button>
      </fieldset>
    </>}
    {result && <section className="space-y-3 rounded-xl border border-line p-4">
      <h2 className="font-semibold">{result.confirmed ? "Остатки записаны в бухгалтерский учёт" : "Результат проверки"}</h2>
      <p>Строк: {result.row_count} · Общая себестоимость: {result.total_byn} BYN · Дата: {result.opening_date}</p>
      <div className="max-h-80 overflow-auto"><table className="w-full text-sm"><thead><tr><th>Товар</th><th>Склад / партия</th><th>Количество</th><th>Себестоимость BYN</th></tr></thead><tbody>{result.rows.map((r, i) => <tr key={i}><td className="p-2">{r.sku_title || r.sku}</td><td>{r.warehouse} / {r.lot}</td><td>{r.quantity} {r.unit}</td><td>{r.amount_byn}</td></tr>)}</tbody></table></div>
      {!result.confirmed && <><label className="block"><input type="checkbox" checked={ack} disabled={busy || fileLoading || uncertain} onChange={e => setAck(e.target.checked)} /> Подтверждаю добавление этих остатков. Это не замена ранее введённых данных.</label>
        <button disabled={busy || fileLoading || !ack} onClick={post}>{uncertain ? "Повторить подтверждение с тем же ключом" : "Записать начальные остатки"}</button></>}
      {result.confirmed && <><p>Проводки: {result.entry_ids.join(", ")}. Текущее складское наличие не изменялось.</p><button onClick={() => {
        setDoc({ request_key: crypto.randomUUID(), opening_date: date, policy_id: context?.policy_id ?? 0, inventory_account: "", counter_account: "", evidence: "", rows: [emptyRow()] });
        setResult(null); setAck(false); setPage(0); setLoaded(false); setError("");
        searchGeneration.current++; setMatches([]); setLookupRow(0); setLookup(""); setAttempt(a => a + 1);
      }}>Новый документ добавления остатков</button></>}
    </section>}
    {busy && <p role="status">Обработка документа…</p>}
    {uncertain && !busy && <button onClick={save}>Скачать документ с ключом для восстановления</button>}
  </main>;
}
