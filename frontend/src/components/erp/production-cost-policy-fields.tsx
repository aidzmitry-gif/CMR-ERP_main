"use client";
import { useEffect, useLayoutEffect, useState } from "react";
import { Select } from "@/components/ui/input";
type Account = { organization_id: number; code: string; title: string; category: string;
  required_dimensions: string[]; cash: boolean; currency_tracking: boolean; quantity_tracking: boolean };
type Settings = { overhead_accounts: string[]; wip_account: string; pool_dimensions: string[];
  order_dimension: "order"; rounding: "largest_remainder_cent"; reference: string; finished_goods_account?: string };
export type ProductionCostSelection = { scope: string; enabled: boolean; value: Settings | null };
type Props = { org: string; effectiveDate: string; onChange: (value: ProductionCostSelection) => void };
export function ProductionCostPolicyFields(props: Props) {
  return <Fields key={`${props.org}:${props.effectiveDate}`} {...props} />;
}
function Fields({ org, effectiveDate, onChange }: Props) {
  const scope = `${org}:${effectiveDate}`;
  const [enabled, setEnabled] = useState(false), [accounts, setAccounts] = useState<Account[] | null>(null);
  const [error, setError] = useState(""), [retry, setRetry] = useState(0);
  const [pool, setPool] = useState(""), [wip, setWip] = useState(""), [finishedGoods, setFinishedGoods] = useState("");
  const [overhead, setOverhead] = useState<string[]>([]), [rounding, setRounding] = useState("");
  const [reference, setReference] = useState("");
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setAccounts(null); setError("");
    void (async () => {
      try {
        if (!/^[1-9]\d*$/.test(org) || !/^\d{4}-\d{2}-\d{2}$/.test(effectiveDate)
          || !Number.isFinite(Date.parse(effectiveDate)) || new Date(effectiveDate).toISOString().slice(0, 10) !== effectiveDate)
          throw new Error("Выберите юрлицо и дату политики.");
        const response = await fetch(`/api/accounting/organizations/${org}/accounts?on=${effectiveDate}`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Не удалось загрузить счета производства.");
        const rows: Account[] = await response.json();
        if (!Array.isArray(rows) || rows.some(a => String(a.organization_id) !== org || !Array.isArray(a.required_dimensions)))
          throw new Error("Справочник счетов не соответствует юрлицу.");
        if (!controller.signal.aborted) setAccounts(rows);
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    })();
    return () => controller.abort();
  }, [enabled, org, effectiveDate, retry]);
  function eligible(a: Account, isWip: boolean) {
    const dimensions = [...(pool === "department" ? ["department"] : []), ...(isWip ? ["order"] : [])].sort();
    return !!pool && (isWip ? a.category === "asset" : ["asset", "expense"].includes(a.category))
      && a.cash === false && a.currency_tracking === false && a.quantity_tracking === false
      && /^[0-9]+(?:\.[0-9]+)*$/.test(a.code) && a.code.length <= 32
      && [...a.required_dimensions].sort().join() === dimensions.join();
  }
  const wipOptions = (accounts ?? []).filter(a => eligible(a, true));
  const overheadOptions = (accounts ?? []).filter(a => eligible(a, false) && a.code !== wip);
  const finishedGoodsOptions = (accounts ?? []).filter(a => a.category === "asset" && a.quantity_tracking
    && !a.cash && !a.currency_tracking && /^[0-9]+(?:\.[0-9]+)*$/.test(a.code) && a.code !== wip);
  const ready = !!accounts && !error && wipOptions.some(a => a.code === wip) && overhead.length > 0
    && overhead.every(code => overheadOptions.some(a => a.code === code)) && rounding === "largest_remainder_cent"
    && reference.trim().length >= 10 && reference.trim().length <= 1000;
  const signature = JSON.stringify({ scope, enabled, value: ready ? { overhead_accounts: overhead, wip_account: wip,
    pool_dimensions: pool === "department" ? ["department"] : [], order_dimension: "order", rounding, reference: reference.trim(),
    ...(finishedGoods ? { finished_goods_account: finishedGoods } : {}) } : null });
  useLayoutEffect(() => { onChange(JSON.parse(signature) as ProductionCostSelection); }, [signature, onChange]);
  return <fieldset className="min-w-0 space-y-2 rounded-lg border border-line p-3">
    <legend>Производственные затраты</legend>
    <label className="block"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> Настроить затраты производства</label>
    {enabled && <>
      <p className="text-sm">Используется база распределения из этой политики. Настройка не означает, что себестоимость рассчитана.</p>
      {error && <p role="alert">{error} <button type="button" onClick={() => setRetry(v => v + 1)}>Повторить загрузку счетов</button></p>}
      <Select aria-label="Группировка производственных затрат" value={pool} onChange={e => { setPool(e.target.value); setWip(""); setOverhead([]); }}>
        <option value="">Выберите группировку</option><option value="department">По подразделениям</option><option value="organization">По юрлицу целиком</option>
      </Select>
      <Select aria-label="Счёт НЗП" value={wip} onChange={e => { setWip(e.target.value); setOverhead([]); }}>
        <option value="">Выберите счёт НЗП</option>{wipOptions.map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}
      </Select>
      <Select aria-label="Счёт готовой продукции" value={finishedGoods} onChange={e => setFinishedGoods(e.target.value)}>
        <option value="">Счёт готовой продукции не настроен</option>{finishedGoodsOptions.map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}
      </Select>
      <p className="text-sm text-muted">Счёт готовой продукции выбирается явно. Без него перенос НЗП в готовую продукцию останется только предварительным просмотром.</p>
      <p>Счета накладных расходов</p>
      {overheadOptions.map(a => <label className="block" key={a.code}><input type="checkbox" checked={overhead.includes(a.code)} onChange={e => setOverhead(e.target.checked ? [...overhead, a.code] : overhead.filter(code => code !== a.code))} /> {a.code} · {a.title}</label>)}
      {accounts && pool && (!wipOptions.length || !overheadOptions.length) && <p>Нет подходящих счетов. Проверьте рабочий план: НЗП требует аналитику заказа, а выбранная группировка — аналитику подразделения.</p>}
      <Select aria-label="Округление производственных затрат" value={rounding} onChange={e => setRounding(e.target.value)}><option value="">Выберите округление</option><option value="largest_remainder_cent">До копеек, остаток по наибольшим долям</option></Select>
      <label className="block">Основание распределения производственных затрат<textarea className="mt-1 block min-h-24 w-full rounded-lg border border-line bg-white p-3" value={reference} maxLength={1000} placeholder="Пункт учётной политики / инструкция" onChange={e => setReference(e.target.value)} /></label>
      {ready && <div className="space-y-1 text-sm" aria-label="Выбранные настройки производственных затрат">
        <p>НЗП: {wip} · {wipOptions.find(a => a.code === wip)?.title}</p>
        {finishedGoods && <p>Готовая продукция: {finishedGoods} · {finishedGoodsOptions.find(a => a.code === finishedGoods)?.title}</p>}
        <p>Накладные расходы: {overhead.map(code => `${code} · ${overheadOptions.find(a => a.code === code)?.title}`).join('; ')}</p>
        <p>Округление: до копеек, остаток распределяется по наибольшим долям.</p>
      </div>}
    </>}
  </fieldset>;
}
