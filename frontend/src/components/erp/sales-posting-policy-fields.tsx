"use client";
import { useEffect, useLayoutEffect, useState } from "react";
import { Select } from "@/components/ui/input";

export const saleAccountFields = [
  ["buyer_account", "Покупатель", "62", "asset"], ["revenue_account", "Выручка", "90.1", "income"],
  ["vat_revenue_account", "НДС из выручки", "90.2", "income"], ["vat_payable_account", "НДС к уплате", "68", "liability"],
  ["expense_account", "Себестоимость", "90.4", "expense"],
] as const;
export type SalesPostingAccounts = Record<typeof saleAccountFields[number][0], string>;
export type SalesPostingSelection = { scope: string; enabled: boolean; value: SalesPostingAccounts | null };
type Account = { organization_id: number; code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean };
type Props = { org: string; effectiveDate: string; onChange: (value: SalesPostingSelection) => void };

export function SalesPostingPolicyFields(props: Props) { return <Fields key={`${props.org}:${props.effectiveDate}`} {...props} />; }
function Fields({ org, effectiveDate, onChange }: Props) {
  const [enabled, setEnabled] = useState(false), [accounts, setAccounts] = useState<Account[] | null>(null);
  const [value, setValue] = useState<SalesPostingAccounts>({ buyer_account: "", revenue_account: "", vat_revenue_account: "", vat_payable_account: "", expense_account: "" });
  const [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/accounting/organizations/${org}/accounts?on=${effectiveDate}`, { cache: "no-store", signal: controller.signal });
        const body = await response.json();
        if (!response.ok || !Array.isArray(body) || body.some(a => String(a.organization_id) !== org
          || typeof a.code !== "string" || typeof a.cash !== "boolean" || typeof a.quantity_tracking !== "boolean")) throw new Error("Не удалось получить счета выбранного юрлица.");
        if (!controller.signal.aborted) { setAccounts(body); setError(""); }
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка загрузки счетов."); }
    })();
    return () => controller.abort();
  }, [enabled, org, effectiveDate]);
  const choices = (root: string, category: string) => (accounts ?? []).filter(a => a.cash === false && a.quantity_tracking === false && a.category === category && (a.code === root || a.code.startsWith(root + ".")));
  const ready = accounts !== null && !error && saleAccountFields.every(([field, , root, category]) => choices(root, category).some(a => a.code === value[field]));
  const signature = JSON.stringify({ scope: `${org}:${effectiveDate}`, enabled, value: enabled && ready ? value : null });
  useLayoutEffect(() => { onChange(JSON.parse(signature)); }, [signature, onChange]);
  return <fieldset className="min-w-0 space-y-3 rounded-lg border border-line p-3">
    <legend>Автоматические счета реализации</legend>
    <label><input type="checkbox" checked={enabled} onChange={e => { setEnabled(e.target.checked); setError(""); }} /> Настроить счета реализации</label>
    {enabled && <><p>Счета применяются ко всему акту отгрузки. Партии, суммы, НДС и аналитики проверяются отдельно.</p>
      {error && <p role="alert">{error}</p>}
      <div className="grid gap-3 sm:grid-cols-2">{saleAccountFields.map(([field, label, root, category]) => <label key={field}>{label}<Select aria-label={`Автоматический счёт реализации · ${label}`} value={value[field]} onChange={e => setValue(current => ({ ...current, [field]: e.target.value }))}>
        <option value="">Выберите счёт</option>{choices(root, category).map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}
      </Select></label>)}</div>
      {!ready && <p>Выберите все пять действующих счетов. Счета не подставляются при настройке.</p>}
    </>}
  </fieldset>;
}
