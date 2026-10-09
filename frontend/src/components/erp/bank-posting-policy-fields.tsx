"use client";
import { useEffect, useLayoutEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Account = { organization_id: number; code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean };
type Rule = { key: string; title: string; direction: string; settlement_account: string; cash_activity: string };
export type BankPostingSelection = { scope: string; enabled: boolean; value: { rules: Record<string, Omit<Rule, "key">> } | null };
type Props = { org: string; effectiveDate: string; onChange: (value: BankPostingSelection) => void };

export function BankPostingPolicyFields(props: Props) { return <Fields key={`${props.org}:${props.effectiveDate}`} {...props} />; }
function Fields({ org, effectiveDate, onChange }: Props) {
  const [enabled, setEnabled] = useState(false), [accounts, setAccounts] = useState<Account[] | null>(null);
  const [rows, setRows] = useState<Rule[]>([]), [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/accounting/organizations/${org}/accounts?on=${effectiveDate}`, { cache: "no-store", signal: controller.signal });
        const body = await response.json();
        if (!response.ok || !Array.isArray(body) || body.some(a => String(a.organization_id) !== org
          || typeof a.cash !== "boolean" || typeof a.quantity_tracking !== "boolean")) throw new Error("Не удалось получить счета выбранного юрлица.");
        if (!controller.signal.aborted) setAccounts(body);
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка загрузки счетов."); }
    })();
    return () => controller.abort();
  }, [enabled, org, effectiveDate]);
  const choices = (accounts ?? []).filter(a => a.cash === false && a.quantity_tracking === false && ["asset", "liability"].includes(a.category));
  const ready = accounts !== null && !error && rows.length > 0 && rows.every((r, i) =>
    /^[a-z][a-z0-9_]{0,49}$/.test(r.key) && rows.findIndex(other => other.key === r.key) === i
    && Boolean(r.title.trim()) && r.title.trim().length <= 100 && ["receipt", "payment"].includes(r.direction)
    && ["operating", "investing", "financing"].includes(r.cash_activity) && choices.some(a => a.code === r.settlement_account));
  const rules = Object.fromEntries(rows.map(({ key, ...rule }) => [key, { ...rule, title: rule.title.trim() }]));
  const signature = JSON.stringify({ scope: `${org}:${effectiveDate}`, enabled, value: enabled && ready ? { rules } : null });
  useLayoutEffect(() => { onChange(JSON.parse(signature)); }, [signature, onChange]);
  function update(i: number, patch: Partial<Rule>) { setRows(current => current.map((r, n) => n === i ? { ...r, ...patch } : r)); }
  return <fieldset className="min-w-0 space-y-3 rounded-lg border border-line p-3">
    <legend>Автоматические проводки банка</legend>
    <label><input type="checkbox" checked={enabled} onChange={e => { setEnabled(e.target.checked); setError(""); }} /> Настроить правила банковских операций</label>
    {enabled && <><p>Для каждой операции укажите направление и счёт расчётов. Денежный счёт берётся из привязки выписки. Контрагента и договор проверяет бухгалтер.</p>
      {error && <p role="alert">{error}</p>}
      {rows.map((r, i) => <div key={i} className="grid gap-2 sm:grid-cols-3">
        <Input aria-label={`Ключ банковской операции ${i + 1}`} placeholder="supplier_payment" value={r.key} onChange={e => update(i, { key: e.target.value })} />
        <Input aria-label={`Название банковской операции ${i + 1}`} placeholder="Оплата поставщику" value={r.title} onChange={e => update(i, { title: e.target.value })} />
        <Select aria-label={`Направление банковской операции ${i + 1}`} value={r.direction} onChange={e => update(i, { direction: e.target.value })}><option value="">Выберите направление</option><option value="receipt">Поступление</option><option value="payment">Списание</option></Select>
        <Select aria-label={`Счёт банковской операции ${i + 1}`} value={r.settlement_account} onChange={e => update(i, { settlement_account: e.target.value })}><option value="">Выберите счёт расчётов</option>{choices.map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select>
        <Select aria-label={`Поток банковской операции ${i + 1}`} value={r.cash_activity} onChange={e => update(i, { cash_activity: e.target.value })}><option value="">Выберите вид потока</option><option value="operating">Текущая деятельность</option><option value="investing">Инвестиционная</option><option value="financing">Финансовая</option></Select>
        <Button variant="secondary" onClick={() => setRows(current => current.filter((_, n) => n !== i))}>Удалить банковское правило</Button>
      </div>)}
      <Button variant="secondary" disabled={rows.length >= 100} onClick={() => setRows(current => [...current, { key: "", title: "", direction: "", settlement_account: "", cash_activity: "" }])}>Добавить банковское правило</Button>
      {!ready && <p>Заполните правила. Ключ — уникальное латинское имя; счета и направление не выбираются автоматически при настройке.</p>}
    </>}
  </fieldset>;
}
