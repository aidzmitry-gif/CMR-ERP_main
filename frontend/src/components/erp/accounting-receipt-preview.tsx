"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AccountingReceiptConfirm } from "./accounting-receipt-confirm";
import { Input, Select } from "@/components/ui/input";

type Source = { id: number; version: number; document: { operation_date: string; items: { sku: string; vat_amount: string }[] } };
type Account = { code: string; title: string; category: string; cash: boolean };
type Policy = { id: number; effective_from: string; reference: string };
type Preview = { digest: string; organization_id: number; source: string; source_version: number; posted: boolean; lines: { account: string; title: string; side: string; amount: string; quantity?: string | null; dimensions: Record<string, string> }[] };

export function AccountingReceiptPreview({ org, source, onVerified }: { org: string; source: Source; onVerified?: () => void }) {
  const [locked, setLocked] = useState(false);
  const [date, setDate] = useState(source.document.operation_date);
  return <section aria-label="Подготовка проводок поступления" className="space-y-3 border-t border-line pt-3">
    <h3 className="font-semibold">Подготовка проводок поступления</h3>
    <label className="block">Дата отражения<Input type="date" disabled={locked} value={date} onChange={e => setDate(e.target.value)} /></label>
    <ReceiptOptions key={`${org}:${source.id}:${source.version}:${date}`} org={org} source={source} date={date} onLock={() => setLocked(true)} onVerified={onVerified} />
  </section>;
}

function ReceiptOptions({ org, source, date, onLock, onVerified }: { org: string; source: Source; date: string; onLock: () => void; onVerified?: () => void }) {
  const [locked, setLocked] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [settlement, setSettlement] = useState("");
  const [vat, setVat] = useState("");
  const [inventory, setInventory] = useState(source.document.items.map(() => ""));
  const [result, setResult] = useState<Preview | null>(null);
  const pending = useRef<AbortController | null>(null);
  const prefix = `/api/accounting/organizations/${org}`;
  const hasVat = source.document.items.some(item => !/^0+(?:\.0+)?$/.test(item.vat_amount));
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const responses = await Promise.all([fetch(`${prefix}/accounts?on=${date}`, { cache: "no-store", signal: controller.signal }), fetch(`${prefix}/policies`, { cache: "no-store", signal: controller.signal })]);
        if (responses.some(response => !response.ok)) throw new Error("Не удалось загрузить рабочие счета и учётную политику.");
        const [rows, policies]: [Account[], Policy[]] = await Promise.all([responses[0].json(), responses[1].json()]);
        if (!controller.signal.aborted) {
          setAccounts(rows);
          setPolicy(policies.filter(row => row.effective_from <= date).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0] ?? null);
        }
      } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка загрузки."); }
    }
    if (date) void load();
    return () => { controller.abort(); pending.current?.abort(); };
  }, [date, prefix]);

  function invalidate() { pending.current?.abort(); setResult(null); setBusy(false); setError(""); }
  function options(roots: string[], category: string) { return accounts.filter(row => roots.includes(row.code.split(".")[0]) && row.category === category && !row.cash).map(row => <option key={row.code} value={row.code}>{row.code} · {row.title}</option>); }
  async function calculate() {
    invalidate();
    const controller = new AbortController(); pending.current = controller; setBusy(true);
    try {
      const response = await fetch(`${prefix}/receipts/${source.id}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal, body: JSON.stringify({ expected_version: source.version, posting_date: date, policy_id: policy?.id, settlement_account: settlement, vat_account: hasVat ? vat : null, inventory_accounts: inventory }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте счета, дату и версию документа.");
      if (typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest) || String(data.organization_id) !== org || data.source !== `procurement:receipt:${source.id}` || data.source_version !== source.version || data.posted !== false || !Array.isArray(data.lines)) throw new Error("Расчёт не соответствует выбранному поступлению.");
      if (!controller.signal.aborted) setResult(data);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Ошибка расчёта."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <div className="space-y-3">
    <p>{policy ? `Учётная политика: ${policy.reference}` : "Для выбранной даты учётная политика не получена. Расчёт недоступен."}</p>
    <fieldset disabled={locked} className="space-y-3"><label className="block">Счёт расчётов с поставщиком<Select value={settlement} onChange={e => { invalidate(); setSettlement(e.target.value); }}><option value="">Выберите счёт</option>{options(["60"], "liability")}</Select></label>
    {hasVat ? <label className="block">Счёт входного НДС<Select value={vat} onChange={e => { invalidate(); setVat(e.target.value); }}><option value="">Выберите счёт</option>{options(["18"], "asset")}</Select></label> : <p>По документу НДС равен нулю. Счёт входного НДС не используется.</p>}
    {source.document.items.map((item, index) => <label className="block" key={index}>Счёт запасов · строка {index + 1} · {item.sku}<Select value={inventory[index]} onChange={e => { invalidate(); setInventory(inventory.map((value, i) => i === index ? e.target.value : value)); }}><option value="">Выберите счёт</option>{options(["10", "41"], "asset")}</Select></label>)}
    <Button disabled={busy || !policy || !settlement || (hasVat && !vat) || inventory.some(value => !value)} onClick={() => void calculate()}>Рассчитать проводки поступления</Button></fieldset>
    {error && <p role="alert">{error}</p>}
    {result && <div aria-label="Расчёт поступления" className="space-y-2"><p>Предварительный расчёт, не проведён. Вычет НДС не выполнялся.</p>{result.lines.map((line, index) => <div key={index} className="border-t border-line pt-2"><p>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN{line.quantity != null ? ` · количество ${line.quantity}` : ""}</p><p className="text-muted">{Object.entries(line.dimensions).map(([key, value]) => `${key}: ${value}`).join("; ")}</p></div>)}</div>}
    {result && <AccountingReceiptConfirm key={result.digest} org={org} receiptId={source.id} version={source.version} command={{ expected_version: source.version, posting_date: date, policy_id: policy?.id, settlement_account: settlement, vat_account: hasVat ? vat : null, inventory_accounts: inventory, digest: result.digest }} onLock={() => { setLocked(true); onLock(); }} onVerified={onVerified} />}
  </div>;
}
