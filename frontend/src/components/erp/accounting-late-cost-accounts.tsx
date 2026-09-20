"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import type { LateCostPending } from "@/lib/late-cost-journal";
import { checkedMaterialOutputs, type MaterialOutput } from "@/lib/late-material-package";

type Allocation = { expected_version: number; policy_id: number; posting_date: string; capitalizable_amount_byn: string; excluded_amount_byn: string; classification_evidence: string; conversion?: { currency: string; rate: string; rate_scale: number; rate_date: string; rate_source: string } };
type Account = { code: string; title: string; valid_from: string; category: string; cash: boolean; quantity_tracking: boolean; required_dimensions: string[] };
type Excluded = { account: string; amount_byn: string; dimensions: Record<string, string> };
type Line = { account: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string> };
const labels: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", department: "Подразделение", employee: "Сотрудник", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", asset: "Основное средство" };
export function AccountingLateCostAccounts({ org, expenseId, allocation, disabled, onPrepared, material = false }: {
  org: string; expenseId: number; allocation: Allocation; disabled: boolean; onPrepared?: (command: LateCostPending | null) => void; material?: boolean;
}) {
  const [accounts, setAccounts] = useState<Account[]>([]), [settlement, setSettlement] = useState("");
  const [excluded, setExcluded] = useState<Excluded[]>([]), [lines, setLines] = useState<Line[] | null>(null);
  const [outputs, setOutputs] = useState<MaterialOutput[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const running = useRef(false), request = useRef<AbortController | null>(null);
  useEffect(() => { if (!lines) onPrepared?.(null); }, [lines, onPrepared]);
  useEffect(() => () => onPrepared?.(null), [onPrepared]);
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`/api/accounting/organizations/${org}/accounts`, { cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Не удалось загрузить рабочий план счетов."); return response.json() as Promise<Account[]>; })
      .then(rows => { if (!controller.signal.aborted) setAccounts(rows); })
      .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => { controller.abort(); request.current?.abort(); };
  }, [org]);
  const effective = [...new Map(accounts.filter(row => row.valid_from <= allocation.posting_date)
    .sort((a, b) => a.valid_from.localeCompare(b.valid_from)).map(row => [row.code, row])).values()];
  const available = effective.filter(row => !row.cash && !row.quantity_tracking);
  const change = (index: number, update: Partial<Excluded>) => { setLines(null); setExcluded(rows => rows.map((row, i) => i === index ? { ...row, ...update } : row)); };
  async function prepare() {
    if (running.current || disabled) return;
    running.current = true; setBusy(true); setError(""); setLines(null);
    const controller = new AbortController(); request.current = controller;
    try {
      const requested = { allocation, accounts: { settlement_account: settlement, excluded_costs: excluded } };
      const response = await fetch(`/api/accounting/organizations/${org}/additional-expenses/${expenseId}${material ? "/material" : ""}/posting-preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify(requested),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте счета, суммы и аналитику.");
      if (String(data.organization_id) !== org || data.expense_id !== expenseId || data.posted !== false
        || typeof data.principal !== "string" || !data.principal || !/^[a-f0-9]{64}$/.test(data.digest) || !/^[a-f0-9]{64}$/.test(data.basis_digest)
        || data.posting?.source_version !== allocation.expected_version || data.posting?.source !== `procurement:additional-expense:${expenseId}`
        || !Array.isArray(data.posting.lines) || !data.posting.lines.length
        || !data.posting.lines.every((line: Line) => line && typeof line.account === "string" && ["debit", "credit"].includes(line.side)
          && typeof line.amount === "string" && /^\d{1,20}\.\d{2}$/.test(line.amount) && line.dimensions
          && Object.values(line.dimensions).every(value => typeof value === "string"))) throw new Error("Пакет проводок не подтверждён.");
      let debit = 0n, credit = 0n;
      for (const line of data.posting.lines as Line[]) { const cents = BigInt(line.amount.replace(".", ""));
        if (cents <= 0n) throw new Error("Некорректная сумма проводки.");
        if (line.side === "debit") debit += cents; else credit += cents;
      }
      const cents = (amount: string) => { const [whole, fraction = ""] = amount.split("."); return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0")); };
      if (debit !== credit || debit !== cents(allocation.capitalizable_amount_byn) + cents(allocation.excluded_amount_byn)) throw new Error("Суммы пакета не соответствуют документу.");
      const outputRows = material ? checkedMaterialOutputs(data, requested) : [];
      if (material && (data.confirmation_available !== true || data.posting_digest !== data.digest)) throw new Error("Производственный пакет ещё нельзя подтвердить.");
      if (!controller.signal.aborted) {
        setOutputs(outputRows);
        setLines(data.posting.lines);
        onPrepared?.({ org, expenseId, principal: data.principal, body: JSON.stringify({ ...(material ? data.command : requested), request_key: crypto.randomUUID(),
          expected_digest: data.digest, expected_basis_digest: data.basis_digest }) });
      }
    } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    finally { running.current = false; if (!controller.signal.aborted) setBusy(false); }
  }
  return <section className="space-y-3 border-t border-line pt-3">
    <h3 className="font-semibold">Счета для проведения</h3>
    <fieldset disabled={disabled || busy} className="min-w-0 space-y-3">
      <label className="block">Счёт расчётов с поставщиком<Select aria-label="Счёт расчётов с поставщиком" value={settlement} onChange={e => { setSettlement(e.target.value); setLines(null); }}>
        <option value="">Выберите счёт</option>{available.filter(row => row.category === "liability" && row.code.split(".")[0] === "60").map(row => <option key={row.code} value={row.code}>{row.code} · {row.title}</option>)}
      </Select></label>
      <p>Исключено из стоимости: {allocation.excluded_amount_byn} BYN. Укажите счета и суммы каждой части.</p>
      {excluded.map((row, index) => <div key={index} className="space-y-2 rounded-lg border border-line p-3">
        <label className="block">Счёт исключённой суммы {index + 1}<Select value={row.account} onChange={e => change(index, { account: e.target.value, dimensions: {} })}>
          <option value="">Выберите счёт</option>{available.filter(a => (a.category === "asset" && a.code.split(".")[0] === "18") || (a.category === "expense" && ["44", "90", "91"].includes(a.code.split(".")[0]))).map(a => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}
        </Select></label>
        <label className="block">Сумма части {index + 1}, BYN<Input inputMode="decimal" value={row.amount_byn} onChange={e => change(index, { amount_byn: e.target.value })} /></label>
        {(effective.find(a => a.code === row.account)?.required_dimensions ?? []).map(name => <label className="block" key={name}>{labels[name] ?? name}<Input value={row.dimensions[name] ?? ""} onChange={e => change(index, { dimensions: { ...row.dimensions, [name]: e.target.value } })} /></label>)}
        <Button variant="secondary" onClick={() => { setExcluded(rows => rows.filter((_, i) => i !== index)); setLines(null); }}>Удалить часть {index + 1}</Button>
      </div>)}
      <Button variant="secondary" disabled={excluded.length >= 100} onClick={() => { setExcluded(rows => [...rows, { account: "", amount_byn: "", dimensions: {} }]); setLines(null); }}>Добавить исключённую сумму</Button>
      <Button disabled={!settlement} onClick={() => void prepare()}>{busy ? "Подготовка…" : "Подготовить проводки"}</Button>
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {lines && <><p role="status">Проводки подготовлены. Проверьте счета, суммы и аналитику перед подтверждением.</p>
      {lines.map((line, index) => <div key={index} className="border-t border-line py-2"><p>{line.side === "debit" ? "Дебет" : "Кредит"} {line.account} · {line.amount} BYN</p>
        {Object.entries(line.dimensions).map(([name, value]) => <p className="break-words text-sm text-muted" key={name}>{labels[name] ?? name}: {value}</p>)}
      </div>)}
      {material && <section className="space-y-3" aria-label="Корректировки себестоимости выпусков">
        <h4 className="font-semibold">Корректировки себестоимости выпусков</h4>
        {!outputs.length && <p>Производственная часть расходов остаётся в НЗП.</p>}
        {outputs.map(output => <div key={output.output_entry_id} className="rounded-lg border border-line p-3">
          <p>Выпуск · операция № {output.output_entry_id} · {output.amount_byn} BYN</p>
          {output.lines.map((line, index) => <div key={index} className="border-t border-line py-2">
            <p>{line.side === "debit" ? "Дебет" : "Кредит"} {line.account} · {line.amount} BYN</p>
            {Object.entries(line.dimensions).map(([name, value]) => <p className="break-words text-sm text-muted" key={name}>{labels[name] ?? name}: {value}</p>)}
          </div>)}
        </div>)}
      </section>}
    </>}
  </section>;
}
