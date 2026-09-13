"use client";

import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Account = { organization_id: number; code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean; required_dimensions: string[] };
export type FinancialClosing = {
  monthly_accounts: string[]; result_account: string; retained_earnings_account: string;
  year_end_month: number; result_dimensions: Record<string, string>; retained_dimensions: Record<string, string>;
  opening_balance_treatment: "include" | "exclude"; reference: string;
};
export type ClosingSelection = { scope: string; enabled: boolean; value: FinancialClosing | null };
const codePattern = /^[0-9]+(?:\.[0-9]+)*$/;
const names: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", employee: "Сотрудник", asset: "Основное средство", department: "Подразделение", owner: "Владелец", serial: "Серийный номер" };
const months = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
function eligible(a: Account, categories: string[]) { return categories.includes(a.category) && !a.cash && !a.quantity_tracking && a.code.length <= 32 && codePattern.test(a.code); }
function validDimensions(account: Account | undefined, values: Record<string, string>) {
  return !!account && Object.keys(values).length === account.required_dimensions.length && account.required_dimensions.every(k =>
    Object.hasOwn(values, k) && k.trim().length > 0 && k.length <= 100 && !k.includes("\0") &&
    values[k].trim().length > 0 && values[k].length <= 200 && !values[k].includes("\0"));
}

/** Keyed by organization and effective date: no account choices cross that boundary. */
type FieldsProps = { org: string; effectiveDate: string; enabled: boolean; onEnabledChange: (enabled: boolean) => void; onChange: (selection: ClosingSelection) => void };
export function FinancialClosingPolicyFields(props: FieldsProps) {
  return <Fields key={`${props.org}:${props.effectiveDate}`} {...props} />;
}
function Fields({ org, effectiveDate, onChange, enabled, onEnabledChange }: FieldsProps) {
  const scope = `${org}:${effectiveDate}`;
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [loadError, setError] = useState("");
  const dateValid = /^\d{4}-\d{2}-\d{2}$/.test(effectiveDate) && Number.isFinite(Date.parse(effectiveDate)) && new Date(effectiveDate).toISOString().slice(0, 10) === effectiveDate;
  const validScope = /^[1-9]\d*$/.test(org) && dateValid;
  const error = validScope ? loadError : "Выберите организацию и календарную дату действия политики.";
  const [retry, setRetry] = useState(0);
  const [monthly, setMonthly] = useState<string[]>([]);
  const [result, setResult] = useState("");
  const [retained, setRetained] = useState("");
  const [month, setMonth] = useState("");
  const [treatment, setTreatment] = useState<"" | "include" | "exclude">("");
  const [reference, setReference] = useState("");
  const [resultDimensions, setResultDimensions] = useState<Record<string, string>>({});
  const [retainedDimensions, setRetainedDimensions] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!enabled || !validScope) return;
    let active = true;
    void (async () => {
      try {
        const response = await fetch(`/api/accounting/organizations/${org}/accounts?on=${effectiveDate}`, { cache: "no-store" });
        const data: unknown = await response.json();
        if (!response.ok) throw new Error("Не удалось загрузить рабочие счета. Проверьте доступ и повторите загрузку.");
        if (!Array.isArray(data) || data.some((a: Account) => !a || a.organization_id !== Number(org) || typeof a.code !== "string" || typeof a.title !== "string" || typeof a.category !== "string" || typeof a.cash !== "boolean" || typeof a.quantity_tracking !== "boolean" || !Array.isArray(a.required_dimensions) || a.required_dimensions.some(k => typeof k !== "string") || new Set(a.required_dimensions).size !== a.required_dimensions.length) || new Set(data.map(a => a.code)).size !== data.length) throw new Error("Ответ не подтверждает рабочие счета выбранной организации.");
        if (active) setAccounts(data);
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Не удалось загрузить счета."); }
    })();
    return () => { active = false; };
  }, [org, effectiveDate, enabled, retry, validScope]);
  function reloadAccounts() { setAccounts(null); setError(""); setRetry(n => n + 1); }
  const resultAccount = accounts?.find(a => a.code === result);
  const retainedAccount = accounts?.find(a => a.code === retained);
  const selection = useMemo<ClosingSelection>(() => {
    const codes = [...monthly, result, retained];
    const valid = accounts && monthly.length >= 1 && monthly.length <= 200 && new Set(codes).size === codes.length &&
      monthly.every(code => accounts.some(a => a.code === code && eligible(a, ["income", "expense"]))) &&
      resultAccount && eligible(resultAccount, ["income"]) && retainedAccount && eligible(retainedAccount, ["equity"]) &&
      validDimensions(resultAccount, resultDimensions) && validDimensions(retainedAccount, retainedDimensions) &&
      /^(?:[1-9]|1[0-2])$/.test(month) && (treatment === "include" || treatment === "exclude") && reference.trim().length > 0 && reference.length <= 1000;
    return { scope, enabled, value: valid ? { monthly_accounts: monthly, result_account: result, retained_earnings_account: retained, year_end_month: Number(month), result_dimensions: resultDimensions, retained_dimensions: retainedDimensions, opening_balance_treatment: treatment as "include" | "exclude", reference } : null };
  }, [scope, enabled, accounts, monthly, result, retained, resultAccount, retainedAccount, resultDimensions, retainedDimensions, month, treatment, reference]);
  useLayoutEffect(() => { onChange(selection); }, [selection, onChange]);
  function analytics(account: Account | undefined, target: string, values: Record<string, string>, change: (v: Record<string, string>) => void) {
    if (!account) return null;
    return <fieldset className="space-y-2"><legend>Аналитика {target}</legend>{account.required_dimensions.length === 0 ? <p className="text-sm text-muted">Аналитика не требуется этим счётом.</p> : account.required_dimensions.map(k => <label key={k} className="block">{names[k] || k} {target}<Input value={values[k] ?? ""} maxLength={200} onChange={e => change({ ...values, [k]: e.target.value })} /></label>)}</fieldset>;
  }
  return <div className="space-y-3 rounded-lg border border-line p-3">
    <label className="block"><input type="checkbox" checked={enabled} onChange={e => { onEnabledChange(e.target.checked); if (e.target.checked) { setAccounts(null); setError(""); } }} /> Задать настройки переноса финансового результата</label>
    <p className="text-sm text-muted">Сохраняется только конфигурация в новой версии учётной политики. Механизм месячного и годового переноса финансового результата ещё не активен. Проводки и закрытие периода не выполняются.</p>
    {enabled && <div className="space-y-3">
      {!accounts && !error && <p role="status">Загрузка рабочих счетов на дату {effectiveDate}…</p>}
      {error && <><p role="alert">{error}</p><Button variant="secondary" onClick={reloadAccounts}>Повторить загрузку счетов закрытия</Button></>}
      {accounts && accounts.length === 0 && <><p role="alert">Рабочие счета на эту дату отсутствуют. Настройте их перед утверждением политики.</p><Button variant="secondary" onClick={reloadAccounts}>Обновить счета закрытия</Button></>}
      {accounts && <>
        <fieldset className="space-y-2"><legend>Счета месячного переноса</legend><p className="text-sm">Выбрано: {monthly.length} из 200.</p><div className="flex flex-wrap gap-3">{accounts.filter(a => eligible(a, ["income", "expense"])).map(a => <label key={a.code}><input type="checkbox" checked={monthly.includes(a.code)} disabled={a.code === result || a.code === retained || (!monthly.includes(a.code) && monthly.length >= 200)} onChange={e => setMonthly(v => e.target.checked ? [...v, a.code] : v.filter(c => c !== a.code))} /> {a.code} · {a.title}</label>)}</div></fieldset>
        <label className="block">Счёт финансового результата<Select value={result} onChange={e => { setResult(e.target.value); setResultDimensions({}); }}><option value="">Выберите счёт</option>{accounts.filter(a => eligible(a, ["income"])).map(a => <option key={a.code} value={a.code} disabled={monthly.includes(a.code) || a.code === retained}>{a.code} · {a.title}</option>)}</Select></label>
        <label className="block">Счёт накопленного результата<Select value={retained} onChange={e => { setRetained(e.target.value); setRetainedDimensions({}); }}><option value="">Выберите счёт</option>{accounts.filter(a => eligible(a, ["equity"])).map(a => <option key={a.code} value={a.code} disabled={monthly.includes(a.code) || a.code === result}>{a.code} · {a.title}</option>)}</Select></label>
        {analytics(resultAccount, "счёта финансового результата", resultDimensions, setResultDimensions)}
        {analytics(retainedAccount, "счёта накопленного результата", retainedDimensions, setRetainedDimensions)}
        <label className="block">Месяц окончания финансового года<Select value={month} onChange={e => setMonth(e.target.value)}><option value="">Выберите месяц</option>{months.map((name, i) => <option key={name} value={i + 1}>{name}</option>)}</Select></label>
        <label className="block">Начальные остатки в расчёте переноса<Select value={treatment} onChange={e => setTreatment(e.target.value as typeof treatment)}><option value="">Выберите правило</option><option value="include">Включать</option><option value="exclude">Исключать</option></Select></label>
        <p className="text-sm text-muted">Выберите правило утверждаемой политики. Этот выбор не выполняет перенос.</p>
        <label className="block">Основание настроек переноса<textarea className="w-full rounded border border-line p-2" maxLength={1000} value={reference} onChange={e => setReference(e.target.value)} /></label>
        {!selection.value && <p className="text-sm text-muted">Для утверждения заполните настройки и аналитику всех выбранных целевых счетов. Роли счетов не должны повторяться.</p>}
      </>}
    </div>}
  </div>;
}
