"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { checkedMaterialOutputs, type MaterialOutput } from "@/lib/late-material-package";

type Line = { account: string; side: "debit" | "credit"; amount: string; currency: string; quantity: null; dimensions: Record<string, string> };
type Package = { organization_id: number; expense_id: number; source_version: number; entry_id: number; posted: boolean;
  digest: string; basis_digest: string; outputCorrections?: MaterialOutput[]; posting: { source: string; posting_date: string; explanation: string; lines: Line[] } };
const dimensionLabels: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов",
  warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", department: "Подразделение", vat_rate: "Ставка НДС", vat_basis: "Основание НДС" };

export function AccountingLateCostPosted({ org, expenseId, version, entryId, material = false }: {
  org: string; expenseId: number; version: number; entryId: number; material?: boolean;
}) {
  const [opened, setOpened] = useState(false);
  const [result, setResult] = useState<{ key: string; data?: Package; error?: string } | null>(null);
  const key = `${org}:${expenseId}:${version}:${entryId}:${material}`;
  const current = result?.key === key ? result : null;
  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    void fetch(`/api/accounting/organizations/${org}/additional-expenses/${expenseId}${material ? "/material" : ""}/posting`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Не удалось проверить проведённый пакет.");
        const raw = await response.json();
        const data: Package = material ? { ...raw, posting: raw.preview?.posting,
          outputCorrections: checkedMaterialOutputs(raw.preview) } : raw;
        if (material && (!Array.isArray(raw.output_revisions) || raw.output_revisions.length !== data.outputCorrections?.length
          || raw.output_revisions.some((row: { output_entry_id: number; output_revision_id: number; amount_byn: string }, index: number) => !row
            || !Number.isSafeInteger(row.output_revision_id) || row.output_revision_id <= 0
            || row.output_entry_id !== data.outputCorrections?.[index].output_entry_id
            || row.amount_byn !== data.outputCorrections?.[index].amount_byn))) throw new Error("Корректировки выпуска не подтверждены.");
        if (String(data.organization_id) !== org || data.expense_id !== expenseId || data.source_version !== version
          || data.entry_id !== entryId || data.posted !== true || !/^[a-f0-9]{64}$/.test(data.digest)
          || !/^[a-f0-9]{64}$/.test(data.basis_digest) || data.posting?.source !== `procurement:additional-expense:${expenseId}`
          || typeof data.posting.posting_date !== "string" || typeof data.posting.explanation !== "string"
          || !Array.isArray(data.posting.lines) || !data.posting.lines.length
          || !data.posting.lines.every(line => line && typeof line.account === "string" && line.account.length > 0
            && ["debit", "credit"].includes(line.side) && typeof line.amount === "string" && /^\d{1,20}\.\d{2}$/.test(line.amount)
            && line.currency === "BYN" && line.quantity === null && line.dimensions && typeof line.dimensions === "object"
            && !Array.isArray(line.dimensions) && Object.values(line.dimensions).every(value => typeof value === "string"))) {
          throw new Error("Получен неподтверждённый пакет проводок.");
        }
        let balance = 0n;
        for (const line of data.posting.lines) {
          const cents = BigInt(line.amount.replace(".", ""));
          if (cents <= 0n) throw new Error("Некорректная сумма проводки.");
          balance += line.side === "debit" ? cents : -cents;
        }
        if (balance !== 0n) throw new Error("Дебет и кредит пакета не сходятся.");
        if (!controller.signal.aborted) setResult({ key, data });
      }).catch((error: Error) => { if (!controller.signal.aborted) setResult({ key, error: error.message }); });
    return () => controller.abort();
  }, [opened, org, expenseId, version, entryId, key, material]);
  return <section className="space-y-3 rounded-xl border border-line p-4">
    <Button variant="secondary" onClick={() => setOpened(value => !value)}>{opened ? "Скрыть проводки" : "Показать проводки"}</Button>
    {opened && <>
      {!current && <p role="status">Проверка проведённого пакета…</p>}
      {current?.error && <p role="alert">{current.error}</p>}
      {current?.data && <div className="space-y-3" aria-label="Проводки дополнительных расходов">
        <p>Операция № {entryId} · {current.data.posting.posting_date}</p>
        <p>{current.data.posting.explanation}</p>
        {current.data.posting.lines.map((line, index) => <div key={index} className="space-y-1 border-t border-line pt-2">
          <p>{line.side === "debit" ? "Дебет" : "Кредит"} {line.account} · {line.amount} BYN</p>
          {Object.entries(line.dimensions).map(([name, value]) => <p key={name} className="break-words text-sm text-muted">{dimensionLabels[name] ?? name}: {value}</p>)}
        </div>)}
        {current.data.outputCorrections?.map(output => <section className="space-y-2 border-t border-line pt-3" key={output.output_entry_id}>
          <h4 className="font-semibold">Корректировка выпуска · операция № {output.output_entry_id} · {output.amount_byn} BYN</h4>
          {output.lines.map((line, index) => <div key={index}>
            <p>{line.side === "debit" ? "Дебет" : "Кредит"} {line.account} · {line.amount} BYN</p>
            {Object.entries(line.dimensions).map(([name, value]) => <p className="break-words text-sm text-muted" key={name}>{dimensionLabels[name] ?? name}: {value}</p>)}
          </div>)}
        </section>)}
      </div>}
    </>}
  </section>;
}
