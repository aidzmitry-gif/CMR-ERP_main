"use client";

import { useEffect, useState } from "react";
import { WmsReservationEditor } from "./wms-reservation-editor";

type Summary = { sku_code: string; warehouse: string; qty: string; source_count: number };
type Company = { id: number; name: string; unp: string };
type Reservation = { id: number; organization_id: number; source: string; version: number; sku_code: string; warehouse: string; qty: string; evidence: string; actor: string };

function useRows<T>(url: string | null, reload: number) {
  const [result, setResult] = useState<{ url: string; reload: number; rows: T[]; error: boolean } | null>(null);
  useEffect(() => {
    if (!url) return;
    let active = true;
    const controller = new AbortController();
    fetch(url, { cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("Load failed");
      const rows = await response.json();
      if (!Array.isArray(rows)) throw new Error("Invalid rows");
      if (active) setResult({ url, reload, rows, error: false });
    }).catch(() => {
      if (active) setResult({ url, reload, rows: [], error: true });
    });
    return () => { active = false; controller.abort(); };
  }, [url, reload]);
  const current = result?.url === url && result.reload === reload ? result : null;
  return { rows: current?.rows ?? [], error: current?.error ?? false, loading: Boolean(url && !current) };
}

export function WmsReservations() {
  const [editor, setEditor] = useState<{ row: Reservation | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [organization, setOrganization] = useState("");
  const [source, setSource] = useState("");
  const [reload, setReload] = useState(0);
  const companies = useRows<Company>("/api/wms/receipt-organizations", reload);
  const reservations = useRows<Reservation>(organization ? `/api/wms/reservations?organization_id=${organization}` : null, reload);
  const summary = useRows<Summary>(organization ? `/api/wms/reservations/summary?organization_id=${organization}` : null, reload);
  const history = useRows<Reservation>(organization && source ? `/api/wms/reservations/history?organization_id=${organization}&source=${encodeURIComponent(source)}` : null, reload);
  return <main className="min-w-0 flex-1 overflow-auto p-6 lg:pr-24">
    <h1 className="text-xl font-semibold">Резервы товаров</h1>
    <p className="mt-2 text-sm text-muted">Отдельный регистр резервов. Количество резерва не является физическим остатком. Автоматические резервы продаж и старые записи ещё не перенесены в этот регистр.</p>
    <fieldset disabled={busy} className="my-4 flex flex-wrap items-center gap-3">
      <label>Юрлицо <select aria-label="Юрлицо" className="rounded border border-line bg-surface p-2" value={organization} onChange={(event) => { setOrganization(event.target.value); setSource(""); setEditor(null); setSaved(false); }}>
        <option value="">Выберите юрлицо</option>
        {companies.rows.map((company) => <option key={company.id} value={company.id}>{company.name} · {company.unp}</option>)}
      </select></label>
      <button type="button" className="rounded border border-line p-2" onClick={() => setReload((value) => value + 1)}>Обновить</button>
      <button type="button" disabled={!organization} className="rounded border border-line p-2" onClick={() => { setEditor({ row: null }); setSaved(false); }}>Создать резерв</button>
    </fieldset>
    {saved && <p role="status">Версия резерва записана.</p>}
    {editor && organization && <WmsReservationEditor key={`${organization}:${editor.row?.id ?? "new"}`} organizationId={Number(organization)} initial={editor.row} onBusy={setBusy} onCancel={() => setEditor(null)} onSaved={() => { setSaved(true); setEditor(null); setReload((value) => value + 1); }} />}
    {companies.error && <p role="alert">Не удалось загрузить юрлица. Проверьте доступ и повторите загрузку.</p>}
    {reservations.error && <p role="alert">Не удалось загрузить резервы. Повторите загрузку.</p>}
    {(companies.loading || reservations.loading) && <p role="status">Загрузка…</p>}
    {organization && !reservations.loading && !reservations.error && <table className="w-full text-left text-sm [&_th]:px-3 [&_th]:py-2 [&_td]:px-3">
      <thead><tr><th>Исходная строка</th><th>Номенклатура</th><th>Склад</th><th>Резерв</th><th>Версия</th><th>Действие</th></tr></thead>
      <tbody>{reservations.rows.map((row) => <tr key={row.id} className="border-b border-line"><td className="max-w-xs break-words py-3">{row.source}</td><td>{row.sku_code}</td><td>{row.warehouse}</td><td>{row.qty}</td><td>{row.version}</td><td><button aria-label={`История ${row.source}`} disabled={busy} className="underline" type="button" onClick={() => setSource(row.source)}>История</button> <button aria-label={`Изменить ${row.source}`} disabled={busy} className="ml-2 underline" type="button" onClick={() => { setEditor({ row }); setSaved(false); }}>Изменить</button></td></tr>)}</tbody>
    </table>}
    {organization && !reservations.loading && !reservations.error && reservations.rows.length === 0 && <p>В этом регистре резервов нет.</p>}
    {organization && <section aria-label="Сводка резервов" className="mt-6">
      <h2 className="font-semibold">Итого по регистру резервов</h2>
      <p className="text-sm text-muted">Только последние версии с ненулевым количеством. Это не расчёт доступного складского остатка.</p>
      {summary.loading && <p role="status">Загрузка сводки…</p>}
      {summary.error && <p role="alert">Не удалось загрузить сводку резервов. Повторите загрузку.</p>}
      {!summary.loading && !summary.error && summary.rows.length === 0 && <p>Активных резервов в регистре нет.</p>}
      {summary.rows.map((row) => <p key={`${row.sku_code}:${row.warehouse}`} className="my-2">{row.sku_code} · {row.warehouse} · Резерв {row.qty} · Исходных строк: {row.source_count}</p>)}
    </section>}
    {source && <section className="mt-6"><h2 className="font-semibold">История: {source}</h2>
      {history.loading && <p role="status">Загрузка истории…</p>}
      {history.error && <p role="alert">Не удалось загрузить историю. Повторите загрузку.</p>}
      {history.rows.map((row) => <article key={row.id} className="my-2 rounded border border-line p-3"><p>Версия {row.version} · Резерв {row.qty}</p><p>{row.evidence}</p><p className="text-sm text-muted">Автор: {row.actor}</p></article>)}
    </section>}
  </main>;
}
