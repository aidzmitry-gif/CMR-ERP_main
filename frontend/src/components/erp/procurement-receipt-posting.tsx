"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";

export type ReceiptAccount = { code: string; title: string; category: string; cash: boolean; quantity_tracking: boolean };
type Preview = { digest: string; lines: { account: string; title: string; side: string; amount: string }[] };
export function ProcurementReceiptPosting({ org, receiptId, version, items, accounts, policyId, date, onPosted, onBusy, blocked = false }: {
  org: string; receiptId: number; version: number; items: { sku: string; lot: string }[];
  accounts: ReceiptAccount[]; policyId?: number; date: string;
  onPosted: (entryId: number) => void; onBusy: (busy: boolean) => void;
  blocked?: boolean;
}) {
  const [inventory, setInventory] = useState(items.map(() => ""));
  const [supplier, setSupplier] = useState(""), [vat, setVat] = useState("");
  const [preview, setPreview] = useState<{ body: string; result: Preview } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function execute(confirm: boolean) {
    if (blocked || busy || !policyId || (confirm && !preview)) return;
    const body = confirm ? JSON.stringify({ ...JSON.parse(preview!.body), digest: preview!.result.digest }) : JSON.stringify({ expected_version: version, posting_date: date, policy_id: policyId, settlement_account: supplier, vat_account: vat === "none" ? null : vat, inventory_accounts: inventory });
    setBusy(true); onBusy(true); setError("");
    try {
      const response = await fetch(`/api/procurement/organizations/${org}/receipt-documents/${receiptId}/${confirm ? "confirm" : "preview"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body });
      const result = await response.json();
      if (confirm && response.ok) { onPosted(result.entry_id); return; }
      if (!active.current) return;
      if (!response.ok) throw new Error(response.status === 409 ? "Накладная или расчёт изменились. Обновите документ и рассчитайте проводки заново." : typeof result.detail === "string" ? result.detail : "Проверьте счета и данные накладной.");
      setPreview({ body, result });
    } catch (e) { if (active.current) setError((e as Error).message); }
    finally { onBusy(false); if (active.current) setBusy(false); }
  }
  const options = (root: string) => accounts.filter((a) => a.code.split(".")[0] === root && !a.cash).map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>);
  return <section className="space-y-3 rounded-lg border border-line p-4">
    <h3 className="font-semibold">Проводки по сохранённой версии {version}</h3>
    <p>Дата отражения: {date}. Суммы и реквизиты берутся из накладной № {receiptId}.</p>
    {error && <p role="alert">{error}</p>}
    {!policyId && <p>Для проведения нужна утверждённая учётная политика на выбранную дату.</p>}
    <fieldset disabled={busy || blocked || !policyId} className="space-y-3">
      <label>Счёт расчётов с поставщиком<Select value={supplier} onChange={(e) => { setSupplier(e.target.value); setPreview(null); }}><option value="">Выберите счёт</option>{options("60")}</Select></label>
      <label>Счёт НДС накладной<Select value={vat} onChange={(e) => { setVat(e.target.value); setPreview(null); }}><option value="">Выберите вариант</option><option value="none">Без суммы НДС</option>{options("18")}</Select></label>
      {items.map((item, i) => <label key={i}>Счёт позиции {i + 1} · {item.sku} · {item.lot}<Select aria-label={`Счёт позиции накладной ${i + 1}`} value={inventory[i]} onChange={(e) => { setInventory(inventory.map((value, index) => index === i ? e.target.value : value)); setPreview(null); }}><option value="">Выберите счёт запасов</option>{accounts.filter((a) => ["10", "41"].includes(a.code.split(".")[0]) && a.category === "asset" && a.quantity_tracking && !a.cash).map((a) => <option key={a.code} value={a.code}>{a.code} · {a.title}</option>)}</Select></label>)}
      <Button disabled={!supplier || !vat || inventory.some((value) => !value)} onClick={() => void execute(false)}>Рассчитать проводки накладной</Button>
      {preview && <div>{preview.result.lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN</p>)}<Button onClick={() => void execute(true)}>Провести сохранённую накладную</Button></div>}
    </fieldset>
  </section>;
}
