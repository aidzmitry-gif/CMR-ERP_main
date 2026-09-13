"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { AccountingOutputVatRegister, type OutputVatRegisterRow } from "./accounting-output-vat-register";

type VatRow = OutputVatRegisterRow & { source: string; source_version: number; operation: string; opening: boolean; correction_of: number | null; account_code: string; account_title: string; dimensions: Record<string, unknown>; review_issues: string[] };
type Worksheet = { totals: Record<string, string>; rows: VatRow[]; rows_needing_metadata_review: number; rows_needing_register_review: number };
const text = (value: unknown) => typeof value === "string" || typeof value === "number" ? String(value) : "—";

export function AccountingOutputVat({ org, start, end, onEntry }: { org: string; start: string; end: string; onEntry: (id: number) => void }) {
  const [reload, setReload] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: Worksheet; error?: boolean } | null>(null);
  const valid = Boolean(org && start && end && start <= end);
  const key = `${org}/${start}/${end}/${reload}`;
  useEffect(() => {
    if (!valid) return;
    let active = true;
    const controller = new AbortController();
    fetch(`/api/accounting/organizations/${org}/output-vat-lines?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, { cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("Unable to load worksheet");
      const data = await response.json();
      if (active) setResult({ key, data });
    }).catch(() => { if (active) setResult({ key, error: true }); });
    return () => { active = false; controller.abort(); };
  }, [org, start, end, valid, key]);
  const current = result?.key === key ? result : null;
  return <section aria-label="Ведомость исходящего НДС" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">Исходящий НДС — проверка проводок</h2><Button variant="secondary" disabled={!valid} onClick={() => setReload((value) => value + 1)}>Обновить ведомость</Button></div>
    <p className="text-sm text-muted">Проведённые строки счёта 90.2 за выбранные даты отражения. Ниже можно сохранить отдельную запись налогового регистра с явным обращением, ЭСЧФ и доказательствами. Проводки, выручка и отчётность автоматически не изменяются.</p>
    {!org ? <p>Выберите юрлицо.</p> : !valid ? <p role="alert">Укажите корректный период.</p> : !current ? <p role="status">Загрузка ведомости…</p> : current.error ? <p role="alert">Не удалось загрузить ведомость. Проверьте доступ и повторите загрузку.</p> : current.data && <>
      <dl className="flex flex-wrap gap-6">{[["debit", "Дебет за период"], ["credit", "Кредит за период"], ["opening_debit", "Ввод остатков: дебет"], ["opening_credit", "Ввод остатков: кредит"]].map(([field, label]) => <div key={field}><dt className="text-sm text-muted">{label}</dt><dd>{current.data!.totals[field]} BYN</dd></div>)}</dl>
      <p>Строк с неполной аналитикой: {current.data.rows_needing_metadata_review}. Без записи в реестре: {current.data.rows_needing_register_review}. Наличие аналитики не подтверждает ставку или экспорт.</p>
      {current.data.rows.map((row) => <article key={row.line_id} className="rounded border border-line p-3">
        <button type="button" className="text-accent underline" onClick={() => onEntry(row.entry_id)}>Операция № {row.entry_id} · {row.source}</button>
        <p>{row.posting_date} · {row.side === "debit" ? "Дт" : "Кт"} {row.account_code} · {row.amount} {row.currency}{row.opening ? " · Ввод остатков" : ""}</p>
        <p className="text-sm">Версия источника: {row.source_version} · Ставка из аналитики: {text(row.dimensions.vat_rate)} · Основание: {text(row.dimensions.vat_basis)}</p>
        <p className="text-sm">Контрагент: {text(row.dimensions.counterparty)} · Договор: {text(row.dimensions.contract)} · Документ расчётов: {text(row.dimensions.settlement_document)}</p>
        {row.correction_of && <p>Корректировка операции № {row.correction_of}</p>}
        {row.review_issues.length > 0 && <p className="text-sm text-amber-700">Проверьте аналитические данные и сторону проводки.</p>}
        <AccountingOutputVatRegister org={org} start={start} row={row} disabled={row.review_issues.length > 0} onRegistered={() => setReload((value) => value + 1)} />
      </article>)}
      {!current.data.rows.length && <p>Проводок по счёту 90.2 за выбранный период нет.</p>}
    </>}
  </section>;
}
