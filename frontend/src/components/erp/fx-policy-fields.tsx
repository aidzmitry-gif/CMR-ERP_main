"use client";
import { useEffect, useMemo, useState } from "react";
import { Input, Select } from "@/components/ui/input";

type Account = { code: string; title: string; category: string; cash: boolean; currency_tracking: boolean; quantity_tracking: boolean; required_dimensions: string[] };
export type FxPolicyValue = { monetary_accounts: string[]; gain_account: string; loss_account: string; gain_dimensions: Record<string, string>; loss_dimensions: Record<string, string>; reference: string; settlement_allocation?: "proportional_carrying"; settlement_rate_date?: "posting_date" };
export type FxPolicySelection = { scope: string; enabled: boolean; value: FxPolicyValue | null };

export function FxPolicyFields({ org, effectiveDate, onChange }: { org: string; effectiveDate: string; onChange: (value: FxPolicySelection) => void }) {
  const [enabled, setEnabled] = useState(false);
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [error, setError] = useState("");
  const [monetary, setMonetary] = useState<string[]>([]);
  const [gain, setGain] = useState("");
  const [loss, setLoss] = useState("");
  const [gainDimensions, setGainDimensions] = useState<Record<string, string>>({});
  const [lossDimensions, setLossDimensions] = useState<Record<string, string>>({});
  const [reference, setReference] = useState("");
  const [settlement, setSettlement] = useState(false);
  const [allocation, setAllocation] = useState("");
  const [rateDate, setRateDate] = useState("");
  useEffect(() => {
    if (!enabled || !org || !effectiveDate) return;
    const controller = new AbortController();
    fetch(`/api/accounting/organizations/${org}/accounts?on=${effectiveDate}`, { signal: controller.signal, cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error("Не удалось загрузить счета валютной политики."); return response.json() as Promise<Account[]>; })
      .then((rows) => { if (!controller.signal.aborted) { setAccounts(rows); setError(""); } })
      .catch((reason) => { if (!controller.signal.aborted) { setAccounts(null); setError(String(reason.message || reason)); } });
    return () => controller.abort();
  }, [enabled, org, effectiveDate]);
  const eligible = useMemo(() => (accounts || []).filter((a) => !a.cash && !a.quantity_tracking), [accounts]);
  const monetaryOptions = useMemo(() => eligible.filter((a) => a.currency_tracking && ["asset", "liability"].includes(a.category)), [eligible]);
  const gains = useMemo(() => eligible.filter((a) => !a.currency_tracking && a.category === "income"), [eligible]);
  const losses = useMemo(() => eligible.filter((a) => !a.currency_tracking && a.category === "expense"), [eligible]);
  const value = useMemo<FxPolicyValue | null>(() => {
    const g = gains.find((a) => a.code === gain), l = losses.find((a) => a.code === loss);
    if (!enabled || !accounts || !monetary.length || monetary.some((code) => !monetaryOptions.some((a) => a.code === code))
      || !g || !l || reference.trim().length < 10
      || g.required_dimensions.some((key) => !gainDimensions[key]?.trim()) || l.required_dimensions.some((key) => !lossDimensions[key]?.trim())
      || (settlement && (allocation !== "proportional_carrying" || rateDate !== "posting_date"))) return null;
    return { monetary_accounts: monetary, gain_account: gain, loss_account: loss,
      gain_dimensions: Object.fromEntries(g.required_dimensions.map((key) => [key, gainDimensions[key].trim()])),
      loss_dimensions: Object.fromEntries(l.required_dimensions.map((key) => [key, lossDimensions[key].trim()])), reference: reference.trim(),
      ...(settlement ? { settlement_allocation: "proportional_carrying" as const, settlement_rate_date: "posting_date" as const } : {}) };
  }, [enabled, accounts, monetary, monetaryOptions, gains, losses, gain, loss, reference, gainDimensions, lossDimensions, settlement, allocation, rateDate]);
  useEffect(() => { onChange({ scope: `${org}:${effectiveDate}`, enabled, value }); }, [org, effectiveDate, enabled, value, onChange]);
  return <fieldset className="space-y-3 rounded-lg border border-line p-3">
    <legend>Валютный учёт</legend>
    <label><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Настроить валютную переоценку</label>
    {enabled && <>
      <p className="text-sm text-muted">Настройки сохраняются в новой версии политики. Выберите методы действующей политики; значения не подставляются автоматически.</p>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {!accounts && !error && <p role="status">Загрузка счетов…</p>}
      <div><p>Денежные счета расчётов</p>{monetaryOptions.map((a) => <label key={a.code} className="mr-4 inline-block"><input type="checkbox" checked={monetary.includes(a.code)} onChange={(e) => setMonetary(e.target.checked ? [...monetary, a.code] : monetary.filter((code) => code !== a.code))} /> {a.code} · {a.title}</label>)}</div>
      {[{ label: "Доход от курсовых разниц", selected: gain, options: gains, set: setGain, dimensions: gainDimensions, setDimensions: setGainDimensions },
        { label: "Расход от курсовых разниц", selected: loss, options: losses, set: setLoss, dimensions: lossDimensions, setDimensions: setLossDimensions }].map((role) => <div key={role.label}>
          <label>{role.label}<Select aria-label={role.label} value={role.selected} onChange={(e) => { role.set(e.target.value); role.setDimensions({}); }}><option value="">Выберите счёт</option>{role.options.map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>
          {role.options.find((a) => a.code === role.selected)?.required_dimensions.map((key) => <label key={key}>{role.label}: {key}<Input aria-label={`${role.label}: ${key}`} maxLength={200} value={role.dimensions[key] || ""} onChange={(e) => role.setDimensions({ ...role.dimensions, [key]: e.target.value })} /></label>)}
        </div>)}
      <label>Основание валютной политики<Input aria-label="Основание валютной политики" maxLength={1000} value={reference} onChange={(e) => setReference(e.target.value)} /></label>
      <label><input type="checkbox" checked={settlement} onChange={(e) => setSettlement(e.target.checked)} /> Настроить предварительный расчёт валютного погашения</label>
      {settlement && <div className="space-y-2">
        <label>Распределение балансовой стоимости<Select aria-label="Распределение балансовой стоимости" value={allocation} onChange={(e) => setAllocation(e.target.value)}><option value="">Выберите метод</option><option value="proportional_carrying">Пропорционально погашаемой сумме валюты</option></Select></label>
        <label>Дата курса погашения<Select aria-label="Дата курса погашения" value={rateDate} onChange={(e) => setRateDate(e.target.value)}><option value="">Выберите правило</option><option value="posting_date">Дата отражения операции</option></Select></label>
        <p className="text-sm text-muted">Доступен предварительный расчёт. Проведение валютного банковского платежа ещё не включено.</p>
      </div>}
    </>}
  </fieldset>;
}
