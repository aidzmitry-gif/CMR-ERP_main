"use client";
import { useEffect, useState } from "react";
import Link from "next/link";

type Source = { organization_id: number; receipt_id: number; entry_id: number; version: number; document: { invoice_reference: string; document_date: string; operation_date: string; supplier: string; supplier_id?: number | null; supplier_unp?: string | null; contract: string; warehouse: string; explanation: string; items: { sku: string; lot: string; quantity: string; net_amount: string; vat_amount: string; vat_rate: string; vat_basis: string; order_id?: number | null }[] } };
export function ProcurementPostedReceipt({ org, entry }: { org: string; entry: string }) {
  const key = `${org}/${entry}`;
  const [result, setResult] = useState<{ key: string; source?: Source; error?: string } | null>(null);
  const current = result?.key === key ? result : null;
  const source = current?.source, error = current?.error;
  useEffect(() => {
    let active = true;
    void fetch(`/api/procurement/organizations/${encodeURIComponent(org)}/receipt-postings/${encodeURIComponent(entry)}`, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 403 ? "Нет доступа к первичному документу этого юрлица." : response.status === 404 ? "Связанная накладная в выбранном юрлице не найдена." : "Не удалось загрузить первичный документ.");
      return await response.json() as Source;
    }).then((value) => { if (active) setResult({ key, source: value }); }).catch((e: Error) => { if (active) setResult({ key, error: e.message }); });
    return () => { active = false; };
  }, [org, entry, key]);
  return <main className="w-full space-y-4 overflow-auto p-6 lg:pr-24"><h1 className="text-2xl font-semibold">Проведённая первичная накладная</h1>
    {error && <p role="alert">{error}</p>}{!source && !error && <p role="status">Загрузка первичного документа…</p>}
    {source && <section className="space-y-3 rounded-xl border border-line bg-surface p-5"><h2 className="font-semibold">{source.document.invoice_reference} · версия {source.version}</h2><p>Юрлицо № {source.organization_id} · накладная № {source.receipt_id} · проводка № {source.entry_id}</p><p>Сохранённая версия, на основании которой выполнено проведение.</p><dl className="grid gap-3 md:grid-cols-2">{[["Дата документа", source.document.document_date], ["Дата операции", source.document.operation_date], ["Поставщик", source.document.supplier], ["Поставщик: справочник", source.document.supplier_id ? `ID ${source.document.supplier_id} · УНП ${source.document.supplier_unp || "не указан"}` : "Связь исторического документа неизвестна"], ["Договор", source.document.contract], ["Склад", source.document.warehouse], ["Содержание", source.document.explanation]].map(([label, value]) => <div key={label}><dt className="text-sm text-muted">{label}</dt><dd>{value}</dd></div>)}</dl><div className="overflow-auto"><table className="w-full text-left text-sm"><caption className="py-3 text-left">Строки накладной · суммы в BYN</caption><thead><tr>{["Номенклатура / партия", "Количество", "Без НДС", "НДС", "Ставка / основание", "Заказ"].map((label) => <th className="p-2" key={label}>{label}</th>)}</tr></thead><tbody>{source.document.items.map((item, i) => <tr key={i} className="border-t border-line"><td className="p-2">{item.sku} · {item.lot}</td><td>{item.quantity}</td><td>{item.net_amount}</td><td>{item.vat_amount}</td><td>{item.vat_rate}% · {item.vat_basis}</td><td>{item.order_id ?? "—"}</td></tr>)}</tbody></table></div></section>}
    {source && <Link className="block text-accent underline" href={`/erp/wms/receipts/from-primary?org=${source.organization_id}&receipt=${source.receipt_id}&version=${source.version}`}>Подготовить складскую приёмку по этой накладной</Link>}
    <Link className="text-accent underline" href="/erp/procurement/receipts">Все накладные на поступление</Link>
  </main>;
}
