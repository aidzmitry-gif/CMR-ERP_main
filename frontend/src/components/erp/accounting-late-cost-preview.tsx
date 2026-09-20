"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AccountingLateCostAccounts } from "./accounting-late-cost-accounts";
import type { LateCostPending } from "@/lib/late-cost-journal";

type Policy = { id: number; effective_from: string; reference: string; late_cost_allocation: { basis: string; rounding: string } | null };
type Conversion = { currency: string; rate: string; rate_scale: number; rate_date: string; rate_source: string };
type Share = { receipt_id: number; version: number; line_number: number; destination: "remaining" | "disposed" | "production"; quantity: string; amount_byn: string };
type Result = { organization_id: number; expense_id: number; source_version: number; policy_id: number; basis_digest: string;
  posted: boolean; confirmation_available: boolean; inventory_method: "specific" | "fifo" | "weighted_average";
  shares: Share[]; normative_verified: boolean; totals_byn: Record<string, string> };
const labels = { remaining: "Остаток", disposed: "Выбытие", production: "Производство" };

export function AccountingLateCostPreview({ org, expenseId, version, initialDate, disabled, currency, onPrepared }: {
  org: string; expenseId: number; version: number; initialDate: string; disabled: boolean; currency?: string; onPrepared?: (command: LateCostPending | null) => void;
}) {
  const [date, setDate] = useState(initialDate), [amount, setAmount] = useState(""), [excluded, setExcluded] = useState("");
  const [rate, setRate] = useState(""), [rateScale, setRateScale] = useState("1"), [rateDate, setRateDate] = useState(initialDate), [rateSource, setRateSource] = useState("");
  const [evidence, setEvidence] = useState(""), [policies, setPolicies] = useState<Policy[]>([]), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [result, setResult] = useState<{ key: string; data: Result } | null>(null);
  const request = useRef<AbortController | null>(null), running = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`/api/accounting/organizations/${org}/policies`, { cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Не удалось загрузить учётную политику."); return response.json() as Promise<Policy[]>; })
      .then(rows => { if (!controller.signal.aborted) setPolicies(rows); })
      .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => { controller.abort(); request.current?.abort(); };
  }, [org]);
  const sourceCurrency = (currency || "BYN").toUpperCase();
  const policy = policies.filter(row => row.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0];
  const conversion: Conversion | undefined = sourceCurrency === "BYN" ? undefined : {
    currency: sourceCurrency, rate, rate_scale: Number(rateScale), rate_date: rateDate, rate_source: rateSource.trim(),
  };
  const key = JSON.stringify([org, expenseId, version, date, amount, excluded, evidence, policy?.id, conversion]);
  const current = result?.key === key ? result.data : null;
  async function calculate() {
    if (running.current || disabled || !policy?.late_cost_allocation) return;
    running.current = true; setBusy(true); setError(""); setResult(null);
    const controller = new AbortController(); request.current = controller;
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/additional-expenses/${expenseId}/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ expected_version: version, policy_id: policy.id, posting_date: date,
          capitalizable_amount_byn: amount, excluded_amount_byn: excluded, classification_evidence: evidence.trim(),
          ...(conversion ? { conversion } : {}) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Расчёт отклонён. Проверьте суммы и основание.");
      if (String(data.organization_id) !== org || data.expense_id !== expenseId || data.source_version !== version
        || data.policy_id !== policy.id || data.posted !== false || data.confirmation_available !== false
        || !/^[a-f0-9]{64}$/.test(data.basis_digest) || !Array.isArray(data.shares) || !data.shares.length
        || !["specific", "fifo", "weighted_average"].includes(data.inventory_method)
        || !data.shares.every((share: Share) => share && Object.hasOwn(labels, share.destination)
          && Number.isSafeInteger(share.receipt_id) && share.receipt_id > 0
          && Number.isSafeInteger(share.version) && share.version > 0
          && Number.isSafeInteger(share.line_number) && share.line_number > 0
          && typeof share.quantity === "string" && typeof share.amount_byn === "string" && /^\d+\.\d{2}$/.test(share.amount_byn))) {
        throw new Error("Ответ расчёта не подтверждён.");
      }
      const cents = (value: string) => {
        const [whole, fraction = ""] = value.split(".");
        return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
      };
      const identities = data.shares.map((share: Share) => `${share.receipt_id}:${share.version}:${share.line_number}:${share.destination}`);
      if (new Set(identities).size !== identities.length
        || data.shares.reduce((total: bigint, share: Share) => total + cents(share.amount_byn), 0n) !== cents(amount)) {
        throw new Error("Доли расчёта не подтверждены: повтор строк или несовпадение суммы.");
      }
      if (!controller.signal.aborted) setResult({ key, data });
    } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    finally { running.current = false; if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="space-y-3 rounded-xl border border-line p-4">
    <h2 className="font-semibold">Распределение дополнительных расходов</h2>
    <p className="text-sm text-muted">Предварительный расчёт по сохранённой версии документа {version} и проверенной истории партии. Проводки не создаются.</p>
    <form onSubmit={event => { event.preventDefault(); void calculate(); }}>
      <fieldset disabled={disabled || busy} className="min-w-0 space-y-3">
        <label className="block">Дата отражения<Input required type="date" value={date} onChange={event => { setDate(event.target.value); setResult(null); }} /></label>
        <p>{policy ? `Политика: ${policy.reference}, действует с ${policy.effective_from}` : "На выбранную дату политика не найдена."}</p>
        {policy && !policy.late_cost_allocation && <p>В этой версии политики не настроено распределение поздних расходов.</p>}
        <div className="grid gap-3 md:grid-cols-2">
          <label>Включить в стоимость, BYN<Input required inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,2})?" value={amount} onChange={event => { setAmount(event.target.value); setResult(null); }} /></label>
          <label>Исключено из стоимости, BYN<Input required inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,2})?" value={excluded} onChange={event => { setExcluded(event.target.value); setResult(null); }} /></label>
        </div>
        {sourceCurrency !== "BYN" && <section className="space-y-2 rounded-lg border border-line p-3">
          <h3 className="font-medium">Конвертация {sourceCurrency} → BYN</h3>
          <p className="text-sm text-muted">Курс, масштаб, дата и источник вводятся бухгалтером. Автоматический курс и резерв не применяются.</p>
          <div className="grid gap-3 md:grid-cols-2">
            <label>Курс {sourceCurrency}<Input required inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,12})?" value={rate} onChange={event => { setRate(event.target.value); setResult(null); }} /></label>
            <label>Масштаб котировки<Input required inputMode="numeric" pattern="[0-9]+" value={rateScale} onChange={event => { setRateScale(event.target.value); setResult(null); }} /></label>
            <label>Дата курса<Input required type="date" value={rateDate} onChange={event => { setRateDate(event.target.value); setResult(null); }} /></label>
            <label>Источник курса<Input required minLength={10} maxLength={200} value={rateSource} onChange={event => { setRateSource(event.target.value); setResult(null); }} /></label>
          </div>
        </section>}
        <label className="block">Основание включения и исключения<Input required minLength={10} maxLength={1000} value={evidence} onChange={event => { setEvidence(event.target.value); setResult(null); }} /></label>
        <Button type="submit" disabled={!policy?.late_cost_allocation}>{busy ? "Расчёт…" : "Рассчитать распределение"}</Button>
      </fieldset>
    </form>
    {error && <p role="alert">{error}</p>}
    {current && <><p role="status">Расчёт готов для проверки. Проводки ещё не созданы.</p>
      {(current.inventory_method === "fifo" || current.inventory_method === "weighted_average") && <p>
        Это предварительное распределение. Окончательный V3-пакет для {current.inventory_method === "fifo" ? "FIFO" : "средней стоимости"}
        формируется сервером после выбора счетов; до его подтверждения себестоимость не является окончательной.
      </p>}
      {!current.normative_verified && <p>Нормативная применимость политики ещё не подтверждена.</p>}
      <p className="text-sm text-muted md:hidden">Прокрутите таблицу вправо, чтобы увидеть количество и сумму.</p>
      <div role="region" aria-label="Доли дополнительных расходов" tabIndex={0} className="max-w-full overflow-x-auto"><table className="w-full min-w-[480px] text-left text-sm"><thead><tr><th>Поступление / строка</th><th>Направление</th><th>Количество</th><th>Расход, BYN</th></tr></thead>
        <tbody>{current.shares.map(share => <tr key={`${share.receipt_id}:${share.version}:${share.line_number}:${share.destination}`}>
          <td>№ {share.receipt_id}, версия {share.version}, строка {share.line_number}</td><td>{labels[share.destination]}</td><td>{share.quantity}</td><td>{share.amount_byn}</td>
        </tr>)}</tbody></table></div>
      {policy && <AccountingLateCostAccounts key={key} org={org} expenseId={expenseId} disabled={disabled || busy} onPrepared={onPrepared}
        mode={current.inventory_method === "fifo" || current.inventory_method === "weighted_average" ? "pool"
          : current.shares.some(share => share.destination === "production" && BigInt(share.amount_byn.replace(".", "")) > 0n) ? "material" : "legacy"}
        allocation={{ expected_version: version, policy_id: policy.id, posting_date: date, capitalizable_amount_byn: amount,
          excluded_amount_byn: excluded, classification_evidence: evidence.trim(), ...(conversion ? { conversion } : {}) }} />}
    </>}
  </section>;
}
