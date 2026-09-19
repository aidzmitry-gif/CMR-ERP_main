"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { AccountingInputVatRegister, type InputVatRegisterRow } from "./accounting-input-vat-register";

type VatRow = InputVatRegisterRow & { source: string; source_version: number; operation: string; opening: boolean; correction_of: number | null; account_code: string; account_title: string; dimensions: Record<string, unknown>; review_issues: string[] };
type Worksheet = { totals: Record<string, string>; rows: VatRow[]; rows_needing_metadata_review: number; rows_needing_register_review: number };
const text = (value: unknown) => typeof value === "string" || typeof value === "number" ? String(value) : "—";
const csv = (value: unknown) => { const valueText = String(value ?? ""); return /[;"\r\n]/.test(valueText) ? "\"" + valueText.replaceAll("\"", "\"\"") + "\"" : valueText; };
export function inputVatCsv(org: string, start: string, end: string, data: Worksheet) {
  const metadata = [
    ["Организация", org], ["С", start], ["По", end],
    ["Дебет, BYN", data.totals.debit], ["Кредит, BYN", data.totals.credit],
    ["Введённые остатки: дебет, BYN", data.totals.opening_debit], ["Введённые остатки: кредит, BYN", data.totals.opening_credit],
    ["Строк с неполной аналитикой", data.rows_needing_metadata_review],
    ["Без записи в реестре", data.rows_needing_register_review ?? data.rows.filter(row => !row.registered).length],
  ];
  const header = ["Entry ID", "Line ID", "Источник", "Версия", "Дата", "Сторона", "Счёт", "Сумма, BYN", "Ввод остатков", "Корректировка", "Зарегистрировано", "Статус реестра", "Проверка", "Аналитика"];
  const rows = data.rows.map(row => [row.entry_id, row.line_id, row.source, row.source_version, row.posting_date, row.side, row.account_code, row.amount, row.opening, row.correction_of ?? "", row.registered, row.deduction_status ?? "", row.review_issues.join(", "), JSON.stringify(row.dimensions)]);
  return [...metadata, [], header, ...rows].map(row => row.map(csv).join(";")).join("\r\n");
}
export function AccountingInputVat({ org, start, end, onEntry }: { org: string; start: string; end: string; onEntry: (id: number) => void }) {
  const [reload, setReload] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: Worksheet; error?: boolean } | null>(null);
  const valid = Boolean(org && start && end && start <= end);
  const key = `${org}/${start}/${end}/${reload}`;
  useEffect(() => {
    if (!valid) return;
    let active = true;
    const controller = new AbortController();
    fetch(`/api/accounting/organizations/${org}/input-vat-lines?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, { cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("Unable to load worksheet");
      const data = await response.json();
      if (active) setResult({ key, data });
    }).catch(() => { if (active) setResult({ key, error: true }); });
    return () => { active = false; controller.abort(); };
  }, [org, start, end, valid, key]);
  const current = result?.key === key ? result : null;
  const download = () => { if (!current?.data) return; const url = URL.createObjectURL(new Blob(["\uFEFF" + inputVatCsv(org, start, end, current.data)], { type: "text/csv;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = "input-vat-" + org + "-" + start + "-" + end + ".csv"; link.click(); URL.revokeObjectURL(url); };
  return <section aria-label="Ведомость входного НДС" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">Входной НДС — проверка проводок</h2><div className="flex gap-2"><Button variant="secondary" disabled={!current?.data} onClick={download}>Скачать CSV</Button><Button variant="secondary" disabled={!valid} onClick={() => setReload((value) => value + 1)}>Обновить ведомость</Button></div></div>
    <p className="text-sm text-muted">Проведённые строки счёта 18 за выбранные даты отражения. Суммы в BYN. Ниже можно сохранить отдельную запись реестра с явными основаниями; право на вычет, ЭСЧФ и налоговая отчётность автоматически не формируются.</p>
    {!org ? <p>Выберите юрлицо.</p> : !valid ? <p role="alert">Укажите корректный период.</p> : !current ? <p role="status">Загрузка ведомости…</p> : current.error ? <p role="alert">Не удалось загрузить ведомость. Проверьте доступ и повторите загрузку.</p> : current.data && <>
      <dl className="flex flex-wrap gap-6">{[["debit", "Дебет за период"], ["credit", "Кредит за период"], ["opening_debit", "Введённые остатки: дебет"], ["opening_credit", "Введённые остатки: кредит"]].map(([field, label]) => <div key={field}><dt className="text-sm text-muted">{label}</dt><dd>{current.data!.totals[field]} BYN</dd></div>)}</dl>
      <p>Строк с неполной аналитикой: {current.data.rows_needing_metadata_review}. Без записи в реестре: {current.data.rows_needing_register_review ?? current.data.rows.filter(row => !row.registered).length}. Наличие аналитики не подтверждает право на вычет.</p>
      {current.data.rows.map((row) => <article key={row.line_id} className="rounded border border-line p-3">
        <button type="button" className="text-accent underline" onClick={() => onEntry(row.entry_id)}>Операция № {row.entry_id} · {row.source}</button>
        <p>{row.posting_date} · {row.side === "debit" ? "Дт" : "Кт"} {row.account_code} · {row.amount} BYN{row.opening ? " · Ввод остатков" : ""}</p>
        <p className="text-sm">Версия источника: {row.source_version} · Ставка из аналитики: {text(row.dimensions.vat_rate)} · Основание: {text(row.dimensions.vat_basis)}</p>
        <p className="text-sm">Контрагент: {text(row.dimensions.counterparty)} · Договор: {text(row.dimensions.contract)} · Документ расчётов: {text(row.dimensions.settlement_document)}</p>
        {row.operation === "inventory_purchase" && /^procurement:receipt:\d+$/.test(row.source) && <Link className="text-accent underline" href={`/erp/procurement/receipts/posted/${row.entry_id}?org=${org}`}>Открыть первичную накладную</Link>}
        {row.correction_of && <p>Корректировка операции № {row.correction_of}</p>}
        {row.review_issues.length > 0 && <p className="text-sm text-amber-700">Проверьте ставку и основание в аналитике проводки.</p>}
        <AccountingInputVatRegister org={org} start={start} row={row} onRegistered={() => setReload((value) => value + 1)} />
      </article>)}
      {!current.data.rows.length && <p>Проводок по счёту 18 за выбранный период нет.</p>}
    </>}
  </section>;
}
