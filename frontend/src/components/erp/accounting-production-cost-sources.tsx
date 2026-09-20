"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { AccountingProductionCostReview } from "./accounting-production-cost-review";
import { AccountingProductionOverheadConfirmation, type PreparedOverhead } from "./accounting-production-overhead-confirmation";
import { AccountingProductionOverheadHistory } from "./accounting-production-overhead-history";
import { AccountingProductionOverheadCorrectionPreview, type CorrectionTarget } from "./accounting-production-overhead-correction-preview";
import { AccountingProductionCorrectionConfirmation } from "./accounting-production-correction-confirmation";
import { AccountingProductionOutputCost } from "./accounting-production-output-cost";
import { AccountingProductionOutputCostRevision } from "./accounting-production-output-cost-revision";
import { AccountingProductionMaterialCost } from "./accounting-production-material-cost";
import { AccountingProductionLaborCost } from "./accounting-production-labor-cost";
import type { PreparedCorrection } from "@/lib/production-correction-journal";
type Policy = { id: number; organization_id: number; effective_from: string; reference: string; production_costing: unknown };
type Balance = { account: string; dimensions: Record<string, string>; role: string; opening_byn: string; debit_byn: string; credit_byn: string; closing_byn: string };
type Line = { entry_id: number; line_id: number; source: string; account: string; dimensions: Record<string, string>;
  posting_date: string; side: string; amount_byn: string; opening: boolean };
type Result = { digest: string; snapshot: { organization_id: number; month: string; policy_id: number;
  scope: string; status: string; final_cost_certified: boolean; balances: Balance[]; lines: Line[]; excluded_allocation?: { entry_id: number } } };
type Props = { org: string; month: string; disabled: boolean; onEntry?: (id: number) => void; onChanged?: () => void; onLock?: (busy: boolean) => void };
export function AccountingProductionCostSources(props: Props) {
  return <Sources key={`${props.org}:${props.month}`} {...props} />;
}
function Sources({ org, month, disabled, onEntry, onChanged, onLock }: Props) {
  const [policies, setPolicies] = useState<Policy[] | null>(null), [policy, setPolicy] = useState("");
  const [result, setResult] = useState<Result | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false), [selected, setSelected] = useState<Balance | null>(null);
  const [prepared, setPrepared] = useState<PreparedOverhead | null>(null);
  const [preparedCorrection, setPreparedCorrection] = useState<PreparedCorrection | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [correction, setCorrection] = useState<CorrectionTarget | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function load(preview: boolean, chosenCorrection?: CorrectionTarget) {
    if (controller.current || disabled) return;
    const pending = new AbortController(); controller.current = pending;
    const target = preview ? chosenCorrection ?? correction : null;
    if (chosenCorrection) { setCorrection(chosenCorrection); setPolicy(String(chosenCorrection.policyId)); }
    if (!preview) setCorrection(null);
    const policyId = String(target?.policyId ?? policy);
    setBusy(true); setError(""); setResult(null); setSelected(null); setPrepared(null); setPreparedCorrection(null);
    try {
      const base = `/api/accounting/organizations/${org}`;
      const sourcePath = target ? `production-overhead-correction-sources?policy_id=${policyId}&original_entry_id=${target.entryId}` : `production-cost-sources?policy_id=${policyId}`;
      const response = await fetch(preview ? `${base}/periods/${month}/${sourcePath}` : `${base}/policies`, { cache: "no-store", signal: pending.signal });
      if (!response.ok) throw new Error(preview ? "Источники затрат недоступны. Проверьте применимую политику и аналитику счетов." : "Не удалось загрузить версии политики.");
      const data = await response.json();
      if (pending.signal.aborted) return;
      if (preview) {
        const s = (data as Result).snapshot;
        if (String(s?.organization_id) !== org || s.month !== month || String(s.policy_id) !== policyId
          || s.scope !== (target ? "production_cost_correction_sources" : "posted_production_cost_accounts")
          || (target && s.excluded_allocation?.entry_id !== target.entryId) || s.status !== "source_review" || s.final_cost_certified !== false
          || !Array.isArray(s.balances) || !Array.isArray(s.lines)
          || s.balances.some(b => ![b.opening_byn, b.debit_byn, b.credit_byn, b.closing_byn].every(v => typeof v === "string" && /^-?\d+\.\d{2}$/.test(v)))
          || s.lines.some(l => !Number.isSafeInteger(l.entry_id) || l.entry_id <= 0 || !["debit", "credit"].includes(l.side)
            || typeof l.amount_byn !== "string" || !/^\d+\.\d{2}$/.test(l.amount_byn))) throw new Error("Результат не соответствует выбранному юрлицу, периоду или денежному формату.");
        setResult(data);
      } else {
        if (!Array.isArray(data) || data.some(p => String(p.organization_id) !== org)) throw new Error("Политики относятся к другому юрлицу.");
        setPolicies(data); setPolicy("");
      }
    } catch (e) { if (!pending.signal.aborted) setError((e as Error).message); }
    finally { if (!pending.signal.aborted) { setBusy(false); controller.current = null; } }
  }
  const matching = (line: Line) => selected && line.account === selected.account
    && Object.keys(line.dimensions).length === Object.keys(selected.dimensions).length
    && Object.entries(selected.dimensions).every(([key, value]) => line.dimensions[key] === value);
  return <section className="min-w-0 space-y-3 break-words rounded-lg border border-line p-3" aria-label="Источники затрат производства">
    <h3 className="font-semibold">Затраты производства · {month}</h3>
    <p className="text-sm">Проведённые суммы по затратным счетам. Состав прямых затрат, связь с нарядами и окончательная себестоимость требуют отдельной проверки.</p>
    <Button disabled={disabled || busy} onClick={() => void load(false)}>Обновить политики производства</Button>
    {policies && <><Select aria-label="Политика затрат производства" disabled={disabled || busy || !!correction} value={policy} onChange={e => { setPolicy(e.target.value); setResult(null); setSelected(null); setPrepared(null); }}>
      <option value="">Выберите версию политики</option>{policies.filter(p => p.production_costing).map(p => <option key={p.id} value={p.id}>{p.effective_from} · {p.reference}</option>)}
    </Select><Button disabled={disabled || busy || !policy} onClick={() => void load(true)}>Показать источники затрат</Button></>}
    {error && <p role="alert">{error}</p>}
    {result && <><p>Суммы в BYN. Остаток не является базой распределения автоматически.</p>
      {correction && <p>Пересчёт проводки №{correction.entryId}. Её собственные движения исключены из исходных затрат.</p>}
      <AccountingProductionCostReview key={result.digest} source={result} disabled={disabled || busy}
        onPrepared={value => { setPrepared(value); setPreparedCorrection(null); }} correctionOf={correction?.entryId} />
      {!correction && policy && <AccountingProductionOutputCost org={org} month={month} policyId={policy} disabled={disabled || busy} onEntry={onEntry} onLock={onLock} />}
      {!correction && <AccountingProductionOutputCostRevision org={org} month={month} disabled={disabled || busy} onEntry={onEntry} onLock={onLock} />}
      {!correction && policy && <AccountingProductionMaterialCost org={org} month={month} policyId={policy} disabled={disabled || busy} onEntry={onEntry} onLock={onLock} />}
      {!correction && policy && <AccountingProductionLaborCost org={org} month={month} policyId={policy} disabled={disabled || busy} onEntry={onEntry} onLock={onLock} />}
      {!result.snapshot.balances.length && <p>Проводки по выбранным затратным счетам за доступную историю не найдены. Это не подтверждает отсутствие неучтённых затрат.</p>}
      {result.snapshot.balances.map((b, i) => <article className="rounded border border-line p-2" key={i}>
        <button className="font-medium underline" onClick={() => setSelected(b)}>Счёт {b.account} · {b.role === "wip" ? "НЗП" : "Накладные расходы"}</button>
        <p>{Object.entries(b.dimensions).map(([k, v]) => `${k === "department" ? "Подразделение" : k === "order" ? "Заказ" : k}: ${v}`).join(' · ')}</p>
        <p>На начало: {b.opening_byn}; дебет: {b.debit_byn}; кредит: {b.credit_byn}; остаток: {b.closing_byn}.</p>
      </article>)}
      {selected && <div aria-label="Проводки затрат">{result.snapshot.lines.filter(matching).map(line => <p key={line.line_id}>
        <button className="underline" disabled={!onEntry || disabled} onClick={() => onEntry?.(line.entry_id)}>Проводка №{line.entry_id}</button>
        {` · ${line.posting_date} · ${line.side === "debit" ? "Дт" : "Кт"} ${line.amount_byn} BYN · ${line.source}${line.opening ? ' · ввод остатков' : ''}`}
      </p>)}</div>}
    </>}
    {correction && <AccountingProductionOverheadCorrectionPreview key={`${correction.entryId}:${prepared?.digest ?? "unreviewed"}`}
      org={org} month={month} target={correction} prepared={prepared} disabled={disabled || busy} onPrepared={setPreparedCorrection} />}
    <AccountingProductionCorrectionConfirmation org={org} month={month} disabled={disabled || busy}
      prepared={preparedCorrection && prepared && result && preparedCorrection.command.expected_review_digest === prepared.digest
        && preparedCorrection.command.review.expected_source_digest === result.digest && preparedCorrection.command.original_entry_id === correction?.entryId ? preparedCorrection : null}
      onEntry={onEntry} onLock={onLock}
      onConfirmed={() => { setPrepared(null); setPreparedCorrection(null); setResult(null); setSelected(null); setHistoryVersion(value => value + 1); onChanged?.(); }}
      onWithdrawn={() => { setPrepared(null); setPreparedCorrection(null); setResult(null); setSelected(null); }} />
    <AccountingProductionOverheadConfirmation org={org} month={month} disabled={disabled || busy} prepared={correction ? null : prepared} onEntry={onEntry} onLock={onLock}
      onConfirmed={() => { setPrepared(null); setResult(null); setSelected(null); setHistoryVersion(value => value + 1); onChanged?.(); }}
      onWithdrawn={() => { setPrepared(null); setResult(null); setSelected(null); }} />
    <AccountingProductionOverheadHistory key={historyVersion} org={org} month={month} disabled={disabled || busy} onEntry={onEntry}
      onCorrection={target => void load(true, target)} />
  </section>;
}
