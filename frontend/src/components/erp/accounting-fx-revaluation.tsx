"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Policy = { id: number; effective_from: string; normative_verified: boolean; currency_revaluation?: { monetary_accounts: string[]; gain_account: string; loss_account: string; gain_dimensions: Record<string, string>; loss_dimensions: Record<string, string>; reference: string; settlement_allocation?: "proportional_carrying"; settlement_rate_date?: "posting_date" } | null };
type Rate = { currency: string; rate: string; rate_scale: string; rate_date: string; rate_source: string };
type Plan = { basis_digest: string; digest: string; period_generation: number; source_line_count: number; adjustments: { account: string; currency: string; original_balance: string; book_balance: string; revalued_balance: string; delta: string; counterpart: string; monetary_side: string; counterpart_side: string }[]; posting_document: { lines: { account: string; side: string; amount: string }[] } | null; confirmation_available: boolean; normative_verified: boolean; statutory_certified: boolean };
type Account = { code: string; title: string; required_dimensions: string[] };
type SettlementPlan = { status: "preview_only"; posting_available: false; basis_digest: string; original_balance: string; book_balance: string; allocated_book_amount: string; documentary_amount: string; exchange_difference: string; difference_account: string | null; difference_side: string | null; remaining_original: string; remaining_book_amount: string };

function lastDay(month: string) {
  const [year, value] = month.split("-").map(Number);
  return new Date(Date.UTC(year, value, 0)).toISOString().slice(0, 10);
}

function requestKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `fx-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function AccountingFxRevaluation({ org, month, date, policy, disabled, onEntry }: { org: string; month: string; date: string; policy?: Policy; disabled?: boolean; onEntry?: (id: number) => void }) {
  return <FxRevaluationForm key={`${org}:${month}:${date}:${policy?.id}`} org={org} month={month} date={date} policy={policy} disabled={disabled} onEntry={onEntry} />;
}

function FxRevaluationForm({ org, month, date, policy, disabled, onEntry }: { org: string; month: string; date: string; policy?: Policy; disabled?: boolean; onEntry?: (id: number) => void }) {
  const [rates, setRates] = useState<Rate[]>([{ currency: "USD", rate: "", rate_scale: "1", rate_date: lastDay(month), rate_source: "" }]);
  const [generation, setGeneration] = useState(0);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [key, setKey] = useState(requestKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [settlementAccounts, setSettlementAccounts] = useState<Account[] | null>(null);
  const [settlement, setSettlement] = useState({ account: "", dimensions: {} as Record<string, string>, amount: "", currency: "USD", rate: "", rate_scale: "1", rate_source: "" });
  const [settlementPlan, setSettlementPlan] = useState<SettlementPlan | null>(null);
  const [settlementBusy, setSettlementBusy] = useState(false);
  const [settlementError, setSettlementError] = useState("");
  const settlementRequest = useRef(0);
  const settlementDate = date;
  const settlementConfigured = policy?.currency_revaluation?.settlement_allocation === "proportional_carrying" && policy.currency_revaluation.settlement_rate_date === "posting_date";

  useEffect(() => {
    let active = true;
    if (!org) return () => { active = false; };
    fetch(`/api/accounting/organizations/${org}/periods`, { cache: "no-store" }).then((response) => response.ok ? response.json() : Promise.reject(new Error("Не удалось загрузить поколения периодов."))).then((rows: { month: string; generation: number }[]) => {
      if (active) setGeneration(rows.find((row) => row.month === month)?.generation ?? 0);
    }).catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [month, org]);

  const monthEnd = useMemo(() => lastDay(month), [month]);
  const ready = !!org && !!policy?.currency_revaluation && !!policy.id && !disabled && !busy;
  const settlementReady = !!org && !!policy?.id && settlementConfigured && !disabled && !settlementBusy;
  const invalidate = () => { setPlan(null); setNotice(""); setKey(requestKey()); };
  const invalidateSettlement = () => { settlementRequest.current += 1; setSettlementPlan(null); setSettlementError(""); };
  const update = (index: number, patch: Partial<Rate>) => {
    invalidate();
    setRates((current) => current.map((rate, row) => {
      if (row !== index) return rate;
      if (patch.currency !== undefined || patch.rate_date !== undefined) {
        return { ...rate, ...patch, rate: "", rate_source: "" };
      }
      const editedOfficial = patch.rate_source === undefined && (patch.rate !== undefined || patch.rate_scale !== undefined) && rate.rate_source.startsWith("НБРБ ");
      return { ...rate, ...patch, ...(editedOfficial ? { rate_source: "" } : {}) };
    }));
  };

  useEffect(() => {
    if (!settlementConfigured || !org || !settlementDate) return;
    const controller = new AbortController();
    fetch(`/api/accounting/organizations/${org}/accounts?on=${encodeURIComponent(settlementDate)}`, { signal: controller.signal, cache: "no-store" })
      .then(async (response) => { if (!response.ok) throw new Error("Не удалось загрузить денежные счета для погашения."); return response.json() as Promise<Account[]>; })
      .then((rows) => { if (!controller.signal.aborted) setSettlementAccounts(rows); })
      .catch((reason) => { if (!controller.signal.aborted) setSettlementError((reason as Error).message); });
    return () => controller.abort();
  }, [org, settlementConfigured, settlementDate]);

  async function loadOfficialRate(index: number) {
    const requested = rates[index];
    invalidate(); setBusy(true); setError("");
    try {
      const response = await fetch(`/api/system/fx/${encodeURIComponent(requested.currency)}?on=${encodeURIComponent(requested.rate_date)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "Не удалось получить курс НБРБ.");
      if (!data || data.currency !== requested.currency || data.date !== requested.rate_date || data.source !== "NBRB"
        || typeof data.official_rate !== "string" || !/^\d+(\.\d+)?$/.test(data.official_rate)
        || !Number.isFinite(Number(data.official_rate)) || Number(data.official_rate) <= 0
        || !Number.isSafeInteger(data.scale) || data.scale <= 0) {
        throw new Error("Ответ НБРБ не соответствует выбранной валюте и дате либо содержит неверный курс.");
      }
      update(index, { rate: data.official_rate, rate_scale: String(data.scale), rate_source: `НБРБ ${data.currency} ${data.date}` });
      setNotice("Курс НБРБ загружен. Проверьте его перед расчётом переоценки.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function preview() {
    if (!policy?.currency_revaluation) { setError("В политике нет явной настройки валютной переоценки."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/fx-revaluation-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_key: key, policy_id: policy.id, posting_date: monthEnd, expected_generation: generation, rates: rates.map((rate) => ({ ...rate, rate_scale: Number(rate.rate_scale) })), evidence: "Проверка бухгалтером документированных курсов" }), cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось рассчитать переоценку.");
      setPlan(data);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  const settlementAccount = settlementAccounts?.find((account) => account.code === settlement.account);
  const eligibleSettlementAccounts = (settlementAccounts || []).filter((account) => policy?.currency_revaluation?.monetary_accounts.includes(account.code));
  const settlementComplete = !!settlementAccount && Number.isFinite(Number(settlement.amount)) && Number(settlement.amount) > 0 && Number.isFinite(Number(settlement.rate)) && Number(settlement.rate) > 0 && Number.isSafeInteger(Number(settlement.rate_scale)) && Number(settlement.rate_scale) > 0 && settlement.rate_source.trim().length >= 10 && settlementAccount.required_dimensions.every((key) => settlement.dimensions[key]?.trim());
  function updateSettlement(patch: Partial<typeof settlement>) {
    invalidateSettlement();
    setSettlement((current) => ({ ...current, ...patch, ...(patch.currency !== undefined && patch.currency !== current.currency ? { rate: "", rate_source: "" } : {}) }));
  }
  async function previewSettlement() {
    if (!policy?.id || !settlementConfigured || !settlementComplete) return;
    const currentRequest = ++settlementRequest.current;
    setSettlementBusy(true); setSettlementError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/fx-settlement/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ policy_id: policy.id, posting_date: settlementDate, account: settlement.account, dimensions: settlement.dimensions, amount: settlement.amount, rate: { currency: settlement.currency, rate: settlement.rate, rate_scale: Number(settlement.rate_scale), rate_date: settlementDate, rate_source: settlement.rate_source.trim() } }), cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось рассчитать валютное погашение.");
      if (currentRequest === settlementRequest.current) setSettlementPlan(data as SettlementPlan);
    } catch (reason) { if (currentRequest === settlementRequest.current) setSettlementError((reason as Error).message); }
    finally { if (currentRequest === settlementRequest.current) setSettlementBusy(false); }
  }

  async function confirm() {
    if (!plan || !policy) return;
    setBusy(true); setError(""); setNotice("");
    const body = { request_key: key, policy_id: policy.id, posting_date: monthEnd, expected_generation: plan.period_generation, rates: rates.map((rate) => ({ ...rate, rate_scale: Number(rate.rate_scale) })), evidence: "Проверка бухгалтером документированных курсов", basis_digest: plan.basis_digest, digest: plan.digest };
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/fx-revaluation-confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Подтверждение переоценки отклонено.");
      setNotice(`Пакет переоценки сохранён${data.entry_id ? `, проводка №${data.entry_id}` : " без корректирующей суммы"}.`);
      if (data.entry_id) onEntry?.(data.entry_id);
    } catch (reason) {
      try {
        const recovery = await fetch(`/api/accounting/organizations/${org}/periods/${month}/fx-revaluation/${encodeURIComponent(key)}`, { cache: "no-store" });
        if (recovery.ok) { const saved = await recovery.json(); setNotice(`Результат подтверждения восстановлен${saved.entry_id ? `, проводка №${saved.entry_id}` : ""}.`); if (saved.entry_id) onEntry?.(saved.entry_id); return; }
      } catch { /* keep the original actionable error */ }
      setError((reason as Error).message);
    } finally { setBusy(false); }
  }

  if (!policy?.currency_revaluation) return <section className="rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Валютная переоценка</h2><p className="mt-2 text-sm text-muted">В действующей политике нет явных денежных счетов, счетов дохода/расхода и основания курса. Автоматический выбор не выполняется.</p></section>;
  return <section aria-label="Валютная переоценка" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div><h2 className="font-semibold">Валютная переоценка · {month}</h2><p className="mt-1 text-sm text-muted">Счета: {policy.currency_revaluation.monetary_accounts.join(", ")}; доход: {policy.currency_revaluation.gain_account}; расход: {policy.currency_revaluation.loss_account}. Курс вводится с датой и источником, без резерва.</p></div>
    {rates.map((rate, index) => <fieldset key={index} disabled={!ready} className="grid gap-3 rounded-lg border border-line p-3 md:grid-cols-5"><legend className="text-sm">Курс {index + 1}</legend><label>Валюта<Select aria-label={`Валюта курса ${index + 1}`} value={rate.currency} onChange={(event) => update(index, { currency: event.target.value })}><option value="USD">USD</option><option value="EUR">EUR</option><option value="RUB">RUB</option><option value="CNY">CNY</option></Select></label><label>Курс<Input aria-label={`Курс ${index + 1}`} inputMode="decimal" value={rate.rate} onChange={(event) => update(index, { rate: event.target.value })} placeholder="3.2000" /></label><label>Масштаб<Input aria-label={`Масштаб курса ${index + 1}`} type="number" min="1" step="1" value={rate.rate_scale} onChange={(event) => update(index, { rate_scale: event.target.value })} /></label><label>Дата курса<Input aria-label={`Дата курса ${index + 1}`} type="date" value={rate.rate_date} max={monthEnd} onChange={(event) => update(index, { rate_date: event.target.value })} /></label><label>Источник<Input aria-label={`Источник курса ${index + 1}`} value={rate.rate_source} onChange={(event) => update(index, { rate_source: event.target.value })} placeholder="Документ/ссылка" /></label><Button variant="secondary" onClick={() => void loadOfficialRate(index)}>Получить курс НБРБ {index + 1}</Button>{rates.length > 1 && <Button variant="ghost" onClick={() => { invalidate(); setRates((current) => current.filter((_, row) => row !== index)); }}>Удалить курс</Button>}</fieldset>)}
    <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={!ready || rates.length >= 20} onClick={() => { invalidate(); setRates((current) => [...current, { currency: "EUR", rate: "", rate_scale: "1", rate_date: monthEnd, rate_source: "" }]); }}>Добавить курс</Button><Button disabled={!ready} onClick={() => void preview()}>Рассчитать переоценку</Button></div>
    {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}{notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}
    {plan && <div className="space-y-2 rounded-xl border border-accent p-4"><p className="text-sm">Источников: {plan.source_line_count}; изменений: {plan.adjustments.length}. Предварительный расчёт, не проведён.</p>{plan.adjustments.map((row) => <div key={`${row.account}-${row.currency}-${row.original_balance}`} className="border-t border-line pt-2 text-sm"><p>{row.account} {row.currency}: {row.book_balance} → {row.revalued_balance} BYN · разница {row.delta} · {row.counterpart}</p><p className="text-muted">{row.monetary_side === "debit" ? "Дт" : "Кт"} денежного счёта, {row.counterpart_side === "debit" ? "Дт" : "Кт"} результата</p></div>)}{!plan.adjustments.length && <p className="text-sm text-muted">Курсовых разниц нет.</p>}{!plan.confirmation_available && <p className="text-sm text-muted">Нормативная база политики не подтверждена: запись заблокирована.</p>}<Button className="mt-2" disabled={!plan.confirmation_available || busy || disabled} onClick={() => void confirm()}>Подтвердить пакет</Button></div>}
    <section aria-label="Предварительный расчёт валютного погашения" className="space-y-3 rounded-xl border border-line p-4"><div><h3 className="font-semibold">Предварительный расчёт валютного погашения</h3><p className="mt-1 text-sm text-muted">Расчёт не создаёт банковский платёж и не формирует проводки.</p></div>
      {!settlementConfigured && <p className="text-sm text-muted">В действующей политике не заданы явные методы распределения и даты курса для валютного погашения.</p>}
      {settlementConfigured && <><div className="grid gap-3 md:grid-cols-3"><p className="text-sm">Дата отражения: {settlementDate}</p><label>Денежный счёт<Select aria-label="Денежный счёт валютного погашения" value={settlement.account} disabled={!settlementReady} onChange={(event) => updateSettlement({ account: event.target.value, dimensions: {} })}><option value="">Выберите счёт</option>{eligibleSettlementAccounts.map((account) => <option key={account.code} value={account.code}>{account.code} · {account.title}</option>)}</Select></label><label>Сумма погашения в валюте<Input aria-label="Сумма валютного погашения" inputMode="decimal" value={settlement.amount} disabled={!settlementReady} placeholder="0.00" onChange={(event) => updateSettlement({ amount: event.target.value })} /></label></div>
        {settlementAccount?.required_dimensions.map((key) => <label key={key} className="block text-sm">Аналитика: {key}<Input aria-label={`Аналитика валютного погашения: ${key}`} value={settlement.dimensions[key] || ""} disabled={!settlementReady} onChange={(event) => updateSettlement({ dimensions: { ...settlement.dimensions, [key]: event.target.value } })} /></label>)}
        <div className="grid gap-3 md:grid-cols-4"><label>Валюта<Select aria-label="Валюта валютного погашения" value={settlement.currency} disabled={!settlementReady} onChange={(event) => updateSettlement({ currency: event.target.value })}><option value="USD">USD</option><option value="EUR">EUR</option><option value="RUB">RUB</option><option value="CNY">CNY</option></Select></label><label>Документированный курс<Input aria-label="Курс валютного погашения" inputMode="decimal" value={settlement.rate} disabled={!settlementReady} placeholder="3.2000" onChange={(event) => updateSettlement({ rate: event.target.value })} /></label><label>Масштаб курса<Input aria-label="Масштаб курса валютного погашения" type="number" min="1" step="1" value={settlement.rate_scale} disabled={!settlementReady} onChange={(event) => updateSettlement({ rate_scale: event.target.value })} /></label><label>Источник курса<Input aria-label="Источник курса валютного погашения" value={settlement.rate_source} disabled={!settlementReady} placeholder="Документ / ссылка" onChange={(event) => updateSettlement({ rate_source: event.target.value })} /></label></div>
        <Button disabled={!settlementReady || !settlementComplete} onClick={() => void previewSettlement()}>{settlementBusy ? "Рассчитываем…" : "Рассчитать погашение"}</Button>{settlementError && <p role="alert" className="text-sm text-rose-700">{settlementError}</p>}{settlementPlan && <div className="space-y-1 rounded-lg border border-accent p-3 text-sm"><p className="font-medium">Предварительный расчёт — проведение недоступно.</p><p>Балансовая стоимость позиции: {settlementPlan.book_balance} BYN; к погашению: {settlementPlan.allocated_book_amount} BYN.</p><p>По документированному курсу: {settlementPlan.documentary_amount} BYN; курсовая разница: {settlementPlan.exchange_difference} BYN{settlementPlan.difference_account ? ` · ${settlementPlan.difference_side === "debit" ? "Дт" : "Кт"} ${settlementPlan.difference_account}` : ""}.</p><p>Остаток: {settlementPlan.remaining_original} {settlement.currency}; {settlementPlan.remaining_book_amount} BYN.</p></div>}</>}
    </section>
  </section>;
}
