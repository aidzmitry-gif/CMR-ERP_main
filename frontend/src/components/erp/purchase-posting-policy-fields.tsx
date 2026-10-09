"use client";
import { useEffect, useLayoutEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
type Account = { organization_id: number; code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean };
type Settings = { default_inventory_account: string | null; default_settlement_account: string | null;
  vat_account: string | null; inventory_by_sku: Record<string, string>;
  inventory_by_category: Record<string, string>; settlement_by_supplier: Record<string, string> };
export type PurchasePostingSelection = { scope: string; enabled: boolean; value: { purchase: Settings } | null };
type Props = { org: string; effectiveDate: string; onChange: (value: PurchasePostingSelection) => void };
type Kind = "inventory_by_sku" | "inventory_by_category" | "settlement_by_supplier";
type Override = { kind: Kind; id: string; account: string; title?: string };
export function PurchasePostingPolicyFields(props: Props) { return <Fields key={`${props.org}:${props.effectiveDate}`} {...props} />; }
function Fields({ org, effectiveDate, onChange }: Props) {
  const [enabled, setEnabled] = useState(false), [accounts, setAccounts] = useState<Account[] | null>(null);
  const [inventory, setInventory] = useState(""), [settlement, setSettlement] = useState(""), [vat, setVat] = useState("");
  const [rows, setRows] = useState<Override[]>([]), [error, setError] = useState("");
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/accounting/organizations/${org}/accounts?on=${effectiveDate}`, { cache: "no-store", signal: controller.signal });
        const data = await response.json();
        if (!response.ok || !Array.isArray(data) || data.some(row => String(row.organization_id) !== org)) throw new Error("Не удалось получить счета выбранного юрлица.");
        if (!controller.signal.aborted) setAccounts(data);
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка загрузки счетов."); }
    })();
    return () => controller.abort();
  }, [enabled, org, effectiveDate]);
  const choices = (kind: "inventory" | "settlement" | "vat") => (accounts ?? []).filter(a => !a.cash
    && (kind === "inventory" ? ["10", "41"].includes(a.code.split(".")[0]) && a.category === "asset" && a.quantity_tracking
      : kind === "settlement" ? a.code.split(".")[0] === "60" && a.category === "liability" && !a.quantity_tracking
        : a.code.split(".")[0] === "18" && a.category === "asset" && !a.quantity_tracking));
  const validAccount = (code: string, kind: "inventory" | "settlement" | "vat") => !code || choices(kind).some(a => a.code === code);
  const overridesValid = rows.every((row, i) => /^[1-9][0-9]{0,9}$/.test(row.id) && Number(row.id) <= 2147483647 && Boolean(row.account) && Boolean(row.title)
    && validAccount(row.account, row.kind === "settlement_by_supplier" ? "settlement" : "inventory")
    && rows.findIndex(other => other.kind === row.kind && other.id === row.id) === i);
  const ready = accounts !== null && !error && overridesValid && validAccount(inventory, "inventory")
    && validAccount(settlement, "settlement") && validAccount(vat, "vat")
    && (inventory || rows.some(row => row.kind !== "settlement_by_supplier"))
    && (settlement || rows.some(row => row.kind === "settlement_by_supplier"));
  const settings: Settings = { default_inventory_account: inventory || null, default_settlement_account: settlement || null,
    vat_account: vat || null, inventory_by_sku: {}, inventory_by_category: {}, settlement_by_supplier: {} };
  rows.forEach(row => { settings[row.kind][row.id] = row.account; });
  const signature = JSON.stringify({ scope: `${org}:${effectiveDate}`, enabled, value: enabled && ready ? { purchase: settings } : null });
  useLayoutEffect(() => { onChange(JSON.parse(signature)); }, [signature, onChange]);
  const options = (kind: "inventory" | "settlement" | "vat") => choices(kind).map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>);
  function update(index: number, value: Partial<Override>) { setRows(rows.map((row, i) => i === index ? { ...row, ...value } : row)); }
  async function verify(index: number) {
    const row = rows[index], kind = { inventory_by_sku: "sku", inventory_by_category: "category", settlement_by_supplier: "supplier" }[row.kind];
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/purchase-posting-selector?kind=${kind}&selector_id=${encodeURIComponent(row.id)}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || String(data.organization_id) !== org || String(data.id) !== row.id
        || data.kind !== kind || typeof data.title !== "string" || !data.title.trim()) throw new Error("Карточка не найдена. Проверьте вид правила и идентификатор.");
      setRows(current => current.map((r, i) => i === index && r.id === row.id && r.kind === row.kind ? { ...r, title: data.title } : r));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка проверки карточки."); }
  }
  return <fieldset className="min-w-0 space-y-3 rounded-lg border border-line p-3">
    <legend>Автоматические проводки поступлений</legend>
    <label><input type="checkbox" checked={enabled} onChange={e => { setEnabled(e.target.checked); setError(""); }} /> Настроить автоматический выбор счетов</label>
    {enabled && <><p>Приоритет: товар → его группа → общий счёт. Правила действуют с даты этой версии политики; история сохраняется.</p>
      {error && <p role="alert">{error}</p>}
      <label className="block">Общий счёт запасов<Select value={inventory} onChange={e => setInventory(e.target.value)}><option value="">Только индивидуальные правила</option>{options("inventory")}</Select></label>
      <label className="block">Общий счёт расчётов с поставщиками<Select value={settlement} onChange={e => setSettlement(e.target.value)}><option value="">Только индивидуальные правила</option>{options("settlement")}</Select></label>
      <label className="block">Счёт входного НДС<Select value={vat} onChange={e => setVat(e.target.value)}><option value="">Не настроен</option>{options("vat")}</Select></label>
      <p className="text-sm">Если в документе есть НДС, его счёт обязателен. Для индивидуального правила укажите идентификатор из карточки товара, группы или поставщика ERP.</p>
      {rows.map((row, index) => <div key={index} className="grid gap-2 sm:grid-cols-4">
        <Select aria-label={`Вид правила ${index + 1}`} value={row.kind} onChange={e => update(index, { kind: e.target.value as Kind, id: "", account: "", title: undefined })}><option value="inventory_by_sku">Товар</option><option value="inventory_by_category">Группа товара</option><option value="settlement_by_supplier">Поставщик</option></Select>
        <div><Input aria-label={`Идентификатор правила ${index + 1}`} placeholder="Идентификатор карточки" value={row.id} onChange={e => { setError(""); update(index, { id: e.target.value, title: undefined }); }} /><Button variant="secondary" disabled={!/^[1-9][0-9]{0,9}$/.test(row.id)} onClick={() => { setError(""); void verify(index); }}>Проверить карточку {index + 1}</Button>{row.title && <p>{row.title}</p>}</div>
        <Select aria-label={`Счёт правила ${index + 1}`} value={row.account} onChange={e => update(index, { account: e.target.value })}><option value="">Выберите счёт</option>{options(row.kind === "settlement_by_supplier" ? "settlement" : "inventory")}</Select>
        <Button variant="secondary" onClick={() => { setError(""); setRows(rows.filter((_, i) => i !== index)); }}>Удалить правило</Button>
      </div>)}
      <Button variant="secondary" disabled={rows.length >= 300} onClick={() => setRows([...rows, { kind: "inventory_by_sku", id: "", account: "" }])}>Добавить индивидуальное правило</Button>
      {!overridesValid && <p role="alert">Заполните уникальные идентификаторы и счета индивидуальных правил.</p>}
    </>}
  </fieldset>;
}
