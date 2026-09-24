"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type UnlinkedPurchase = {
  entry_id: number;
  document_date: string;
  posting_date: string;
  source: string;
  source_version: number;
};
type Page = { rows: UnlinkedPurchase[]; next_after_id: number | null };

export function ProcurementUnlinkedPurchases({ org }: { org: string }) {
  const [rows, setRows] = useState<UnlinkedPurchase[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    const url = `/api/accounting/organizations/${encodeURIComponent(org)}/purchases/unlinked-primary?limit=100${cursor === null ? "" : `&after_id=${cursor}`}`;
    void fetch(url, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 403
        ? "Нет доступа к бухгалтерским поступлениям этого юрлица."
        : "Не удалось проверить поступления без первички.");
      return await response.json() as Page;
    }).then((page) => {
      if (!active) return;
      setRows((previous) => cursor === null ? page.rows : [...previous, ...page.rows]);
      setNext(page.next_after_id);
      setError("");
    }).catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [org, cursor, retry]);

  return <section aria-label="Поступления без связанной первички закупок" className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Поступления без связанной первички закупок</h2>
    <p className="text-sm text-muted">Это бухгалтерские проводки для сверки, а не сохранённые накладные поставщика. Связь с первичным документом требует отдельной проверки.</p>
    {error && <p role="alert" className="text-red-700">{error} <button className="text-accent underline" onClick={() => { setLoading(true); setRetry((value) => value + 1); }}>Повторить</button></p>}
    {loading && <p role="status">Проверка бухгалтерских поступлений…</p>}
    {!loading && !error && rows.length === 0 && <p className="text-sm text-muted">Поступлений без связанной первички не найдено.</p>}
    {rows.length > 0 && <ul className="divide-y divide-line">{rows.map((row) => <li key={row.entry_id} className="py-2 text-sm">
      <Link className="text-accent underline" href={`/erp/accounting?org=${encodeURIComponent(org)}&entry=${row.entry_id}`}>Проводка № {row.entry_id}</Link>
      <span> · документ от {row.document_date} · отражено {row.posting_date}</span>
      <p className="break-words text-muted">{row.source} · версия {row.source_version}</p>
    </li>)}</ul>}
    {next !== null && !error && <button disabled={loading} className="text-sm text-accent underline disabled:opacity-50" onClick={() => { setLoading(true); setCursor(next); }}>Показать ещё</button>}
  </section>;
}
