"use client";
import { Button } from "@/components/ui/button";

export type AccountMovement = { entry_id: number; line_id: number; source: string; date: string; account: string; side: string; amount: string; currency: string; ledger_currency?: string; valuation_only?: boolean; dimensions: Record<string, string> };
export type AccountBalance = { account: string; title: string; currency: string; dimensions: Record<string, string>; opening: string; debit: string; credit: string; closing: string };

export function AccountingAccountActivity({ row, movements, openingMovements, onEntry, onClose }: { row: AccountBalance; movements: AccountMovement[]; openingMovements?: AccountMovement[]; onEntry: (id: number) => void; onClose: () => void }) {
  const keys = Object.keys(row.dimensions);
  const matches = (m: AccountMovement) => m.account === row.account && m.currency === row.currency && Object.keys(m.dimensions).length === keys.length && keys.every((key) => m.dimensions[key] === row.dimensions[key]);
  const matching = movements.filter(matches);
  const opening = openingMovements?.filter(matches);
  return <section aria-label="Обороты счёта" className="rounded-xl border border-accent bg-surface p-4">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">Обороты счёта {row.account} · {row.title}</h2><Button variant="secondary" onClick={onClose}>Закрыть обороты</Button></div>
    <p className="my-2 text-sm text-muted">Валюта аналитического учёта: {row.currency}. Сальдо и суммы проводок ниже — в BYN.</p>
    <dl className="flex flex-wrap gap-5">{[["Начальное сальдо", row.opening], ["Дебет", row.debit], ["Кредит", row.credit], ["Конечное сальдо", row.closing]].map(([label, value]) => <div key={label}><dt className="text-sm text-muted">{label}</dt><dd className="tabular-nums">{value}</dd></div>)}</dl>
    <p className="my-3 text-sm text-muted">Показаны проводки выбранного периода с точным совпадением аналитики строки ОСВ. Операции начального сальдо в этот список не входят.</p>
    <details className="my-3"><summary className="cursor-pointer text-accent">Проводки начального сальдо</summary>{opening === undefined ? <p>Расшифровка не получена. Обновите отчёт.</p> : opening.length ? opening.map((m) => <p key={m.line_id} className="py-2"><button className="text-accent underline" onClick={() => onEntry(m.entry_id)}>№ {m.entry_id} · {m.source}</button> · {m.date} · {m.side === "debit" ? "Дт" : "Кт"} {m.account} · {m.amount} BYN{m.valuation_only && " · Переоценка"}</p>) : <p>Начальное сальдо не содержит проводок.</p>}</details>
    {matching.map((m) => <div key={m.line_id} className="flex flex-wrap justify-between gap-3 border-t border-line py-2"><button className="text-accent underline" onClick={() => onEntry(m.entry_id)}>№ {m.entry_id} · {m.source}</button><span>{m.date} · {m.side === "debit" ? "Дт" : "Кт"} {m.account} · {m.amount} BYN{m.valuation_only && " · Переоценка"}</span></div>)}
    {!matching.length && <p>Оборотов по этой аналитике в выбранном периоде нет.</p>}
  </section>;
}
